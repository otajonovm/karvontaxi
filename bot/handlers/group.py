import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.db_requests import (
    claim_order_atomic,
    get_driver_by_telegram,
    get_order,
    is_driver_access_active,
)
from bot.keyboards.inline_kb import subscribe_kb
from bot.services.formatters import (
    order_claimed_card,
    order_driver_private,
    order_passenger_accepted,
)
from bot.services.group_ops import (
    drivers_group_id,
    is_group_bound,
    persist_drivers_group,
)
from bot.services.ui import safe_send

logger = logging.getLogger(__name__)
router = Router(name="group")


async def _bind_group(chat) -> bool:
    if chat.type not in {"group", "supergroup"}:
        return False
    await persist_drivers_group(chat.id, getattr(chat, "title", None))
    return True


@router.my_chat_member()
async def bot_membership_changed(event: ChatMemberUpdated) -> None:
    status = str(getattr(event.new_chat_member, "status", ""))
    logger.info(
        "Bot guruh holati: id=%s type=%s title=%s status=%s",
        event.chat.id,
        event.chat.type,
        event.chat.title,
        status,
    )
    if event.chat.type not in {"group", "supergroup"}:
        return
    if status in {"left", "kicked"}:
        return
    await _bind_group(event.chat)
    try:
        await event.bot.send_message(
            event.chat.id,
            "✅ <b>Karvon Taxi ulandi.</b>\n"
            "Bu maxfiy haydovchilar guruhi. Mijoz buyurtmalari shu yerga tushadi.",
        )
    except TelegramBadRequest:
        logger.warning("Guruhga tasdiq yozilmadi, ID saqlandi: %s", event.chat.id)


@router.message(Command("ulanish"), F.chat.type.in_({"group", "supergroup"}))
@router.message(Command("start"), F.chat.type.in_({"group", "supergroup"}))
async def bind_command(message: Message) -> None:
    await _bind_group(message.chat)
    await message.reply(
        "✅ <b>Karvon Taxi shu maxfiy guruhga ulandi.</b>\n"
        f"Guruh ID: <code>{message.chat.id}</code>\n\n"
        "Endi mijoz buyurtmalari shu yerga tushadi."
    )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def autobind_on_group_message(message: Message) -> None:
    if is_group_bound() and message.chat.id == drivers_group_id():
        return
    if not is_group_bound():
        await _bind_group(message.chat)
        await message.reply(
            "✅ <b>Karvon Taxi ulandi.</b>\n"
            "Mijoz buyurtmalari shu maxfiy guruhga tushadi."
        )


@router.callback_query(F.data.startswith("claim_order:"))
async def claim_order(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if callback.from_user is None:
        await callback.answer()
        return

    try:
        order_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri buyurtma.", show_alert=True)
        return

    chat = callback.message.chat if callback.message else None
    if chat is None or chat.type not in {"group", "supergroup"}:
        await callback.answer("Bu tugma faqat haydovchilar guruhida ishlaydi.", show_alert=True)
        return
    if chat.id != drivers_group_id():
        logger.warning(
            "Claim guruh ID mos kelmadi: got=%s expected=%s. Davom etamiz.",
            chat.id,
            drivers_group_id(),
        )

    driver = await get_driver_by_telegram(session, callback.from_user.id)
    if driver is None:
        await callback.answer(
            "Avval botda haydovchi sifatida ro'yxatdan o'ting.",
            show_alert=True,
        )
        return

    if not is_driver_access_active(driver):
        await callback.answer(
            "Obunangiz tugagan. Qabul qilish uchun obuna bo'ling.",
            show_alert=True,
        )
        await safe_send(
            bot,
            driver.telegram_id,
            "Buyurtmani qabul qilish uchun obunani yangilang.",
            reply_markup=subscribe_kb(),
        )
        return

    order = await get_order(session, order_id)
    if order is None:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return

    claimed = await claim_order_atomic(session, order_id, driver)
    if claimed is None:
        await callback.answer(
            "Kechirasiz, bu buyurtma allaqachon olindi!",
            show_alert=True,
        )
        return

    try:
        await callback.message.edit_text(
            order_claimed_card(driver.full_name),
            reply_markup=None,
        )
    except TelegramBadRequest:
        logger.warning("Guruh xabarini tahrirlab bo'lmadi: order=%s", order_id)

    sent = await safe_send(bot, driver.telegram_id, order_driver_private(claimed))
    if not sent:
        await callback.answer(
            "Qabul qilindi, lekin shaxsiy chatga yozib bo'lmadi. Botni /start qiling.",
            show_alert=True,
        )
    else:
        await callback.answer("Buyurtma sizniki! Tafsilotlar shaxsiy chatda.")

    await safe_send(
        bot,
        claimed.passenger_id,
        order_passenger_accepted(
            driver.full_name, driver.car_model, driver.car_number, driver.phone
        ),
    )

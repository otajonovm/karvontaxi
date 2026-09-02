import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.db_requests import (
    CLAIM_COOLDOWN_HOURS,
    complete_order_atomic,
    get_driver_by_telegram,
    get_order,
    order_driver_telegram,
    reopen_order_atomic,
    set_order_group_message,
)
from bot.database.models import Order
from bot.keyboards.inline_kb import CANCEL_REASON_LABELS, claim_order_kb
from bot.services.formatters import order_reactivated_card, order_trip_started_card
from bot.services.group_ops import edit_or_resend_group_message
from bot.services.ui import safe_send, strip_inline
from bot.utils.dt import format_tashkent, now_utc

logger = logging.getLogger(__name__)

PASSENGER_REOPEN_TEXT = (
    "Buyurtmangiz qayta haydovchilar guruhiga chiqarildi. "
    "Tez orada boshqa haydovchi siz bilan bog'lanadi."
)
DRIVER_REOPEN_TEXT = (
    "Buyurtma bekor qilindi va boshqa haydovchilar uchun qayta ochildi."
)


def reason_label(code: str) -> str:
    return CANCEL_REASON_LABELS.get(code, CANCEL_REASON_LABELS["other"])


def _cooldown_note(until) -> str:
    if until is None or until <= now_utc():
        return ""
    return (
        f"\n\n⛔️ 24 soat ichida 3 marta bekor qilganingiz uchun "
        f"{CLAIM_COOLDOWN_HOURS} soatlik cheklov: "
        f"{format_tashkent(until)} gacha yangi buyurtma olmaysiz."
    )


async def _drop_markup(callback: CallbackQuery, text: str | None = None) -> None:
    if callback.message is None:
        return
    try:
        if text:
            await callback.message.edit_text(text, reply_markup=None)
        else:
            await strip_inline(callback)
    except TelegramBadRequest:
        await strip_inline(callback)


async def publish_open_order_card(bot: Bot, session: AsyncSession, order: Order) -> None:
    sent = await edit_or_resend_group_message(
        bot,
        order.group_message_id,
        order_reactivated_card(order),
        reply_markup=claim_order_kb(order.id),
    )
    await set_order_group_message(session, order.id, sent.message_id)


async def handle_reopen(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    order_id: int,
    *,
    reason: str,
    initiated_by: str,
) -> bool:
    if callback.from_user is None:
        await callback.answer()
        return False

    actor_id = callback.from_user.id
    before = await get_order(session, order_id)
    previous_driver_tg = order_driver_telegram(before) if before else None

    order = await reopen_order_atomic(
        session,
        order_id,
        actor_telegram_id=actor_id,
        reason=reason,
        initiated_by=initiated_by,
    )
    if order is None:
        await callback.answer(
            "Bu buyurtma endi faol emas yoki allaqachon bekor qilingan.",
            show_alert=True,
        )
        await strip_inline(callback)
        return False

    cooldown_until = None
    if initiated_by == "driver" and previous_driver_tg is not None:
        driver = await get_driver_by_telegram(session, previous_driver_tg)
        if driver is not None:
            cooldown_until = driver.claim_cooldown_until

    try:
        await publish_open_order_card(bot, session, order)
    except Exception:
        logger.exception("Qayta e'lon guruhga chiqmadi #%s", order_id)

    if order.passenger_id != actor_id:
        await safe_send(bot, order.passenger_id, PASSENGER_REOPEN_TEXT)
    if previous_driver_tg is not None and previous_driver_tg != actor_id:
        await safe_send(bot, previous_driver_tg, DRIVER_REOPEN_TEXT)

    if initiated_by == "driver":
        await _drop_markup(callback, DRIVER_REOPEN_TEXT + _cooldown_note(cooldown_until))
    else:
        await _drop_markup(callback, PASSENGER_REOPEN_TEXT)
    await callback.answer("Buyurtma qayta ochildi.")
    return True


async def handle_deal_success(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    order_id: int,
) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    order = await complete_order_atomic(
        session, order_id, actor_telegram_id=callback.from_user.id
    )
    if order is None:
        await callback.answer(
            "Bu buyurtmani yakunlab bo'lmaydi (allaqachon yopilgan yoki sizniki emas).",
            show_alert=True,
        )
        return

    driver_name = callback.from_user.full_name
    if order.driver:
        driver_name = order.driver.full_name
    try:
        await edit_or_resend_group_message(
            bot,
            order.group_message_id,
            order_trip_started_card(driver_name),
            reply_markup=None,
        )
    except Exception:
        logger.exception("Guruh kartochkasi yakunlanmadi #%s", order_id)

    await _drop_markup(callback, "✅ Safar boshlandi. Mijoz bilan kelishdingiz.")
    await safe_send(
        bot,
        order.passenger_id,
        "✅ Haydovchi safar boshlanganini tasdiqladi. Oq yo'l!",
    )
    await callback.answer("Tasdiqlandi.")

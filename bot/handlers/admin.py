import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.db_requests import (
    approve_payment,
    get_stats,
    grant_subscription,
    list_pending_payments,
    list_recent_drivers,
    reject_payment,
    search_drivers,
)
from bot.filters.admin import IsAdmin
from bot.keyboards.inline_kb import admin_panel_kb
from bot.services.group_ops import create_one_time_invite
from bot.services.ui import html_escape
from bot.states.form_states import AdminGrant
from bot.utils.dt import format_price, format_tashkent

logger = logging.getLogger(__name__)
router = Router(name="admin")
router.message.filter(F.chat.type == "private", IsAdmin())
router.callback_query.filter(F.message.chat.type == "private", IsAdmin())


def _stats_text(stats: dict[str, int]) -> str:
    return (
        "📊 <b>Karvon Taxi — statistika</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{stats['users']}</b>\n"
        f"🚖 Haydovchilar: <b>{stats['drivers']}</b>\n"
        f"   • Sinov: {stats['trial']}\n"
        f"   • Obuna: {stats['active']}\n"
        f"   • Tugagan: {stats['expired']}\n"
        f"🧾 Buyurtmalar: <b>{stats['orders']}</b> (bugun: {stats['orders_today']})\n"
        f"⏳ Ochiq buyurtmalar: {stats['open_orders']}\n"
        f"🔄 Faol qaytish reyslari: {stats['trips']}\n"
        f"💰 Kutilayotgan to'lovlar: {stats['pending_pay']}"
    )


@router.message(Command("admin"))
@router.message(F.text == "🛠 Admin panel")
async def admin_home(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🛠 <b>Admin panel</b>", reply_markup=admin_panel_kb())


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    stats = await get_stats(session)
    await callback.message.edit_text(_stats_text(stats), reply_markup=admin_panel_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:drivers")
async def admin_drivers(callback: CallbackQuery, session: AsyncSession) -> None:
    drivers = await list_recent_drivers(session)
    if not drivers:
        await callback.answer("Haydovchilar yo'q.", show_alert=True)
        return
    lines = ["🚖 <b>So'nggi haydovchilar</b>\n"]
    for d in drivers:
        lines.append(
            f"• {html_escape(d.full_name)} — <code>{d.telegram_id}</code>\n"
            f"  {html_escape(d.car_model)} {html_escape(d.car_number)} | {d.status.value}"
        )
    await callback.message.edit_text("\n".join(lines), reply_markup=admin_panel_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:payments")
async def admin_payments(callback: CallbackQuery, session: AsyncSession) -> None:
    from bot.keyboards.inline_kb import payment_admin_kb

    pending = await list_pending_payments(session)
    if not pending:
        await callback.message.edit_text(
            "Kutilayotgan to'lovlar yo'q.", reply_markup=admin_panel_kb()
        )
        await callback.answer()
        return
    await callback.message.edit_text(f"💰 Kutilayotgan: {len(pending)} ta")
    for req in pending:
        d = req.driver
        await callback.message.answer(
            f"#{req.id} {html_escape(d.full_name)} — {format_price(req.amount)}\n"
            f"<code>{d.telegram_id}</code>",
            reply_markup=payment_admin_kb(req.id),
        )
    await callback.answer()


@router.callback_query(F.data == "admin:grant")
async def admin_grant_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminGrant.waiting_query)
    await callback.message.edit_text(
        "Haydovchi Telegram ID, ism yoki mashina raqamini yozing:"
    )
    await callback.answer()


@router.message(AdminGrant.waiting_query)
async def admin_grant_query(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    query = (message.text or "").strip()
    drivers = await search_drivers(session, query)
    if not drivers:
        await message.answer("Topilmadi. Qayta yozing yoki /admin bosing.")
        return
    driver = drivers[0]
    await state.update_data(grant_telegram_id=driver.telegram_id)
    await state.set_state(AdminGrant.waiting_days)
    await message.answer(
        f"Topildi: <b>{html_escape(driver.full_name)}</b> "
        f"(<code>{driver.telegram_id}</code>)\n"
        f"Necha kunga obuna beramiz? (masalan: {settings.subscription_days})"
    )


@router.message(AdminGrant.waiting_days)
async def admin_grant_days(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    raw = "".join(ch for ch in (message.text or "") if ch.isdigit())
    if not raw:
        await message.answer("Kun sonini raqamda yozing.")
        return
    days = int(raw)
    data = await state.get_data()
    telegram_id = data["grant_telegram_id"]
    driver = await grant_subscription(session, telegram_id, days)
    await state.clear()
    if driver is None:
        await message.answer("Haydovchi topilmadi.")
        return
    invite = await create_one_time_invite(bot, telegram_id)
    if invite:
        driver.invite_link = invite
    await bot.send_message(
        telegram_id,
        "✅ <b>Obuna tasdiqlandi!</b>\n\n"
        f"Muddat: {format_tashkent(driver.subscription_until)} gacha."
        + (f"\n\n🔗 Guruhga qaytish havolasi:\n{invite}" if invite else ""),
    )
    await message.answer(
        f"✅ {html_escape(driver.full_name)} uchun {days} kunlik obuna berildi.",
        reply_markup=admin_panel_kb(),
    )


@router.callback_query(F.data.startswith("payadm:"))
async def admin_payment_action(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
) -> None:
    _, action, raw_id = callback.data.split(":")
    request_id = int(raw_id)
    if action == "ok":
        driver = await approve_payment(session, request_id, callback.from_user.id)
        if driver is None:
            await callback.answer("So'rov allaqachon ko'rib chiqilgan.", show_alert=True)
            return
        invite = await create_one_time_invite(bot, driver.telegram_id)
        if invite:
            driver.invite_link = invite
        await bot.send_message(
            driver.telegram_id,
            "✅ <b>To'lov tasdiqlandi. Obuna faol!</b>\n"
            f"Tugash: {format_tashkent(driver.subscription_until)}"
            + (f"\n\n🔗 Guruh havolasi (bir martalik):\n{invite}" if invite else ""),
        )
        await callback.message.edit_text(
            callback.message.html_text + "\n\n✅ Tasdiqlandi."
        )
        await callback.answer("Tasdiqlandi")
        return

    request = await reject_payment(session, request_id, callback.from_user.id)
    if request is None:
        await callback.answer("So'rov topilmadi.", show_alert=True)
        return
    await bot.send_message(
        request.driver.telegram_id,
        "❌ To'lov tasdiqlanmadi. Admin bilan bog'laning yoki qayta yuboring.",
    )
    await callback.message.edit_text(callback.message.html_text + "\n\n❌ Rad etildi.")
    await callback.answer("Rad etildi")


@router.message(Command("grant"))
async def cmd_grant(message: Message, session: AsyncSession, bot: Bot) -> None:
    parts = (message.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Ishlatish: <code>/grant telegram_id kun</code>")
        return
    telegram_id = int(parts[1])
    days = int(parts[2])
    driver = await grant_subscription(session, telegram_id, days)
    if driver is None:
        await message.answer("Haydovchi topilmadi.")
        return
    invite = await create_one_time_invite(bot, telegram_id)
    if invite:
        driver.invite_link = invite
    await bot.send_message(
        telegram_id,
        f"✅ Obuna {days} kunga ochildi.\nTugash: {format_tashkent(driver.subscription_until)}"
        + (f"\n\n🔗 {invite}" if invite else ""),
    )
    await message.answer("Obuna berildi.")

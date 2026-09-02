import logging
import re
from datetime import datetime, time, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.data.locations import route_for
from bot.database.db_requests import (
    cancel_return_trip,
    create_driver,
    create_payment_request,
    create_return_trip,
    get_driver_by_telegram,
    get_or_create_user,
    get_order,
    is_driver_access_active,
    list_driver_trips,
    order_driver_telegram,
)
from bot.database.models import DriverStatus, FeedbackRating, OrderStatus
from bot.keyboards.default_kb import (
    BTN_BECOME_DRIVER,
    BTN_CANCEL,
    BTN_MY_TRIPS,
    BTN_POST_RETURN,
    BTN_PROFILE,
    BTN_SUBSCRIBE,
    cancel_keyboard,
    contact_keyboard,
)
from bot.keyboards.inline_kb import (
    cancel_reason_kb,
    direction_kb,
    my_trip_kb,
    payment_admin_kb,
    subscribe_kb,
    trip_date_kb,
    trip_seats_kb,
)
from bot.services.deals import handle_deal_success, handle_reopen, reason_label
from bot.services.formatters import return_trip_card
from bot.services.group_ops import create_one_time_invite
from bot.services.ui import html_escape, normalize_phone, show_main_menu
from bot.states.form_states import DriverReg, ReturnTripForm
from bot.utils.dt import format_price, format_tashkent, now_utc, to_tashkent, tz

logger = logging.getLogger(__name__)
router = Router(name="driver")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")


@router.message(StateFilter(DriverReg, ReturnTripForm), F.text.in_({BTN_CANCEL, "/cancel"}))
async def cancel_driver_flow(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    await show_main_menu(message, session, "Bekor qilindi. Bosh menyu:")


def _access_text(driver) -> str:
    moment = now_utc()
    if driver.status == DriverStatus.BANNED:
        return "🚫 Profilingiz bloklangan."
    if driver.subscription_until and driver.subscription_until > moment:
        return f"✅ Obuna: {format_tashkent(driver.subscription_until)} gacha"
    if driver.trial_ends_at > moment:
        left = (driver.trial_ends_at.date() - moment.date()).days
        return f"🎁 Sinov: {max(left, 0)} kun qoldi (tugash: {format_tashkent(driver.trial_ends_at)})"
    return "⛔️ Obuna tugagan — guruhga kirish yopiq."


@router.message(F.text == BTN_BECOME_DRIVER)
async def become_driver(message: Message, state: FSMContext, session: AsyncSession) -> None:
    existing = await get_driver_by_telegram(session, message.from_user.id)
    if existing:
        await show_main_menu(
            message,
            session,
            "Siz allaqachon haydovchi sifatida ro'yxatdan o'tgansiz.\n\n"
            + _profile_text(existing),
        )
        return
    await state.clear()
    await state.set_state(DriverReg.full_name)
    await message.answer(
        "🚖 <b>Haydovchi ro'yxatidan o'tish</b>\n\n"
        "7 kunlik bepul sinov boshlanadi. Ismingizni yozing (masalan: Akmal Karimov):",
        reply_markup=cancel_keyboard(),
    )


def _profile_text(driver) -> str:
    return (
        f"👤 {html_escape(driver.full_name)}\n"
        f"🚗 {html_escape(driver.car_model)} — <code>{html_escape(driver.car_number)}</code>\n"
        f"📞 {html_escape(driver.phone)}\n"
        f"{_access_text(driver)}"
    )


@router.message(DriverReg.full_name)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if message.text == BTN_CANCEL:
        return
    if len(name) < 3:
        await message.answer("Ism kamida 3 ta belgidan iborat bo'lsin.")
        return
    await state.update_data(full_name=name)
    await state.set_state(DriverReg.car_model)
    await message.answer("Mashina rusumini yozing (masalan: Cobalt, Gentra, Malibu):")


@router.message(DriverReg.car_model)
async def reg_car(message: Message, state: FSMContext) -> None:
    model = (message.text or "").strip()
    if message.text == BTN_CANCEL:
        return
    if len(model) < 2:
        await message.answer("Mashina rusumini to'g'ri yozing.")
        return
    await state.update_data(car_model=model)
    await state.set_state(DriverReg.car_number)
    await message.answer("Davlat raqamini yozing (masalan: 01 A 123 BC):")


@router.message(DriverReg.car_number)
async def reg_plate(message: Message, state: FSMContext) -> None:
    plate = (message.text or "").strip().upper()
    if message.text == BTN_CANCEL:
        return
    cleaned = re.sub(r"\s+", " ", plate)
    if len(cleaned) < 5:
        await message.answer("Davlat raqami juda qisqa. Qayta yozing.")
        return
    await state.update_data(car_number=cleaned)
    await state.set_state(DriverReg.phone)
    await message.answer(
        "Telefon raqamingizni ulashing:",
        reply_markup=contact_keyboard(),
    )


@router.message(DriverReg.phone, F.contact)
async def reg_phone_contact(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    phone = normalize_phone(message.contact.phone_number)
    await _finish_driver_reg(message, state, session, bot, phone)


@router.message(DriverReg.phone, F.text)
async def reg_phone_text(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    if message.text == BTN_CANCEL:
        return
    await _finish_driver_reg(
        message, state, session, bot, normalize_phone(message.text)
    )


async def _finish_driver_reg(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    phone: str | None,
) -> None:
    if not phone:
        await message.answer("Raqam noto'g'ri. Kontakt tugmasini bosing yoki +998... yozing.")
        return
    user = message.from_user
    data = await state.get_data()
    await get_or_create_user(session, user.id, user.full_name, user.username)
    invite = await create_one_time_invite(bot, user.id)
    driver = await create_driver(
        session,
        telegram_id=user.id,
        full_name=data["full_name"],
        car_model=data["car_model"],
        car_number=data["car_number"],
        phone=phone,
        invite_link=invite,
    )
    await state.clear()
    invite_block = (
        f"\n\n🔗 Guruhga kirish (bir martalik havola):\n{invite}"
        if invite
        else "\n\n⚠️ Taklif havolasini yaratib bo'lmadi. Admin botni guruhda admin qilganini tekshirsin."
    )
    await show_main_menu(
        message,
        session,
        "🎉 <b>Xush kelibsiz, haydovchi!</b>\n\n"
        f"{_profile_text(driver)}\n"
        f"{invite_block}\n\n"
        f"{settings.trial_days} kun bepul sinov boshlandi. "
        "Buyurtmalarni guruhdagi tugma orqali qabul qilasiz.",
    )


@router.message(F.text == BTN_PROFILE)
async def profile(message: Message, session: AsyncSession) -> None:
    driver = await get_driver_by_telegram(session, message.from_user.id)
    if driver is None:
        await message.answer("Avval haydovchi sifatida ro'yxatdan o'ting.")
        return
    extra = ""
    if driver.invite_link and is_driver_access_active(driver):
        extra = f"\n\n🔗 Guruh havolasi:\n{driver.invite_link}"
    await message.answer("👤 <b>Profilingiz</b>\n\n" + _profile_text(driver) + extra)


@router.message(F.text == BTN_SUBSCRIBE)
async def subscribe_info(message: Message, session: AsyncSession) -> None:
    driver = await get_driver_by_telegram(session, message.from_user.id)
    if driver is None:
        await message.answer("Avval haydovchi sifatida ro'yxatdan o'ting.")
        return
    card = (
        f"\n💳 Karta: <code>{html_escape(settings.payment_card)}</code>"
        if settings.payment_card
        else ""
    )
    info = f"\n{html_escape(settings.payment_info)}" if settings.payment_info else ""
    await message.answer(
        "💳 <b>Oylik obuna</b>\n\n"
        f"{_access_text(driver)}\n\n"
        f"💵 Narxi: <b>{format_price(settings.subscription_price)}</b> / "
        f"{settings.subscription_days} kun"
        f"{card}{info}",
        reply_markup=subscribe_kb(),
    )


@router.callback_query(F.data == "pay:confirm")
async def pay_confirm(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
) -> None:
    driver = await get_driver_by_telegram(session, callback.from_user.id)
    if driver is None:
        await callback.answer("Haydovchi profili topilmadi.", show_alert=True)
        return
    request = await create_payment_request(session, driver.id)
    if request is None:
        await callback.answer("Sizda allaqachon kutilayotgan to'lov so'rovi bor.", show_alert=True)
        return
    text = (
        "💰 <b>Yangi to'lov so'rovi</b>\n\n"
        f"👤 {html_escape(driver.full_name)} (<code>{driver.telegram_id}</code>)\n"
        f"🚗 {html_escape(driver.car_model)} {html_escape(driver.car_number)}\n"
        f"📞 {html_escape(driver.phone)}\n"
        f"💵 {format_price(request.amount)} / {request.days} kun"
    )
    for admin_id in settings.admin_id_list:
        await bot.send_message(admin_id, text, reply_markup=payment_admin_kb(request.id))
    await callback.message.answer(
        "✅ So'rov adminga yuborildi. Tasdiqlangach obuna avtomatik ochiladi."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fb:"))
async def feedback(callback: CallbackQuery, session: AsyncSession) -> None:
    rating = callback.data.split(":", 1)[1]
    driver = await get_driver_by_telegram(session, callback.from_user.id)
    if driver is None:
        await callback.answer()
        return
    mapping = {
        "great": FeedbackRating.GREAT,
        "ok": FeedbackRating.OK,
        "bad": FeedbackRating.BAD,
    }
    driver.feedback_rating = mapping.get(rating)
    thanks = {
        "great": "Rahmat! 👍",
        "ok": "Fikringiz uchun rahmat.",
        "bad": "Afsus. Yaxshilashga harakat qilamiz.",
    }
    await callback.message.edit_text(thanks.get(rating, "Rahmat!"))
    await callback.answer()


@router.message(F.text == BTN_POST_RETURN)
async def post_return_start(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    driver = await get_driver_by_telegram(session, message.from_user.id)
    if driver is None:
        await message.answer("Avval haydovchi sifatida ro'yxatdan o'ting.")
        return
    if not is_driver_access_active(driver):
        await message.answer(
            "Obunangiz tugagan. E'lon berish uchun obunani yangilang.",
            reply_markup=subscribe_kb(),
        )
        return
    await state.clear()
    await state.set_state(ReturnTripForm.direction)
    await message.answer(
        "🚗 <b>Qaytish reysini e'lon qilish</b>\n"
        "Yo'nalish: G'uzor ↔ Toshkent\n\nYo'nalishni tanlang:",
        reply_markup=direction_kb("tdir"),
    )


@router.callback_query(ReturnTripForm.direction, F.data.startswith("tdir:"))
async def trip_direction(callback: CallbackQuery, state: FSMContext) -> None:
    origin, dest = route_for(callback.data.split(":", 1)[1])
    await state.update_data(from_location=origin, to_location=dest)
    await state.set_state(ReturnTripForm.departure_date)
    await callback.message.edit_text(
        f"📍 {origin} → {dest}\n\n📅 Qachon jo'naysiz?",
        reply_markup=trip_date_kb(),
    )
    await callback.answer()


@router.callback_query(ReturnTripForm.departure_date, F.data.startswith("tdate:"))
async def trip_date(callback: CallbackQuery, state: FSMContext) -> None:
    kind = callback.data.split(":", 1)[1]
    local_today = to_tashkent(now_utc()).date()
    if kind == "custom":
        await state.set_state(ReturnTripForm.custom_datetime)
        await callback.message.edit_text(
            "Sana va vaqtni yozing.\nMasalan: <code>03.09.2026 18:00</code> yoki <code>18:00</code>"
        )
        await callback.answer()
        return
    day = local_today if kind == "today" else local_today + timedelta(days=1)
    await state.update_data(trip_date=day.isoformat())
    await state.set_state(ReturnTripForm.custom_datetime)
    label = "Bugun" if kind == "today" else "Ertaga"
    await callback.message.edit_text(f"{label} soat nechida? Masalan: <code>18:00</code>")
    await callback.answer()


@router.message(ReturnTripForm.custom_datetime)
async def trip_datetime(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    data = await state.get_data()
    parsed = _parse_datetime(raw, data.get("trip_date"))
    if parsed is None:
        await message.answer("Vaqtni tushunmadim. Masalan: 18:00 yoki 03.09.2026 18:00")
        return
    await state.update_data(departure_at=parsed.isoformat())
    await state.set_state(ReturnTripForm.seats)
    await message.answer("🪑 Nechta bo'sh joy bor?", reply_markup=trip_seats_kb())


def _parse_datetime(raw: str, date_iso: str | None) -> datetime | None:
    raw = raw.strip()
    try:
        if date_iso and re.fullmatch(r"\d{1,2}[:.]\d{2}", raw):
            hh, mm = re.split(r"[:.]", raw)
            local_date = datetime.fromisoformat(date_iso).date()
            local_dt = datetime.combine(local_date, time(int(hh), int(mm)), tzinfo=tz())
            return local_dt.astimezone(timezone.utc).replace(tzinfo=None)
        for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H.%M", "%d/%m/%Y %H:%M"):
            try:
                local_dt = datetime.strptime(raw, fmt).replace(tzinfo=tz())
                return local_dt.astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                continue
    except (ValueError, TypeError):
        return None
    return None


@router.callback_query(ReturnTripForm.seats, F.data.startswith("tseats:"))
async def trip_seats(callback: CallbackQuery, state: FSMContext) -> None:
    seats = int(callback.data.split(":")[1])
    await state.update_data(seats=seats)
    await state.set_state(ReturnTripForm.price)
    await callback.message.edit_text(
        f"💵 Bir o'rindiq narxini {settings.currency} da yozing (masalan: 80000):"
    )
    await callback.answer()


@router.message(ReturnTripForm.price)
async def trip_price(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    digits = "".join(ch for ch in (message.text or "") if ch.isdigit())
    if not digits:
        await message.answer("Faqat raqam yozing, masalan: 80000")
        return
    price = int(digits)
    if price < 1000:
        await message.answer("Narx juda kichik. Qayta yozing.")
        return
    data = await state.get_data()
    driver = await get_driver_by_telegram(session, message.from_user.id)
    departure_at = datetime.fromisoformat(data["departure_at"])
    trip = await create_return_trip(
        session,
        driver_id=driver.id,
        from_location=data["from_location"],
        to_location=data["to_location"],
        departure_at=departure_at,
        seats=int(data["seats"]),
        price=price,
    )
    await state.clear()
    await show_main_menu(
        message,
        session,
        "✅ <b>Qaytish reysi e'lon qilindi!</b>\n\n" + return_trip_card(trip),
    )


@router.message(F.text == BTN_MY_TRIPS)
async def my_trips(message: Message, session: AsyncSession) -> None:
    driver = await get_driver_by_telegram(session, message.from_user.id)
    if driver is None:
        await message.answer("Avval haydovchi sifatida ro'yxatdan o'ting.")
        return
    trips = await list_driver_trips(session, driver.id)
    if not trips:
        await message.answer("Sizda e'lonlar yo'q.")
        return
    for trip in trips[:8]:
        status = trip.status.value
        await message.answer(
            f"{return_trip_card(trip)}\n📌 Holat: {status}",
            reply_markup=my_trip_kb(trip.id) if trip.status.value == "active" else None,
        )


@router.callback_query(F.data.startswith("rtcancel:"))
async def cancel_trip(callback: CallbackQuery, session: AsyncSession) -> None:
    trip_id = int(callback.data.split(":")[1])
    driver = await get_driver_by_telegram(session, callback.from_user.id)
    if driver is None:
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    ok = await cancel_return_trip(session, trip_id, driver.id)
    if not ok:
        await callback.answer("E'lon yopilmadi.", show_alert=True)
        return
    await callback.message.edit_text("❌ E'lon yopildi.")
    await callback.answer("Yopildi")


def _parse_order_id(data: str) -> int | None:
    try:
        return int(data.split(":")[1])
    except (IndexError, ValueError):
        return None


@router.callback_query(F.data.startswith("deal_success:"))
async def deal_success(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
) -> None:
    order_id = _parse_order_id(callback.data or "")
    if order_id is None:
        await callback.answer("Noto'g'ri buyurtma.", show_alert=True)
        return
    await handle_deal_success(callback, session, bot, order_id)


@router.callback_query(F.data.startswith("deal_failed:"))
async def deal_failed(callback: CallbackQuery, session: AsyncSession) -> None:
    order_id = _parse_order_id(callback.data or "")
    if order_id is None or callback.from_user is None:
        await callback.answer("Noto'g'ri buyurtma.", show_alert=True)
        return
    order = await get_order(session, order_id)
    if (
        order is None
        or order.status != OrderStatus.ACCEPTED
        or order_driver_telegram(order) != callback.from_user.id
    ):
        await callback.answer(
            "Bu buyurtma endi sizniki emas yoki allaqachon yopilgan.",
            show_alert=True,
        )
        return
    if callback.message:
        try:
            await callback.message.edit_text(
                "Bekor qilish sababini tanlang:",
                reply_markup=cancel_reason_kb(order_id, "drej"),
            )
        except TelegramBadRequest:
            await callback.message.answer(
                "Bekor qilish sababini tanlang:",
                reply_markup=cancel_reason_kb(order_id, "drej"),
            )
    await callback.answer()


@router.callback_query(F.data.startswith("drej:"))
async def deal_failed_reason(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Noto'g'ri sabab.", show_alert=True)
        return
    try:
        order_id = int(parts[1])
    except ValueError:
        await callback.answer("Noto'g'ri buyurtma.", show_alert=True)
        return
    await handle_reopen(
        callback,
        session,
        bot,
        order_id,
        reason=reason_label(parts[2]),
        initiated_by="driver",
    )

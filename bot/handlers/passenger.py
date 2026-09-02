import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.data.locations import CARGO_TYPES, GUZOR, TASHKENT, is_corridor, route_for
from bot.database.db_requests import (
    book_return_trip_atomic,
    create_order,
    get_or_create_user,
    get_order,
    get_return_trip,
    get_user,
    list_active_return_trips,
    save_user_phone,
    search_return_trips,
    set_order_group_message,
)
from bot.database.models import OrderStatus, OrderType
from bot.keyboards.default_kb import (
    BTN_CARGO,
    BTN_CANCEL,
    BTN_GUZOR_TASHKENT,
    BTN_MAIN,
    BTN_RETURN_TRIPS,
    BTN_TAXI,
    BTN_TASHKENT_GUZOR,
    contact_keyboard,
)
from bot.keyboards.inline_kb import (
    cancel_reason_kb,
    cargo_kb,
    claim_order_kb,
    direction_kb,
    return_trips_list_kb,
    seats_kb,
    time_kb,
    trip_detail_kb,
)
from bot.services.deals import handle_reopen, reason_label
from bot.services.formatters import order_group_card, return_trip_card
from bot.services.group_ops import send_to_drivers_group
from bot.services.ui import normalize_phone, show_main_menu
from bot.states.form_states import BrowseTrips, Onboarding, OrderForm
from bot.utils.dt import format_tashkent, now_utc, to_tashkent

logger = logging.getLogger(__name__)
router = Router(name="passenger")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

WELCOME = (
    "Assalomu alaykum, <b>{name}</b>!\n\n"
    "Bu <b>Karvon Taxi</b> — faqat <b>G'uzor ↔ Toshkent</b> yo'nalishi.\n\n"
    "Yo'nalishni tanlang:"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    user = message.from_user
    if user is None:
        return
    await get_or_create_user(session, user.id, user.full_name, user.username)
    await state.set_state(Onboarding.phone)
    await message.answer(
        WELCOME.format(name=user.full_name)
        + "\n\n📞 Avval telefon raqamingizni ulashing.\n"
        "Pastdagi <b>Kontaktni ulashish</b> tugmasini bosing.",
        reply_markup=contact_keyboard(),
    )


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
@router.message(F.text == BTN_MAIN)
async def cmd_cancel(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await show_main_menu(message, session, "Bosh menyu. Yo'nalishni tanlang.")


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await show_main_menu(callback, session, "Bekor qilindi. Bosh menyu:")


@router.message(Onboarding.phone, F.contact)
async def onboarding_phone(message: Message, state: FSMContext, session: AsyncSession) -> None:
    phone = normalize_phone(message.contact.phone_number)
    if not phone:
        await message.answer(
            "Raqamni o'qib bo'lmadi. Qayta ulashing.",
            reply_markup=contact_keyboard(),
        )
        return
    await save_user_phone(session, message.from_user.id, phone)
    await state.clear()
    await show_main_menu(
        message,
        session,
        f"✅ Raqam qabul qilindi: <code>{phone}</code>\n\nYo'nalishni tanlang:",
    )


@router.message(
    Onboarding.phone,
    F.text,
    ~F.text.in_(
        {
            BTN_CANCEL,
            BTN_MAIN,
            BTN_GUZOR_TASHKENT,
            BTN_TASHKENT_GUZOR,
            BTN_TAXI,
            BTN_CARGO,
            BTN_RETURN_TRIPS,
        }
    ),
)
async def onboarding_phone_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer(
            "📞 Tugma orqali kontakt ulashing yoki raqamni +998XXXXXXXXX ko'rinishida yozing.",
            reply_markup=contact_keyboard(),
        )
        return
    await save_user_phone(session, message.from_user.id, phone)
    await state.clear()
    await show_main_menu(
        message,
        session,
        f"✅ Raqam qabul qilindi: <code>{phone}</code>\n\nYo'nalishni tanlang:",
    )


async def _begin_order(
    message: Message, state: FSMContext, order_type: OrderType, origin: str, dest: str
) -> None:
    await state.clear()
    await state.update_data(
        order_type=order_type.value,
        from_location=origin,
        to_location=dest,
        departure_time="Hozir",
    )
    await _ask_quantity_message(message, state)


@router.message(F.text == BTN_GUZOR_TASHKENT)
async def taxi_guzor_tashkent(message: Message, state: FSMContext) -> None:
    await _begin_order(message, state, OrderType.TAXI, GUZOR, TASHKENT)


@router.message(F.text == BTN_TASHKENT_GUZOR)
async def taxi_tashkent_guzor(message: Message, state: FSMContext) -> None:
    await _begin_order(message, state, OrderType.TAXI, TASHKENT, GUZOR)


@router.message(F.text == BTN_TAXI)
async def start_taxi(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(order_type=OrderType.TAXI.value, departure_time="Hozir")
    await state.set_state(OrderForm.direction)
    await message.answer(
        "🚕 Yo'nalishni tanlang:",
        reply_markup=direction_kb("odir"),
    )


@router.message(F.text == BTN_CARGO)
async def start_cargo(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(order_type=OrderType.CARGO.value, departure_time="Hozir")
    await state.set_state(OrderForm.direction)
    await message.answer(
        "📦 <b>Pochta / Yuk</b>\n\nYo'nalishni tanlang:",
        reply_markup=direction_kb("odir"),
    )


@router.callback_query(OrderForm.direction, F.data.startswith("odir:"))
async def order_direction(callback: CallbackQuery, state: FSMContext) -> None:
    origin, dest = route_for(callback.data.split(":", 1)[1])
    await state.update_data(from_location=origin, to_location=dest)
    await _ask_quantity(callback, state)
    await callback.answer()


async def _ask_quantity(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    route = f"{data.get('from_location')} → {data.get('to_location')}"
    if data.get("order_type") == OrderType.CARGO.value:
        await state.set_state(OrderForm.cargo_type)
        await callback.message.edit_text(
            f"📍 {route}\n\n📦 Yuk turini tanlang:",
            reply_markup=cargo_kb(),
        )
        return
    await state.set_state(OrderForm.seats)
    await callback.message.edit_text(
        f"📍 {route}\n⏰ Jo'nash: <b>Hozir</b>\n\n👥 Nechta odam?",
        reply_markup=seats_kb(),
    )


async def _ask_quantity_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    route = f"{data.get('from_location')} → {data.get('to_location')}"
    if data.get("order_type") == OrderType.CARGO.value:
        await state.set_state(OrderForm.cargo_type)
        await message.answer(
            f"📍 {route}\n\n📦 Yuk turini tanlang:",
            reply_markup=cargo_kb(),
        )
        return
    await state.set_state(OrderForm.seats)
    await message.answer(
        f"📍 {route}\n⏰ Jo'nash: <b>Hozir</b>\n\n👥 Nechta odam?",
        reply_markup=seats_kb(),
    )


@router.callback_query(OrderForm.seats, F.data == "otime:pick")
async def order_pick_time(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("⏰ Jo'nash vaqtini tanlang:", reply_markup=time_kb())
    await callback.answer()


@router.callback_query(OrderForm.seats, F.data.startswith("otime:"))
async def order_set_time(callback: CallbackQuery, state: FSMContext) -> None:
    kind = callback.data.split(":", 1)[1]
    if kind == "pick":
        return
    if kind == "custom":
        await state.set_state(OrderForm.custom_time)
        await callback.message.edit_text(
            "Vaqtni yozing, masalan: <code>15:00</code>"
        )
        await callback.answer()
        return
    if kind == "now":
        label = f"Hozir ({to_tashkent(now_utc()).strftime('%H:%M')})"
    else:
        label = f"Bugun {kind} da"
    await state.update_data(departure_time=label)
    data = await state.get_data()
    route = f"{data.get('from_location')} → {data.get('to_location')}"
    await callback.message.edit_text(
        f"📍 {route}\n⏰ Jo'nash: <b>{label}</b>\n\n👥 Nechta odam?",
        reply_markup=seats_kb(),
    )
    await callback.answer()


@router.message(OrderForm.custom_time)
async def order_custom_time(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 4 or len(text) > 40:
        await message.answer("Vaqtni to'g'ri yozing, masalan: 15:00")
        return
    await state.update_data(departure_time=text)
    await state.set_state(OrderForm.seats)
    data = await state.get_data()
    await message.answer(
        f"📍 {data.get('from_location')} → {data.get('to_location')}\n"
        f"⏰ {text}\n\n👥 Nechta odam?",
        reply_markup=seats_kb(with_other_time=False),
    )


@router.callback_query(OrderForm.seats, F.data.startswith("oseats:"))
async def order_seats(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    count = int(callback.data.split(":", 1)[1])
    await state.update_data(passengers_count=count)
    await _ask_contact(callback, state)


@router.callback_query(OrderForm.cargo_type, F.data.startswith("ocargo:"))
async def order_cargo(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    code = callback.data.split(":", 1)[1]
    title = next((t for c, t in CARGO_TYPES if c == code), code)
    await state.update_data(cargo_type=title)
    await _ask_contact(callback, state)


async def _ask_contact(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(OrderForm.contact)
    await callback.message.edit_text(
        "📞 Telefon raqamingizni ulashing — haydovchi shu raqam orqali bog'lanadi."
    )
    await callback.message.answer(
        "Pastdagi <b>Kontaktni ulashish</b> tugmasini bosing.",
        reply_markup=contact_keyboard(),
    )
    await callback.answer()


@router.message(OrderForm.contact, F.contact)
async def order_contact(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    phone = normalize_phone(message.contact.phone_number)
    if not phone:
        await message.answer("Raqamni o'qib bo'lmadi. Qayta ulashing.")
        return
    await _finish_order(message, state, session, bot, phone)


@router.message(OrderForm.contact, F.text)
async def order_contact_text(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    if message.text in {BTN_CANCEL, BTN_MAIN}:
        return
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer(
            "Raqamni +998XXXXXXXXX ko'rinishida yozing yoki kontakt tugmasini bosing."
        )
        return
    await _finish_order(message, state, session, bot, phone)


async def _finish_order(
    event: Message | CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    phone: str,
) -> None:
    user = event.from_user
    data = await state.get_data()
    await save_user_phone(session, user.id, phone)
    order = await create_order(
        session,
        passenger_id=user.id,
        order_type=OrderType(data["order_type"]),
        from_location=data["from_location"],
        to_location=data["to_location"],
        departure_time=data.get("departure_time") or "Hozir",
        phone=phone,
        passengers_count=data.get("passengers_count"),
        cargo_type=data.get("cargo_type"),
    )
    await session.commit()
    try:
        sent = await send_to_drivers_group(
            bot,
            order_group_card(order),
            reply_markup=claim_order_kb(order.id),
        )
        await set_order_group_message(session, order.id, sent.message_id)
    except Exception:
        logger.exception("Guruhga buyurtma yuborilmadi #%s", order.id)
        await show_main_menu(
            event,
            session,
            "Buyurtma saqlandi, lekin haydovchilar guruhiga yuborishda xatolik. "
            "Bot maxfiy guruhda admin ekanini tekshiring.",
        )
        await state.clear()
        return

    await state.clear()
    extra = f"👥 {data.get('passengers_count')} ta\n" if data.get("passengers_count") else ""
    cargo = f"📦 {data.get('cargo_type')}\n" if data.get("cargo_type") else ""
    await show_main_menu(
        event,
        session,
        "✅ <b>Buyurtma haydovchilar guruhiga yuborildi!</b>\n\n"
        f"📍 {data['from_location']} → {data['to_location']}\n"
        f"{extra}{cargo}"
        f"⏰ {data.get('departure_time') or 'Hozir'}\n\n"
        "Haydovchi qabul qilishi bilan sizga xabar beramiz.",
    )


@router.message(F.text == BTN_RETURN_TRIPS)
async def browse_trips(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🔄 <b>Qaytish reyslari</b> — G'uzor ↔ Toshkent\n\nYo'nalishni tanlang:",
        reply_markup=direction_kb("bdir"),
    )


@router.callback_query(F.data.startswith("bdir:"))
async def browse_direction(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    origin, dest = route_for(callback.data.split(":", 1)[1])
    await state.update_data(from_query=origin, to_query=dest, trip_page=0)
    await _show_trip_list(callback, state, session)
    await callback.answer()


async def _show_trip_list(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    page: int | None = None,
) -> None:
    data = await state.get_data()
    from_q = data.get("from_query", GUZOR)
    to_q = data.get("to_query", TASHKENT)
    trips = await search_return_trips(session, from_q, to_q)
    if not trips:
        trips = [
            t
            for t in await list_active_return_trips(session)
            if is_corridor(t.from_location, t.to_location)
            and from_q.lower() in t.from_location.lower()
            and to_q.lower() in t.to_location.lower()
        ]
    page = data.get("trip_page", 0) if page is None else page
    await state.update_data(trip_ids=[t.id for t in trips], trip_page=page)
    if not trips:
        await callback.message.edit_text("Hozircha bu yo'nalishda qaytish reysi yo'q.")
        return
    await callback.message.edit_text(
        f"🔄 {from_q} → {to_q}\nTopilgan reyslar: {len(trips)} ta",
        reply_markup=return_trips_list_kb(trips, page),
    )


@router.callback_query(F.data.startswith("rtpage:"))
async def trip_page(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    page = int(callback.data.split(":")[1])
    await _show_trip_list(callback, state, session, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith("rtd:"))
async def trip_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    trip_id = int(callback.data.split(":")[1])
    trip = await get_return_trip(session, trip_id)
    if trip is None or trip.available_seats <= 0:
        await callback.answer("Bu reys endi mavjud emas.", show_alert=True)
        return
    await callback.message.edit_text(
        return_trip_card(trip), reply_markup=trip_detail_kb(trip.id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rtbook:"))
async def trip_book_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    trip_id = int(callback.data.split(":")[1])
    trip = await get_return_trip(session, trip_id)
    if trip is None or trip.available_seats <= 0:
        await callback.answer("Bu reys band qilingan.", show_alert=True)
        return
    await state.update_data(book_trip_id=trip_id)
    await state.set_state(BrowseTrips.contact)
    await callback.message.edit_text("📞 Bron uchun telefon raqamingizni ulashing.")
    await callback.message.answer(
        "Pastdagi <b>Kontaktni ulashish</b> tugmasini bosing.",
        reply_markup=contact_keyboard(),
    )
    await callback.answer()


@router.message(BrowseTrips.contact, F.contact)
async def trip_book_contact(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    phone = normalize_phone(message.contact.phone_number)
    await _complete_booking(message, state, session, bot, phone)


@router.message(BrowseTrips.contact, F.text)
async def trip_book_contact_text(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    if message.text in {BTN_CANCEL, BTN_MAIN}:
        return
    phone = normalize_phone(message.text)
    await _complete_booking(message, state, session, bot, phone)


async def _complete_booking(
    event: Message | CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    phone: str | None,
) -> None:
    if not phone:
        if isinstance(event, Message):
            await event.answer("Raqam noto'g'ri. Qayta yuboring.")
        else:
            await event.answer("Raqam noto'g'ri.", show_alert=True)
        return
    data = await state.get_data()
    trip_id = data.get("book_trip_id")
    user = event.from_user
    await save_user_phone(session, user.id, phone)
    trip = await book_return_trip_atomic(
        session, trip_id=trip_id, passenger_id=user.id, seats=1, phone=phone
    )
    await state.clear()
    if trip is None:
        await show_main_menu(
            event,
            session,
            "Kechirasiz, joy band qilinmadi (allaqachon olingan yoki siz bron qilgansiz).",
        )
        if isinstance(event, CallbackQuery):
            await event.answer()
        return
    await bot.send_message(
        trip.driver.telegram_id,
        "🔔 <b>Yangi bron!</b>\n\n"
        f"🔄 {trip.from_location} → {trip.to_location}\n"
        f"⏰ {format_tashkent(trip.departure_at)}\n"
        f"👤 {user.full_name}\n"
        f"📞 <code>{phone}</code>\n"
        f"🪑 1 ta joy\n"
        f"💵 {trip.price} {settings.currency}",
    )
    await show_main_menu(
        event,
        session,
        "✅ <b>Joy band qilindi!</b>\n\n"
        f"🚗 {trip.driver.full_name} — {trip.driver.car_model} "
        f"({trip.driver.car_number})\n"
        f"📞 <code>{trip.driver.phone}</code>\n\n"
        "Haydovchi bilan bog'lanishingiz mumkin.",
    )
    if isinstance(event, CallbackQuery):
        await event.answer("Bron qilindi")


def _parse_order_id(data: str) -> int | None:
    try:
        return int(data.split(":")[1])
    except (IndexError, ValueError):
        return None


async def _passenger_owns_accepted(
    session: AsyncSession, order_id: int, user_id: int
) -> bool:
    order = await get_order(session, order_id)
    return (
        order is not None
        and order.status == OrderStatus.ACCEPTED
        and order.passenger_id == user_id
    )


@router.callback_query(F.data.startswith("client_reject:"))
async def client_reject(callback: CallbackQuery, session: AsyncSession) -> None:
    order_id = _parse_order_id(callback.data or "")
    if order_id is None or callback.from_user is None:
        await callback.answer("Noto'g'ri buyurtma.", show_alert=True)
        return
    if not await _passenger_owns_accepted(session, order_id, callback.from_user.id):
        await callback.answer(
            "Bu buyurtma endi faol emas yoki sizniki emas.",
            show_alert=True,
        )
        return
    if callback.message:
        try:
            await callback.message.edit_text(
                "Boshqa haydovchi qidirish sababini tanlang:",
                reply_markup=cancel_reason_kb(order_id, "prej"),
            )
        except TelegramBadRequest:
            await callback.message.answer(
                "Boshqa haydovchi qidirish sababini tanlang:",
                reply_markup=cancel_reason_kb(order_id, "prej"),
            )
    await callback.answer()


@router.callback_query(F.data.startswith("prej:"))
async def client_reject_reason(
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
        initiated_by="passenger",
    )


@router.callback_query(F.data.startswith("no_contact:"))
async def no_contact(
    callback: CallbackQuery, session: AsyncSession, bot: Bot
) -> None:
    order_id = _parse_order_id(callback.data or "")
    if order_id is None or callback.from_user is None:
        await callback.answer("Noto'g'ri buyurtma.", show_alert=True)
        return
    if not await _passenger_owns_accepted(session, order_id, callback.from_user.id):
        await callback.answer(
            "Bu buyurtma endi faol emas yoki sizniki emas.",
            show_alert=True,
        )
        return
    await handle_reopen(
        callback,
        session,
        bot,
        order_id,
        reason=reason_label("phone"),
        initiated_by="passenger",
    )

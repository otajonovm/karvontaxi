from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.data.locations import CARGO_TYPES, GUZOR, TASHKENT
from bot.utils.dt import format_price


def _cancel_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")]


def direction_kb(prefix: str = "odir") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🏞 {GUZOR} → {TASHKENT}", callback_data=f"{prefix}:g2t")
    builder.button(text=f"🏙 {TASHKENT} → {GUZOR}", callback_data=f"{prefix}:t2g")
    builder.adjust(1)
    builder.row(*_cancel_row())
    return builder.as_markup()


def time_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ Hozir", callback_data="otime:now")
    builder.button(text="Bugun 08:00", callback_data="otime:08:00")
    builder.button(text="Bugun 12:00", callback_data="otime:12:00")
    builder.button(text="Bugun 18:00", callback_data="otime:18:00")
    builder.button(text="Bugun 21:00", callback_data="otime:21:00")
    builder.button(text="✏️ Yozish", callback_data="otime:custom")
    builder.adjust(1, 2, 2, 1)
    builder.row(*_cancel_row())
    return builder.as_markup()


def seats_kb(*, with_other_time: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for n in (1, 2, 3, 4):
        builder.button(text=f"{n} ta", callback_data=f"oseats:{n}")
    builder.button(text="5+", callback_data="oseats:5")
    builder.adjust(3)
    if with_other_time:
        builder.row(
            InlineKeyboardButton(text="🕐 Boshqa vaqt", callback_data="otime:pick")
        )
    builder.row(*_cancel_row())
    return builder.as_markup()


def cargo_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, title in CARGO_TYPES:
        builder.button(text=title, callback_data=f"ocargo:{code}")
    builder.adjust(1)
    builder.row(*_cancel_row())
    return builder.as_markup()


def claim_order_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤝 Buyurtmani qabul qilish",
                    callback_data=f"claim_order:{order_id}",
                )
            ]
        ]
    )


def trip_date_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Bugun", callback_data="tdate:today")
    builder.button(text="Ertaga", callback_data="tdate:tomorrow")
    builder.button(text="📅 Sana va vaqtni yozish", callback_data="tdate:custom")
    builder.adjust(2)
    builder.row(*_cancel_row())
    return builder.as_markup()


def trip_seats_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for n in range(1, 5):
        builder.button(text=f"{n} ta", callback_data=f"tseats:{n}")
    builder.adjust(4)
    builder.row(*_cancel_row())
    return builder.as_markup()


def feedback_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👍 A'lo", callback_data="fb:great"),
                InlineKeyboardButton(text="😐 Yaxshi", callback_data="fb:ok"),
                InlineKeyboardButton(text="👎 Yomon", callback_data="fb:bad"),
            ]
        ]
    )


def subscribe_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 To'lov qildim", callback_data="pay:confirm"
                )
            ]
        ]
    )


def payment_admin_kb(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash", callback_data=f"payadm:ok:{request_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish", callback_data=f"payadm:no:{request_id}"
                ),
            ]
        ]
    )


def admin_panel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Statistika", callback_data="admin:stats")
    builder.button(text="🚖 Haydovchilar", callback_data="admin:drivers")
    builder.button(text="💰 To'lovlar", callback_data="admin:payments")
    builder.button(text="🎁 Obuna berish", callback_data="admin:grant")
    builder.adjust(2)
    return builder.as_markup()


def return_trips_list_kb(
    trips: list, page: int, per_page: int = 5
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * per_page
    chunk = trips[start : start + per_page]
    for trip in chunk:
        label = (
            f"{trip.from_location} → {trip.to_location} | "
            f"{trip.available_seats} joy | {format_price(trip.price)}"
        )
        if len(label) > 60:
            label = label[:57] + "..."
        builder.button(text=label, callback_data=f"rtd:{trip.id}")
    builder.adjust(1)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"rtpage:{page - 1}"))
    if start + per_page < len(trips):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"rtpage:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(*_cancel_row())
    return builder.as_markup()


def trip_detail_kb(trip_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📞 Haydovchi bilan bog'lanish",
                    callback_data=f"rtbook:{trip_id}",
                )
            ],
            [InlineKeyboardButton(text="🔙 Ro'yxat", callback_data="rtpage:0")],
            _cancel_row(),
        ]
    )


def my_trip_kb(trip_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 E'lonni yopish", callback_data=f"rtcancel:{trip_id}"
                )
            ]
        ]
    )

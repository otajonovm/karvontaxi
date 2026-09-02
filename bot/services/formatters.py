from bot.database.models import Order, OrderType, ReturnTrip
from bot.services.ui import html_escape
from bot.utils.dt import format_price, format_tashkent


def order_group_card(order: Order) -> str:
    route = f"{html_escape(order.from_location)} -> {html_escape(order.to_location)}"
    if order.order_type == OrderType.CARGO:
        extra = f"📦 <b>Yuk:</b> {html_escape(order.cargo_type or 'Noma’lum')}"
    else:
        extra = f"👥 <b>Odam soni:</b> {order.passengers_count or 1} ta"
    return (
        "🚖 <b>Yangi buyurtma!</b>\n\n"
        f"📍 <b>Yo'nalish:</b> {route}\n"
        f"{extra}\n"
        f"⏰ <b>Vaqt:</b> {html_escape(order.departure_time)}\n\n"
        "⚠️ <i>Mijoz raqamini ko'rish uchun buyurtmani qabul qiling.</i>"
    )


def order_reactivated_card(order: Order) -> str:
    route = f"{html_escape(order.from_location)} -> {html_escape(order.to_location)}"
    if order.order_type == OrderType.CARGO:
        extra = f"📦 <b>Yuk:</b> {html_escape(order.cargo_type or '-')} | ⏰ <b>Vaqt:</b> {html_escape(order.departure_time)}"
    else:
        extra = (
            f"👥 <b>Odam soni:</b> {order.passengers_count or 1} ta"
            f" | ⏰ <b>Vaqt:</b> {html_escape(order.departure_time)}"
        )
    return (
        "⚠️ <b>BUYURTMA QAYTA FAOLLASHTIRILDI!</b>\n"
        "<i>(Avvalgi haydovchi bilan kelishilmadi)</i>\n\n"
        f"📍 <b>Yo'nalish:</b> {route}\n"
        f"{extra}"
    )


def order_trip_started_card(driver_name: str) -> str:
    return (
        f"✅ Safar boshlandi. Haydovchi <b>{html_escape(driver_name)}</b> "
        "mijoz bilan kelishdi."
    )


def order_claimed_card(driver_name: str) -> str:
    return (
        f"✅ Ushbu buyurtmani Haydovchi <b>{html_escape(driver_name)}</b> qabul qildi."
    )


def order_driver_private(order: Order) -> str:
    passenger_name = html_escape(order.passenger.full_name if order.passenger else "Mijoz")
    if order.order_type == OrderType.CARGO:
        extra = f"📦 Yuk: {html_escape(order.cargo_type or '-')}"
    else:
        extra = f"👥 Odam soni: {order.passengers_count or 1} ta"
    return (
        "✅ <b>Buyurtma sizniki!</b>\n\n"
        f"👤 Mijoz: {passenger_name}\n"
        f"📞 Telefon: <code>{html_escape(order.phone)}</code>\n"
        f"📍 Yo'nalish: {html_escape(order.from_location)} -> {html_escape(order.to_location)}\n"
        f"{extra}\n"
        f"⏰ Vaqt: {html_escape(order.departure_time)}\n"
        f"🆔 Buyurtma: #{order.id}\n\n"
        "Mijoz bilan bog'laning. Kelishilmasa pastdagi tugma orqali buyurtmani "
        "boshqa haydovchilarga qaytaring."
    )


def order_passenger_accepted(driver_name: str, car_model: str, car_number: str, phone: str) -> str:
    return (
        "✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
        f"🚖 Haydovchi: {html_escape(driver_name)}\n"
        f"🚗 Mashina: {html_escape(car_model)} — <code>{html_escape(car_number)}</code>\n"
        f"📞 Telefon: <code>{html_escape(phone)}</code>\n\n"
        "Haydovchi tez orada siz bilan bog'lanadi.\n"
        "Agar kelishilmasa yoki haydovchi javob bermasa — pastdagi tugmalardan foydalaning."
    )


def return_trip_card(trip: ReturnTrip) -> str:
    driver = trip.driver
    return (
        "🔄 <b>Qaytish reysi</b>\n\n"
        f"📍 {html_escape(trip.from_location)} → {html_escape(trip.to_location)}\n"
        f"⏰ {format_tashkent(trip.departure_at)}\n"
        f"🪑 Bo'sh joy: {trip.available_seats} / {trip.seats}\n"
        f"💵 O'rindiq narxi: {format_price(trip.price)}\n"
        f"🚗 {html_escape(driver.car_model)} — <code>{html_escape(driver.car_number)}</code>\n"
        f"👤 {html_escape(driver.full_name)}"
    )

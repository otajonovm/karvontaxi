from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

BTN_TAXI = "🚕 Taksi chaqirish"
BTN_GUZOR_TASHKENT = "🚕 G'uzor → Toshkent"
BTN_TASHKENT_GUZOR = "🚕 Toshkent → G'uzor"
BTN_RETURN_TRIPS = "🔄 Qaytish reyslarini ko'rish"
BTN_CARGO = "📦 Pochta / Yuk yuborish"
BTN_BECOME_DRIVER = "🚖 Haydovchi sifatida ishlash"
BTN_POST_RETURN = "🚗 Qaytish reysini e'lon qilish"
BTN_MY_TRIPS = "📋 Mening e'lonlarim"
BTN_PROFILE = "👤 Profilim"
BTN_SUBSCRIBE = "💳 Obuna"
BTN_ADMIN = "🛠 Admin panel"
BTN_SHARE_CONTACT = "📱 Kontaktni ulashish"
BTN_CANCEL = "❌ Bekor qilish"
BTN_BACK = "🔙 Orqaga"
BTN_MAIN = "🏠 Bosh menyu"

REMOVE_KB = ReplyKeyboardRemove()


def main_menu(*, is_driver: bool = False, is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=BTN_GUZOR_TASHKENT)],
        [KeyboardButton(text=BTN_TASHKENT_GUZOR)],
        [KeyboardButton(text=BTN_RETURN_TRIPS), KeyboardButton(text=BTN_CARGO)],
    ]
    if is_driver:
        rows.append(
            [KeyboardButton(text=BTN_POST_RETURN), KeyboardButton(text=BTN_MY_TRIPS)]
        )
        rows.append(
            [KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_SUBSCRIBE)]
        )
    else:
        rows.append([KeyboardButton(text=BTN_BECOME_DRIVER)])
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SHARE_CONTACT, request_contact=True)],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


def cancel_back_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BACK)],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.db_requests import get_driver_by_telegram
from bot.keyboards.default_kb import main_menu


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("998") and len(digits) >= 12:
        return "+" + digits[:12]
    if len(digits) == 9:
        return "+998" + digits
    if digits.startswith("0") and len(digits) == 10:
        return "+998" + digits[1:]
    if 9 <= len(digits) <= 15:
        return "+" + digits
    return None


async def show_main_menu(
    event: Message | CallbackQuery,
    session: AsyncSession,
    text: str,
) -> None:
    user = event.from_user
    if user is None:
        return
    driver = await get_driver_by_telegram(session, user.id)
    markup = main_menu(
        is_driver=driver is not None,
        is_admin=settings.is_admin(user.id),
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            try:
                await event.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
            await event.message.answer(text, reply_markup=markup)
        return
    await event.answer(text, reply_markup=markup)


async def safe_send(bot, chat_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(chat_id, text, **kwargs)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False

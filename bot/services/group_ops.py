import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from bot.config import ROOT_DIR, settings

logger = logging.getLogger(__name__)

_resolved_chat_id: int | None = None
_GROUP_FILE = ROOT_DIR / "data" / "drivers_group.txt"


def _load_saved_id() -> int | None:
    if not _GROUP_FILE.exists():
        return None
    raw = _GROUP_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def bind_drivers_group(chat_id: int, title: str | None = None) -> None:
    global _resolved_chat_id
    _resolved_chat_id = chat_id
    _GROUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    _GROUP_FILE.write_text(str(chat_id), encoding="utf-8")
    logger.info("Haydovchilar maxfiy guruhi saqlandi: %s [%s]", title or "", chat_id)


def is_group_bound() -> bool:
    return _resolved_chat_id is not None


def group_id_candidates() -> list[int]:
    ids: list[int] = []
    saved = _load_saved_id()
    if saved is not None:
        ids.append(saved)
    raw = settings.supergroup_id
    if raw not in ids:
        ids.append(raw)
    return ids


def drivers_group_id() -> int:
    if _resolved_chat_id is not None:
        return _resolved_chat_id
    saved = _load_saved_id()
    if saved is not None:
        return saved
    return settings.supergroup_id


def _remember(chat_id: int) -> None:
    bind_drivers_group(chat_id)


async def resolve_drivers_group(bot: Bot) -> int | None:
    for cid in group_id_candidates():
        try:
            chat = await bot.get_chat(cid)
            bind_drivers_group(chat.id, getattr(chat, "title", None))
            return chat.id
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.warning("Guruh ID %s ishlamadi: %s", cid, exc)
    logger.error(
        "Haydovchilar guruhiga ulanib bo'lmadi. "
        "Maxfiy guruhda /ulanish buyrug'ini yozing. Sinab ko'rilgan ID: %s",
        group_id_candidates(),
    )
    return None


async def send_to_drivers_group(bot: Bot, text: str, **kwargs) -> Message:
    last_error: Exception | None = None
    tried: list[int] = []
    current = drivers_group_id()
    for cid in [current, *group_id_candidates()]:
        if cid in tried:
            continue
        tried.append(cid)
        try:
            sent = await bot.send_message(cid, text, **kwargs)
            _remember(cid)
            return sent
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            last_error = exc
            logger.warning("Guruhga yuborish %s: %s", cid, exc)
    raise last_error or RuntimeError("Haydovchilar guruhiga yuborib bo'lmadi")


async def create_one_time_invite(bot: Bot, user_id: int) -> str | None:
    expire = int(
        (datetime.now(timezone.utc) + timedelta(days=settings.trial_days + 1)).timestamp()
    )
    try:
        link = await bot.create_chat_invite_link(
            chat_id=drivers_group_id(),
            name=f"karvon_{user_id}",
            member_limit=1,
            expire_date=expire,
        )
        return link.invite_link
    except TelegramBadRequest as exc:
        logger.warning("Invite link yaratilmadi (user=%s): %s", user_id, exc)
        return None


async def kick_then_unban(bot: Bot, user_id: int) -> bool:
    try:
        await bot.ban_chat_member(chat_id=drivers_group_id(), user_id=user_id)
        await bot.unban_chat_member(
            chat_id=drivers_group_id(), user_id=user_id, only_if_banned=True
        )
        return True
    except TelegramBadRequest as exc:
        logger.warning("Guruhdan chiqarib bo'lmadi (user=%s): %s", user_id, exc)
        return False

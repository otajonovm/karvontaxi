from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bot.config import settings


def tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_tashkent(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz())


def format_tashkent(dt: datetime, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return to_tashkent(dt).strftime(fmt)


def format_price(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + f" {settings.currency}"

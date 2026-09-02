import logging
from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import settings
from bot.database.db_requests import (
    is_driver_access_active,
    list_drivers_for_scheduler,
)
from bot.database.models import DriverStatus
from bot.keyboards.inline_kb import feedback_kb, subscribe_kb
from bot.services.group_ops import kick_then_unban
from bot.services.ui import html_escape, safe_send
from bot.utils.dt import format_price, now_utc

logger = logging.getLogger(__name__)


def _day_number(driver) -> int:
    return (now_utc().date() - driver.trial_started_at.date()).days + 1


def _subscribe_text() -> str:
    card = f"\n💳 Karta: <code>{html_escape(settings.payment_card)}</code>" if settings.payment_card else ""
    info = f"\n{html_escape(settings.payment_info)}" if settings.payment_info else ""
    return (
        "⏰ <b>Sinov muddati tugaydi</b>\n\n"
        "Guruhda qolish va buyurtmalarni qabul qilish uchun oylik obunani rasmiylashtiring.\n"
        f"💵 Narxi: <b>{format_price(settings.subscription_price)}</b> / {settings.subscription_days} kun"
        f"{card}{info}\n\n"
        "To'lovni amalga oshirgach, pastdagi tugmani bosing."
    )


async def check_driver_subscriptions(bot: Bot, session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        drivers = await list_drivers_for_scheduler(session)
        moment = now_utc()
        for driver in drivers:
            try:
                await _process_driver(bot, session, driver, moment)
            except Exception:
                logger.exception("Haydovchi #%s tekshiruvida xato", driver.id)
        await session.commit()


async def _process_driver(bot, session, driver, moment) -> None:
    paid = bool(driver.subscription_until and driver.subscription_until > moment)
    if paid:
        if driver.status != DriverStatus.ACTIVE:
            driver.status = DriverStatus.ACTIVE
        driver.kicked_day8 = False
        return

    day = _day_number(driver)
    trial_active = driver.trial_ends_at > moment

    if trial_active and day >= 5 and not driver.feedback_day5_sent:
        sent = await safe_send(
            bot,
            driver.telegram_id,
            "👋 <b>Xizmatimiz qanday ketyapti?</b>\n\n"
            "2 kundan so'ng sinov muddati tugaydi. "
            "Fikringiz biz uchun muhim — qisqa baho qoldiring.",
            reply_markup=feedback_kb(),
        )
        if sent:
            driver.feedback_day5_sent = True
            logger.info("Day-5 eslatma yuborildi: %s", driver.telegram_id)

    if day >= settings.trial_days and not driver.day7_offer_sent:
        sent = await safe_send(
            bot,
            driver.telegram_id,
            _subscribe_text(),
            reply_markup=subscribe_kb(),
        )
        if sent:
            driver.day7_offer_sent = True
            logger.info("Day-7 obuna taklifi yuborildi: %s", driver.telegram_id)

    if day >= settings.trial_days + 1 and not is_driver_access_active(driver, moment):
        driver.status = DriverStatus.EXPIRED
        if not driver.kicked_day8:
            await kick_then_unban(bot, driver.telegram_id)
            await safe_send(
                bot,
                driver.telegram_id,
                "⛔️ <b>Sinov muddati tugadi</b>\n\n"
                "Siz haydovchilar guruhidan chiqarildingiz. "
                "Qayta qo'shilish uchun obunani to'lang, admin tasdiqlagach "
                "yangi taklif havolasi yuboriladi.\n\n" + _subscribe_text(),
                reply_markup=subscribe_kb(),
            )
            driver.kicked_day8 = True
            logger.info("Day-8 kick: %s", driver.telegram_id)

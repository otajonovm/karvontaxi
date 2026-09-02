import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import settings  # noqa: E402
from bot.database.engine import SessionFactory, dispose_engine, init_db  # noqa: E402
from bot.handlers import setup_routers  # noqa: E402
from bot.middlewares.db import DatabaseMiddleware  # noqa: E402
from bot.services.group_ops import resolve_drivers_group  # noqa: E402
from bot.services.scheduler import check_driver_subscriptions  # noqa: E402
from bot.utils.dt import tz  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("karvon")


async def main() -> None:
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DatabaseMiddleware(SessionFactory))
    dp.include_router(setup_routers())

    @dp.error()
    async def on_error(event: ErrorEvent) -> bool:
        logger.exception("Update xatosi: %s", event.exception)
        return True

    scheduler = AsyncIOScheduler(timezone=tz())
    scheduler.add_job(
        check_driver_subscriptions,
        CronTrigger(hour=9, minute=0, timezone=tz()),
        kwargs={"bot": bot, "session_factory": SessionFactory},
        id="daily_subscription_check",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        check_driver_subscriptions,
        CronTrigger(hour=21, minute=0, timezone=tz()),
        kwargs={"bot": bot, "session_factory": SessionFactory},
        id="evening_subscription_check",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("Scheduler ishga tushdi (09:00 va 21:00, %s)", settings.timezone)

    async def on_startup() -> None:
        me = await bot.get_me()
        group_id = await resolve_drivers_group(bot)
        logger.info(
            "Bot @%s ishga tushdi. Haydovchilar guruhi: %s",
            me.username,
            group_id or "ULANMAGAN",
        )
        if group_id is None:
            logger.warning(
                "Guruh hali ulanmagan. Maxfiy haydovchilar guruhida /ulanish yozing."
            )
        if not settings.admin_id_list:
            logger.warning("ADMIN_IDS bo'sh — admin panel ishlamaydi. .env ga Telegram ID qo'ying.")

    dp.startup.register(on_startup)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "callback_query",
                "my_chat_member",
                "edited_message",
            ],
        )
    finally:
        scheduler.shutdown(wait=False)
        await dispose_engine()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("To'xtatildi.")

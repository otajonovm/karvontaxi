from aiogram import Router

from bot.handlers.admin import router as admin_router
from bot.handlers.driver import router as driver_router
from bot.handlers.group import router as group_router
from bot.handlers.passenger import router as passenger_router


def setup_routers() -> Router:
    root = Router(name="root")
    root.include_router(admin_router)
    root.include_router(group_router)
    root.include_router(driver_router)
    root.include_router(passenger_router)
    return root

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.config import settings
from bot.database.models import Base

_engine_kwargs: dict = {
    "echo": False,
    "future": True,
    "pool_pre_ping": True,
}

if settings.is_postgres:
    _engine_kwargs.update(
        pool_size=5,
        max_overflow=5,
        pool_recycle=280,
    )
    if settings.postgres_ssl:
        _engine_kwargs["connect_args"] = {"ssl": True}

engine: AsyncEngine = create_async_engine(settings.database_url, **_engine_kwargs)

SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    await engine.dispose()

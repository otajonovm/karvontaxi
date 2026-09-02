from sqlalchemy import inspect, text
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

_ORDER_COLUMNS = {
    "accepted_driver_id": "BIGINT",
    "rejected_drivers": "TEXT",
    "cancel_reason": "VARCHAR(255)",
}
_DRIVER_COLUMNS = {
    "claim_cooldown_until": "TIMESTAMP" if settings.is_postgres else "DATETIME",
}


def _add_missing_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if "orders" in tables:
        existing = {col["name"] for col in inspector.get_columns("orders")}
        for name, ddl in _ORDER_COLUMNS.items():
            if name not in existing:
                default = " DEFAULT '[]'" if name == "rejected_drivers" else ""
                sync_conn.execute(
                    text(f"ALTER TABLE orders ADD COLUMN {name} {ddl}{default}")
                )
    if "drivers" in tables:
        existing = {col["name"] for col in inspector.get_columns("drivers")}
        for name, ddl in _DRIVER_COLUMNS.items():
            if name not in existing:
                sync_conn.execute(text(f"ALTER TABLE drivers ADD COLUMN {name} {ddl}"))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def dispose_engine() -> None:
    await engine.dispose()

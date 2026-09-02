from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.database.models import (
    Driver,
    DriverStatus,
    Order,
    OrderStatus,
    OrderType,
    PaymentRequest,
    PaymentStatus,
    ReturnTrip,
    TripBooking,
    TripStatus,
    User,
    UserRole,
)
from bot.utils.dt import now_utc


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    username: str | None,
) -> User:
    user = await session.get(User, telegram_id)
    if user is None:
        role = UserRole.ADMIN if settings.is_admin(telegram_id) else UserRole.PASSENGER
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            role=role,
        )
        session.add(user)
        await session.flush()
        return user

    user.full_name = full_name
    user.username = username
    if settings.is_admin(telegram_id) and user.role != UserRole.ADMIN:
        user.role = UserRole.ADMIN
    await session.flush()
    return user


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.get(User, telegram_id)


async def save_user_phone(session: AsyncSession, telegram_id: int, phone: str) -> None:
    user = await session.get(User, telegram_id)
    if user:
        user.phone = phone
        await session.flush()


async def get_driver_by_telegram(
    session: AsyncSession, telegram_id: int
) -> Driver | None:
    result = await session.execute(
        select(Driver)
        .options(selectinload(Driver.user))
        .where(Driver.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


def is_driver_access_active(driver: Driver, moment: datetime | None = None) -> bool:
    moment = moment or now_utc()
    if driver.status == DriverStatus.BANNED:
        return False
    if driver.subscription_until and driver.subscription_until > moment:
        return True
    if driver.trial_ends_at and driver.trial_ends_at > moment:
        return True
    return False


async def create_driver(
    session: AsyncSession,
    *,
    telegram_id: int,
    full_name: str,
    car_model: str,
    car_number: str,
    phone: str,
    invite_link: str | None,
) -> Driver:
    started = now_utc()
    driver = Driver(
        telegram_id=telegram_id,
        full_name=full_name,
        car_model=car_model,
        car_number=car_number.upper(),
        phone=phone,
        status=DriverStatus.TRIAL,
        trial_started_at=started,
        trial_ends_at=started + timedelta(days=settings.trial_days),
        invite_link=invite_link,
    )
    session.add(driver)
    user = await session.get(User, telegram_id)
    if user and user.role != UserRole.ADMIN:
        user.role = UserRole.DRIVER
        user.phone = phone
    await session.flush()
    return driver


async def create_order(
    session: AsyncSession,
    *,
    passenger_id: int,
    order_type: OrderType,
    from_location: str,
    to_location: str,
    departure_time: str,
    phone: str,
    passengers_count: int | None = None,
    cargo_type: str | None = None,
) -> Order:
    order = Order(
        passenger_id=passenger_id,
        order_type=order_type,
        from_location=from_location,
        to_location=to_location,
        departure_time=departure_time,
        phone=phone,
        passengers_count=passengers_count,
        cargo_type=cargo_type,
        status=OrderStatus.NEW,
    )
    session.add(order)
    await session.flush()
    return order


async def set_order_group_message(
    session: AsyncSession, order_id: int, message_id: int
) -> None:
    order = await session.get(Order, order_id)
    if order:
        order.group_message_id = message_id
        await session.flush()


async def get_order(session: AsyncSession, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order)
        .options(
            selectinload(Order.passenger),
            selectinload(Order.driver).selectinload(Driver.user),
        )
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def claim_order_atomic(
    session: AsyncSession, order_id: int, driver: Driver
) -> Order | None:
    """Race-condition safe claim: only the first UPDATE with status=NEW wins."""
    stmt = (
        update(Order)
        .where(Order.id == order_id, Order.status == OrderStatus.NEW)
        .values(
            status=OrderStatus.ACCEPTED,
            driver_id=driver.id,
            claimed_at=now_utc(),
        )
    )
    result = await session.execute(stmt)
    await session.commit()
    if result.rowcount != 1:
        return None
    return await get_order(session, order_id)


async def create_return_trip(
    session: AsyncSession,
    *,
    driver_id: int,
    from_location: str,
    to_location: str,
    departure_at: datetime,
    seats: int,
    price: int,
) -> ReturnTrip:
    trip = ReturnTrip(
        driver_id=driver_id,
        from_location=from_location,
        to_location=to_location,
        departure_at=departure_at,
        seats=seats,
        available_seats=seats,
        price=price,
        status=TripStatus.ACTIVE,
    )
    session.add(trip)
    await session.flush()
    return trip


def _trip_query() -> Select[tuple[ReturnTrip]]:
    return (
        select(ReturnTrip)
        .options(selectinload(ReturnTrip.driver))
        .where(
            ReturnTrip.status == TripStatus.ACTIVE,
            ReturnTrip.available_seats > 0,
            ReturnTrip.departure_at >= now_utc(),
        )
        .order_by(ReturnTrip.departure_at.asc())
    )


async def search_return_trips(
    session: AsyncSession,
    from_query: str,
    to_query: str,
) -> list[ReturnTrip]:
    stmt = _trip_query().where(
        ReturnTrip.from_location.ilike(f"%{from_query}%"),
        ReturnTrip.to_location.ilike(f"%{to_query}%"),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_active_return_trips(session: AsyncSession) -> list[ReturnTrip]:
    result = await session.execute(_trip_query())
    return list(result.scalars().all())


async def get_return_trip(session: AsyncSession, trip_id: int) -> ReturnTrip | None:
    result = await session.execute(
        select(ReturnTrip)
        .options(selectinload(ReturnTrip.driver), selectinload(ReturnTrip.bookings))
        .where(ReturnTrip.id == trip_id)
    )
    return result.scalar_one_or_none()


async def list_driver_trips(session: AsyncSession, driver_id: int) -> list[ReturnTrip]:
    result = await session.execute(
        select(ReturnTrip)
        .where(ReturnTrip.driver_id == driver_id)
        .order_by(ReturnTrip.created_at.desc())
        .limit(20)
    )
    return list(result.scalars().all())


async def cancel_return_trip(
    session: AsyncSession, trip_id: int, driver_id: int
) -> bool:
    result = await session.execute(
        update(ReturnTrip)
        .where(
            ReturnTrip.id == trip_id,
            ReturnTrip.driver_id == driver_id,
            ReturnTrip.status == TripStatus.ACTIVE,
        )
        .values(status=TripStatus.CANCELLED)
    )
    await session.flush()
    return result.rowcount == 1


async def book_return_trip_atomic(
    session: AsyncSession,
    *,
    trip_id: int,
    passenger_id: int,
    seats: int,
    phone: str,
) -> ReturnTrip | None:
    trip = await get_return_trip(session, trip_id)
    if trip is None:
        return None
    existing = await session.execute(
        select(TripBooking).where(
            TripBooking.trip_id == trip_id,
            TripBooking.passenger_id == passenger_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None

    result = await session.execute(
        update(ReturnTrip)
        .where(
            ReturnTrip.id == trip_id,
            ReturnTrip.status == TripStatus.ACTIVE,
            ReturnTrip.available_seats >= seats,
        )
        .values(available_seats=ReturnTrip.available_seats - seats)
    )
    if result.rowcount != 1:
        return None

    session.add(
        TripBooking(
            trip_id=trip_id,
            passenger_id=passenger_id,
            seats=seats,
            phone=phone,
        )
    )
    await session.flush()
    refreshed = await get_return_trip(session, trip_id)
    if refreshed and refreshed.available_seats <= 0:
        refreshed.status = TripStatus.FULL
        await session.flush()
    await session.commit()
    return await get_return_trip(session, trip_id)


async def create_payment_request(
    session: AsyncSession, driver_id: int
) -> PaymentRequest | None:
    pending = await session.execute(
        select(PaymentRequest).where(
            PaymentRequest.driver_id == driver_id,
            PaymentRequest.status == PaymentStatus.PENDING,
        )
    )
    if pending.scalar_one_or_none() is not None:
        return None
    request = PaymentRequest(
        driver_id=driver_id,
        amount=settings.subscription_price,
        days=settings.subscription_days,
        status=PaymentStatus.PENDING,
    )
    session.add(request)
    await session.flush()
    return request


async def get_payment_request(
    session: AsyncSession, request_id: int
) -> PaymentRequest | None:
    result = await session.execute(
        select(PaymentRequest)
        .options(selectinload(PaymentRequest.driver))
        .where(PaymentRequest.id == request_id)
    )
    return result.scalar_one_or_none()


async def approve_payment(
    session: AsyncSession, request_id: int, admin_id: int
) -> Driver | None:
    request = await get_payment_request(session, request_id)
    if request is None or request.status != PaymentStatus.PENDING:
        return None
    request.status = PaymentStatus.APPROVED
    request.admin_id = admin_id
    request.processed_at = now_utc()
    driver = request.driver
    moment = now_utc()
    base = driver.subscription_until if driver.subscription_until and driver.subscription_until > moment else moment
    driver.subscription_until = base + timedelta(days=request.days)
    driver.status = DriverStatus.ACTIVE
    driver.kicked_day8 = False
    await session.flush()
    return driver


async def reject_payment(
    session: AsyncSession, request_id: int, admin_id: int
) -> PaymentRequest | None:
    request = await get_payment_request(session, request_id)
    if request is None or request.status != PaymentStatus.PENDING:
        return None
    request.status = PaymentStatus.REJECTED
    request.admin_id = admin_id
    request.processed_at = now_utc()
    await session.flush()
    return request


async def grant_subscription(
    session: AsyncSession, telegram_id: int, days: int
) -> Driver | None:
    driver = await get_driver_by_telegram(session, telegram_id)
    if driver is None:
        return None
    moment = now_utc()
    base = (
        driver.subscription_until
        if driver.subscription_until and driver.subscription_until > moment
        else moment
    )
    driver.subscription_until = base + timedelta(days=days)
    driver.status = DriverStatus.ACTIVE
    driver.kicked_day8 = False
    await session.flush()
    return driver


async def list_pending_payments(session: AsyncSession) -> list[PaymentRequest]:
    result = await session.execute(
        select(PaymentRequest)
        .options(selectinload(PaymentRequest.driver))
        .where(PaymentRequest.status == PaymentStatus.PENDING)
        .order_by(PaymentRequest.created_at.asc())
    )
    return list(result.scalars().all())


async def list_drivers_for_scheduler(session: AsyncSession) -> list[Driver]:
    result = await session.execute(
        select(Driver).where(Driver.status != DriverStatus.BANNED)
    )
    return list(result.scalars().all())


async def list_recent_drivers(session: AsyncSession, limit: int = 15) -> list[Driver]:
    result = await session.execute(
        select(Driver).order_by(Driver.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_stats(session: AsyncSession) -> dict[str, int]:
    today_start = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    users = await session.scalar(select(func.count(User.telegram_id))) or 0
    drivers = await session.scalar(select(func.count(Driver.id))) or 0
    trial = await session.scalar(
        select(func.count(Driver.id)).where(Driver.status == DriverStatus.TRIAL)
    ) or 0
    active = await session.scalar(
        select(func.count(Driver.id)).where(Driver.status == DriverStatus.ACTIVE)
    ) or 0
    expired = await session.scalar(
        select(func.count(Driver.id)).where(Driver.status == DriverStatus.EXPIRED)
    ) or 0
    orders = await session.scalar(select(func.count(Order.id))) or 0
    orders_today = await session.scalar(
        select(func.count(Order.id)).where(Order.created_at >= today_start)
    ) or 0
    open_orders = await session.scalar(
        select(func.count(Order.id)).where(Order.status == OrderStatus.NEW)
    ) or 0
    trips = await session.scalar(
        select(func.count(ReturnTrip.id)).where(ReturnTrip.status == TripStatus.ACTIVE)
    ) or 0
    pending_pay = await session.scalar(
        select(func.count(PaymentRequest.id)).where(
            PaymentRequest.status == PaymentStatus.PENDING
        )
    ) or 0
    return {
        "users": users,
        "drivers": drivers,
        "trial": trial,
        "active": active,
        "expired": expired,
        "orders": orders,
        "orders_today": orders_today,
        "open_orders": open_orders,
        "trips": trips,
        "pending_pay": pending_pay,
    }


async def search_drivers(session: AsyncSession, query: str) -> list[Driver]:
    like = f"%{query}%"
    numeric = query.isdigit()
    conditions = [
        Driver.full_name.ilike(like),
        Driver.car_number.ilike(like),
        Driver.phone.ilike(like),
    ]
    if numeric:
        conditions.append(Driver.telegram_id == int(query))
    result = await session.execute(
        select(Driver).where(or_(*conditions)).limit(10)
    )
    return list(result.scalars().all())

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _enum(enum_cls: type[enum.Enum]):
    return Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda members: [item.value for item in members],
        length=32,
    )


class UserRole(str, enum.Enum):
    PASSENGER = "passenger"
    DRIVER = "driver"
    ADMIN = "admin"


class OrderType(str, enum.Enum):
    TAXI = "taxi"
    CARGO = "cargo"


class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


OPEN_ORDER_STATUSES = (OrderStatus.NEW, OrderStatus.PENDING)


class DriverStatus(str, enum.Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    BANNED = "banned"


class TripStatus(str, enum.Enum):
    ACTIVE = "active"
    FULL = "full"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class FeedbackRating(str, enum.Enum):
    GREAT = "great"
    OK = "ok"
    BAD = "bad"


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        _enum(UserRole), default=UserRole.PASSENGER, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    driver: Mapped[Driver | None] = relationship(
        back_populates="user", uselist=False, lazy="selectin"
    )
    orders: Mapped[list[Order]] = relationship(
        back_populates="passenger", foreign_keys="Order.passenger_id"
    )


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), unique=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    car_model: Mapped[str] = mapped_column(String(128), nullable=False)
    car_number: Mapped[str] = mapped_column(String(32), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[DriverStatus] = mapped_column(
        _enum(DriverStatus), default=DriverStatus.TRIAL, nullable=False
    )
    trial_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    trial_ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    subscription_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    feedback_day5_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    day7_offer_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    kicked_day8: Mapped[bool] = mapped_column(Boolean, default=False)
    claim_cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invite_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feedback_rating: Mapped[FeedbackRating | None] = mapped_column(
        _enum(FeedbackRating), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="driver")
    trips: Mapped[list[ReturnTrip]] = relationship(back_populates="driver")
    accepted_orders: Mapped[list[Order]] = relationship(
        back_populates="driver", foreign_keys="Order.driver_id"
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    passenger_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    driver_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("drivers.id"), nullable=True, index=True
    )
    accepted_driver_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    order_type: Mapped[OrderType] = mapped_column(_enum(OrderType), nullable=False)
    from_location: Mapped[str] = mapped_column(String(255), nullable=False)
    to_location: Mapped[str] = mapped_column(String(255), nullable=False)
    departure_time: Mapped[str] = mapped_column(String(128), nullable=False)
    passengers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cargo_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        _enum(OrderStatus), default=OrderStatus.NEW, nullable=False, index=True
    )
    group_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_drivers: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]", nullable=False
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    passenger: Mapped[User] = relationship(
        back_populates="orders", foreign_keys=[passenger_id]
    )
    driver: Mapped[Driver | None] = relationship(
        back_populates="accepted_orders", foreign_keys=[driver_id]
    )


class ReturnTrip(Base):
    __tablename__ = "return_trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.id"), nullable=False, index=True
    )
    from_location: Mapped[str] = mapped_column(String(255), nullable=False)
    to_location: Mapped[str] = mapped_column(String(255), nullable=False)
    departure_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    seats: Mapped[int] = mapped_column(Integer, nullable=False)
    available_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TripStatus] = mapped_column(
        _enum(TripStatus), default=TripStatus.ACTIVE, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    driver: Mapped[Driver] = relationship(back_populates="trips")
    bookings: Mapped[list[TripBooking]] = relationship(back_populates="trip")


class TripBooking(Base):
    __tablename__ = "trip_bookings"
    __table_args__ = (
        UniqueConstraint("trip_id", "passenger_id", name="uq_trip_passenger"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("return_trips.id"), nullable=False
    )
    passenger_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False
    )
    seats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    trip: Mapped[ReturnTrip] = relationship(back_populates="bookings")
    passenger: Mapped[User] = relationship()


class PaymentRequest(Base):
    __tablename__ = "payment_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        _enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False, index=True
    )
    admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    driver: Mapped[Driver] = relationship()


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)


class DriverCancelLog(Base):
    __tablename__ = "driver_cancel_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.id"), nullable=False, index=True
    )
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id"), nullable=False, index=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    initiated_by: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

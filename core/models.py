"""
Ani's data model, defined with SQLAlchemy.

This module has no Django imports so it can be used by the scrapers and by
standalone scripts as well as by the web application.
"""
from datetime import date as date_type, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(256))  # hashed, never plain text
    location: Mapped[str] = mapped_column(String(120), default="")
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    saved_crops: Mapped[List["SavedCrop"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by="SavedCrop.created_at"
    )
    alerts: Mapped[List["PriceAlert"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by="PriceAlert.created_at"
    )
    devices: Mapped[List["DeviceToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def first_name(self):
        return self.name.split()[0] if self.name else ""


class Crop(Base):
    __tablename__ = "crops"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)  # e.g. "Kamatis"
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    english_name: Mapped[str] = mapped_column(String(80), default="")  # e.g. "Tomato"
    category: Mapped[str] = mapped_column(String(40), default="Vegetables")
    unit: Mapped[str] = mapped_column(String(20), default="kg")
    icon: Mapped[str] = mapped_column(String(16), default="🌱")  # emoji shown next to the name
    image_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)

    prices: Mapped[List["CropPrice"]] = relationship(back_populates="crop")

    def __repr__(self):
        return f"<Crop {self.name}>"


class Market(Base):
    __tablename__ = "markets"
    __table_args__ = (UniqueConstraint("name", "location", name="uq_market_name_location"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))  # e.g. "Kadiwa"
    location: Mapped[str] = mapped_column(String(120), index=True)  # e.g. "Batangas"
    source: Mapped[str] = mapped_column(String(120))  # e.g. "Kadiwa price list"
    source_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    prices: Mapped[List["CropPrice"]] = relationship(back_populates="market")

    def __repr__(self):
        return f"<Market {self.name} ({self.location})>"


class CropPrice(Base):
    """One price observation. All rows for a crop/market over time form its price history."""

    __tablename__ = "crop_prices"
    __table_args__ = (
        # Prevents the same price from being stored twice by repeated scraper runs.
        UniqueConstraint("crop_id", "market_id", "date", "source", name="uq_price_per_day"),
        Index("ix_price_crop_date", "crop_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id", ondelete="CASCADE"))
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id", ondelete="CASCADE"))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    unit: Mapped[str] = mapped_column(String(20), default="kg")
    date: Mapped[date_type] = mapped_column(Date, index=True)  # the date the price applies to
    source: Mapped[str] = mapped_column(String(120))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    crop: Mapped[Crop] = relationship(back_populates="prices")
    market: Mapped[Market] = relationship(back_populates="prices")


class SavedCrop(Base):
    __tablename__ = "saved_crops"
    __table_args__ = (UniqueConstraint("user_id", "crop_id", name="uq_saved_crop"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="saved_crops")
    crop: Mapped[Crop] = relationship()


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    ABOVE = "above"
    BELOW = "below"
    CONDITIONS = (ABOVE, BELOW)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id", ondelete="CASCADE"))
    target_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    condition: Mapped[str] = mapped_column(String(10))  # "above" or "below"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Date of the price that last triggered this alert, so the same price
    # never sends the same notification twice.
    last_notified_on: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="alerts")
    crop: Mapped[Crop] = relationship()

    def is_met_by(self, price):
        if self.condition == self.ABOVE:
            return price >= self.target_price
        return price <= self.target_price


class Notification(Base):
    """An alert message shown inside Ani (and sent by push when possible)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    alert_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("price_alerts.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(300), default="")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    push_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="notifications")


class DeviceToken(Base):
    """A Firebase Cloud Messaging registration token for one of a user's devices."""

    __tablename__ = "device_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(512), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="devices")


class ScrapeRun(Base):
    """A log entry for one scraper run, used for monitoring and the Help page."""

    __tablename__ = "scrape_runs"

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(120), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=SUCCESS)
    records_found: Mapped[int] = mapped_column(Integer, default=0)
    records_saved: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")

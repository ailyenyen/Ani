"""
Price queries used by the pages.

Everything a farmer sees is answered here: the latest price of a crop, where
it comes from, whether it went up or down, and which market pays the most.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from django.conf import settings
from django.utils import timezone
from sqlalchemy import func, select
from sqlalchemy.orm import contains_eager

from .models import Crop, CropPrice, Market, SavedCrop, ScrapeRun

# "From last week" compares against the price about 7 days earlier.
CHANGE_WINDOW_DAYS = 7
# A market's latest price is shown only if it is at most this old.
FRESH_WITHIN_DAYS = 14

WHEN_CHOICES = [
    ("today", "Today", 0),
    ("yesterday", "Yesterday", 1),
    ("week", "1 week ago", 7),
    ("month", "1 month ago", 30),
]

RANGE_CHOICES = [
    (7, "7 Days"),
    (30, "30 Days"),
    (90, "3 Months"),
]


# Each market keeps the same colour in charts and lists (brand palette order).
MARKET_COLORS = ["#2E7D32", "#A5D6A7", "#FBC02D", "#F4E7C1"]
_MARKET_COLOR_ORDER = {"DA Bantay Presyo": 0, "Kadiwa": 1, "Local Market": 2, "Sari-sari Market": 3}


def market_color_index(market_name):
    if market_name in _MARKET_COLOR_ORDER:
        return _MARKET_COLOR_ORDER[market_name]
    return sum(map(ord, market_name)) % len(MARKET_COLORS)


def today():
    return timezone.localdate()


def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class PriceRow:
    """The latest price of one crop at one market."""

    crop: Crop
    market: Market
    price: Decimal
    date: object
    source: str
    previous_price: Optional[Decimal] = None

    @property
    def change_pct(self):
        if not self.previous_price:
            return None
        return float((self.price - self.previous_price) / self.previous_price * 100)

    @property
    def direction(self):
        pct = self.change_pct
        if pct is None:
            return None
        if pct >= 0.05:
            return "up"
        if pct <= -0.05:
            return "down"
        return "same"


@dataclass
class CropSummary:
    """One crop with its headline price and its prices at every market."""

    crop: Crop
    headline: PriceRow
    rows: List[PriceRow] = field(default_factory=list)

    @property
    def low(self):
        return min(r.price for r in self.rows)

    @property
    def high(self):
        return max(r.price for r in self.rows)

    @property
    def market_count(self):
        return len(self.rows)


# --- Lookups ----------------------------------------------------------------

def list_locations(db):
    return list(db.scalars(select(Market.location).distinct().order_by(Market.location)))


def list_crops(db, category=None):
    stmt = select(Crop).order_by(Crop.sort_order, Crop.name)
    if category:
        stmt = stmt.where(Crop.category == category)
    return list(db.scalars(stmt))


def list_categories(db):
    return list(db.scalars(select(Crop.category).distinct().order_by(Crop.category)))


def list_sources(db):
    return list(db.scalars(select(Market.source).distinct().order_by(Market.source)))


def get_crop(db, slug):
    return db.scalar(select(Crop).where(Crop.slug == slug))


def saved_crop_ids(db, user):
    if user is None:
        return []
    return list(
        db.scalars(
            select(SavedCrop.crop_id).where(SavedCrop.user_id == user.id).order_by(SavedCrop.created_at)
        )
    )


def as_of_for(when):
    for key, _label, days_ago in WHEN_CHOICES:
        if key == when:
            return today() - timedelta(days=days_ago)
    return today()


# --- Prices -----------------------------------------------------------------

def latest_prices(db, as_of=None, location=None, crop_ids=None, category=None, source=None):
    """
    The most recent price for every crop/market pair, on or before ``as_of``,
    with the price about a week earlier for the "up/down" indicator.
    """
    as_of = as_of or today()
    oldest = as_of - timedelta(days=FRESH_WITHIN_DAYS + CHANGE_WINDOW_DAYS + 7)

    stmt = (
        select(CropPrice)
        .join(CropPrice.market)
        .join(CropPrice.crop)
        .options(contains_eager(CropPrice.market), contains_eager(CropPrice.crop))
        .where(CropPrice.date <= as_of, CropPrice.date >= oldest)
        .order_by(CropPrice.date)
    )
    if location:
        stmt = stmt.where(Market.location == location)
    if crop_ids is not None:
        stmt = stmt.where(CropPrice.crop_id.in_(crop_ids))
    if category:
        stmt = stmt.where(Crop.category == category)
    if source:
        stmt = stmt.where(Market.source == source)

    history = defaultdict(list)
    for record in db.scalars(stmt):
        history[(record.crop_id, record.market_id)].append(record)

    rows = []
    stale_before = as_of - timedelta(days=FRESH_WITHIN_DAYS)
    for records in history.values():
        latest = records[-1]
        if latest.date < stale_before:
            continue
        compare_on_or_before = latest.date - timedelta(days=CHANGE_WINDOW_DAYS)
        previous = next((r for r in reversed(records) if r.date <= compare_on_or_before), None)
        rows.append(
            PriceRow(
                crop=latest.crop,
                market=latest.market,
                price=money(latest.price),
                date=latest.date,
                source=latest.source,
                previous_price=money(previous.price) if previous else None,
            )
        )

    rows.sort(key=lambda r: (r.crop.sort_order, r.crop.name, r.market.location, r.market.name))
    return rows


def pick_headline(rows):
    """Prefer the official reference source; otherwise the most recently updated price."""
    reference = settings.ANI_REFERENCE_SOURCE
    official = [r for r in rows if r.market.source == reference or r.source == reference]
    pool = official or rows
    return sorted(pool, key=lambda r: r.date, reverse=True)[0]


def summarize_by_crop(rows):
    by_crop = defaultdict(list)
    for row in rows:
        by_crop[row.crop.id].append(row)
    summaries = [
        CropSummary(crop=crop_rows[0].crop, headline=pick_headline(crop_rows), rows=crop_rows)
        for crop_rows in by_crop.values()
    ]
    summaries.sort(key=lambda s: (s.crop.sort_order, s.crop.name))
    return summaries


def sort_summaries(summaries, sort):
    if sort == "price_high":
        return sorted(summaries, key=lambda s: s.headline.price, reverse=True)
    if sort == "price_low":
        return sorted(summaries, key=lambda s: s.headline.price)
    if sort == "change":
        return sorted(summaries, key=lambda s: abs(s.headline.change_pct or 0), reverse=True)
    if sort == "name":
        return sorted(summaries, key=lambda s: s.crop.name)
    return summaries


def compare_markets(db, crop, location, as_of=None):
    """Latest price of one crop at each market in a location, highest first."""
    rows = latest_prices(db, as_of=as_of, location=location, crop_ids=[crop.id])
    return sorted(rows, key=lambda r: (-r.price, r.market.name))


def price_trend(db, crop, market, days, as_of=None):
    """Daily prices of a crop at one market: [(date, price), ...]."""
    as_of = as_of or today()
    start = as_of - timedelta(days=days - 1)
    stmt = (
        select(CropPrice.date, CropPrice.price)
        .where(
            CropPrice.crop_id == crop.id,
            CropPrice.market_id == market.id,
            CropPrice.date >= start,
            CropPrice.date <= as_of,
        )
        .order_by(CropPrice.date)
    )
    return [(d, money(p)) for d, p in db.execute(stmt)]


def price_stats(db, crop, location, days, as_of=None):
    """Highest, lowest and average price across a location's markets over a period."""
    as_of = as_of or today()
    start = as_of - timedelta(days=days - 1)
    base = (
        select(CropPrice)
        .join(CropPrice.market)
        .options(contains_eager(CropPrice.market))
        .where(CropPrice.crop_id == crop.id, CropPrice.date >= start, CropPrice.date <= as_of)
    )
    if location:
        base = base.where(Market.location == location)

    highest = db.scalar(base.order_by(CropPrice.price.desc(), CropPrice.date.desc()).limit(1))
    lowest = db.scalar(base.order_by(CropPrice.price.asc(), CropPrice.date.desc()).limit(1))
    avg_stmt = select(func.avg(CropPrice.price)).join(CropPrice.market).where(
        CropPrice.crop_id == crop.id, CropPrice.date >= start, CropPrice.date <= as_of
    )
    if location:
        avg_stmt = avg_stmt.where(Market.location == location)
    average = db.scalar(avg_stmt)

    if highest is None:
        return None
    return {
        "highest": highest,
        "lowest": lowest,
        "average": money(average),
    }


def chart_data(points, title):
    return {
        "title": title,
        "labels": [f"{d:%b} {d.day}" for d, _ in points],
        "values": [float(p) for _, p in points],
    }


def latest_scrape_runs(db):
    """Most recent run per source, for showing data freshness on the Help page."""
    latest_ids = select(func.max(ScrapeRun.id)).group_by(ScrapeRun.source)
    return list(db.scalars(select(ScrapeRun).where(ScrapeRun.id.in_(latest_ids)).order_by(ScrapeRun.source)))


def last_price_date(db):
    return db.scalar(select(func.max(CropPrice.date)))

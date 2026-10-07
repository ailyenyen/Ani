"""
Stores scraper results in the database and records every run in ``ScrapeRun``.

- Markets are created the first time a source mentions them.
- A price already stored for the same crop, market, date and source is not
  stored again (it is updated only if the source corrected the value).
- Prices that jump suspiciously far from the last known price are skipped and
  logged, since that usually means the page layout changed and a wrong column
  was read.
- One failing source never stops the others.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from core.models import Crop, CropPrice, Market, ScrapeRun

from .base import ScraperError

logger = logging.getLogger("scrapers")

# A new price more than 4x or less than 1/4 of the previous one is suspicious.
MAX_JUMP_RATIO = Decimal("4")


@dataclass
class StoreCounts:
    saved: int = 0
    updated: int = 0
    skipped: int = 0
    rejected: int = 0


def _get_or_create_market(db, record, cache):
    key = (record.market, record.location)
    if key in cache:
        return cache[key]
    market = db.scalar(select(Market).where(Market.name == record.market, Market.location == record.location))
    if market is None:
        market = Market(
            name=record.market, location=record.location, source=record.source, source_url=record.source_url or None
        )
        db.add(market)
        db.flush()
        logger.info("New market: %s (%s)", market.name, market.location)
    cache[key] = market
    return market


def _is_suspicious(db, crop, market, record):
    previous = db.scalar(
        select(CropPrice.price)
        .where(CropPrice.crop_id == crop.id, CropPrice.market_id == market.id, CropPrice.date < record.price_date)
        .order_by(CropPrice.date.desc())
        .limit(1)
    )
    if previous is None or previous == 0:
        return False
    ratio = record.price / previous
    return ratio > MAX_JUMP_RATIO or ratio < 1 / MAX_JUMP_RATIO


def store_records(db, result):
    counts = StoreCounts(rejected=len(result.rejected))
    crops = {c.name: c for c in db.scalars(select(Crop))}
    markets = {}

    for record in result.records:
        crop = crops.get(record.crop_name)
        if crop is None:
            logger.warning("Crop %r is not in the database; run `manage.py seed` first.", record.crop_name)
            counts.rejected += 1
            continue
        market = _get_or_create_market(db, record, markets)

        existing = db.scalar(
            select(CropPrice).where(
                CropPrice.crop_id == crop.id,
                CropPrice.market_id == market.id,
                CropPrice.date == record.price_date,
                CropPrice.source == record.source,
            )
        )
        if existing is not None:
            if existing.price == record.price:
                counts.skipped += 1
            else:
                logger.info(
                    "Corrected price for %s at %s on %s: %s -> %s",
                    crop.name, market.name, record.price_date, existing.price, record.price,
                )
                existing.price = record.price
                existing.collected_at = record.collected_at
                counts.updated += 1
            continue

        if _is_suspicious(db, crop, market, record):
            logger.warning(
                "Skipped suspicious price for %s at %s (%s): %s",
                crop.name, market.name, market.location, record.price,
            )
            counts.rejected += 1
            continue

        db.add(
            CropPrice(
                crop_id=crop.id,
                market_id=market.id,
                price=record.price,
                unit=record.unit,
                date=record.price_date,
                source=record.source,
                collected_at=record.collected_at,
            )
        )
        counts.saved += 1

    return counts


def run_scrapers(db, scrapers, today=None):
    """Run each scraper, store its results and log a ScrapeRun. Returns the ScrapeRun rows."""
    runs = []
    for scraper in scrapers:
        run = ScrapeRun(source=scraper.source_name, started_at=datetime.now(timezone.utc))
        try:
            result = scraper.run(today=today)
            counts = store_records(db, result)
            run.records_found = result.found
            run.records_saved = counts.saved
            run.records_updated = counts.updated
            run.records_skipped = counts.skipped
            run.records_rejected = counts.rejected
            run.status = ScrapeRun.PARTIAL if counts.rejected else ScrapeRun.SUCCESS
        except ScraperError as exc:
            db.rollback()
            run.status = ScrapeRun.FAILED
            run.error_message = str(exc)
            logger.error("[%s] %s", scraper.slug, exc)
        except Exception as exc:  # unexpected bug in one adapter must not stop the others
            db.rollback()
            run.status = ScrapeRun.FAILED
            run.error_message = f"{type(exc).__name__}: {exc}"
            logger.exception("[%s] Unexpected error", scraper.slug)
        run.finished_at = datetime.now(timezone.utc)
        db.add(run)
        db.commit()
        runs.append(run)
        logger.info(
            "[%s] %s: found %d, saved %d, updated %d, unchanged %d, rejected %d",
            scraper.slug, run.status, run.records_found, run.records_saved,
            run.records_updated, run.records_skipped, run.records_rejected,
        )
    return runs

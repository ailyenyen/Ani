"""Publish regional source records into the catalog used by every crop screen."""
from sqlalchemy import delete, select

from .models import CatalogQuote, Crop, CropPrice, Market, PriceEvidence, RegionalQuote


def remove_batch(db, source, region, category, day):
    ids = select(CatalogQuote.price_id).join(RegionalQuote).where(
        RegionalQuote.source == source, RegionalQuote.region == region,
        RegionalQuote.category == category, RegionalQuote.date == day,
    )
    db.execute(delete(CropPrice).where(CropPrice.id.in_(ids)).execution_options(synchronize_session=False))


def publish(db, quotes):
    crops = {c.slug: c for c in db.scalars(select(Crop))}
    markets = {(m.location, m.name): m for m in db.scalars(select(Market))}
    for q in quotes:
        slug = "market-" + q.product_key
        crop = crops.get(slug)
        if crop is None:
            spec = "Infanta" if q.specification.startswith("Variety/grade not specified") else q.specification
            name = f"{q.product} ({spec})"
            if len(name) > 80:
                name = name[:69] + " " + q.product_key[:10]
            crop = Crop(slug=slug, name=name, english_name=q.product, category=q.category, unit=q.unit)
            crops[slug] = crop
            db.add(crop)
        location = "NCR" if q.region.startswith("NCR (") else q.region
        key = (location, q.market)
        market = markets.get(key)
        if market is None:
            market = Market(name=q.market, location=location, source=q.source, source_url=q.source_url)
            markets[key] = market
            db.add(market)
        price = CropPrice(crop=crop, market=market, date=q.date, price=q.low, source=q.source,
                          unit=q.unit, collected_at=q.collected_at)
        price.evidence = PriceEvidence(source_url=q.source_url, report_start=q.date, report_end=q.date,
                                      raw_row=q.raw_row, sha256=q.sha256, note=q.specification)
        db.add(CatalogQuote(price=price, quote=q))


def backfill(db):
    pending = select(RegionalQuote).where(~RegionalQuote.id.in_(select(CatalogQuote.quote_id)))
    quotes = list(db.scalars(pending))
    publish(db, quotes)
    return len(quotes)

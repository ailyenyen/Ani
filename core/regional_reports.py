"""Lowest-price rankings only within the same product, specification, unit and date."""
import re
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select

from .models import RegionalQuote, RegionalImport


def family(product):
    text = product.casefold()
    if "rice" in text or "commercial (" in text or text == "nfa":
        return "Rice"
    aliases = {"tomato": "Tomato / Kamatis", "kamatis": "Tomato / Kamatis", "eggplant": "Eggplant / Talong", "talong": "Eggplant / Talong",
        "garlic": "Garlic / Bawang", "bawang": "Garlic / Bawang", "calamansi": "Calamansi", "kalamansi": "Calamansi",
        "carrot": "Carrot", "karot": "Carrot", "onion": "Onion", "sibuyas": "Onion", "potato": "Potato", "patatas": "Potato",
        "cabbage": "Cabbage", "repolyo": "Cabbage", "banana": "Banana", "lakatan": "Banana", "latundan": "Banana",
        "mango": "Mango", "mangga": "Mango", "chili": "Chili", "chilli": "Chili", "sili": "Chili"}
    return next((name for alias, name in aliases.items() if alias in text), product.title())


def build_report(db, as_of, days, regions=(), source="", crop="Tomato / Kamatis", product=""):
    cutoff = as_of - timedelta(days=days - 1)
    stmt = select(RegionalQuote).where(RegionalQuote.date >= cutoff, RegionalQuote.date <= as_of)
    if regions:
        stmt = stmt.where(RegionalQuote.region.in_(regions))
    if source:
        stmt = stmt.where(RegionalQuote.source == source)
    records = list(db.scalars(stmt.order_by(RegionalQuote.date.desc(), RegionalQuote.id.desc())))
    latest = {}
    for row in records:
        if family(row.product) == crop:
            latest.setdefault((row.source, row.region, row.market, row.product_key), row)
    records = list(latest.values())
    product_options = sorted({(r.product_key, r.product + " · " + r.specification) for r in records}, key=lambda x:x[1])
    if product:
        records = [r for r in records if r.product_key == product]
    grouped, by_source = defaultdict(list), defaultdict(list)
    for row in records:
        grouped[(row.product_key, row.date)].append(row)
        by_source[row.source].append(row)
    groups = []
    for (_, day), rows in grouped.items():
        rows.sort(key=lambda r: (r.low, r.high, r.region, r.market, r.source))
        lowest = rows[0].low
        winners = [r for r in rows if r.low == lowest]
        region_rows = defaultdict(list)
        for row in rows:
            region_rows[row.region].append(row)
        groups.append({"product": rows[0].product, "specification": rows[0].specification, "date": day,
            "rows": rows, "lowest": lowest, "winners": winners,
            "regional": [{"name": name, "low": items[0].low, "high": items[0].high,
                          "markets": [r for r in items if r.low == items[0].low]} for name, items in sorted(region_rows.items(), key=lambda item:(item[1][0].low,item[0]))]})
    groups.sort(key=lambda g:(g["product"], g["specification"], -g["date"].toordinal()))
    sources = [{"name": name, "count": len(rows), "regions": len({r.region for r in rows}),
        "products": len({r.product_key for r in rows}), "low": min(r.low for r in rows), "high": max(r.high for r in rows),
        "oldest": min(r.date for r in rows), "newest": max(r.date for r in rows)} for name, rows in sorted(by_source.items())]
    runs = {}
    for run in db.scalars(select(RegionalImport).order_by(RegionalImport.checked_at.desc(), RegionalImport.id.desc())):
        if (not regions or run.region in regions) and (not source or run.source == source):
            runs.setdefault((run.source, run.region, run.category), run)
    return {"groups": groups, "source_summary": sources, "records": records, "products": product_options,
            "runs": list(runs.values()), "cutoff": cutoff}

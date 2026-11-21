import json
from collections import defaultdict
from dataclasses import dataclass
from typing import NamedTuple
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from scrapers.psa_farmgate import SNAPSHOT, TABLE, VARIETIES

from scrapers.psa_openstat import FARMGATE, WHOLESALE

from . import market_overview, services
from .crop_families import CropFamily, identify_family, variety_name
from .market_overview import REGION_NAMES, REGIONS, PriceLine, freshness, pick_middle, psa_line, psa_rows_for, region_id, retail_average
from .models import CatalogQuote, Crop, CropPrice, Market, RegionalQuote


@dataclass(frozen=True)
class CropListing:
    crop: Crop
    family: CropFamily
    product: str
    specification: str
    variety: str


def catalog(db):
    products = {
        key: (product, specification)
        for key, product, specification in db.execute(select(
            RegionalQuote.product_key, RegionalQuote.product, RegionalQuote.specification,
        ).distinct().order_by(RegionalQuote.product, RegionalQuote.specification))
    }
    listings = {}
    for crop in services.list_crops(db):
        product, specification = products.get(crop.slug.removeprefix("market-"), (crop.english_name or crop.name, ""))
        family = identify_family(product)
        if not family.slug:
            family = CropFamily(crop.slug, family.name)
        listings[crop.id] = CropListing(crop, family, product, specification, variety_name(family, product, specification))
    return listings


def group_summaries(summaries, listings):
    """One preview per family, in the caller's priority order."""
    grouped = {}
    for summary in summaries:
        listing = listings[summary.crop.id]
        grouped.setdefault(listing.family.slug, {"family": listing.family, "listing": listing, "summary": summary})
    return list(grouped.values())


class CropFilters(forms.Form):
    variety = forms.ChoiceField(required=False)
    source = forms.ChoiceField(required=False, label="Price source")
    market = forms.TypedChoiceField(required=False, coerce=int, empty_value=None)
    date_from = forms.DateField(required=False, label="From date", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, label="Through date", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        values = super().clean()
        start, end = values.get("date_from"), values.get("date_to")
        if start and end and start > end:
            self.add_error("date_to", "Choose a date on or after the start date.")
        return values


def latest_banana_farmgate(variety=""):
    path = Path(settings.BASE_DIR) / "data" / "farmgate" / SNAPSHOT
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if snapshot["table"] != TABLE:
            return []
        current_month = services.today().replace(day=1)
        latest = {}
        for record in snapshot["observations"]:
            name = record["variety"]
            month = date.fromisoformat(record["month"])
            price = Decimal(record["price"])
            if name not in VARIETIES or (variety and name != variety) or month >= current_month:
                continue
            if price.is_finite() and price > 0 and (name not in latest or month > latest[name]["month"]):
                latest[name] = {"variety": name, "month": month, "price": price}
        return [latest[name] for name in VARIETIES if name in latest]
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
        return []


class MarketRow(NamedTuple):
    listing: CropListing
    price: CropPrice
    quote: RegionalQuote
    low: Decimal
    high: Decimal
    difference: Decimal   # midpoint minus the retail average shown above, when comparing latest reports
    bar: int              # bar length (upper end) in percent of the highest price on the page
    newest: bool          # the newest report on the page
    fresh: str
    low_bar: int = 0      # bar length of the lower end, when the market published a range


MARKET_SORTS = (("", "Lowest price first"), ("high", "Highest price first"), ("newest", "Newest first"))
VIEWS = ("markets", "regions")


def _psa_line(kind, series, area, slug, variety, fallback=True):
    rows, place = psa_rows_for(series, area, slug, fallback)
    rows = [row for row in rows if row.variety == variety] if variety else rows
    return psa_line(kind, rows, national=bool(area) and place == "ph")


def _farmgate_line(area, slug, variety, fallback=True):
    line = _psa_line("farmgate", FARMGATE, area, slug, variety, fallback)
    if line.value is not None or slug != "banana":
        return line
    # Banana farmgate comes from its own PSA table (national, by variety).
    line = PriceLine("farmgate", "Farmgate", "What farmers are paid")
    published = latest_banana_farmgate(variety)
    if published:
        shown = pick_middle(published, key=lambda row: (row["price"], row["variety"]))
        line.value = line.low = shown["price"]
        line.day, line.count = shown["month"], len(published)
        line.when = f"{line.day:%b %Y}"
        line.source_note = f"{shown['variety']} (green) · PSA monthly average, whole country"
    return line


def _family_base(request, slug):
    """What both crop pages share: the products, region, filters and the three price types."""
    db = request.db
    listings = {id_: item for id_, item in catalog(db).items() if item.family.slug == slug}
    if not listings:
        raise Http404("Crop not found")
    first = next(iter(listings.values()))
    region = market_overview.remembered_region(request)
    region_name = REGION_NAMES.get(region, "the Philippines")
    view = request.GET.get("view", "")
    view = view if view in VIEWS else "markets"
    varieties = defaultdict(list)
    for id_, item in listings.items():
        varieties[item.variety].append(id_)

    region_locations = [loc for loc in services.list_locations(db) if region_id(loc) == region] if region else None
    market_query = select(Market.id, Market.name, Market.location, CropPrice.source).join(CropPrice).where(
        CropPrice.crop_id.in_(listings)).distinct().order_by(Market.name, Market.location)
    if region_locations is not None:
        market_query = market_query.where(Market.location.in_(region_locations or ["-"]))
    markets_and_sources = list(db.execute(market_query))
    form = CropFilters(request.GET)
    form.fields["variety"].choices = [("", "All varieties")] + [(v, v) for v in sorted(varieties)]
    form.fields["variety"].widget.attrs["data-autosubmit"] = ""  # applies as soon as a variety is picked
    form.fields["source"].choices = [("", "All sources")] + [(s, s) for s in sorted({row[3] for row in markets_and_sources})]
    form.fields["market"].choices = [("", "All markets")] + list({id_: f"{name} · {location}" for id_, name, location, _ in markets_and_sources}.items())
    valid = form.is_valid()
    values = form.cleaned_data if valid else {}
    variety = values.get("variety", "")
    sort = request.GET.get("sort", "")
    sort = sort if sort in dict(MARKET_SORTS) else ""
    include_psa = not settings.ANI_SAMPLE_DATA_NOTICE

    # Retail: each market's latest report from every dataset, averaged per region.
    observations = [o for o in market_overview.retail_by_family(db, listings).get(slug, [])
                    if not variety or o["variety"] == variety]
    by_region = defaultdict(list)
    for observation in observations:
        by_region[region_id(observation["location"])].append(observation)
    retail = retail_average(by_region.get(region, []) if region else observations)

    if retail:
        # Where each dataset's average and the overall average sit between the lowest and highest report.
        span_ = (retail["high"] - retail["low"]) or 1
        place = lambda value: max(0, min(100, round((value - retail["low"]) / span_ * 100, 1)))
        retail["average_pos"] = place(retail["average"])
        for source in retail["sources"]:
            source["pos"] = place(source["average"])

    farmgate = _farmgate_line(region, slug, variety) if include_psa else None
    wholesale = _psa_line("wholesale", WHOLESALE, region, slug, variety) if include_psa else None

    keep = {key: request.GET.getlist(key) for key in ("variety", "source", "market", "date_from", "date_to", "sort", "range", "view", "snap")
            if key in request.GET}

    def link(**changes):
        params = request.GET.copy()
        for key in ("page", "location"):
            params.pop(key, None)
        for key, value in changes.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
        return "?" + params.urlencode()

    return {
        "db": db, "request": request, "slug": slug, "listings": listings, "first": first, "region": region, "region_name": region_name,
        "view": view, "varieties": varieties, "region_locations": region_locations, "form": form, "valid": valid,
        "values": values, "variety": variety, "sort": sort, "include_psa": include_psa, "observations": observations,
        "by_region": by_region, "retail": retail, "farmgate": farmgate, "wholesale": wholesale, "keep": keep, "link": link,
    }


def _context(base, **extra):
    first, region = base["first"], base["region"]
    return {
        "family": first.family, "form": base["form"], "region": region, "region_name": base["region_name"],
        "regions": REGIONS, "keep": base["keep"], "retail": base["retail"], "farmgate": base["farmgate"],
        "wholesale": base["wholesale"], "include_psa": base["include_psa"], "variety": base["variety"],
        "stand_in": base["slug"] in market_overview.FARMGATE_STAND_INS,
        "crop_slug": first.crop.slug,
        "saved": bool(set(services.saved_crop_ids(base["db"], getattr(base["request"], "ani_user", None))) & set(base["listings"])),
        "compare_markets_link": f"{reverse('crop_family_compare', args=[base['slug']])}{base['link'](view='markets')}",
        "compare_regions_link": f"{reverse('crop_family_compare', args=[base['slug']])}{base['link'](view='regions')}",
        **extra,
    }


def _region_rows(base):
    """Retail average and PSA wholesale/farmgate for the whole country and each region with any price."""
    slug, variety, include_psa = base["slug"], base["variety"], base["include_psa"]
    rows = []
    for key, name, _words in (("", "Whole country", ()), *REGIONS):
        average = retail_average(base["observations"] if not key else base["by_region"].get(key, []))
        # Each region shows only its own PSA figures here, so regions can be compared fairly.
        farm = _farmgate_line(key, slug, variety, fallback=False) if include_psa else None
        whole = _psa_line("wholesale", WHOLESALE, key, slug, variety, fallback=False) if include_psa else None
        if not average and not (farm and farm.value is not None) and not (whole and whole.value is not None):
            continue
        rows.append({"key": key, "name": name, "retail": average, "farmgate": farm, "wholesale": whole,
                     "current": key == base["region"]})
    return rows


def _row_value(row, kind):
    if kind == "retail":
        return row["retail"]["average"] if row["retail"] else None
    line = row[kind]
    return line.value if line is not None else None


SNAP_KINDS = (("retail", "Retail"), ("wholesale", "Wholesale"), ("farmgate", "Farmgate"))


def _snapshot(base, rows, kind):
    """The price snapshot: where the crop is cheapest, and the low and high ends in the chosen region."""
    region = base["region"]
    short = lambda name: name.split(" (")[0]
    region_name = short(base["region_name"])
    place = region_name if region else "the Philippines"
    ranked = sorted(((v, row) for row in rows if row["key"] and (v := _row_value(row, kind)) is not None),
                    key=lambda item: (item[0], item[1]["name"]))
    here = next((row for row in rows if row["key"] == region), None)
    here_value = _row_value(here, kind) if here else None
    cards = []
    cheapest = ranked[0] if ranked else None
    if cheapest:
        value, row = cheapest
        note, tone = "", ""
        if here_value is not None and row["key"] != region:
            note, tone = f"₱{here_value - value:,.2f} less than {short(here['name']) if region else 'the national average'}", "good"
        elif row["key"] == region:
            note, tone = "Your region is the cheapest", "good"
        cards.append({"icon": "pin", "title": "Cheapest region", "chip": "Nationwide", "value": value,
                      "name": row["name"], "note": note, "tone": tone,
                      "meta": "" if kind == "retail" else f"PSA monthly average · {row[kind].when}"})
    if kind == "retail":
        observations = base["observations"]
        mid = lambda o: (o["low"] + (o["high"] or o["low"])) / 2
        if observations:
            low = min(observations, key=lambda o: (o["low"], o["market"]))
            cards.append({"icon": "store", "title": "Cheapest market, any region", "chip": "Nationwide",
                          "value": low["low"], "high": low["high"] if low["high"] and low["high"] > low["low"] else None,
                          "name": low["market"].title(),
                          "meta": f"{REGION_NAMES.get(region_id(low['location']), low['location'])} · reported {low['day']:%b %-d}"})
        local = base["by_region"].get(region, []) if region else observations
        average = base["retail"]["average"] if base["retail"] else None
        for icon, title, pick, word in (("arrow-down", "Lowest in", min, "below"), ("arrow-up", "Highest in", max, "above")):
            if not local:
                continue
            o = pick(local, key=lambda o: (o["high"] or o["low"]) if pick is max else o["low"])
            value = (o["high"] or o["low"]) if pick is max else o["low"]
            gap = abs(mid(o) - average).quantize(Decimal("0.01"))
            cards.append({"icon": icon, "title": f"{title} {place}", "chip": "Your region" if region else "Nationwide",
                          "value": value, "name": o["market"].title(),
                          "note": f"₱{gap:,.2f} {word} the {'region' if region else 'national'} average" if gap else "Same as the average",
                          "tone": ("good" if word == "below" else "warn") if gap else "", "when": f"{o['day']:%b %-d}"})
        spread = (base["retail"]["high"] - base["retail"]["low"]) if base["retail"] else None
        spread_label = "spread within the region" if region else "spread across markets"
    else:
        if ranked:
            value, row = ranked[-1]
            note = f"₱{value - here_value:,.2f} more than {short(here['name'])}" if here_value is not None and row["key"] != region else ""
            cards.append({"icon": "arrow-up", "title": "Priciest region", "chip": "Nationwide", "value": value,
                          "name": row["name"], "note": note, "tone": "warn", "meta": f"PSA monthly average · {row[kind].when}"})
        line = base[kind]
        if region and line is not None and line.value is not None:
            national = rows[0][kind] if rows and not rows[0]["key"] else None
            note = ""
            if national is not None and national.value is not None and not line.national:
                gap = line.value - national.value
                note = f"₱{abs(gap):,.2f} {'below' if gap < 0 else 'above'} the national average" if gap else "Same as the national average"
            cards.append({"icon": "pin", "title": f"In {region_name}", "chip": "Your region", "value": line.value,
                          "name": line.source_note.split(" · ")[0], "note": note or ("Whole-country figure; none for this region" if line.national else ""),
                          "tone": "good" if national and national.value and line.value < national.value else "warn" if note else "",
                          "when": line.when})
        whole = rows[0][kind] if rows and not rows[0]["key"] else None
        if whole is not None and whole.value is not None:
            cards.append({"icon": "bars", "title": "Whole country", "chip": "Nationwide", "value": whole.value,
                          "name": whole.source_note.split(" · ")[0], "meta": f"PSA monthly average · {whole.when}"})
        spread = (ranked[-1][0] - ranked[0][0]) if len(ranked) > 1 else None
        spread_label = "spread between regions"
    rank = next((i for i, (_v, row) in enumerate(ranked, 1) if row["key"] == region), None) if region else None
    name = base["first"].family.name
    return {"kind": kind, "crop": name.split(" / ")[-1].lower() if " / " in name else name.lower(), "cards": cards[:4], "rank": rank, "of": len(ranked), "spread": spread,
            "spread_label": spread_label, "place": place}


def crop_family(request, slug):
    """One crop: the retail average for a region, the monthly trend, PSA averages and a price snapshot."""
    base = _family_base(request, slug)
    include_psa = base["include_psa"]
    region, farmgate, wholesale, retail, link = (base[k] for k in ("region", "farmgate", "wholesale", "retail", "link"))
    # Trend: PSA monthly averages, with today's retail average marked as the newest point.
    ranges = {key: months for key, _label, months in market_overview.RANGES}
    span = request.GET.get("range", "12")
    span = span if span in ranges else "12"
    chart = None
    if include_psa:
        retail_point = PriceLine("retail", "Retail", "")
        if retail:
            retail_point.value, retail_point.day = retail["average"], retail["newest"]["day"]
        chart = market_overview.price_history(slug, region, market_overview.TYPE_KEYS, ranges[span],
                                              [line for line in (farmgate, wholesale, retail_point) if line])
        if chart and len(chart["labels"]) < 2:
            chart = None


    snap = request.GET.get("snap", "retail")
    kinds = SNAP_KINDS if include_psa else SNAP_KINDS[:1]
    snap = snap if snap in dict(kinds) else "retail"
    rows = _region_rows(base)
    return render(request, "core/crop_family.html", _context(
        base, chart=chart, span=span,
        range_links=[(key, label, link(range=key) + "#trend") for key, label, _m in market_overview.RANGES],
        snapshot=_snapshot(base, rows, snap),
        snap_links=[(key, label, link(snap=key) + "#snapshot") for key, label in kinds],
    ))


def crop_family_compare(request, slug):
    """Compare one crop's prices: the markets inside a region, or the regions against each other."""
    base = _family_base(request, slug)
    db, listings, varieties, region_locations = (base[k] for k in ("db", "listings", "varieties", "region_locations"))
    valid, values, variety, sort, view, retail, link = (base[k] for k in ("valid", "values", "variety", "sort", "view", "retail", "link"))
    region = base["region"]
    # Markets: the latest report from each market (or every report in a chosen date range).
    has_date_range = False
    average_bar = None
    page = Paginator([], 25).get_page(1)
    if valid and view == "markets":
        product_ids = varieties[variety] if variety else listings
        candidates = select(CropPrice.id).where(CropPrice.crop_id.in_(product_ids), CropPrice.date <= services.today())
        if region_locations is not None:
            candidates = candidates.where(CropPrice.market.has(Market.location.in_(region_locations or ["-"])))
        if values["source"]:
            candidates = candidates.where(CropPrice.source == values["source"])
        if values["market"]:
            candidates = candidates.where(CropPrice.market_id == values["market"])
        if values["date_from"]:
            candidates = candidates.where(CropPrice.date >= values["date_from"])
        if values["date_to"]:
            candidates = candidates.where(CropPrice.date <= values["date_to"])
        has_date_range = bool(values["date_from"] or values["date_to"])
        if not has_date_range:
            latest = candidates.add_columns(func.row_number().over(
                partition_by=(CropPrice.crop_id, CropPrice.market_id, CropPrice.source, CropPrice.unit),
                order_by=(CropPrice.date.desc(), CropPrice.id.desc()),
            ).label("rank")).subquery()
            candidates = select(latest.c.id).where(latest.c.rank == 1)
        order = {"high": (CropPrice.price.desc(),), "newest": (CropPrice.date.desc(),)}.get(
            sort, (CropPrice.date.desc(),) if has_date_range else (CropPrice.price,))
        rows = select(CropPrice).where(CropPrice.id.in_(candidates)).options(
            joinedload(CropPrice.market), selectinload(CropPrice.evidence),
            selectinload(CropPrice.regional_listing).joinedload(CatalogQuote.quote),
        ).order_by(*order, CropPrice.date.desc(), CropPrice.id)
        total = db.scalar(select(func.count()).select_from(rows.order_by(None).subquery()))
        paginator = Paginator(range(total), 25)
        page = paginator.get_page(request.GET.get("page"))
        prices = list(db.scalars(rows.offset((page.number - 1) * paginator.per_page).limit(paginator.per_page)))
        ranged = []
        for price in prices:
            quote = price.regional_listing.quote if price.regional_listing else None
            low = Decimal(quote.low) if quote else Decimal(price.price)
            high = Decimal(quote.high) if quote and quote.high > quote.low else low
            ranged.append((price, quote, low, high))
        top = max([high for *_, high in ranged] + ([retail["average"]] if retail and not has_date_range else []), default=0) or 1
        newest_day = max((price.date for price, *_ in ranged), default=None)
        page.object_list = [
            MarketRow(listings[price.crop_id], price, quote, low, high,
                      ((low + high) / 2 - retail["average"]).quantize(Decimal("0.01")) if retail and not has_date_range else None,
                      max(2, round(high / top * 100)), price.date == newest_day, freshness(price.date),
                      max(2, round(low / top * 100)))
            for price, quote, low, high in ranged
        ]
        average_bar = round(retail["average"] / top * 100, 1) if retail and not has_date_range else None

    region_rows = []
    if view == "regions":
        region_rows = _region_rows(base)
        for row in region_rows:
            row["markets_link"] = link(region=row["key"], view="markets")
        # One shared scale so retail, wholesale and farmgate bars can be read against each other.
        top = max((v for row in region_rows for kind, _l in SNAP_KINDS if (v := _row_value(row, kind)) is not None), default=0) or 1
        for row in region_rows:
            row["bars"] = {kind: max(2, round(value / top * 100, 1)) if (value := _row_value(row, kind)) is not None else None
                           for kind, _l in SNAP_KINDS}
    region_name = base["region_name"]
    return render(request, "core/crop_family_compare.html", _context(
        base, view=view,
        view_links=[("markets", f"Markets in {REGION_NAMES[region]}" if region else "All markets", link(view="markets")),
                    ("regions", "Compare regions", link(view="regions"))],
        sort=sort, sort_choices=MARKET_SORTS, page=page, page_link=link(), has_date_range=has_date_range,
        region_rows=region_rows, average_bar=average_bar,
        crop_link=f"{reverse('crop_family', args=[slug])}?{urlencode({'region': region})}",
        compare_link=f"{reverse('compare')}?{urlencode({'crop': base['first'].family.name})}",
    ))

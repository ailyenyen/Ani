import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from django import forms
from django.conf import settings
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from scrapers.psa_farmgate import SNAPSHOT, SOURCE_URL, TABLE, VARIETIES

from . import services
from .crop_families import CropFamily, identify_family, variety_name
from .farmgate import crop_farmgate_preview
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
    location = forms.ChoiceField(required=False, label="Location")
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


def crop_family(request, slug):
    db = request.db
    listings = {id_: item for id_, item in catalog(db).items() if item.family.slug == slug}
    if not listings:
        raise Http404("Crop not found")
    first = next(iter(listings.values()))
    varieties = defaultdict(list)
    for id_, item in listings.items():
        varieties[item.variety].append(id_)

    markets_and_sources = list(db.execute(
        select(Market.id, Market.name, Market.location, CropPrice.source).join(CropPrice)
        .where(CropPrice.crop_id.in_(listings)).distinct().order_by(Market.name, Market.location)
    ))
    markets = {id_: f"{name} · {location}" for id_, name, location, _ in markets_and_sources}
    locations = sorted({location for _, _, location, _ in markets_and_sources})
    sources = sorted({source for _, _, _, source in markets_and_sources})
    form = CropFilters(request.GET)
    form.fields["variety"].choices = [("", "All varieties")] + [(v, v) for v in sorted(varieties)]
    form.fields["source"].choices = [("", "All sources")] + [(s, s) for s in sources]
    form.fields["market"].choices = [("", "All markets")] + list(markets.items())
    form.fields["location"].choices = [("", "All locations")] + [(loc, loc) for loc in locations]
    valid = form.is_valid()
    active = valid and any(form.cleaned_data.values())
    has_date_range = False

    if valid:
        values = form.cleaned_data
        product_ids = varieties[values["variety"]] if values["variety"] else listings
        candidates = select(CropPrice.id).where(CropPrice.crop_id.in_(product_ids), CropPrice.date <= services.today())
        if values["source"]:
            candidates = candidates.where(CropPrice.source == values["source"])
        if values["market"]:
            candidates = candidates.where(CropPrice.market_id == values["market"])
        if values["location"]:
            candidates = candidates.where(CropPrice.market.has(Market.location == values["location"]))
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

        rows = select(CropPrice).where(CropPrice.id.in_(candidates)).options(
            joinedload(CropPrice.market), selectinload(CropPrice.evidence),
            selectinload(CropPrice.regional_listing).joinedload(CatalogQuote.quote),
        ).order_by(CropPrice.date.desc(), CropPrice.crop_id, CropPrice.id)

        total = db.scalar(select(func.count()).select_from(rows.order_by(None).subquery()))
        paginator = Paginator(range(total), 25)
        page = paginator.get_page(request.GET.get("page"))
        observations = db.scalars(rows.offset((page.number - 1) * paginator.per_page).limit(paginator.per_page))
        page.object_list = [
            (listings[price.crop_id], price, price.regional_listing.quote if price.regional_listing else None)
            for price in observations
        ]
    else:
        page = Paginator([], 25).get_page(1)
    query = request.GET.copy()
    query.pop("page", None)
    show_farmgate = not settings.ANI_SAMPLE_DATA_NOTICE
    farmgate_prices, farmgate_has_crop = ([], False)
    if valid and show_farmgate:
        variety = form.cleaned_data.get("variety", "")
        farmgate_prices, farmgate_has_crop = crop_farmgate_preview(slug, variety)
        if slug == "banana" and not farmgate_has_crop:
            farmgate_prices = [dict(row, product=f"{row['variety']} (green)", unit="kg", source_url=SOURCE_URL)
                               for row in latest_banana_farmgate(variety)]
    return render(request, "core/crop_family.html", {
        "family": first.family, "form": form, "active_filters": active,
        "page": page, "filter_query": query.urlencode(), "has_date_range": has_date_range,
        "has_regional_comparisons": any(item.crop.slug.startswith("market-") for item in listings.values()),
        "show_farmgate": show_farmgate, "farmgate_has_crop": farmgate_has_crop,
        "farmgate_prices": farmgate_prices,
    })

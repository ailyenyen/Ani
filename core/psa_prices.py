"""Read the PSA monthly price snapshots (farmgate, wholesale, retail) separately from ANI's live retail catalog.

Each series is imported by its own ``sync_*`` command into ``data/<kind>/<table>.json``.
These are monthly averages published about two months after the fact, so they are shown
as an official reference next to the real-time retail prices, never mixed into them.
"""
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from django import forms
from django.conf import settings
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils.text import slugify

from scrapers.psa_openstat import FARMGATE, RETAIL, WHOLESALE

from .crop_families import CropFamily, identify_family, variety_name
from .services import today

# Previews on crop pages use this region; matched by name because each PSA table numbers locations differently.
HOME_REGION = "calabarzon"


@dataclass(frozen=True)
class PsaPrice:
    family: CropFamily
    series: str
    product: str
    variety: str
    location_code: str
    location: str
    level: str
    month: date
    price: str
    unit: str
    source_url: str


@dataclass(frozen=True)
class SeriesPage:
    """How one PSA series is presented in ANI."""

    series: object
    title: str
    noun: str
    lead: str
    price_heading: str
    url_name: str
    preview_hint: str


FARMGATE_PAGE = SeriesPage(
    FARMGATE, "Farmgate Prices", "farmgate",
    "Browse the Philippine Statistics Authority’s monthly averages of prices received by producers.",
    "Farmgate price", "farmgate_prices",
    "Prices received by producers.",
)
WHOLESALE_PAGE = SeriesPage(
    WHOLESALE, "Wholesale Prices", "wholesale",
    "Browse the Philippine Statistics Authority’s monthly averages of prices traders sell at in bulk.",
    "Wholesale price", "wholesale_prices",
    "Prices traders sell at in bulk.",
)
RETAIL_PAGE = SeriesPage(
    RETAIL, "Monthly Retail Averages", "retail",
    "Browse the Philippine Statistics Authority’s monthly average retail prices. "
    "For the newest retail prices, use Retail Prices.",
    "Average retail price", "retail_monthly_prices",
    "Official monthly retail averages. Retail Prices has the newest daily and weekly reports.",
)
PAGES = (FARMGATE_PAGE, WHOLESALE_PAGE, RETAIL_PAGE)

_UNIT_WORDS = {"kg": "kg", "kilo": "kg", "kilogram": "kg", "pc": "piece", "pcs": "piece", "piece": "piece",
               "bundle": "bundle", "dozen": "dozen", "liter": "liter", "litre": "liter", "stem": "stem"}
_BYPRODUCT = re.compile(r"\b(?:hay|hays|straw)\b", re.IGNORECASE)
_QUANTITY = re.compile(r",\s*(\d+(?:\.\d+)?)\s*([a-z]+)\.?\s*$", re.IGNORECASE)


def _location(raw):
    level = "Province / city" if raw.startswith("....") else "Region" if raw.startswith("..") else "National"
    return re.sub(r"\s+(?:[a-z]|\d+)/$", "", raw.lstrip(".").strip()), level


def location_key(name):
    """A stable key for a place, independent of each table's own code and capitalisation."""
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _display_product(product):
    """'TOMATO, 1 KG' -> 'Tomato'. Labels that are not all capitals are kept as published."""
    text = _QUANTITY.sub("", product).strip()
    if text.isupper():
        text = re.sub(r"[A-Za-z]+", lambda m: m[0].capitalize(), text.lower())
    return text or product


def product_unit(product):
    """The unit of a published price, or "" when PSA defines it elsewhere (see the PSA table)."""
    quantity = _QUANTITY.search(product)
    if quantity:
        amount, word = quantity.groups()
        unit = _UNIT_WORDS.get(word.casefold())
        return unit if unit and float(amount) == 1 else ""
    text = product.casefold()
    explicit = re.search(r"(?:\bper\s+|/\s*)(piece|stem|bundle|dozen|liter|litre)\b", text)
    if explicit:
        return _UNIT_WORDS[explicit[1]]
    if "*" in product or re.search(r"\b[a-z]/", text):
        return ""
    return "kg"


@lru_cache(maxsize=40)
def _read_table(series, path, modified, size):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        table = data["table"]
        if table not in series.tables or path.stem != Path(table).stem:
            return {}
        locations = {}
        for code, label in data["locations"].items():
            name, level = _location(label)
            locations[code] = (location_key(name), name, level)
        products = {}
        for code, product in data["commodities"].items():
            shown = _display_product(product)
            family = identify_family(shown)
            if family.aliases and _BYPRODUCT.search(shown):
                # e.g. "Rice hay, dried hays" is animal feed, not rice: keep it out of the crop's prices.
                family = CropFamily(slugify(shown), shown)
            elif not family.aliases:
                family = identify_family(re.split(r"[,\[(]", shown, maxsplit=1)[0].strip() or shown)
            products[code] = (family, shown, variety_name(family, shown), product_unit(product))
        grouped = defaultdict(list)
        source_url = series.source_url(table)
        for commodity, area, month, price in data["observations"]:
            group, product, variety, unit = products[commodity]
            key, location, level = locations[area]
            grouped[group.slug].append(PsaPrice(group, f"{table}:{commodity}", product, variety, key, location,
                                                level, date.fromisoformat(month), price, unit, source_url))
        return grouped
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def catalog(series, family=""):
    folder = Path(settings.BASE_DIR) / "data" / series.kind
    records = []
    for table in series.tables:
        path = folder / (Path(table).stem + ".json")
        try:
            stat = path.stat()
        except OSError:
            continue
        groups = _read_table(series, path, stat.st_mtime_ns, stat.st_size)
        if family:
            records.extend(groups.get(family, ()))
        else:
            for rows in groups.values():
                records.extend(rows)
    return records


def latest_rows(rows):
    latest = {}
    for row in rows:
        key = (row.series, row.location_code)
        previous = latest.get(key)
        if previous is None or row.month > previous.month:
            latest[key] = row
    return list(latest.values())


def home_region_key(records):
    return next((row.location_code for row in records if row.level == "Region" and HOME_REGION in row.location_code), "")


def crop_preview(series, family, variety=""):
    """Latest home-region prices for one crop, and whether the series has the crop at all."""
    records = catalog(series, family)
    filtered = [row for row in records if not variety or row.variety == variety]
    region = home_region_key(records)
    local = latest_rows(row for row in filtered if region and row.location_code == region)
    return sorted(local, key=lambda row: (row.product.casefold(), row.series))[:6], bool(records)


def crop_previews(family, variety=""):
    """Preview cards for a crop page, in farmgate → wholesale → retail order."""
    previews = []
    for page in PAGES:
        prices, has_crop = crop_preview(page.series, family, variety)
        previews.append({"page": page, "prices": prices, "has_crop": has_crop})
    return previews


class SeriesFilters(forms.Form):
    crop = forms.ChoiceField(required=False, label="Crop")
    commodity = forms.ChoiceField(required=False, label="Product / variety")
    location = forms.ChoiceField(required=False, label="Geography")
    month = forms.TypedChoiceField(required=False, label="Reporting month", coerce=date.fromisoformat, empty_value=None)


def series_prices(request, page):
    records = catalog(page.series) if not settings.ANI_SAMPLE_DATA_NOTICE else []
    current_month = today().replace(day=1)
    records = [row for row in records if row.month < current_month]
    query = request.GET.copy()
    query.setdefault("location", home_region_key(records))
    family = query.get("crop", "")
    crop_choices = {row.family.slug: row.family.name for row in records}
    crop_records = [row for row in records if row.family.slug == family] if family else records
    commodities = {row.series: row.product for row in crop_records}
    areas = {}
    for row in records:
        areas.setdefault(row.location_code, f"{row.location} · {row.level}")
    months = sorted({row.month for row in crop_records}, reverse=True)
    form = SeriesFilters(query)
    form.fields["crop"].choices = [("", "All crops"), *sorted(crop_choices.items(), key=lambda item: item[1])]
    form.fields["crop"].widget.attrs.update({"data-autosubmit": True, "onchange": "this.form.elements.commodity.value=''; this.form.elements.month.value='';"})
    form.fields["commodity"].choices = [("", "All products"), *sorted(commodities.items(), key=lambda item: item[1])]
    form.fields["location"].choices = [("", "All published locations"), ("regions", "All regions"), ("provinces", "All provinces and cities"), *sorted(areas.items(), key=lambda item: item[1])]
    form.fields["month"].choices = [("", "Latest available"), *((month.isoformat(), month.strftime("%B %Y")) for month in months)]
    rows = []
    if form.is_valid():
        values = form.cleaned_data
        area = values["location"]
        level = {"regions": "Region", "provinces": "Province / city"}.get(area)
        for row in crop_records:
            if level and row.level != level:
                continue
            if area and not level and row.location_code != area:
                continue
            if values["commodity"] and row.series != values["commodity"]:
                continue
            if values["month"] and row.month != values["month"]:
                continue
            rows.append(row)
        if not values["month"]:
            rows = latest_rows(rows)
        rows.sort(key=lambda row: (row.family.name, row.product.casefold(), row.location, row.series))
    query.pop("page", None)
    return render(request, "core/psa_prices.html", {
        "series_page": page, "other_pages": [other for other in PAGES if other is not page],
        "form": form, "page": Paginator(rows, 30).get_page(request.GET.get("page")),
        "filter_query": query.urlencode(), "has_catalog": bool(records),
    })


def wholesale_prices(request):
    return series_prices(request, WHOLESALE_PAGE)


def retail_monthly_prices(request):
    return series_prices(request, RETAIL_PAGE)

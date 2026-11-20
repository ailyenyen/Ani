"""Read the official farmgate snapshots separately from ANI's retail catalog."""
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

from scrapers.psa_farmgate import CROP_TABLES, REGION_CODE, SOURCE_URL, TABLE

from .crop_families import CropFamily, identify_family, variety_name
from .services import today


@dataclass(frozen=True)
class FarmgatePrice:
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


def _location(raw):
    level = "Province / city" if raw.startswith("....") else "Region" if raw.startswith("..") else "National"
    return re.sub(r"\s+(?:[a-z]|\d+)/$", "", raw.lstrip(".").strip()), level


def _product_unit(product):
    text = product.casefold()
    explicit = re.search(r"(?:\bper\s+|/\s*)(piece|stem|bundle|dozen|liter|litre)\b", text)
    if explicit:
        return explicit[1]
    if "*" in product or re.search(r"\b[a-z]/", text):
        return ""
    return "kg"


@lru_cache(maxsize=20)
def _read_table(path, modified, size):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        table = data["table"]
        if table not in CROP_TABLES or path.stem != Path(table).stem:
            return {}
        locations = {code: _location(label) for code, label in data["locations"].items()}
        products = {}
        for code, product in data["commodities"].items():
            family = identify_family(product)
            if not family.aliases:
                family = identify_family(re.split(r"[,\[(]", product, maxsplit=1)[0].strip() or product)
            products[code] = (family, product, variety_name(family, product), _product_unit(product))
        grouped = defaultdict(list)
        for commodity, area, month, price in data["observations"]:
            group, product, variety, unit = products[commodity]
            location, level = locations[area]
            grouped[group.slug].append(FarmgatePrice(group, f"{table}:{commodity}", product, variety, area, location,
                                                    level, date.fromisoformat(month), price, unit, SOURCE_URL.replace(TABLE, table)))
        return grouped
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def farmgate_catalog(family=""):
    folder = Path(settings.BASE_DIR) / "data" / "farmgate"
    records = []
    for table in CROP_TABLES:
        path = folder / (Path(table).stem + ".json")
        try:
            stat = path.stat()
        except OSError:
            continue
        groups = _read_table(path, stat.st_mtime_ns, stat.st_size)
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


def crop_farmgate_preview(family, variety=""):
    records = farmgate_catalog(family)
    filtered = [row for row in records if not variety or row.variety == variety]
    local = latest_rows(row for row in filtered if row.location_code == REGION_CODE)
    return sorted(local, key=lambda row: (row.product.casefold(), row.series))[:6], bool(records)


class FarmgateFilters(forms.Form):
    crop = forms.ChoiceField(required=False, label="Crop")
    commodity = forms.ChoiceField(required=False, label="Product / variety")
    location = forms.ChoiceField(required=False, label="Geography")
    month = forms.TypedChoiceField(required=False, label="Reporting month", coerce=date.fromisoformat, empty_value=None)


def farmgate_prices(request):
    records = farmgate_catalog() if not settings.ANI_SAMPLE_DATA_NOTICE else []
    current_month = today().replace(day=1)
    records = [row for row in records if row.month < current_month]
    query = request.GET.copy()
    query.setdefault("location", REGION_CODE if records and any(row.location_code == REGION_CODE for row in records) else "")
    family = query.get("crop", "")
    crop_choices = {row.family.slug: row.family.name for row in records}
    crop_records = [row for row in records if row.family.slug == family] if family else records
    commodities = {row.series: row.product for row in crop_records}
    areas = {row.location_code: f"{row.location} · {row.level}" for row in records}
    months = sorted({row.month for row in crop_records}, reverse=True)
    form = FarmgateFilters(query)
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
    return render(request, "core/farmgate_prices.html", {
        "form": form, "page": Paginator(rows, 30).get_page(request.GET.get("page")),
        "filter_query": query.urlencode(), "has_catalog": bool(records),
    })

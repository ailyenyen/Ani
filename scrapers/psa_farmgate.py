"""Fetch monthly crop farmgate values from the PSA OpenSTAT crop tables."""
import calendar
import json
from datetime import date
from decimal import Decimal

from .base import ScraperError

TABLE = "0032M4AFN07.px"
API_URL = f"https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB/2M/NFG/{TABLE}"
SOURCE_URL = f"https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__NFG/{TABLE}/"
SNAPSHOT = "psa-banana-calabarzon.json"
VARIETIES = ("Lakatan", "Latundan", "Saba")
REGION_CODE = "040000000"
CROP_TABLES = {
    f"0032M4AFN{index:02d}.px": category for index, category in enumerate((
        "Cereals", "Root crops", "Beans and legumes", "Condiments", "Fruit vegetables",
        "Leafy vegetables", "Fruits", "Commercial crops", "Cutflowers",
    ), 1)
}


def _read_reply(response):
    response.raise_for_status()
    return json.loads(response.content.decode("utf-8-sig"))


def fetch_crop_farmgate(session, table, as_of):
    """Fetch the current and previous calendar years, retaining PSA series identifiers."""
    url = API_URL.replace(TABLE, table)
    try:
        metadata = _read_reply(session.get(url, timeout=(10, 25)))
        dimensions = {v["code"]: dict(zip(v["values"], v["valueTexts"], strict=True)) for v in metadata["variables"]}
        if set(dimensions) != {"Geolocation", "Commodity", "Year", "Period"}:
            raise ScraperError("Unexpected PSA farmgate dimensions.")
        locations = dimensions["Geolocation"]
        commodities = dimensions["Commodity"]
        years = {code: int(label) for code, label in dimensions["Year"].items()
                 if label.isdigit() and as_of.year - 1 <= int(label) <= as_of.year}
        month_names = {calendar.month_name[index]: index for index in range(1, 13)}
        periods = {code: month_names[label] for code, label in dimensions["Period"].items() if label in month_names}
        rows = {}
        for year_code, year in years.items():
            selected_periods = {code: month for code, month in periods.items() if date(year, month, 1) < as_of.replace(day=1)}
            if not selected_periods:
                continue
            selection = {"Geolocation": list(locations), "Commodity": list(commodities), "Year": [year_code], "Period": list(selected_periods)}
            query = [{"code": key, "selection": {"filter": "item", "values": values}} for key, values in selection.items()]
            reply = _read_reply(session.post(url, json={"query": query, "response": {"format": "json"}}, timeout=(10, 45)))
            columns = [column["code"] for column in reply["columns"] if column["code"] in selection]
            fixed = {name: values[0] for name, values in selection.items() if len(values) == 1 and name not in columns}
            if len(columns) != len(set(columns)) or set(columns) | fixed.keys() != selection.keys():
                raise ScraperError(f"Unexpected PSA farmgate dimensions in results: {columns!r}.")
            if len(reply["data"]) != len(locations) * len(commodities) * len(selected_periods):
                raise ScraperError("PSA returned an incomplete set of monthly cells.")
            for cell in reply["data"]:
                key = {**fixed, **dict(zip(columns, cell["key"], strict=True))}
                commodity, location = key["Commodity"], key["Geolocation"]
                if commodity not in commodities or location not in locations or key["Year"] != year_code:
                    raise ScraperError("PSA returned a series outside the request.")
                month = date(year, selected_periods[key["Period"]], 1).isoformat()
                row_id = (commodity, location, month)
                if row_id in rows:
                    raise ScraperError("Duplicate PSA farmgate cell.")
                value, = cell["values"]
                if value is None or str(value).strip() in {"", ".", "..", "...", "-"}:
                    rows[row_id] = None
                    continue
                price = Decimal(str(value))
                if not price.is_finite() or price < 0:
                    raise ScraperError("Invalid PSA farmgate price.")
                rows[row_id] = str(price) if price else None
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        raise ScraperError(f"Unrecognized PSA farmgate response: {exc}") from exc

    observations = [[*key, value] for key, value in rows.items() if value is not None]
    if not observations:
        raise ScraperError("PSA returned no published farmgate prices for this table.")
    return {"table": table, "retrieved_on": as_of.isoformat(), "commodities": commodities,
            "locations": locations, "observations": observations}


def fetch_banana_farmgate(session, as_of):
    """Return verified monthly values; leave unpublished cells out of the result."""
    try:
        metadata = _read_reply(session.get(API_URL, timeout=(10, 25)))
        dimensions = {
            v["code"]: dict(zip(v["valueTexts"], v["values"], strict=True)) for v in metadata["variables"]
        }
        if set(dimensions) != {"Geolocation", "Commodity", "Year", "Period"}:
            raise ScraperError("PSA fruit farmgate dimension names changed.")
        if not any(code == REGION_CODE and "CALABARZON" in label.upper()
                   for label, code in dimensions["Geolocation"].items()):
            raise ScraperError("PSA CALABARZON geography no longer matches the configured series.")

        commodities = {dimensions["Commodity"][f"Banana {variety}, green"]: variety for variety in VARIETIES}
        years = {code: int(label) for label, code in dimensions["Year"].items()
                 if label.isdigit() and as_of.year - 1 <= int(label) <= as_of.year}
        months = {dimensions["Period"][calendar.month_name[i]]: i for i in range(1, 13)}
        selections = {"Geolocation": [REGION_CODE], "Commodity": list(commodities), "Year": list(years), "Period": list(months)}
        query = [{"code": key, "selection": {"filter": "item", "values": values}} for key, values in selections.items()]
        reply = _read_reply(session.post(API_URL, json={"query": query, "response": {"format": "json"}}, timeout=(10, 25)))
        columns = [col["code"] for col in reply["columns"] if col["type"] == "d"]
        if len(columns) != len(selections) or set(columns) != set(selections):
            raise ScraperError("PSA farmgate response did not use the expected dimensions.")
        rows = {}
        for cell in reply["data"]:
            keys = dict(zip(columns, cell["key"], strict=True))
            if keys["Geolocation"] != REGION_CODE:
                raise ScraperError("Unexpected geography in the PSA farmgate response.")
            variety = commodities[keys["Commodity"]]
            period = date(years[keys["Year"]], months[keys["Period"]], 1)
            value, = cell["values"]
            if period >= as_of.replace(day=1) or value is None or str(value).strip() in {"", ".", "..", "...", "-"}:
                continue
            price = Decimal(str(value))
            if not price.is_finite() or price < 0:
                raise ScraperError("Invalid amount in the PSA farmgate response.")
            if price == 0:
                continue
            if (variety, period) in rows:
                raise ScraperError("Duplicate variety and month in the PSA farmgate response.")
            rows[variety, period] = {"variety": variety, "month": period.isoformat(), "price": str(price)}
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        raise ScraperError(f"Unrecognized PSA farmgate response: {exc}") from exc

    if not rows:
        raise ScraperError("PSA returned no published prices for the pilot selection.")
    return [rows[key] for key in sorted(rows)]

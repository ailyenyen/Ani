"""Fetch monthly crop farmgate values from the PSA OpenSTAT crop tables."""
import calendar
from datetime import date
from decimal import Decimal

from .base import ScraperError
from .psa_openstat import FARMGATE, _pairs, fetch_table, read_reply

TABLE = "0032M4AFN07.px"
API_URL = f"https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB/2M/NFG/{TABLE}"
SOURCE_URL = f"https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__NFG/{TABLE}/"
SNAPSHOT = "psa-banana-calabarzon.json"
VARIETIES = ("Lakatan", "Latundan", "Saba")
REGION_CODE = "040000000"
CROP_TABLES = FARMGATE.tables


def _read_reply(response):
    return read_reply(response)


def fetch_crop_farmgate(session, table, as_of):
    """Fetch the current and previous calendar years, retaining PSA series identifiers."""
    return fetch_table(session, FARMGATE, table, as_of)


def fetch_banana_farmgate(session, as_of):
    """Return verified monthly values; leave unpublished cells out of the result."""
    try:
        metadata = _read_reply(session.get(API_URL, timeout=(10, 25)))
        dimensions = {
            v["code"]: _pairs(v["valueTexts"], v["values"]) for v in metadata["variables"]
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
            if len(cell["key"]) != len(columns):
                raise ValueError("PSA cell key does not match the result columns.")
            keys = dict(zip(columns, cell["key"]))
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

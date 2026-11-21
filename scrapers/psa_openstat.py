"""Fetch monthly crop prices from the PSA OpenSTAT price tables.

The Philippine Statistics Authority publishes three monthly price series with the
same layout (Geolocation × Commodity × Year × Period):

* farmgate prices received by producers,
* wholesale selling prices, and
* retail prices.

Each series is split into the same eight crop categories. One reader handles all
of them; each series only names its OpenSTAT folder and table identifiers.
"""
import calendar
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .base import ScraperError

API_ROOT = "https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB/2M"
PAGE_ROOT = "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__"
UNPUBLISHED = {"", ".", "..", "...", "-"}
CROP_CATEGORIES = (
    "Cereals", "Root crops", "Beans and legumes", "Condiments", "Fruit vegetables",
    "Leafy vegetables", "Fruits", "Commercial crops",
)


@dataclass(frozen=True, eq=False)  # compared by identity, so it can key caches
class PsaSeries:
    kind: str     # "farmgate", "wholesale" or "retail"; also the data/<kind>/ snapshot folder
    folder: str   # OpenSTAT folder, e.g. "NFG"
    tables: dict  # OpenSTAT table id -> crop category

    def api_url(self, table):
        return f"{API_ROOT}/{self.folder}/{table}"

    def source_url(self, table):
        return f"{PAGE_ROOT}{self.folder}/{table}/"


FARMGATE = PsaSeries("farmgate", "NFG", {
    f"0032M4AFN{index:02d}.px": category
    for index, category in enumerate((*CROP_CATEGORIES, "Cutflowers"), 1)
})
WHOLESALE = PsaSeries("wholesale", "NWSNEW", {
    f"0052M4AWB{index:02d}.px": category for index, category in enumerate(CROP_CATEGORIES, 1)
})
RETAIL = PsaSeries("retail", "2018NEW", {
    f"0042M4ARN{index:02d}.px": category for index, category in enumerate(CROP_CATEGORIES, 1)
})
SERIES = {series.kind: series for series in (FARMGATE, WHOLESALE, RETAIL)}


def read_reply(response):
    response.raise_for_status()
    return json.loads(response.content.decode("utf-8-sig"))


def _pairs(values, texts):
    if len(values) != len(texts):
        raise ValueError("PSA codes and labels have different lengths.")
    return dict(zip(values, texts))


def fetch_table(session, series, table, as_of):
    """Fetch the current and previous calendar years of one table, keeping PSA series identifiers.

    Months from the current month onward are never requested, and unpublished cells are
    left out of the result.
    """
    url = series.api_url(table)
    label = series.kind
    try:
        metadata = read_reply(session.get(url, timeout=(10, 25)))
        dimensions = {v["code"]: _pairs(v["values"], v["valueTexts"]) for v in metadata["variables"]}
        if set(dimensions) != {"Geolocation", "Commodity", "Year", "Period"}:
            raise ScraperError(f"Unexpected PSA {label} dimensions.")
        locations = dimensions["Geolocation"]
        commodities = dimensions["Commodity"]
        years = {code: int(text) for code, text in dimensions["Year"].items()
                 if text.isdigit() and as_of.year - 1 <= int(text) <= as_of.year}
        month_names = {calendar.month_name[index]: index for index in range(1, 13)}
        periods = {code: month_names[text] for code, text in dimensions["Period"].items() if text in month_names}
        rows = {}
        for year_code, year in years.items():
            selected_periods = {code: month for code, month in periods.items() if date(year, month, 1) < as_of.replace(day=1)}
            if not selected_periods:
                continue
            selection = {"Geolocation": list(locations), "Commodity": list(commodities),
                         "Year": [year_code], "Period": list(selected_periods)}
            query = [{"code": key, "selection": {"filter": "item", "values": values}} for key, values in selection.items()]
            reply = read_reply(session.post(url, json={"query": query, "response": {"format": "json"}}, timeout=(10, 45)))
            columns = [column["code"] for column in reply["columns"] if column["code"] in selection]
            fixed = {name: values[0] for name, values in selection.items() if len(values) == 1 and name not in columns}
            if len(columns) != len(set(columns)) or set(columns) | fixed.keys() != selection.keys():
                raise ScraperError(f"Unexpected PSA {label} dimensions in results: {columns!r}.")
            if len(reply["data"]) != len(locations) * len(commodities) * len(selected_periods):
                raise ScraperError("PSA returned an incomplete set of monthly cells.")
            for cell in reply["data"]:
                if len(cell["key"]) != len(columns):
                    raise ValueError("PSA cell key does not match the result columns.")
                key = {**fixed, **dict(zip(columns, cell["key"]))}
                commodity, location = key["Commodity"], key["Geolocation"]
                if commodity not in commodities or location not in locations or key["Year"] != year_code:
                    raise ScraperError("PSA returned a series outside the request.")
                month = date(year, selected_periods[key["Period"]], 1).isoformat()
                row_id = (commodity, location, month)
                if row_id in rows:
                    raise ScraperError(f"Duplicate PSA {label} cell.")
                value, = cell["values"]
                if value is None or str(value).strip() in UNPUBLISHED:
                    rows[row_id] = None
                    continue
                price = Decimal(str(value))
                if not price.is_finite() or price < 0:
                    raise ScraperError(f"Invalid PSA {label} price.")
                rows[row_id] = str(price) if price else None
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        raise ScraperError(f"Unrecognized PSA {label} response: {exc}") from exc

    observations = [[*key, value] for key, value in rows.items() if value is not None]
    if not observations:
        raise ScraperError(f"PSA returned no published {label} prices for this table.")
    return {"table": table, "retrieved_on": as_of.isoformat(), "commodities": commodities,
            "locations": locations, "observations": observations}

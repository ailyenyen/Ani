"""Adapters for the public Bantay Presyo AJAX tables and Infanta LGU page."""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import requests
from bs4 import BeautifulSoup

from .base import ScraperError

PORTAL = "http://www.bantaypresyo.da.gov.ph/"
INFANTA = "https://infanta.gov.ph/icc"
DA_SOURCE = "DA Bantay Presyo portal"
LGU_SOURCE = "Infanta LGU"
CATEGORIES = {"1": "Rice", "5": "Fruits", "6": "Highland vegetables", "7": "Lowland vegetables", "9": "Spices"}


@dataclass(frozen=True)
class Quote:
    product: str
    specification: str
    market: str
    low: Decimal
    high: Decimal
    raw: str
    unit: str = "kg"


def clean(value):
    return " ".join(value.split())


def product_key(product, specification, unit="kg"):
    # Exact product/specification identity avoids merging local/imported rice,
    # named varieties, or LGU products whose specification is not provided.
    identity = "|".join(clean(v).casefold() for v in (product, specification, unit))
    return hashlib.sha256(identity.encode()).hexdigest()


def price_range(text):
    text = clean(text).replace(",", "").replace("₱", "").strip()
    if text.lower() in {"n/a", "na", "-", "", "none"}:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d{1,2})?)(?:\s*[-–]\s*(\d+(?:\.\d{1,2})?))?", text)
    if not match:
        raise ScraperError(f"Unrecognized price: {text}")
    low, high = Decimal(match[1]), Decimal(match[2] or match[1])
    if not Decimal("1") <= low <= high <= Decimal("5000"):
        raise ScraperError(f"Invalid price range: {text}")
    return low, high


def page_date(text, today):
    text = clean(text)
    for fmt in ("%B %d, %Y", "%A, %B %d, %Y"):
        try:
            result = datetime.strptime(text, fmt).date()
            if result > today:
                raise ScraperError("Source date is in the future.")
            return result
        except ValueError:
            pass
    raise ScraperError(f"Unrecognized source date: {text[:100]}")


def fetch(session, url, data=None):
    try:
        response = session.get(url, timeout=(10, 30)) if data is None else session.post(url, data=data, timeout=(10, 30))
        response.raise_for_status()
        if len(response.content) > 10_000_000:
            raise ScraperError("Source response too large.")
        return response.content
    except requests.RequestException as exc:
        raise ScraperError(f"Source request failed: {exc}") from exc


def discover_regions(session):
    soup = BeautifulSoup(fetch(session, PORTAL + "tbl_rice.php"), "html.parser")
    options = soup.select("select#region option[value]")
    regions = [(o["value"], clean(o.get_text())) for o in options if re.fullmatch(r"\d{9}", o["value"])]
    if not regions:
        raise ScraperError("Regional selector missing; review portal layout.")
    return regions


def parse_da(header, body, with_warnings=False):
    heads = BeautifulSoup(header, "html.parser").select("tr")
    if len(heads) != 1:
        raise ScraperError("Unexpected table header structure.")
    columns = [clean(c.get_text()) for c in heads[0].find_all(["td", "th"], recursive=False)]
    if len(columns) < 3 or columns[:2] != ["COMMODITY", "SPECIFICATIONS"] or any(not c for c in columns):
        raise ScraperError("Unrecognized market columns.")
    ambiguous = {c for c in columns[2:] if columns[2:].count(c) > 1}
    warnings = "Ambiguous repeated market columns excluded: " + ", ".join(sorted(ambiguous)) if ambiguous else ""
    rows = BeautifulSoup(body, "html.parser").select("tr")
    quotes = []
    for row in rows:
        cells = [clean(c.get_text()) for c in row.find_all(["td", "th"], recursive=False)]
        if len(cells) != len(columns):
            if len(cells) == 1 and re.search(r"no .*?(data|record|price)|not available", cells[0], re.I):
                continue
            raise ScraperError("Price columns do not match market headers; import stopped.")
        product, specification = cells[:2]
        if not product or not specification:
            raise ScraperError("Missing product specification.")
        # Categories imported here are crop/rice tables quoted per kilogram.
        # Explicit non-kg specifications must not be coerced to kilograms.
        if re.search(r"\b(pc|piece|bundle|liter|litre|bottle)\b", specification, re.I):
            continue
        for market, value in zip(columns[2:], cells[2:]):
            if market in ambiguous:
                continue
            parsed = price_range(value)
            if parsed:
                quotes.append(Quote(product, specification, market, *parsed, " | ".join([product, specification, market, value])))
    return (quotes, warnings) if with_warnings else quotes


def fetch_da(session, code, category, today):
    params = {"region": code, "commodity": category}
    date_before = fetch(session, PORTAL + "tbl_rice.php", {**params, "action": "get_latest_date"})
    date_value = page_date(date_before.decode("utf-8-sig"), today)
    header = fetch(session, PORTAL + "tbl_price_get_comm_header_rice.php", params)
    body = fetch(session, PORTAL + "tbl_price_get_comm_price_rice.php", params)
    date_after = fetch(session, PORTAL + "tbl_rice.php", {**params, "action": "get_latest_date"})
    if clean(date_before.decode()) != clean(date_after.decode()):
        raise ScraperError("Source date changed during collection; retry the import.")
    quotes, warnings = parse_da(header, body, with_warnings=True)
    archive = json.dumps({"request": params, "date": date_before.decode(), "header": header.decode(), "body": body.decode(), "warnings": warnings}, ensure_ascii=False).encode()
    return date_value, quotes, archive, warnings


def parse_infanta(content, today):
    soup = BeautifulSoup(content, "html.parser")
    label = next((clean(p.get_text()) for p in soup.select("p") if clean(p.get_text()).startswith("As of ")), None)
    if not label:
        raise ScraperError("Infanta reporting date missing.")
    report_date = page_date(label.removeprefix("As of "), today)
    quotes = []
    for row in soup.select("div.row.d-flex.p-2"):
        cells = row.select(":scope > .row-item")
        if len(cells) != 3:
            continue
        texts = []
        for cell in cells:
            copy = BeautifulSoup(str(cell), "html.parser")
            for hidden in copy.select(".hidden-label"):
                hidden.decompose()
            texts.append(clean(copy.get_text()))
        product, category, value = texts
        if category != "Crops" or not product.lower().endswith("(kg)"):
            continue
        parsed = price_range(value)
        if parsed:
            quotes.append(Quote(product[:-4].strip(), "Variety/grade not specified by LGU", "Infanta Commercial Center, Quezon", *parsed, " | ".join(texts)))
    if not quotes:
        raise ScraperError("Infanta crop rows were not recognized.")
    return report_date, quotes

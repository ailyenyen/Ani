"""
Kadiwa price lists.

Expected layout: a "long" table with one row per product and location:

    As of 07 Oct 2026
    | Product | Kadiwa Center | Province | Unit | Price (PHP) |
"""
import re
from collections import defaultdict

from bs4 import BeautifulSoup

from .base import BaseScraper, RawRecord, ScraperError, cell_text, column_index, find_table
from .normalize import normalize_crop_name, normalize_unit, parse_date
from .regional import Quote, price_range

KADIWA_OUTLET_SOURCE = "Kadiwa outlet price list"


class KadiwaScraper(BaseScraper):
    slug = "kadiwa"
    source_name = "Kadiwa"
    default_market = "Kadiwa"
    fixture_name = "kadiwa.html"

    def parse(self, soup):
        table, headers = find_table(soup, ["product", "price"])
        if table is None:
            table, headers = find_table(soup, ["commodity", "price"])
        if table is None:
            raise ScraperError("Could not find the Kadiwa price table.")

        crop_col = column_index(headers, "product", "commodity", "item")
        price_col = column_index(headers, "price")
        unit_col = column_index(headers, "unit")
        location_col = column_index(headers, "province", "location", "city")
        date_col = column_index(headers, "date")

        page_date = self._find_date(soup)
        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(crop_col, price_col):
                continue

            def cell(index, default=""):
                return cell_text(cells[index]) if index is not None and index < len(cells) else default

            yield RawRecord(
                crop=cell(crop_col),
                price=cell(price_col),
                unit=cell(unit_col, "kg"),
                market="Kadiwa",
                location=cell(location_col),
                date=cell(date_col) or page_date,
            )

    @staticmethod
    def _find_date(soup):
        tagged = soup.select_one(".as-of, time[datetime]")
        if tagged is not None:
            return tagged.get("datetime") or cell_text(tagged)
        match = re.search(r"as of\s+(\d{1,2} [A-Za-z]+ \d{4}|[A-Za-z]+ \d{1,2},? \d{4})", soup.get_text(" "), re.I)
        return match.group(1) if match else None


def parse_outlet_price_list(content, today):
    """Parse a verified Kadiwa outlet bulletin into date and province batches."""
    soup = BeautifulSoup(content, "html.parser")
    required = ("product", "kadiwa center", "province", "unit", "price (php)")
    table, headers = find_table(soup, required)
    if table is None or any(headers.count(header) != 1 for header in required):
        raise ScraperError("Expected explicit product, Kadiwa center, province, unit and PHP price columns.")
    report_date = KadiwaScraper._find_date(soup)
    batches = defaultdict(list)
    seen = set()
    for row in table.find_all("tr")[1:]:
        cells = [cell_text(cell) for cell in row.find_all(["td", "th"], recursive=False)]
        if len(cells) != len(headers):
            raise ScraperError("Kadiwa price row does not match the table header.")
        fields = dict(zip(headers, cells))
        product, outlet, province, unit, value = (fields[key] for key in required)
        if not normalize_crop_name(product) or not unit or normalize_unit(unit) != "kg":
            continue
        parsed = price_range(value)
        if parsed is None:
            continue
        day = parse_date(fields.get("date") or report_date)
        specification = fields.get("specification") or "Kadiwa outlet · grade not specified"
        if not day or day > today or not outlet or not province:
            raise ScraperError("Kadiwa quote requires a published date, outlet and province.")
        if len(outlet) > 120 or len(province) > 100 or len(product) > 80 or len(specification) > 200:
            raise ScraperError("Kadiwa quote contains labels longer than the catalog can store.")
        identity = (day, province, outlet, product.casefold(), specification.casefold())
        if identity in seen:
            raise ScraperError("Duplicate product and outlet in the Kadiwa price list.")
        seen.add(identity)
        batches[day, province].append(Quote(product, specification, outlet, *parsed, " | ".join(cells)))
    if not batches:
        raise ScraperError("No supported per-kilogram crops in the Kadiwa price list.")
    return batches

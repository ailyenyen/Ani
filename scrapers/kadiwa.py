"""
Kadiwa price lists.

Expected layout: a "long" table with one row per product and location:

    As of 07 Oct 2026
    | Product | Kadiwa Center | Province | Unit | Price (PHP) |
"""
import re

from .base import BaseScraper, RawRecord, ScraperError, cell_text, column_index, find_table


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

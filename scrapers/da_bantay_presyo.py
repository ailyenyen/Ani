"""
DA Bantay Presyo (Department of Agriculture price monitoring).

Expected layout: one "wide" table with a commodity per row and one column per
location, plus the price date somewhere above the table:

    Date: October 7, 2026
    | Commodity | Unit | Batangas | Laguna | Quezon |
    | Tomato    | kg   | 35.00    | 36.50  | n/a    |
"""
import re

from .base import BaseScraper, RawRecord, ScraperError, cell_text, column_index, find_table
from .normalize import parse_date

NON_LOCATION_COLUMNS = ("commodity", "unit", "specification", "category", "remarks")


class DABantayPresyoScraper(BaseScraper):
    slug = "da_bantay_presyo"
    source_name = "DA Bantay Presyo"
    default_market = "DA Bantay Presyo"
    fixture_name = "da_bantay_presyo.html"

    def parse(self, soup):
        table, headers = find_table(soup, ["commodity"])
        if table is None:
            raise ScraperError("Could not find the price table (no 'Commodity' column).")

        commodity_col = column_index(headers, "commodity")
        unit_col = column_index(headers, "unit")
        location_cols = [
            (i, h) for i, h in enumerate(headers)
            if i not in (commodity_col, unit_col) and not any(w in h for w in NON_LOCATION_COLUMNS)
        ]
        if not location_cols:
            raise ScraperError("The price table has no location columns.")

        price_date = self._find_date(soup)
        header_cells = table.find("tr").find_all(["th", "td"])

        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= commodity_col:
                continue
            crop = cell_text(cells[commodity_col])
            unit = cell_text(cells[unit_col]) if unit_col is not None and unit_col < len(cells) else "kg"
            for i, _header in location_cols:
                if i >= len(cells):
                    continue
                value = cell_text(cells[i])
                if not value or value.lower() in {"n/a", "-", "—", "na"}:
                    continue  # this location has no price for the crop today
                yield RawRecord(
                    crop=crop,
                    price=value,
                    unit=unit,
                    location=cell_text(header_cells[i]),
                    date=price_date,
                )

    @staticmethod
    def _find_date(soup):
        tagged = soup.select_one(".price-date, [data-price-date], time[datetime]")
        if tagged is not None:
            return tagged.get("datetime") or tagged.get("data-price-date") or cell_text(tagged)
        match = re.search(r"(?:date|as of)[:\s]+([A-Za-z]+ \d{1,2},? \d{4})", soup.get_text(" "), re.I)
        return parse_date(match.group(1)) if match else None

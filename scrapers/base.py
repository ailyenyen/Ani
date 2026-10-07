"""
The common shape every source adapter follows.

A scraper only has to implement ``parse()``: turn the source's HTML into
``RawRecord`` objects. Fetching, normalizing and validating are shared, so a
source that changes its HTML only requires changing its own ``parse()``.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from . import normalize

logger = logging.getLogger("scrapers")

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class ScraperError(Exception):
    """The source could not be fetched or its page structure was not recognized."""


@dataclass
class RawRecord:
    """A price exactly as it appeared on the source page (all text)."""

    crop: str
    price: str
    unit: str = "kg"
    market: str = ""
    location: str = ""
    date: object = None


@dataclass(frozen=True)
class PriceRecord:
    """A cleaned, validated price ready to be stored."""

    crop_name: Optional[str]
    price: Optional[Decimal]
    unit: Optional[str]
    market: str
    location: str
    source: str
    price_date: Optional[date]
    collected_at: datetime
    source_url: str = ""


@dataclass
class ScrapeResult:
    source: str
    collected_at: datetime
    records: List[PriceRecord] = field(default_factory=list)
    rejected: List[Tuple[RawRecord, str]] = field(default_factory=list)

    @property
    def found(self):
        return len(self.records) + len(self.rejected)


class BaseScraper(ABC):
    #: Short identifier used on the command line, e.g. "kadiwa".
    slug = ""
    #: Source name shown to users next to every price, e.g. "Kadiwa".
    source_name = ""
    #: Market name used when the page doesn't name one.
    default_market = ""
    #: Location used when the page doesn't name one.
    default_location = ""
    #: Sample page in scrapers/fixtures/ used for offline development and tests.
    fixture_name = ""

    def __init__(self, url="", offline=False, timeout=20, user_agent="AniPriceBot/1.0", http=None):
        self.url = url
        self.offline = offline or not url
        self.timeout = timeout
        self.user_agent = user_agent
        self.http = http or requests

    # -- fetching ---------------------------------------------------------

    def fetch(self):
        if self.offline:
            path = FIXTURES_DIR / self.fixture_name
            logger.info("[%s] Reading sample page %s (offline mode)", self.slug, path.name)
            return path.read_text(encoding="utf-8")
        logger.info("[%s] Fetching %s", self.slug, self.url)
        try:
            response = self.http.get(
                self.url, timeout=self.timeout, headers={"User-Agent": self.user_agent}
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ScraperError(f"Could not download {self.url}: {exc}") from exc
        response.encoding = response.encoding or "utf-8"
        return response.text

    # -- parsing (source-specific) ---------------------------------------

    @abstractmethod
    def parse(self, soup: BeautifulSoup) -> Iterable[RawRecord]:
        """Extract raw price rows from the page. Raise ScraperError if the layout is unrecognized."""

    # -- shared pipeline --------------------------------------------------

    def normalize(self, raw, collected_at):
        return PriceRecord(
            crop_name=normalize.normalize_crop_name(raw.crop),
            price=normalize.parse_price(raw.price),
            unit=normalize.normalize_unit(raw.unit),
            market=(raw.market or self.default_market).strip(),
            location=(raw.location or self.default_location).strip(),
            source=self.source_name,
            price_date=normalize.parse_date(raw.date),
            collected_at=collected_at,
            source_url=self.url,
        )

    def run(self, today=None):
        """Fetch, parse, normalize and validate. Never writes to the database."""
        collected_at = datetime.now(timezone.utc)
        today = today or collected_at.date()
        html = self.fetch()
        soup = BeautifulSoup(html, "html.parser")
        raw_records = list(self.parse(soup))
        if not raw_records:
            raise ScraperError("No prices found on the page. The page layout may have changed.")

        result = ScrapeResult(source=self.source_name, collected_at=collected_at)
        seen = set()
        max_age = None if self.offline else 365
        for raw in raw_records:
            record = self.normalize(raw, collected_at)
            problems = normalize.validate(record, today, max_age_days=max_age)
            if problems:
                result.rejected.append((raw, "; ".join(problems)))
                continue
            key = (record.crop_name, record.market, record.location, record.price_date)
            if key in seen:
                result.rejected.append((raw, "duplicate row on the same page"))
                continue
            seen.add(key)
            result.records.append(record)

        for raw, reason in result.rejected:
            logger.warning("[%s] Skipped %r (%s): %s", self.slug, raw.crop, raw.price, reason)
        logger.info(
            "[%s] %d valid price(s), %d skipped", self.slug, len(result.records), len(result.rejected)
        )
        return result


# --- Helpers for table-based pages -------------------------------------------

def cell_text(cell):
    return " ".join(cell.get_text(" ", strip=True).split())


def find_table(soup, required_headers):
    """
    Find the first table whose header row contains all ``required_headers``
    (case-insensitive substrings). Returns (table, [header texts]) or (None, None).

    Matching on header words instead of CSS classes keeps scrapers working
    when a site renames classes or adds wrapper elements.
    """
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if header_row is None:
            continue
        headers = [cell_text(c).lower() for c in header_row.find_all(["th", "td"])]
        if all(any(req in h for h in headers) for req in required_headers):
            return table, headers
    return None, None


def column_index(headers, *candidates):
    for i, header in enumerate(headers):
        if any(c in header for c in candidates):
            return i
    return None

"""Verified weekly retail observations published by DA-AMAS, including Kadiwa rice.

No guessed prices, location expansion, OCR, or fixture fallback. Unsupported layouts
fail closed. Weekly values are dated at period end, never called daily quotations.
"""
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import urljoin, urlparse

import pdfplumber
import requests
from bs4 import BeautifulSoup

from .base import ScraperError

INDEX_URL = "https://www.da.gov.ph/price-monitoring/"


@dataclass(frozen=True)
class Observation:
    slug: str
    name: str
    source: str
    price: Decimal
    raw: str
    note: str = ""


@dataclass(frozen=True)
class Report:
    start: object
    end: object
    observations: list
    text: str


# Exact products: similar varieties must not be collapsed into the same crop.
PRODUCTS = {
    "Tomato": ("kamatis", "Kamatis"),
    "Eggplant": ("talong", "Talong"),
    "Carrots, Local": ("karot", "Karot (Local)"),
    "White Potato, Local": ("patatas", "Patatas (Local)"),
    "Red Onion, Local": ("sibuyas", "Sibuyas (Pula, Local)"),
    "Garlic, Native/Local": ("bawang", "Bawang (Native/Local)"),
    "Calamansi": ("kalamansi", "Kalamansi"),
    "Banana (Lakatan)": ("saging", "Saging (Lakatan)"),
    "Mango (Carabao)": ("mangga", "Mangga (Carabao)"),
    "Chilli (Red), Local": ("sili", "Sili (Red Tingala, Local)"),
    "Cabbage (Wonder Ball)": ("repolyo", "Repolyo (Wonder Ball)"),
}


def trusted_url(url):
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in {"da.gov.ph", "www.da.gov.ph"}


def download(url):
    if not trusted_url(url):
        raise ScraperError("Only official HTTPS da.gov.ph report URLs are accepted.")
    try:
        response = requests.get(url, timeout=(10, 60), headers={"User-Agent": "AniPriceBot/1.0"})
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ScraperError(f"Could not fetch {url}: {exc}") from exc
    if not trusted_url(response.url):
        raise ScraperError("Report redirected outside the official DA domain.")
    if len(response.content) > 15_000_000:
        raise ScraperError("Report exceeds the 15 MB size limit.")
    return response.content


def discover_reports(limit=4):
    soup = BeautifulSoup(download(INDEX_URL), "html.parser")
    urls = []
    for link in soup.select("a[href]"):
        url = urljoin(INDEX_URL, link["href"])
        if (trusted_url(url) and "weekly-average-prices-" in url.lower()
                and url.lower().endswith(".pdf") and url not in urls):
            urls.append(url)
    if not urls:
        raise ScraperError("DA index has no recognized weekly report links; review its layout.")
    # DA lists newest weekly reports first; each downloaded period is validated.
    return urls[:limit]


def parse_pdf(content, today):
    if not content.startswith(b"%PDF-"):
        raise ScraperError("DA returned something other than a PDF.")
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) > 20:
                raise ScraperError("Unexpected report length.")
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ScraperError:
        raise
    except Exception as exc:
        raise ScraperError(f"Unreadable report PDF: {exc}") from exc
    return parse_text(text, today)


def parse_text(text, today):
    flat = " ".join(text.split())
    if "Weekly Average Retail Price" not in flat or "NCR Markets" not in flat:
        raise ScraperError("Expected an NCR weekly average retail price report.")
    period = re.search(
        r"For the period of ([A-Za-z]+) (\d{1,2})\s*-\s*(?:([A-Za-z]+) )?(\d{1,2}), (\d{4})", flat
    )
    if not period:
        raise ScraperError("Report period was not recognized.")
    month1, day1, month2, day2, year = period.groups()
    try:
        end = datetime.strptime(f"{month2 or month1} {day2} {year}", "%B %d %Y").date()
        start_year = int(year) - (1 if month1 == "December" and month2 == "January" else 0)
        start = datetime.strptime(f"{month1} {day1} {start_year}", "%B %d %Y").date()
    except ValueError as exc:
        raise ScraperError("Invalid report period.") from exc
    if not 0 <= (end - start).days <= 7 or end > today:
        raise ScraperError("Report period is invalid or in the future.")
    rows = []
    seen = set()
    section = ""
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if line in {"LOCAL COMMERCIAL RICE", "IMPORTED COMMERCIAL RICE", "KADIWA RICE-FOR-ALL", "CORN PRODUCTS"}:
            section = line
        match = re.match(r"^(.+?)\s+kg\s+(\d+(?:\.\d{1,2})?)$", line)
        if not match:
            continue
        label, number = match.groups()
        product = None
        source = "DA Bantay Presyo"
        note = ""
        if section == "KADIWA RICE-FOR-ALL" and label.startswith("P20 Benteng Bigas Meron Na"):
            product = ("kadiwa-program-rice", "Kadiwa P20 program rice")
            source = "Kadiwa (DA-reported program)"
            note = "Program price; eligibility and outlet restrictions apply. See the report footnote for covered markets. Not a farmer buying offer."
            if "available only" not in flat.lower():
                raise ScraperError("Kadiwa availability footnote missing; review report before importing.")
        elif section == "LOCAL COMMERCIAL RICE" and label.startswith("Regular Milled "):
            product = ("bigas", "Bigas (Regular, Local)")
        else:
            for prefix, value in PRODUCTS.items():
                if label == prefix or label.startswith(prefix + " "):
                    product = value
                    break
        if not product:
            continue
        slug, name = product
        if slug in seen:
            raise ScraperError(f"Ambiguous duplicate product: {slug}")
        seen.add(slug)
        price = Decimal(number)
        if not Decimal("1") <= price <= Decimal("5000"):
            raise ScraperError(f"Out-of-range price: {label}")
        rows.append(Observation(slug, name, source, price, line, note))
    if len([r for r in rows if r.source == "DA Bantay Presyo"]) < 5:
        raise ScraperError("Too few recognized crop rows; report layout may have changed.")
    return Report(start, end, rows, text)


def digest(content):
    return hashlib.sha256(content).hexdigest()

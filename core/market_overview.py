"""Market prices overview: retail, wholesale and farmgate prices for each crop, side by side.

* Retail comes from ANI's live catalog (weekly DA reports and regional sources), so it keeps
  updating as those sources publish.
* Wholesale and farmgate come from the PSA monthly snapshots (see ``core/psa_prices.py``).

Each source names regions differently ("NCR", "NATIONAL CAPITAL REGION (NCR)",
"NCR - National Capital Region"), so places are matched to one list of regions by keyword.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from sqlalchemy import func, select

from scrapers.psa_openstat import FARMGATE, RETAIL, WHOLESALE

from . import services
from .models import CatalogQuote, CropPrice, Market, RegionalQuote
from .psa_prices import FARMGATE_PAGE, RETAIL_PAGE, WHOLESALE_PAGE, catalog as psa_catalog, latest_rows

# (id, display name, keywords found in any source's spelling of the region)
REGIONS = (
    ("ncr", "National Capital Region (NCR)", ("national capital", "ncr")),
    ("car", "Cordillera (CAR)", ("cordillera", "(car)", "car -")),
    ("r1", "Ilocos Region (Region I)", ("ilocos",)),
    ("r2", "Cagayan Valley (Region II)", ("cagayan valley",)),
    ("r3", "Central Luzon (Region III)", ("central luzon",)),
    ("r4a", "CALABARZON (Region IV-A)", ("calabarzon",)),
    ("r4b", "MIMAROPA (Region IV-B)", ("mimaropa",)),
    ("r5", "Bicol Region (Region V)", ("bicol",)),
    ("r6", "Western Visayas (Region VI)", ("western visayas",)),
    ("nir", "Negros Island Region", ("negros island",)),
    ("r7", "Central Visayas (Region VII)", ("central visayas",)),
    ("r8", "Eastern Visayas (Region VIII)", ("eastern visayas",)),
    ("r9", "Zamboanga Peninsula (Region IX)", ("zamboanga",)),
    ("r10", "Northern Mindanao (Region X)", ("northern mindanao",)),
    ("r11", "Davao Region (Region XI)", ("davao",)),
    ("r12", "SOCCSKSARGEN (Region XII)", ("soccsksargen",)),
    ("r13", "Caraga (Region XIII)", ("caraga",)),
    ("barmm", "Bangsamoro (BARMM)", ("bangsamoro", "barmm", "armm")),
)
REGION_NAMES = {key: name for key, name, _words in REGIONS}
RETAIL_WINDOW_DAYS = 120

SHOW_CHOICES = (("", "All crops"), ("complete", "With every selected price"), ("mine", "My crops"))
# Price types, in the order they appear everywhere (cards, legend, chart).
PRICE_TYPES = (
    ("farmgate", "Farmgate", "What farmers are paid"),
    ("wholesale", "Wholesale", "What traders charge in bulk"),
    ("retail", "Retail", "What shoppers pay at markets"),
)
FRESH_DAYS = 30      # within 30 days: newest
AGING_DAYS = 92      # up to about 3 months: getting old
TYPE_KEYS = tuple(key for key, _label, _meaning in PRICE_TYPES)
SORT_CHOICES = (("", "My crops first"), ("newest", "Newest update"), ("name", "Name, A to Z"), ("gap", "Biggest retail–farmgate gap"))


def region_id(name):
    """Map any source's region label to a region id, or "" if it is not a region."""
    text = f" {name.casefold()} "
    for key, _name, words in REGIONS:
        if any(word in text for word in words):
            return key
    return ""


def freshness(day):
    """'new' (within 30 days), 'aging' (1–3 months) or 'old' (older), from a report date."""
    if day is None:
        return ""
    age = (services.today() - day).days
    return "new" if age <= FRESH_DAYS else "aging" if age <= AGING_DAYS else "old"


@dataclass
class PriceLine:
    """One price type on a crop card."""

    kind: str          # "retail", "wholesale" or "farmgate"
    label: str
    meaning: str
    value: Decimal = None      # the published price (lower end when the source publishes a range)
    low: Decimal = None
    high: Decimal = None       # upper end of a published range, otherwise None
    count: int = 0             # how many markets / products were published for this crop
    unit: str = "kg"
    when: str = ""
    detail: str = ""
    link: str = ""
    day: object = None   # date of the report; first day of the month for monthly averages
    source_note: str = ""  # what exactly is shown, e.g. "Lipa City Public Market · DA Bantay Presyo portal"
    series: str = ""       # PSA series id of the product shown (used for the trend line)
    national: bool = False  # a whole-country figure, shown because the region has none

    @property
    def ranged(self):
        return self.high is not None and self.value is not None and self.high > self.value

    @property
    def fresh(self):
        return freshness(self.day)


@dataclass
class CropCard:
    slug: str
    name: str
    icon: str
    varieties: list = field(default_factory=list)
    search_text: str = ""
    has_retail_listing: bool = False
    saved: bool = False
    lines: list = field(default_factory=list)       # the selected price types
    all_lines: list = field(default_factory=list)   # every price type, for figures that need two of them
    detail_link: str = ""

    def any_line(self, kind):
        return next((line for line in self.all_lines if line.kind == kind), None)

    @property
    def available(self):
        return sum(1 for line in self.lines if line.value is not None)

    def line(self, kind):
        return next((line for line in self.lines if line.kind == kind), None)

    @property
    def title(self):
        return self.name.split(" / ")[0]

    @property
    def subtitle(self):
        parts = self.name.split(" / ", 1)
        return parts[1] if len(parts) > 1 else ""

    @property
    def spread(self):
        """Retail minus farmgate, when both are available (whichever price types are being shown)."""
        retail, farmgate = self.any_line("retail"), self.any_line("farmgate")
        if retail and farmgate and retail.value is not None and farmgate.value is not None:
            return retail.value - farmgate.value
        return None

    @property
    def spread_abs(self):
        return abs(self.spread) if self.spread is not None else None

    @property
    def spread_note(self):
        retail, farmgate = self.any_line("retail"), self.any_line("farmgate")
        if self.spread is None:
            if farmgate is not None and farmgate.value is None:
                return "Needs farmgate"
            return "Needs retail"
        if (retail.day.year, retail.day.month) != (farmgate.day.year, farmgate.day.month):
            return f"{farmgate.day:%b} vs {retail.day:%b} data"
        return f"{retail.day:%b %Y}"

    @property
    def gap(self):
        """Spread between the highest and lowest selected price, when at least two are available."""
        values = [line.value for line in self.lines if line.value is not None]
        return max(values) - min(values) if len(values) >= 2 else None


def pick_middle(observations, key):
    """The middle published observation (lower middle for an even count). Never an average,
    so every price on the page is a figure that exists in the source data."""
    ordered = sorted(observations, key=key)
    return ordered[(len(ordered) - 1) // 2]


# --- Retail: live catalog ------------------------------------------------------

def retail_by_family(db, listings, retail_locations=None):
    """Each market's latest published kg price (with its range, market and source), grouped by crop family.

    Includes every live retail dataset: DA weekly reports, the Bantay Presyo portal, LGU bulletins
    and Kadiwa price lists, so the newest import from any of them shows up here.
    """
    since = services.today() - timedelta(days=RETAIL_WINDOW_DAYS)
    ranked = (
        select(
            CropPrice.id.label("price_id"), CropPrice.crop_id, CropPrice.price, CropPrice.date, CropPrice.unit,
            CropPrice.source, Market.id.label("market_id"), Market.name.label("market"), Market.location,
            func.row_number().over(
                partition_by=(CropPrice.crop_id, CropPrice.market_id, CropPrice.source, CropPrice.unit),
                order_by=(CropPrice.date.desc(), CropPrice.id.desc()),
            ).label("rank"),
        )
        .join(Market, Market.id == CropPrice.market_id)
        .where(CropPrice.date >= since)
    )
    if retail_locations is not None:
        ranked = ranked.where(Market.location.in_(retail_locations or ["-"]))
    ranked = ranked.subquery()
    query = (
        select(ranked.c.crop_id, ranked.c.price, RegionalQuote.high, ranked.c.date, ranked.c.unit,
               ranked.c.market_id, ranked.c.market, ranked.c.source, ranked.c.location)
        .outerjoin(CatalogQuote, CatalogQuote.price_id == ranked.c.price_id)
        .outerjoin(RegionalQuote, RegionalQuote.id == CatalogQuote.quote_id)
        .where(ranked.c.rank == 1)
    )
    grouped = defaultdict(list)
    for crop_id, price, high, day, unit, market_id, market, source, location in db.execute(query):
        listing = listings.get(crop_id)
        if listing is None or (unit or "kg").casefold() != "kg" or not price:
            continue
        low = Decimal(price)
        high = Decimal(high) if high is not None and Decimal(high) > low else None
        grouped[listing.family.slug].append({"low": low, "high": high, "day": day, "market_id": market_id,
                                             "market": market, "source": source, "product": listing.product,
                                             "variety": listing.variety, "location": location})
    return grouped


def retail_average(observations):
    """Average of each market's latest report across every retail dataset, a per-dataset breakdown,
    and the newest report. A published range counts at its midpoint."""
    if not observations:
        return None
    middle = lambda o: (o["low"] + (o["high"] or o["low"])) / 2
    average = lambda items: (sum(middle(o) for o in items) / len(items)).quantize(Decimal("0.01"))
    by_source = defaultdict(list)
    for observation in observations:
        by_source[observation["source"]].append(observation)
    newest = max(observations, key=lambda o: (o["day"], o["source"], o["market"]))
    sources = sorted((
        {"source": source, "average": average(items), "reports": len(items),
         "markets": len({o["market_id"] for o in items}), "latest": max(o["day"] for o in items),
         "market": items[0]["market"] if len({o["market_id"] for o in items}) == 1 else "",
         "fresh": freshness(max(o["day"] for o in items))}
        for source, items in by_source.items()
    ), key=lambda item: (item["latest"], item["reports"]), reverse=True)
    sources[0]["newest"] = True
    return {
        "average": average(observations), "reports": len(observations),
        "markets": len({o["market_id"] for o in observations}), "sources": sources, "newest": newest,
        "fresh": freshness(newest["day"]),
        "low": min(o["low"] for o in observations), "high": max(o["high"] or o["low"] for o in observations),
    }


def remembered_region(request):
    """The region from ?region= (or a market ?location=), else the one remembered in the session or the user's own."""
    region = request.GET.get("region")
    if region is None and request.GET.get("location"):
        region = region_id(request.GET["location"])
    if region is not None and (region in REGION_NAMES or region == ""):
        request.session["region"] = region
    region = request.session.get("region")
    user = getattr(request, "ani_user", None)
    if region is None:
        region = region_id(user.location) if user and user.location else ""
    return region if region in REGION_NAMES else ""


# --- Wholesale and farmgate: PSA monthly snapshots --------------------------------

def _signature(series):
    folder = Path(settings.BASE_DIR) / "data" / series.kind
    stats = []
    for table in series.tables:
        try:
            stat = (folder / (Path(table).stem + ".json")).stat()
            stats.append((table, stat.st_mtime_ns, stat.st_size))
        except OSError:
            continue
    return tuple(stats)


@lru_cache(maxsize=8)
def _psa_index(series, signature, current_month):
    """area ("ph" or a region id) -> family slug -> latest published kg rows."""
    index = defaultdict(lambda: defaultdict(list))
    rows = [row for row in psa_catalog(series) if row.month < current_month and row.unit == "kg"]
    for row in latest_rows(rows):
        if row.level == "National":
            area = "ph"
        elif row.level == "Region":
            area = region_id(row.location)
        else:
            continue
        if area:
            index[area][row.family.slug].append(row)
    return {area: dict(families) for area, families in index.items()}


def psa_by_family(series, area):
    index = _psa_index(series, _signature(series), services.today().replace(day=1))
    return index.get(area or "ph", {})


# Farmers sell rice as palay (unmilled), so PSA publishes rice farmgate prices under palay.
FARMGATE_STAND_INS = {"rice": "palay"}


def _families_for(series, slug):
    stand_in = FARMGATE_STAND_INS.get(slug) if series is FARMGATE else None
    return (slug, stand_in) if stand_in else (slug,)


def psa_rows_for(series, area, slug, fallback=True):
    """(rows, area used): the crop's latest PSA rows for the region, else (with fallback) the whole country's."""
    for place in ([area, "ph"] if area and fallback else [area or "ph"]):
        families = psa_by_family(series, place)
        for family in _families_for(series, slug):
            if families.get(family):
                return families[family], place
    return [], area or "ph"


def psa_line(kind, rows, labels=None, national=False):
    """A wholesale or farmgate line showing the middle published product (never an average)."""
    label, meaning = (labels or {key: (l, m) for key, l, m in PRICE_TYPES})[kind]
    line = PriceLine(kind, label, meaning)
    if rows:
        shown = pick_middle(rows, key=lambda row: (Decimal(row.price), row.product))
        line.value = line.low = Decimal(shown.price)
        line.count = len(rows)
        line.day = shown.month
        line.when = f"{line.day:%b %Y}"
        line.series = shown.series
        line.source_note = f"{shown.product} · PSA monthly average" + (", whole country" if national else "")
        line.national = national
    return line


# --- Cards ------------------------------------------------------------------------

def build_cards(db, listings, region="", saved_families=(), include_psa=True, types=TYPE_KEYS):
    """One card per crop with its latest price for each selected price type."""
    retail_locations = None
    if region:
        retail_locations = [loc for loc in services.list_locations(db) if region_id(loc) == region]
    retail = retail_by_family(db, listings, retail_locations)
    wholesale = psa_by_family(WHOLESALE, region) if include_psa else {}
    farmgate = psa_by_family(FARMGATE, region) if include_psa else {}

    families = defaultdict(list)
    for listing in listings.values():
        families[listing.family.slug].append(listing)

    cards = {}
    for slug, items in families.items():
        family = items[0].family
        cards[slug] = CropCard(
            slug, family.name, items[0].crop.icon,
            varieties=sorted({item.variety for item in items if item.variety and item.variety != "Unspecified variety"}),
            search_text=" ".join([family.name, *family.aliases, *(f"{i.product} {i.variety} {i.crop.name}" for i in items)]).casefold(),
            has_retail_listing=True, saved=slug in saved_families,
        )
    for source in (wholesale, farmgate):
        for slug, rows in source.items():
            if slug not in cards:
                family = rows[0].family
                cards[slug] = CropCard(slug, family.name, "🌱",
                                       search_text=" ".join([family.name, *family.aliases]).casefold(),
                                       saved=slug in saved_families)
            cards[slug].search_text += " " + " ".join(row.product.casefold() for row in rows)

    labels = {key: (label, meaning) for key, label, meaning in PRICE_TYPES}
    for slug, card in cards.items():
        lines = {}
        retail_query = {"location": retail_locations[0]} if region and retail_locations else {}
        line = PriceLine("retail", *labels["retail"])
        observations = retail.get(slug)
        if observations:
            shown = pick_middle(observations, key=lambda o: (o["low"], o["high"] or o["low"], o["market"]))
            line.value, line.low, line.high = shown["low"], shown["low"], shown["high"]
            line.count = len({o["market_id"] for o in observations})
            line.day = shown["day"]
            line.when = f"{line.day:%b} {line.day.day}, {line.day.year}"
            line.source_note = f"{shown['market']} · {shown['source']}"
        lines["retail"] = line
        if card.has_retail_listing:
            card.detail_link = reverse("crop_family", args=[slug]) + (f"?{urlencode(retail_query)}" if retail_query else "")
        if include_psa:
            for kind, page, series in (("wholesale", WHOLESALE_PAGE, WHOLESALE), ("farmgate", FARMGATE_PAGE, FARMGATE)):
                rows, place = psa_rows_for(series, region, slug)
                line = psa_line(kind, rows, labels, national=bool(region) and place == "ph")
                if rows:
                    query = {"crop": slug, "location": rows[0].location_code}
                    line.link = f"{reverse(page.url_name)}?{urlencode(query)}"
                    card.detail_link = card.detail_link or line.link
                lines[kind] = line
        card.all_lines = [lines[kind] for kind, _label, _meaning in PRICE_TYPES if kind in lines]
        card.lines = [lines[kind] for kind in types if kind in lines]
    return list(cards.values())


def filter_and_sort(cards, search="", show="", sort=""):
    terms = search.casefold().split()
    result = [
        card for card in cards
        if all(term in card.search_text for term in terms)
        and card.available
        and (show != "complete" or card.available == len(card.lines))
        and (show != "mine" or card.saved)
    ]
    if sort == "name":
        result.sort(key=lambda card: card.name)
    elif sort == "newest":
        # Crops with the most recent report of any shown price type first.
        newest = lambda card: max((line.day for line in card.lines if line.value is not None and line.day), default=None)
        result.sort(key=lambda card: card.name)
        result.sort(key=lambda card: newest(card) or date.min, reverse=True)
    elif sort == "gap":
        spread = lambda card: card.spread if card.spread is not None else card.gap
        result.sort(key=lambda card: (spread(card) is None, -(spread(card) or 0), card.name))
    else:
        reports = lambda card: sum(line.count for line in card.lines)
        result.sort(key=lambda card: (not card.saved, -card.available, -reports(card), card.name))
    return result


# --- Trend chart: monthly price history per price type ---------------------------

HISTORY_MONTHS = 18
CHART_SERIES = (("retail", RETAIL), ("wholesale", WHOLESALE), ("farmgate", FARMGATE))


@lru_cache(maxsize=8)
def _psa_history(series, signature, current_month):
    """area ("ph" or region id) -> family slug -> PSA series id -> month -> published kg price."""
    history = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for row in psa_catalog(series):
        if row.month >= current_month or row.unit != "kg":
            continue
        area = "ph" if row.level == "National" else region_id(row.location) if row.level == "Region" else ""
        if area:
            history[area][row.family.slug][row.series][row.month] = Decimal(row.price)
    return {area: {slug: dict(products) for slug, products in families.items()} for area, families in history.items()}


def summary_insight(card):
    """One plain sentence comparing the newest reports, e.g. 'Retail is ₱6.19 above wholesale (Nov vs Oct reports).'"""
    retail = card.line("retail")
    if retail is None or retail.value is None:
        return ""
    for kind in ("wholesale", "farmgate"):
        other = card.line(kind)
        if other is not None and other.value is not None:
            difference = retail.value - other.value
            word = "above" if difference >= 0 else "below"
            months = f"{retail.day:%b} vs {other.day:%b} reports" if (retail.day.month, retail.day.year) != (other.day.month, other.day.year) else f"{retail.day:%b %Y} reports"
            return f"Retail is ₱{abs(difference):,.2f} {word} {other.label.lower()} ({months})."
    return ""


RANGES = (("6", "6M", 6), ("12", "1Y", 12), ("all", "All", None))


def _month_add(month, count):
    index = month.year * 12 + month.month - 1 + count
    return month.replace(year=index // 12, month=index % 12 + 1, day=1)


def price_history(family, region="", types=TYPE_KEYS, months=12, newest=None):
    """Chart.js data for the trend banner.

    Each line follows one published PSA product month by month: the same product shown on the
    crop card (for retail, the matching PSA monthly retail product). Months after the last published
    average up to now are "not published yet", and markers show the newest report for each type.
    """
    current = services.today().replace(day=1)
    area = region or "ph"
    shown = {line.kind: line for line in newest or ()}
    by_kind = {}
    for kind, series in CHART_SERIES:
        if kind not in types:
            continue
        line = shown.get(kind)
        place = "ph" if line is not None and line.national else area
        history = _psa_history(series, _signature(series), current).get(place, {})
        products = next((history[f] for f in _families_for(series, family) if history.get(f)), {})
        if not products:
            continue
        chosen = line.series if line is not None and line.series in products else ""
        if not chosen:
            latest = [(months_[max(months_)], sid) for sid, months_ in products.items()]
            chosen = pick_middle(latest, key=lambda item: (item[0], item[1]))[1]
        by_kind[kind] = products[chosen]
    published = sorted({month for values in by_kind.values() for month in values})
    if not published:
        return None
    first = published[0] if months is None else max(published[0], _month_add(current, -(months - 1)))
    axis = []
    month = first
    while month <= current:
        axis.append(month)
        month = _month_add(month, 1)
    labels = {key: label for key, label, _meaning in PRICE_TYPES}
    datasets = [
        {"kind": kind, "label": labels[kind],
         "values": [float(values[m]) if m in values else None for m in axis]}
        for kind, values in by_kind.items()
    ]
    last_published = max((m for m in published if m >= first), default=None)
    markers = []
    for line in newest or ():
        if line.kind in types and line.value is not None and line.day is not None:
            point = line.day.replace(day=1)
            if point in axis:
                text = f"₱{line.value:,.2f} {line.day:%b}" + (f" {line.day.day}" if line.kind == "retail" else "")
                markers.append({"kind": line.kind, "label": labels[line.kind], "index": axis.index(point),
                                "value": float(line.value), "text": text})
    return {
        "labels": [f"{m:%b %Y}" for m in axis],
        "datasets": datasets,
        "markers": markers,
        "publishedUntil": axis.index(last_published) if last_published in axis else len(axis) - 1,
        "pendingLabel": "PSA averages not published yet",
    }


def chart_families(cards, region="", types=TYPE_KEYS):
    """Crops (in result order) that have enough history for a trend line."""
    current = services.today().replace(day=1)
    available = set()
    for kind, series in CHART_SERIES:
        if kind in types:
            families = set(_psa_history(series, _signature(series), current).get(region or "ph", {}))
            available |= families | {slug for slug, stand_in in FARMGATE_STAND_INS.items()
                                     if series is FARMGATE and stand_in in families}
    return [card for card in cards if card.slug in available]


def legend(include_psa=True, types=TYPE_KEYS):
    """The selected price types in card order, each with a link to its full table."""
    links = {"retail": ("Latest reports", "prices"), "wholesale": ("PSA monthly average", WHOLESALE_PAGE.url_name),
             "farmgate": ("PSA monthly average", FARMGATE_PAGE.url_name)}
    return [
        {"kind": key, "label": label, "meaning": meaning, "note": links[key][0], "url_name": links[key][1]}
        for key, label, meaning in PRICE_TYPES
        if key in types and (include_psa or key == "retail")
    ]


__all__ = ["REGIONS", "REGION_NAMES", "SHOW_CHOICES", "SORT_CHOICES", "PRICE_TYPES", "TYPE_KEYS", "RANGES", "region_id",
           "build_cards", "filter_and_sort", "price_history", "chart_families", "legend", "RETAIL_PAGE"]

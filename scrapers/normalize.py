"""
Turns the messy text found on source websites into clean, comparable values.

Every scraper produces ``RawRecord`` objects with plain strings; this module
converts them into ``PriceRecord`` objects or explains why a record was rejected.
"""
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

# Each canonical crop name (as stored in the Crop table) followed by the
# spellings different sources use for it. Matching ignores case and spacing.
CROP_ALIASES = {
    "Palay (Rough)": ["palay", "rough rice", "rice, rough", "rice, rough (palay)", "palay (fresh)", "palay, dry"],
    "Bigas (Regular)": ["bigas", "regular milled rice", "rice, regular milled", "rmr", "rice (regular milled)"],
    "Mais": ["corn", "yellow corn", "corn, yellow", "mais (yellow)", "corn grains"],
    "Kamatis": ["tomato", "tomatoes", "tomato (local)"],
    "Sili": ["chili", "chilli", "sili (labuyo)", "siling labuyo", "chili, labuyo", "hot pepper"],
    "Talong": ["eggplant", "eggplant (talong)"],
    "Sibuyas (Pula)": ["sibuyas", "red onion", "onion, red", "onion (red)", "red onion (local)"],
    "Bawang": ["garlic", "garlic (local)", "native garlic"],
    "Repolyo": ["cabbage", "cabbage (repolyo)"],
    "Patatas": ["potato", "potatoes"],
    "Karot": ["carrot", "carrots", "carrots (karot)"],
    "Kamote": ["sweet potato", "camote", "kamote tops"],
    "Pipino": ["cucumber"],
    "Saging (Lakatan)": ["saging", "banana lakatan", "lakatan", "banana, lakatan"],
    "Mangga (Carabao)": ["mangga", "mango", "carabao mango", "mango, carabao"],
    "Kalamansi": ["calamansi", "calamondin"],
}


def _key(text):
    return re.sub(r"\s+", " ", text or "").strip().lower()


_ALIAS_LOOKUP = {}
for canonical, aliases in CROP_ALIASES.items():
    _ALIAS_LOOKUP[_key(canonical)] = canonical
    for alias in aliases:
        _ALIAS_LOOKUP[_key(alias)] = canonical


def normalize_crop_name(text):
    """Return the canonical crop name, or None if the crop isn't tracked by Ani."""
    key = _key(text)
    if key in _ALIAS_LOOKUP:
        return _ALIAS_LOOKUP[key]
    # Try again without a trailing note in brackets, e.g. "Tomato (per kg)".
    key = re.sub(r"\s*\(.*?\)\s*$", "", key)
    return _ALIAS_LOOKUP.get(key)


_UNIT_ALIASES = {
    "kg": "kg",
    "kilo": "kg",
    "kilos": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "per kg": "kg",
    "per kilo": "kg",
    "/kg": "kg",
    "php/kg": "kg",
    "₱/kg": "kg",
}


def normalize_unit(text):
    """Return "kg" for any per-kilogram unit, or None for units Ani can't compare (piece, bundle...)."""
    key = _key(text).replace(" ", "") if text else "kg"
    for alias, unit in _UNIT_ALIASES.items():
        if key == alias.replace(" ", ""):
            return unit
    return None


_NUMBER = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"


def parse_price(text):
    """
    "₱35.00" -> 35.00, "PHP 1,200" -> 1200, "60-64" -> 62.00 (middle of a range).
    Returns None when no price is present ("n/a", "-", "").
    """
    if text is None:
        return None
    if isinstance(text, (int, float, Decimal)):
        return Decimal(str(text)).quantize(Decimal("0.01"))
    cleaned = str(text).replace("₱", " ").replace("PHP", " ").replace("Php", " ")
    numbers = re.findall(_NUMBER, cleaned)
    if not numbers:
        return None
    try:
        values = [Decimal(n.replace(",", "")) for n in numbers[:2]]
    except InvalidOperation:
        return None
    is_range = len(values) == 2 and re.search(r"\d\s*(-|–|to)\s*\d", cleaned)
    value = (values[0] + values[1]) / 2 if is_range else values[0]
    return value.quantize(Decimal("0.01"))


_DATE_FORMATS = [
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%m/%d/%Y",
    "%B %d %Y",
]


def parse_date(text):
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text
    if not text:
        return None
    cleaned = re.sub(r"^(as of|date:|updated:?|price date:?)\s*", "", _key(text), flags=re.I)
    cleaned = cleaned.strip().strip(".").title()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


MIN_PRICE = Decimal("1.00")
MAX_PRICE = Decimal("5000.00")


def validate(record, today, max_age_days=365):
    """Return a list of problems with a normalized record (empty if it is valid)."""
    problems = []
    if not record.crop_name:
        problems.append("crop is not tracked by Ani")
    if record.price is None:
        problems.append("price is missing")
    elif not (MIN_PRICE <= record.price <= MAX_PRICE):
        problems.append(f"price {record.price} is outside the expected range")
    if record.unit is None:
        problems.append("unit is not per kilogram")
    if not record.market:
        problems.append("market is missing")
    if not record.location:
        problems.append("location is missing")
    if record.price_date is None:
        problems.append("date is missing or unreadable")
    else:
        if record.price_date > today + timedelta(days=1):
            problems.append("date is in the future")
        if max_age_days is not None and record.price_date < today - timedelta(days=max_age_days):
            problems.append("date is too old")
    return problems

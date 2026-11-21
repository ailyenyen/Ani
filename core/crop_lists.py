"""Readable names and choice lists for the My Crops and Price Alerts pages."""
import re
from collections import defaultdict

from .crop_browse import catalog
from .market_overview import REGION_NAMES, region_id

LGU_SPEC = "Variety/grade not specified"
CATEGORY_LABELS = {
    "Rice": "Rice", "Grains": "Rice",
    "Highland vegetables": "Vegetables", "Lowland vegetables": "Vegetables",
    "Fruits": "Fruits", "Spices": "Spices",
}
CATEGORY_ORDER = ("Rice", "Vegetables", "Fruits", "Spices", "Other")
# A target this low is met by any report: "tell me when a price is reported".
REPORT_TARGET = "0.01"


def _pretty(text):
    text = re.sub(r"(\d)\s*-\s*(\d)", r"\1–\2", text.strip())
    if text.upper() == "KG":
        return "Per kg"
    return text[:1].upper() + text[1:].lower() if text.isupper() else text


def title(listing):
    """ "160 Rice", "Ampalaya", "Commercial (Local) Regular Milled"."""
    product = listing.product.strip()
    return product.title() if product.isupper() or "(LOCAL)" in product or "(IMPORTED)" in product else product


def is_lgu(listing):
    return listing.specification.startswith(LGU_SPEC)


def variety_label(listing):
    """Short chip label that tells the products of one crop apart."""
    parts = []
    product = listing.product.lower()
    if "imported" in product:
        parts.append("Imported")
    elif "(local)" in product:
        parts.append("Local")
    if listing.variety != "Unspecified variety":
        parts.append(listing.variety)
    if parts in ([], ["Imported"], ["Local"]):
        parts.append("Infanta LGU" if is_lgu(listing) else _pretty(listing.specification) or title(listing))
    return " · ".join(parts)


def family_categories(listings):
    """family slug -> "Rice" / "Vegetables" / "Fruits" / "Spices" / "Other"."""
    found = defaultdict(set)
    for listing in listings.values():
        label = CATEGORY_LABELS.get(listing.crop.category)
        if label:
            found[listing.family.slug].add(label)
    return {slug: next((c for c in CATEGORY_ORDER if c in labels), "Other") for slug, labels in found.items()}


def tags(listing, categories):
    detail = "Infanta" if is_lgu(listing) else _pretty(listing.specification)
    return [t for t in (categories.get(listing.family.slug, "Other"), detail) if t]


def short_region(location):
    name = REGION_NAMES.get(region_id(location or ""), "")
    return name.split(" (")[0] if name else ""


def region_label(location):
    return REGION_NAMES.get(region_id(location or ""), "")


def add_groups(db, saved_ids):
    """Crops to add, one group per crop family with a chip per product."""
    listings = catalog(db)
    categories = family_categories(listings)
    groups = {}
    for listing in sorted(listings.values(), key=lambda l: (l.family.name, variety_label(l))):
        family = listing.family
        name, _, local = family.name.partition(" / ")
        group = groups.setdefault(family.slug, {
            "slug": family.slug, "name": name, "subtitle": local, "category": categories.get(family.slug, "Other"),
            "icon": listing.crop.icon, "items": [], "search": family.name.lower(),
        })
        group["items"].append({"crop": listing.crop, "label": variety_label(listing),
                               "saved": listing.crop.id in saved_ids})
        group["search"] += " " + listing.crop.name.lower()
    ordered = sorted(groups.values(), key=lambda g: (CATEGORY_ORDER.index(g["category"]), g["name"]))
    present = [c for c in CATEGORY_ORDER if any(g["category"] == c for g in ordered)]
    return ordered, present


def alert_choices(db, current, saved_ids, region_short):
    """Every product for the new-alert dialog: My Crops first, then those with a recent price."""
    listings = catalog(db)
    choices = []
    for listing in listings.values():
        summary = current.get(listing.crop.id)
        row = {"crop": listing.crop, "title": title(listing), "label": variety_label(listing),
               "family": listing.family.name, "saved": listing.crop.id in saved_ids, "summary": summary}
        if summary:
            head = summary.headline
            row["low"] = head.quote.low if head.quote else head.price
            row["high"] = head.quote.high if head.quote else head.price
            row["note"] = f"{head.source} · {summary.market_count} market{'s' if summary.market_count != 1 else ''} · {head.date:%b %-d}"
        else:
            row["note"] = f"No recent price{f' in {region_short}' if region_short else ''}"
        choices.append(row)
    choices.sort(key=lambda c: (not c["saved"], c["summary"] is None, c["family"], c["label"]))
    return choices

"""
Sample data for development and demos.

Generates crops, markets and a few months of price history so the interface
can be built and tested without depending on external websites. The prices
are illustrative only; they are NOT real market prices.
"""
import random
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select

from .auth import hash_password
from .models import (
    Crop,
    CropPrice,
    DeviceToken,
    Market,
    Notification,
    PriceAlert,
    SavedCrop,
    ScrapeRun,
    User,
)

# (name, slug, English name, category, emoji, typical ₱/kg)
CROPS = [
    ("Palay (Rough)", "palay", "Rough rice", "Grains", "🌾", 22.0),
    ("Kamatis", "kamatis", "Tomato", "Vegetables", "🍅", 34.0),
    ("Sili", "sili", "Chili pepper", "Vegetables", "🌶️", 60.0),
    ("Mais", "mais", "Yellow corn", "Grains", "🌽", 17.5),
    ("Bigas (Regular)", "bigas", "Regular milled rice", "Grains", "🍚", 45.0),
    ("Talong", "talong", "Eggplant", "Vegetables", "🍆", 50.0),
    ("Sibuyas (Pula)", "sibuyas", "Red onion", "Vegetables", "🧅", 90.0),
    ("Bawang", "bawang", "Garlic", "Vegetables", "🧄", 110.0),
    ("Repolyo", "repolyo", "Cabbage", "Vegetables", "🥬", 45.0),
    ("Patatas", "patatas", "Potato", "Vegetables", "🥔", 70.0),
    ("Karot", "karot", "Carrot", "Vegetables", "🥕", 65.0),
    ("Kamote", "kamote", "Sweet potato", "Root crops", "🍠", 40.0),
    ("Pipino", "pipino", "Cucumber", "Vegetables", "🥒", 38.0),
    ("Saging (Lakatan)", "saging", "Banana (Lakatan)", "Fruits", "🍌", 70.0),
    ("Mangga (Carabao)", "mangga", "Carabao mango", "Fruits", "🥭", 120.0),
    ("Kalamansi", "kalamansi", "Calamansi", "Fruits", "🍋", 60.0),
]

LOCATIONS = ["Batangas", "Laguna", "Quezon"]

# (market name, source shown to users, typical price level vs. DA reference)
MARKETS = [
    ("DA Bantay Presyo", "DA Bantay Presyo", 1.00),
    ("Kadiwa", "Kadiwa", 0.96),
    ("Local Market", "Local market bulletin", 0.90),
    ("Sari-sari Market", "Local market bulletin", 0.94),
]

# Today's prices for Batangas, matching the examples in the product brief,
# so the demo tells a consistent story.
ANCHORS = {
    ("palay", "DA Bantay Presyo"): 22.50,
    ("palay", "Kadiwa"): 24.00,
    ("palay", "Local Market"): 20.00,
    ("palay", "Sari-sari Market"): 21.50,
    ("kamatis", "DA Bantay Presyo"): 35.00,
    ("kamatis", "Kadiwa"): 32.00,
    ("kamatis", "Local Market"): 28.00,
    ("kamatis", "Sari-sari Market"): 30.00,
    ("sili", "DA Bantay Presyo"): 60.00,
    ("mais", "DA Bantay Presyo"): 17.50,
}

# Sari-sari markets only report a few staple crops.
SARI_SARI_CROPS = {"palay", "kamatis", "mais", "bigas", "sibuyas", "bawang"}

DEMO_EMAIL = "juan@example.com"
DEMO_PASSWORD = "ani12345"


def _round_price(value):
    step = Decimal("0.25") if value < 100 else Decimal("1")
    return (Decimal(str(value)) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def _series(rng, base, days, anchor=None, volatility=0.018):
    """A gentle random walk that drifts around ``base`` and optionally ends at ``anchor``."""
    value = base * rng.uniform(0.9, 1.1)
    values = []
    for _ in range(days):
        value += value * rng.gauss(0, volatility) + (base - value) * 0.05
        values.append(value)
    if anchor:
        scale = anchor / values[-1]
        # Blend the correction in gradually so history still looks natural.
        values = [v * (1 + (scale - 1) * (i + 1) / days) for i, v in enumerate(values)]
    return [_round_price(v) for v in values]


def reset(db):
    for model in (Notification, DeviceToken, PriceAlert, SavedCrop, CropPrice, ScrapeRun, Market, User, Crop):
        db.execute(delete(model))
    db.commit()


def seed(db, days=120, as_of=None, with_demo_user=True, rng_seed=7):
    from .services import today

    as_of = as_of or today()
    rng = random.Random(rng_seed)

    crops = {}
    for order, (name, slug, english, category, icon, _base) in enumerate(CROPS):
        crop = db.scalar(select(Crop).where(Crop.slug == slug))
        if crop is None:
            crop = Crop(slug=slug)
            db.add(crop)
        crop.name, crop.english_name, crop.category, crop.icon = name, english, category, icon
        crop.unit, crop.sort_order = "kg", order
        crops[slug] = crop
    db.flush()

    markets = []
    for location in LOCATIONS:
        for market_name, source, level in MARKETS:
            market = db.scalar(select(Market).where(Market.name == market_name, Market.location == location))
            if market is None:
                market = Market(name=market_name, location=location, source=source)
                db.add(market)
            markets.append((market, level))
    db.flush()

    db.execute(delete(CropPrice).where(CropPrice.date > as_of - timedelta(days=days)))
    location_level = {"Batangas": 1.0, "Laguna": 1.03, "Quezon": 0.98}
    count = 0
    for market, level in markets:
        for name, slug, _english, _category, _icon, base in CROPS:
            if market.name == "Sari-sari Market" and slug not in SARI_SARI_CROPS:
                continue
            market_base = base * level * location_level[market.location] * rng.uniform(0.95, 1.05)
            anchor = ANCHORS.get((slug, market.name)) if market.location == "Batangas" else None
            volatility = 0.03 if slug in {"kamatis", "sili", "sibuyas"} else 0.015
            prices = _series(rng, market_base, days, anchor, volatility)
            for offset, price in enumerate(prices):
                day = as_of - timedelta(days=days - 1 - offset)
                is_today = offset == days - 1
                # Smaller markets don't report every day; Kadiwa is closed on Sundays.
                if not is_today:
                    if market.name == "Kadiwa" and day.weekday() == 6:
                        continue
                    if market.name != "DA Bantay Presyo" and rng.random() < 0.08:
                        continue
                db.add(
                    CropPrice(
                        crop_id=crops[slug].id,
                        market_id=market.id,
                        price=price,
                        unit="kg",
                        date=day,
                        source=market.source,
                    )
                )
                count += 1
    db.commit()

    if with_demo_user:
        _seed_demo_user(db, crops)
    return count


def _seed_demo_user(db, crops):
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is not None:
        return user
    user = User(name="Juan Dela Cruz", email=DEMO_EMAIL, password=hash_password(DEMO_PASSWORD), location="Batangas")
    db.add(user)
    db.flush()
    for slug in ("palay", "kamatis", "sili", "mais"):
        db.add(SavedCrop(user_id=user.id, crop_id=crops[slug].id))
    db.add(PriceAlert(user_id=user.id, crop_id=crops["palay"].id, target_price=Decimal("20.00"), condition="below"))
    db.add(PriceAlert(user_id=user.id, crop_id=crops["kamatis"].id, target_price=Decimal("40.00"), condition="above"))
    db.commit()
    return user

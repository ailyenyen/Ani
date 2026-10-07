from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import SimpleTestCase

from scrapers.base import PriceRecord
from scrapers.normalize import normalize_crop_name, normalize_unit, parse_date, parse_price, validate


class NormalizeTests(SimpleTestCase):
    def test_crop_aliases(self):
        self.assertEqual(normalize_crop_name("Tomato"), "Kamatis")
        self.assertEqual(normalize_crop_name("  rice, ROUGH (palay) "), "Palay (Rough)")
        self.assertEqual(normalize_crop_name("Siling Labuyo"), "Sili")
        self.assertIsNone(normalize_crop_name("Ampalaya"))

    def test_prices(self):
        self.assertEqual(parse_price("₱35.00"), Decimal("35.00"))
        self.assertEqual(parse_price("PHP 1,200"), Decimal("1200.00"))
        self.assertEqual(parse_price("60 - 64"), Decimal("62.00"))
        self.assertIsNone(parse_price("n/a"))
        self.assertIsNone(parse_price(""))

    def test_units(self):
        self.assertEqual(normalize_unit("kilo"), "kg")
        self.assertEqual(normalize_unit("per kg"), "kg")
        self.assertEqual(normalize_unit(""), "kg")
        self.assertIsNone(normalize_unit("pc"))
        self.assertIsNone(normalize_unit("tali"))

    def test_dates(self):
        self.assertEqual(parse_date("Date: October 7, 2026"), date(2026, 10, 7))
        self.assertEqual(parse_date("As of 07 Oct 2026"), date(2026, 10, 7))
        self.assertEqual(parse_date("2026-10-07"), date(2026, 10, 7))
        self.assertIsNone(parse_date("sometime"))

    def test_validate(self):
        def record(**kw):
            base = dict(crop_name="Kamatis", price=Decimal("35"), unit="kg", market="Kadiwa", location="Batangas",
                        source="Kadiwa", price_date=date(2026, 10, 7), collected_at=datetime.now(timezone.utc))
            base.update(kw)
            return PriceRecord(**base)

        today = date(2026, 10, 8)
        self.assertEqual(validate(record(), today), [])
        self.assertTrue(validate(record(price=Decimal("0")), today))
        self.assertTrue(validate(record(price=None), today))
        self.assertTrue(validate(record(unit=None), today))
        self.assertTrue(validate(record(location=""), today))
        self.assertTrue(validate(record(price_date=date(2026, 12, 1)), today))
        self.assertTrue(validate(record(price_date=date(2024, 1, 1)), today))

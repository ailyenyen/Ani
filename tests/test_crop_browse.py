import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from core.management.commands.sync_regions import store
from scrapers.regional import Quote
from scrapers.psa_farmgate import SNAPSHOT, TABLE

from .base import TODAY, DatabaseTestCase


@patch("core.services.today", return_value=TODAY)
class CropBrowseTests(DatabaseTestCase):
    seed_data = False

    def setUp(self):
        super().setUp()
        with override_settings(BASE_DIR=Path(self._tmp.name)):
            self.publish("DA", TODAY, "Market A", ("Banana (Lakatan)", "Banana (Latundan)", "Commercial (Local) Regular Milled"))
            self.publish("LGU", TODAY, "Market B", ("Saging (Lakatan)", "Saba", "Palay", "Puso ng Saging"))
            self.publish("LGU", TODAY - timedelta(days=1), "Market B", ("Saging (Lakatan)",))

    def publish(self, source, day, market, products):
        rows = [Quote(product, "Grade A", market, Decimal("30"), Decimal("40"), product) for product in products]
        store(source, "Batangas", "Crops", day, rows, b"published evidence", "https://example.org/report")

    def test_catalog_groups_varieties_and_searches_both_languages(self, _today):
        for term in ("Banana", "saging", "Lakatan", "Saba"):
            with self.subTest(term=term):
                response = self.client.get("/prices/", {"q": term})
                groups = [group for group in response.context["groups"] if group["family"].slug == "banana"]
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]["varieties"], ["Lakatan", "Latundan", "Saba"])
                self.assertContains(response, 'href="/crops/family/banana/"', count=1)
        response = self.client.get("/prices/")
        self.assertContains(response, 'href="/crops/family/rice/"')
        self.assertContains(response, 'href="/crops/family/palay/"')

    def test_family_keeps_each_source_and_filters_variety_market_and_date(self, _today):
        response = self.client.get("/crops/family/banana/compare/")
        observations = response.context["page"].object_list
        self.assertEqual({row.listing.variety for row in observations}, {"Lakatan", "Latundan", "Saba"})
        self.assertEqual({row.price.source for row in observations if row.listing.variety == "Lakatan"}, {"DA", "LGU"})
        self.assertTrue(all(row.price.date == TODAY for row in observations))
        market_b = next(row.price.market_id for row in observations if row.price.market.name == "Market B")
        response = self.client.get("/crops/family/banana/compare/", {
            "variety": "Lakatan", "source": "LGU", "market": market_b,
            "date_from": (TODAY - timedelta(days=1)).isoformat(), "date_to": (TODAY - timedelta(days=1)).isoformat(),
        })
        row, = response.context["page"].object_list
        self.assertEqual((row.listing.product, row.price.source, row.price.date), ("Saging (Lakatan)", "LGU", TODAY - timedelta(days=1)))
        self.assertEqual((row.low, row.high), (Decimal("30"), Decimal("40")))
        self.assertContains(response, "https://example.org/report")

    def test_regional_compare_accepts_old_family_names(self, _today):
        response = self.client.get("/compare/", {"crop": "Banana", "as_of": TODAY.isoformat(), "days": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_crop"], "Banana / Saging")
        self.assertEqual(len(response.context["report"]["records"]), 4)

    def test_banana_shows_published_farmgate_separately_from_retail(self, _today):
        folder = Path(self._tmp.name) / "data" / "farmgate"
        folder.mkdir()
        (folder / SNAPSHOT).write_text(json.dumps({"table": TABLE, "observations": [
            {"variety": "Lakatan", "price": "45.25", "month": "2026-09-01"},
            {"variety": "Lakatan", "price": "40.00", "month": "2026-08-01"},
            {"variety": "Latundan", "price": "24.00", "month": "2026-09-01"},
        ]}), encoding="utf-8")
        with override_settings(BASE_DIR=Path(self._tmp.name), ANI_SAMPLE_DATA_NOTICE=False):
            response = self.client.get("/crops/family/banana/", {"variety": "Lakatan"})
            self.assertNotContains(response, "All PSA farmgate prices")
            self.assertContains(response, "Compare prices")
            self.assertContains(response, "Sep 2026")
            self.assertContains(response, "₱45.25")
            self.assertNotContains(response, "₱24.00")


class PlantPartFamilyTests(SimpleTestCase):
    def test_leaves_and_tops_are_not_the_crop_itself(self):
        from core.crop_families import identify_family
        self.assertEqual(identify_family("Ampalaya fruit [Bitter gourd]").slug, "bitter-gourd")
        self.assertNotEqual(identify_family("Ampalaya leaves").slug, "bitter-gourd")
        self.assertNotEqual(identify_family("Camote tops").slug, "sweet-potato")
        self.assertNotEqual(identify_family("Rice hay, dried hays").slug, "rice")
        self.assertEqual(identify_family("Banana leaves").slug, "banana-leaves")
        self.assertEqual(identify_family("Onion Leaves").slug, "spring-onion")

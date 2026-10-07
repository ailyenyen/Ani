from decimal import Decimal

from django.test import SimpleTestCase
from sqlalchemy import func, select

from core.models import CropPrice, Market, ScrapeRun
from scrapers.base import ScraperError
from scrapers.da_bantay_presyo import DABantayPresyoScraper
from scrapers.kadiwa import KadiwaScraper
from scrapers.local_market import LocalMarketScraper
from scrapers.pipeline import run_scrapers
from scrapers.registry import build_scrapers

from .base import TODAY, DatabaseTestCase


class ParserTests(SimpleTestCase):
    def test_da_wide_table(self):
        result = DABantayPresyoScraper(offline=True).run(today=TODAY)
        palay = {r.location: r.price for r in result.records if r.crop_name == "Palay (Rough)"}
        self.assertEqual(palay, {"Batangas": Decimal("22.50"), "Laguna": Decimal("23.00"), "Quezon": Decimal("22.00")})
        sili = [r for r in result.records if r.crop_name == "Sili"]
        self.assertEqual(sili[0].price, Decimal("62.00"))  # "60 - 64" range
        rejected = {raw.crop for raw, _ in result.rejected}
        self.assertEqual(rejected, {"Ampalaya", "Coconut"})

    def test_kadiwa_long_table(self):
        result = KadiwaScraper(offline=True).run(today=TODAY)
        self.assertTrue(all(r.market == "Kadiwa" for r in result.records))
        self.assertIn(("Kamote", "Batangas"), {(r.crop_name, r.location) for r in result.records})
        reasons = dict((raw.crop, reason) for raw, reason in result.rejected)
        self.assertIn("price is missing", reasons["Potato"])

    def test_local_bulletins(self):
        result = LocalMarketScraper(offline=True).run(today=TODAY)
        markets = {(r.market, r.location) for r in result.records}
        self.assertIn(("Sari-sari Market", "Batangas"), markets)
        self.assertIn(("Local Market", "Laguna"), markets)

    def test_changed_layout_raises(self):
        scraper = KadiwaScraper(offline=True)
        scraper.fetch = lambda: "<html><body><p>Site under maintenance</p></body></html>"
        with self.assertRaises(ScraperError):
            scraper.run(today=TODAY)

    def test_unknown_source(self):
        with self.assertRaises(KeyError):
            build_scrapers(["nope"])


class PipelineTests(DatabaseTestCase):
    def test_store_and_deduplicate(self):
        before = self.db.scalar(select(func.count(CropPrice.id)))
        runs = run_scrapers(self.db, build_scrapers(offline=True), today=TODAY)
        self.assertTrue(all(r.status != ScrapeRun.FAILED for r in runs))
        after_first = self.db.scalar(select(func.count(CropPrice.id)))
        self.assertGreaterEqual(after_first, before)

        runs = run_scrapers(self.db, build_scrapers(offline=True), today=TODAY)
        self.assertEqual(self.db.scalar(select(func.count(CropPrice.id))), after_first)
        self.assertTrue(all(r.records_saved == 0 and r.records_updated == 0 for r in runs))

    def test_scraped_price_is_stored(self):
        run_scrapers(self.db, build_scrapers(["kadiwa"], offline=True), today=TODAY)
        market = self.db.scalar(select(Market).where(Market.name == "Kadiwa", Market.location == "Batangas"))
        price = self.db.scalar(
            select(CropPrice.price).where(CropPrice.market_id == market.id, CropPrice.date == TODAY.replace(day=7))
            .join(CropPrice.crop).where(CropPrice.crop.has(slug="kamote"))
        )
        self.assertEqual(price, Decimal("40.00"))

    def test_failure_is_logged_and_others_continue(self):
        broken = KadiwaScraper(offline=True)
        broken.fetch = lambda: "<html></html>"
        runs = run_scrapers(self.db, [broken, LocalMarketScraper(offline=True)], today=TODAY)
        self.assertEqual(runs[0].status, ScrapeRun.FAILED)
        self.assertTrue(runs[0].error_message)
        self.assertNotEqual(runs[1].status, ScrapeRun.FAILED)

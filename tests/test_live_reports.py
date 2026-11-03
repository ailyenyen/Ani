from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from sqlalchemy import func, select

from core.models import CropPrice, PriceEvidence
from scrapers.base import BaseScraper, ScraperError
from scrapers.da_reports import parse_text, discover_reports
from scrapers.local_market import LocalMarketScraper
from .base import DatabaseTestCase


TEXT = (Path(__file__).resolve().parent.parent / "scrapers/fixtures/da_weekly_2026_11_01.txt").read_text(encoding="utf-8")
TODAY = date(2026, 11, 4)


class OfficialReportTests(SimpleTestCase):
    def test_verified_values_and_product_separation(self):
        report = parse_text(TEXT, TODAY)
        rows = {r.slug: r for r in report.observations}
        self.assertEqual((report.start, report.end), (date(2026, 10, 26), date(2026, 11, 1)))
        self.assertEqual(len(rows), 13)
        self.assertEqual(rows["kamatis"].price, Decimal("99.58"))
        self.assertEqual(rows["bigas"].price, Decimal("45.42"))
        self.assertEqual(rows["kadiwa-program-rice"].price, Decimal("20"))
        self.assertTrue(rows["kadiwa-program-rice"].note)
        self.assertNotIn("mais", rows)  # sweet corn is not yellow corn grain

    def test_wrong_region_or_layout_is_rejected(self):
        for text in (TEXT.replace("NCR Markets", "Laguna Markets"), "maintenance"):
            with self.assertRaises(ScraperError):
                parse_text(text, TODAY)

    def test_future_report_is_rejected(self):
        with self.assertRaises(ScraperError):
            parse_text(TEXT, date(2026, 10, 31))

    def test_missing_price_is_not_fabricated(self):
        report = parse_text(TEXT.replace("kg 99.58", "kg -"), TODAY)
        self.assertNotIn("kamatis", [r.slug for r in report.observations])

    def test_ambiguous_duplicate_is_rejected(self):
        with self.assertRaises(ScraperError):
            parse_text(TEXT + "\nTomato kg 20.00", TODAY)

    def test_unconfigured_source_never_loads_fixtures(self):
        with self.assertRaisesMessage(ScraperError, "not configured"):
            LocalMarketScraper().fetch()

    @patch("scrapers.da_reports.download")
    def test_discovery_only_uses_official_pdf_links(self, download):
        download.return_value = b'<a href="https://evil.example/weekly-average-prices-x.pdf">bad</a><a href="/wp-content/uploads/2026/11/Weekly-Average-Prices-test.pdf">good</a>'
        self.assertEqual(discover_reports(), ["https://www.da.gov.ph/wp-content/uploads/2026/11/Weekly-Average-Prices-test.pdf"])


@override_settings(ANI_SAMPLE_DATA_NOTICE=False)
class LiveImportTests(DatabaseTestCase):
    seed_data = False

    @patch("core.management.commands.sync_live.parse_pdf")
    @patch("core.management.commands.sync_live.download", return_value=b"%PDF-test")
    @patch("core.management.commands.sync_live.discover_reports", return_value=["https://www.da.gov.ph/report.pdf"])
    def test_repeat_import_is_idempotent_and_pages_show_evidence(self, discover, download, parse):
        parse.return_value = parse_text(TEXT, TODAY)
        with override_settings(BASE_DIR=Path(self._tmp.name)):
            call_command("sync_live", reports=1, stdout=StringIO())
            call_command("sync_live", reports=1, stdout=StringIO())
        self.assertEqual(self.db.scalar(select(func.count(CropPrice.id))), 13)
        self.assertEqual(self.db.scalar(select(func.count(PriceEvidence.price_id))), 13)
        with patch("core.services.today", return_value=TODAY):
            response = self.client.get("/crops/kamatis/?location=NCR")
            self.assertContains(response, "https://www.da.gov.ph/report.pdf")
            self.assertContains(response, "99.58")
            self.assertContains(response, "Weekly retail average, NCR")
            self.assertEqual(self.client.get("/home/").status_code, 200)

    def test_live_mode_blocks_sample_seed_and_offline_scrape(self):
        with self.assertRaises(CommandError):
            call_command("seed", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("scrape", offline=True, stdout=StringIO())

    @patch("core.management.commands.sync_live.download", side_effect=ScraperError("unavailable"))
    @patch("core.management.commands.sync_live.discover_reports", return_value=["https://www.da.gov.ph/report.pdf"])
    def test_failure_records_status_without_creating_prices(self, discover, download):
        with self.assertRaises(CommandError):
            call_command("sync_live", reports=1, stdout=StringIO(), stderr=StringIO())
        self.assertEqual(self.db.scalar(select(func.count(CropPrice.id))), 0)

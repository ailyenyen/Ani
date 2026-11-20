from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from sqlalchemy import select

from core.models import CropPrice, RegionalQuote
from scrapers.kadiwa import KADIWA_OUTLET_SOURCE

from .base import TODAY, DatabaseTestCase


@override_settings(ANI_SAMPLE_DATA_NOTICE=False)
class RefreshLiveTests(DatabaseTestCase):
    seed_data = False

    @patch("core.management.commands.refresh_live.call_command")
    def test_live_refresh_checks_alerts_after_imports(self, run):
        stdout, stderr = StringIO(), StringIO()
        call_command("refresh_live", stdout=stdout, stderr=stderr)
        self.assertEqual([args[0] for args, _ in run.call_args_list], ["sync_live", "sync_regions", "check_alerts"])

    @patch("core.management.commands.refresh_live.call_command")
    def test_source_failure_keeps_other_import_and_reports_failure(self, run):
        run.side_effect = [CommandError("Weekly source unavailable"), None, None]
        with self.assertRaisesMessage(CommandError, "sync_live"):
            call_command("refresh_live", stdout=StringIO(), stderr=StringIO())
        self.assertEqual([args[0] for args, _ in run.call_args_list], ["sync_live", "sync_regions", "check_alerts"])

    @patch("core.management.commands.refresh_live.call_command")
    def test_import_only_skips_alerts(self, run):
        call_command("refresh_live", no_alerts=True, stdout=StringIO(), stderr=StringIO())
        self.assertEqual([args[0] for args, _ in run.call_args_list], ["sync_live", "sync_regions"])

    @override_settings(ANI_KADIWA_OUTLET_PRICE_LIST_URL="https://example.org/price-list")
    @patch("core.management.commands.sync_regions.today", return_value=TODAY)
    @patch("core.management.commands.sync_regions.fetch")
    def test_configured_kadiwa_list_preserves_outlet_and_publication(self, fetch, _today):
        fixture = Path(__file__).resolve().parents[1] / "scrapers" / "fixtures" / "kadiwa.html"
        fetch.return_value = fixture.read_bytes()
        with override_settings(BASE_DIR=Path(self._tmp.name)):
            call_command("sync_regions", source="kadiwa", stdout=StringIO())
        quote = self.db.scalar(select(RegionalQuote).where(RegionalQuote.product == "Tomato"))
        self.assertEqual((quote.source, quote.region, quote.market), (KADIWA_OUTLET_SOURCE, "Batangas", "Kadiwa Lipa"))
        price = self.db.scalar(select(CropPrice).where(CropPrice.source == KADIWA_OUTLET_SOURCE))
        self.assertEqual(price.evidence.source_url, "https://example.org/price-list")

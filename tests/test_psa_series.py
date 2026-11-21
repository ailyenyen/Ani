import calendar
import json
from io import StringIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from decimal import Decimal

from core.management.commands.sync_regions import store
from core.psa_prices import catalog, crop_preview, product_unit, _display_product
from scrapers.regional import Quote
from scrapers.base import ScraperError
from scrapers.psa_openstat import RETAIL, WHOLESALE, fetch_table

from .base import TODAY, DatabaseTestCase

MONTHS = list(calendar.month_name)[1:]


def openstat_session(locations, commodities, cells):
    """A fake PSA OpenSTAT session: metadata on GET, the given cells on POST."""
    labels = {
        "Geolocation": locations,
        "Commodity": commodities,
        "Year": {"y25": "2025", "y26": "2026"},
        "Period": {str(index): name for index, name in enumerate(MONTHS, 1)},
    }
    metadata = {"variables": [{"code": key, "values": list(pairs), "valueTexts": list(pairs.values())}
                              for key, pairs in labels.items()]}

    def post(url, json=None, timeout=None):
        selection = {item["code"]: item["selection"]["values"] for item in json["query"]}
        year, = selection["Year"]
        data = []
        for location in selection["Geolocation"]:
            for commodity in selection["Commodity"]:
                for period in selection["Period"]:
                    data.append({"key": [location, commodity, period],
                                 "values": [cells.get((location, commodity, year, period), "..")]})
        reply = Mock()
        reply.content = __import__("json").dumps({
            "columns": [{"code": "Geolocation"}, {"code": "Commodity"}, {"code": "Period"}],  # Year is fixed, so omitted
            "data": data,
        }).encode("utf-8-sig")
        return reply

    session = Mock()
    session.get.return_value.content = json.dumps(metadata).encode("utf-8")
    session.post.side_effect = post
    return session


class OpenstatSeriesTests(TestCase):
    def test_wholesale_reads_the_wholesale_folder_and_skips_unpublished_and_current_months(self):
        session = openstat_session(
            {"0": "PHILIPPINES", "27": "..REGION IV-A (CALABARZON)"},
            {"t": "Tomato, ripe"},
            {("27", "t", "y26", "9"): "75.93", ("0", "t", "y26", "9"): "65.29",
             ("27", "t", "y26", "10"): "80.00", ("27", "t", "y25", "12"): "0"},
        )
        snapshot = fetch_table(session, WHOLESALE, "0052M4AWB05.px", TODAY)
        self.assertIn("/NWSNEW/0052M4AWB05.px", session.get.call_args.args[0])
        self.assertEqual(sorted(snapshot["observations"]), [
            ["t", "0", "2026-09-01", "65.29"],
            ["t", "27", "2026-09-01", "75.93"],
        ])  # October is the current month (not published yet); a zero is treated as unpublished
        self.assertEqual(snapshot["table"], "0052M4AWB05.px")

    def test_unexpected_layout_is_rejected(self):
        session = openstat_session({"0": "PHILIPPINES"}, {"t": "Tomato"}, {})
        metadata = json.loads(session.get.return_value.content)
        metadata["variables"][0]["code"] = "Region"
        session.get.return_value.content = json.dumps(metadata).encode()
        with self.assertRaisesRegex(ScraperError, "Unexpected PSA retail dimensions"):
            fetch_table(session, RETAIL, "0042M4ARN05.px", TODAY)

    def test_retail_labels_are_readable_and_keep_their_unit(self):
        self.assertEqual(_display_product("TOMATO, 1 KG"), "Tomato")
        self.assertEqual(_display_product("BITTER GOURD (AMPALAYA), FRUIT, 1 KG"), "Bitter Gourd (Ampalaya), Fruit")
        self.assertEqual(_display_product("Banana Lakatan, ripe*"), "Banana Lakatan, ripe*")
        self.assertEqual(product_unit("TOMATO, 1 KG"), "kg")
        self.assertEqual(product_unit("PINEAPPLE, 1 PC"), "piece")
        self.assertEqual(product_unit("GARLIC, 250 G"), "")
        self.assertEqual(product_unit("Banana Lakatan, ripe*"), "")
        self.assertEqual(product_unit("Cucumber"), "kg")


@patch("core.psa_prices.today", return_value=TODAY)
@patch("core.services.today", return_value=TODAY)
class SeriesPageTests(DatabaseTestCase):
    seed_data = False

    def write(self, kind, table, locations, commodities, observations):
        folder = Path(self._tmp.name) / "data" / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (Path(table).stem + ".json")).write_text(json.dumps({
            "table": table, "retrieved_on": TODAY.isoformat(),
            "locations": locations, "commodities": commodities, "observations": observations,
        }), encoding="utf-8")

    def setUp(self):
        super().setUp()
        # Each PSA table numbers CALABARZON differently; matching must use the name.
        self.write("wholesale", "0052M4AWB05.px", {"0": "PHILIPPINES", "27": "..REGION IV-A (CALABARZON)"},
                   {"t": "Tomato, ripe"},
                   [["t", "27", "2026-08-01", "70.00"], ["t", "27", "2026-09-01", "75.93"], ["t", "0", "2026-09-01", "65.29"]])
        self.write("retail", "0042M4ARN05.px", {"040000000": "..IV-A - CALABARZON"},
                   {"x": "TOMATO, 1 KG"}, [["x", "040000000", "2026-09-01", "92.50"]])
        self.live = override_settings(BASE_DIR=Path(self._tmp.name), ANI_SAMPLE_DATA_NOTICE=False)
        self.live.enable()
        # A real-time retail report for the crop page (the live catalog keeps working alongside PSA monthly data).
        store("DA", "Batangas", "Crops", TODAY, [Quote("Tomato", "Grade A", "Market A", Decimal("80"), Decimal("90"), "Tomato")],
              b"published evidence", "https://example.org/report")

    def tearDown(self):
        self.live.disable()
        super().tearDown()

    def test_crop_previews_find_the_home_region_by_name(self, *_):
        prices, has_crop = crop_preview(WHOLESALE, "tomato")
        self.assertTrue(has_crop)
        self.assertEqual([(row.product, row.price, row.month.isoformat()) for row in prices],
                         [("Tomato, ripe", "75.93", "2026-09-01")])
        retail, _ = crop_preview(RETAIL, "tomato")
        self.assertEqual([(row.product, row.unit, row.price) for row in retail], [("Tomato", "kg", "92.50")])

    def test_wholesale_page_lists_latest_price_per_location(self, *_):
        response = self.client.get("/prices/wholesale/", {"location": "regions"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wholesale Prices")
        self.assertContains(response, "₱75.93")
        self.assertNotContains(response, "₱70.00")  # older month for the same series and place
        self.assertContains(response, "/DB__2M__NWSNEW/0052M4AWB05.px/")

    def test_monthly_retail_page_and_links_back_to_live_prices(self, *_):
        response = self.client.get("/prices/retail/monthly/")
        self.assertContains(response, "Monthly Retail Averages")
        self.assertContains(response, "₱92.50")
        self.assertContains(response, 'href="/prices/"')

    def test_crop_page_shows_all_three_official_series_next_to_live_retail(self, *_):
        response = self.client.get("/crops/family/tomato/", {"region": "r4a"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["wholesale"].value, Decimal("75.93"))
        self.assertContains(response, "₱75.93")
        # The trend uses the PSA monthly series, including PSA monthly retail.
        self.assertEqual({d["kind"] for d in response.context["chart"]["datasets"]}, {"retail", "wholesale"})
        # Whole country: the live retail report (₱80–₱90 counts at its midpoint) next to national PSA prices.
        national = self.client.get("/crops/family/tomato/", {"region": ""})
        self.assertEqual((national.context["retail"]["average"], national.context["wholesale"].value),
                         (Decimal("85.00"), Decimal("65.29")))

    def test_pages_are_empty_in_sample_mode(self, *_):
        with override_settings(ANI_SAMPLE_DATA_NOTICE=True):
            response = self.client.get("/prices/wholesale/")
        self.assertContains(response, "No published wholesale data loaded")
        self.assertEqual(catalog(WHOLESALE, "tomato")[0].location, "REGION IV-A (CALABARZON)")


@override_settings(ANI_SAMPLE_DATA_NOTICE=False)
class SyncCommandTests(DatabaseTestCase):
    seed_data = False

    def test_sync_wholesale_writes_snapshots_and_keeps_old_ones_on_failure(self):
        snapshot = {"table": "0052M4AWB05.px", "retrieved_on": "2026-10-08", "commodities": {"t": "Tomato"},
                    "locations": {"0": "PHILIPPINES"}, "observations": [["t", "0", "2026-09-01", "65.29"]]}

        def fake_fetch(session, series, table, as_of):
            if table == "0052M4AWB06.px":
                raise ScraperError("PSA unavailable")
            return dict(snapshot, table=table)

        folder = Path(self._tmp.name) / "data" / "wholesale"
        folder.mkdir(parents=True)
        (folder / "0052M4AWB06.json").write_text("previous", encoding="utf-8")
        with override_settings(BASE_DIR=Path(self._tmp.name)), \
                patch("core.management.commands._psa_sync.fetch_table", side_effect=fake_fetch):
            with self.assertRaisesMessage(CommandError, "0052M4AWB06.px"):
                call_command("sync_wholesale", table=["0052M4AWB05.px", "0052M4AWB06.px"],
                             stdout=StringIO(), stderr=StringIO())
        self.assertEqual(json.loads((folder / "0052M4AWB05.json").read_text())["observations"], snapshot["observations"])
        self.assertEqual((folder / "0052M4AWB06.json").read_text(), "previous")

    @patch("core.management.commands.refresh_live.call_command")
    def test_refresh_live_keeps_realtime_by_default_and_adds_monthly_on_request(self, run):
        call_command("refresh_live", no_alerts=True, stdout=StringIO(), stderr=StringIO())
        self.assertEqual([args[0] for args, _ in run.call_args_list], ["sync_live", "sync_regions"])
        run.reset_mock()
        call_command("refresh_live", monthly=True, stdout=StringIO(), stderr=StringIO())
        self.assertEqual([args[0] for args, _ in run.call_args_list],
                         ["sync_live", "sync_regions", "check_alerts", "sync_farmgate", "sync_wholesale", "sync_psa_retail"])

    @patch("core.management.commands.refresh_live.call_command")
    def test_monthly_failure_does_not_block_realtime_prices_or_alerts(self, run):
        run.side_effect = [None, None, None, None, CommandError("PSA down"), None]
        with self.assertRaisesMessage(CommandError, "sync_wholesale"):
            call_command("refresh_live", monthly=True, stdout=StringIO(), stderr=StringIO())
        self.assertIn("check_alerts", [args[0] for args, _ in run.call_args_list])

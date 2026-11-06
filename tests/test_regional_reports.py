from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from sqlalchemy import func, select

from core.management.commands.sync_regions import store
from core.models import RegionalQuote
from core.regional_reports import build_report
from scrapers.base import ScraperError
from scrapers.regional import parse_da, parse_infanta, price_range, page_date, product_key, Quote
from .base import DatabaseTestCase

FIXTURES = Path(__file__).resolve().parent.parent / "scrapers/fixtures/regional"
DAY = date(2026, 11, 3)


class RegionalParserTests(SimpleTestCase):
    def test_real_calabarzon_rows_align_with_markets_and_keep_grades(self):
        rows = parse_da((FIXTURES / "header.html").read_bytes(), (FIXTURES / "rice.html").read_bytes())
        local = [r for r in rows if r.product == "COMMERCIAL (LOCAL) Regular Milled"]
        self.assertEqual(next(r.low for r in local if r.market == "BINAN CITY PUBLIC MARKET"), Decimal("48"))
        self.assertEqual(next(r.low for r in local if r.market == "SAN PABLO CITY PUBLIC MARKET"), Decimal("45"))
        self.assertFalse(any(r.market == "TANZA PUBLIC MARKET" for r in local))
        self.assertNotEqual(product_key(local[0].product,local[0].specification), product_key("COMMERCIAL (IMPORTED) Regular Milled",local[0].specification))

    def test_real_infanta_preserves_ranges_and_excludes_non_kg(self):
        day, rows = parse_infanta((FIXTURES / "infanta.html").read_bytes(), DAY)
        self.assertEqual(day, DAY)
        row = next(r for r in rows if r.product == "Calamansi")
        self.assertEqual((row.low,row.high), (Decimal("120"),Decimal("150")))
        self.assertFalse(any(r.product == "Okra" for r in rows))
        self.assertTrue(all("not specified" in r.specification for r in rows))

    def test_shifted_column_fails_instead_of_misassigning_market(self):
        with self.assertRaises(ScraperError):
            parse_da(b'<tr><th>COMMODITY</th><th>SPECIFICATIONS</th><th>A</th></tr>', b'<tr><td>Tomato</td><td>kg</td><td>10</td><td>20</td></tr>')

    def test_duplicate_market_names_excluded_and_reported(self):
        rows, warning = parse_da('<tr><th>COMMODITY</th><th>SPECIFICATIONS</th><th>A</th><th>A</th><th>B</th></tr>', '<tr><td>Tomato</td><td>KG</td><td>10</td><td>20</td><td>30</td></tr>', with_warnings=True)
        self.assertEqual([(r.market,r.low) for r in rows],[("B",Decimal("30"))])
        self.assertIn("A",warning)

    def test_bad_dates_and_prices_fail(self):
        for value in ("0", "100-50", "10 per bundle", "6000"):
            with self.subTest(value=value), self.assertRaises(ScraperError):
                price_range(value)
        self.assertIsNone(price_range("N/A"))
        with self.assertRaises(ScraperError):
            page_date("November 04, 2026",DAY)
        with self.assertRaises(ScraperError):
            page_date("No available date",DAY)


class RegionalReportTests(DatabaseTestCase):
    seed_data = False

    def add(self,market,price,region="Region A",source="DA",spec="Grade A",day=DAY,high=None):
        row = RegionalQuote(source=source, region=region, market=market, category="Vegetables", product_key=product_key("Tomato",spec),
            product="Tomato", specification=spec, low=Decimal(price), high=Decimal(high or price), date=day,
            source_url="https://example.org/source",sha256="a"*64,raw_row="published row")
        self.db.add(row)
        self.db.commit()
        return row

    def test_lowest_and_ties_are_grouped_by_specification_and_date(self):
        self.add("A","20")
        self.add("B","20",region="Region B",source="LGU")
        self.add("C","30")
        self.add("Unspecified","5",source="LGU",spec="Unspecified")
        self.add("Yesterday","1",day=DAY-timedelta(days=1))
        report = build_report(self.db,DAY,7)
        group = next(g for g in report["groups"] if g["specification"] == "Grade A" and g["date"] == DAY)
        self.assertEqual(group["lowest"],Decimal("20"))
        self.assertEqual({w.market for w in group["winners"]},{"A","B"})
        self.assertEqual(len(group["regional"]),2)
        self.assertEqual(len(report["groups"]),3)

    def test_region_source_and_freshness_filters_apply_before_ranking(self):
        self.add("A","20")
        self.add("B","5",region="Region B")
        self.add("LGU","1",source="LGU")
        self.add("Stale","1",day=DAY-timedelta(days=15))
        report = build_report(self.db,DAY,7,regions=["Region A"],source="DA")
        self.assertEqual([r.market for r in report["records"]],["A"])

    def test_latest_per_market_and_range_lower_bound(self):
        self.add("A","10",day=DAY-timedelta(days=1))
        self.add("A","25",high="35")
        self.add("B","30")
        report = build_report(self.db,DAY,7)
        self.assertEqual(len(report["records"]),2)
        self.assertEqual(report["groups"][0]["lowest"],Decimal("25"))

    def test_import_idempotence_withdrawals_and_atomic_validation(self):
        rows = [Quote("Tomato","Grade A","A",Decimal("20"),Decimal("20"),"raw"), Quote("Eggplant","Grade A","B",Decimal("30"),Decimal("30"),"raw")]
        with override_settings(BASE_DIR=Path(self._tmp.name)):
            store("DA","Region A","Vegetables",DAY,rows,b"archive","https://example.org")
            store("DA","Region A","Vegetables",DAY,rows[:1],b"archive","https://example.org")
            self.assertEqual(self.db.scalar(select(func.count(RegionalQuote.id))),1)
            with self.assertRaises(ScraperError):
                store("DA","Region A","Vegetables",DAY,rows[:1]*2,b"archive","https://example.org")
            self.assertEqual(self.db.scalar(select(func.count(RegionalQuote.id))),1)

    @patch("core.regional_views.today",return_value=DAY)
    def test_report_and_csv_use_filters_and_reject_invalid_inputs(self,_today):
        self.add("A","20")
        self.add("B","5",region="Region B")
        params={"crop":"Tomato / Kamatis","as_of":str(DAY),"days":"7","region":["Region A"]}
        response=self.client.get("/reports/regions/",params)
        self.assertContains(response,"Lowest reported: ₱20.00/kg")
        response=self.client.get("/reports/regions/",{**params,"format":"csv"})
        self.assertIn("Region A",response.content.decode())
        self.assertNotIn("Region B",response.content.decode())
        self.assertEqual(response["Content-Type"],"text/csv; charset=utf-8")
        self.assertEqual(self.client.get("/reports/regions/",{**params,"days":"99"}).status_code,400)

    def test_empty_database_has_useful_empty_state(self):
        self.assertContains(self.client.get("/reports/regions/"),"No comparable current prices")

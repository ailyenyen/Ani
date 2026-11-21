import json
from decimal import Decimal
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from django.test import override_settings

from core.management.commands.sync_regions import store
from core.market_overview import region_id
from scrapers.regional import Quote

from .base import TODAY, DatabaseTestCase


class RegionMatchingTests(TestCase):
    def test_each_sources_spelling_maps_to_one_region(self):
        for label in ("NCR", "..NATIONAL CAPITAL REGION (NCR)", "..NCR - National Capital Region"):
            self.assertEqual(region_id(label), "ncr", label)
        for label in ("REGION IV-A (CALABARZON)", "..REGION IV-A (CALABARZON)", "..IV-A - CALABARZON"):
            self.assertEqual(region_id(label), "r4a", label)
        self.assertEqual(region_id("CAR (CORDILLERA ADMINISTRATIVE REGION)"), "car")
        self.assertEqual(region_id("BARMM (Bangsamoro Autonomous Region of Muslim Mindanao)"), "barmm")
        self.assertEqual(region_id("REGION XIII (Caraga)"), "r13")
        self.assertEqual(region_id("PHILIPPINES"), "")


@patch("core.psa_prices.today", return_value=TODAY)
@patch("core.services.today", return_value=TODAY)
class MarketPricesHomeTests(DatabaseTestCase):
    seed_data = False

    def snapshot(self, kind, table, locations, commodities, observations):
        folder = Path(self._tmp.name) / "data" / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (Path(table).stem + ".json")).write_text(json.dumps({
            "table": table, "retrieved_on": TODAY.isoformat(), "locations": locations,
            "commodities": commodities, "observations": observations,
        }), encoding="utf-8")

    def setUp(self):
        super().setUp()
        self.live = override_settings(BASE_DIR=Path(self._tmp.name), ANI_SAMPLE_DATA_NOTICE=False)
        self.live.enable()
        quotes = lambda price: [Quote("Tomato", "Grade A", "Market", Decimal(price), Decimal(price), "Tomato")]
        store("DA", "REGION IV-A (CALABARZON)", "Crops", TODAY, quotes("100"), b"evidence", "https://example.org/a")
        # One source batch per region and day (a later batch for the same day replaces it, as in real imports).
        store("DA", "NCR", "Crops", TODAY,
              quotes("120") + [Quote("Cabbage", "Grade A", "Market", Decimal("60"), Decimal("60"), "Cabbage")],
              b"evidence", "https://example.org/b")
        # Wholesale and farmgate number CALABARZON differently (27 vs 28); both must match by name.
        self.snapshot("wholesale", "0052M4AWB05.px", {"0": "PHILIPPINES", "27": "..REGION IV-A (CALABARZON)"},
                      {"t": "Tomato, ripe"}, [["t", "27", "2026-08-01", "75.00"], ["t", "0", "2026-08-01", "65.00"]])
        self.snapshot("farmgate", "0032M4AFN05.px", {"0": "PHILIPPINES", "28": "..REGION IV-A (CALABARZON)"},
                      {"t": "Tomato"}, [["t", "28", "2026-06-01", "23.00"], ["t", "0", "2026-06-01", "20.00"]])

    def tearDown(self):
        self.live.disable()
        super().tearDown()

    def card(self, response, slug):
        return next(card for card in response.context["page"].object_list if card.slug == slug)

    def test_crop_card_combines_live_retail_with_psa_wholesale_and_farmgate_for_the_region(self, *_):
        response = self.client.get("/home/", {"region": "r4a"})
        self.assertEqual(response.status_code, 200)
        tomato = self.card(response, "tomato")
        values = {line.kind: line.value for line in tomato.lines}
        self.assertEqual(values, {"retail": Decimal("100.00"), "wholesale": Decimal("75.00"), "farmgate": Decimal("23.00")})
        self.assertContains(response, "₱100.00")
        self.assertContains(response, "CALABARZON (Region IV-A)")

    def test_whole_country_uses_national_psa_values_and_all_retail_markets(self, *_):
        tomato = self.card(self.client.get("/home/", {"region": ""}), "tomato")
        values = {line.kind: line.value for line in tomato.lines}
        # Two markets published ₱100 and ₱120: the card shows a real published price, never their ₱110 average.
        self.assertEqual(values, {"retail": Decimal("100.00"), "wholesale": Decimal("65.00"), "farmgate": Decimal("20.00")})
        retail = tomato.line("retail")
        self.assertEqual((retail.count, retail.source_note), (2, "Market · DA"))

    def test_filters_search_completeness_and_gap(self, *_):
        response = self.client.get("/home/", {"region": "", "q": "kamatis"})
        self.assertEqual([card.slug for card in response.context["page"].object_list], ["tomato"])
        complete = self.client.get("/home/", {"region": "", "show": "complete"})
        self.assertEqual([card.slug for card in complete.context["page"].object_list], ["tomato"])
        gap = self.client.get("/home/", {"region": "", "sort": "gap"})
        self.assertEqual(gap.context["page"].object_list[0].slug, "tomato")

    def test_region_choice_is_remembered(self, *_):
        self.client.get("/home/", {"region": "ncr"})
        self.assertEqual(self.client.get("/home/").context["region"], "ncr")

    def test_navigation_is_simplified(self, *_):
        response = self.client.get("/home/")
        nav = response.content.decode().split('<ul class="side-nav">', 1)[1].split("</ul>", 1)[0]
        for label in ("Home", "Price Alerts", "My Crops"):
            self.assertIn(label, nav)
        self.assertNotIn("Compare Markets", nav)
        account = response.content.decode().split('<div class="side-account"', 1)[1].split("</div>", 1)[0]
        for label in ("Help &amp; Support", "Dark mode", "Log in"):
            self.assertIn(label, account)
        self.assertNotIn("topbar-actions", response.content.decode())
        self.assertNotIn("Good evening", response.content.decode())
        for label in ("Buyer Offers", "Farmgate Prices", "Wholesale Prices", "Market Prices", "Retail Prices"):
            self.assertNotIn(label, nav)
        self.assertEqual(self.client.get("/compare/offers/").status_code, 404)

    def test_retail_prices_page_is_named_retail(self, *_):
        response = self.client.get("/prices/")
        self.assertContains(response, "<h1>Retail Prices</h1>", html=False)
        self.assertNotContains(response, "Market Prices")

    def test_choosing_price_types_limits_cards_and_chart(self, *_):
        self.snapshot("farmgate", "0032M4AFN05.px", {"28": "..REGION IV-A (CALABARZON)"}, {"t": "Tomato"},
                      [["t", "28", "2026-05-01", "21.00"], ["t", "28", "2026-06-01", "23.00"]])
        response = self.client.get("/home/", {"region": "r4a", "types": ["retail", "farmgate"]})
        tomato = self.card(response, "tomato")
        self.assertEqual([line.kind for line in tomato.lines], ["farmgate", "retail"])  # farm to shelf
        self.assertNotContains(response, "₱75.00")  # the wholesale price is hidden
        chart = response.context["chart"]
        self.assertEqual([dataset["kind"] for dataset in chart["datasets"]], ["farmgate"])  # retail history needs PSA retail data
        self.assertContains(response, 'name="types" value="farmgate" checked', html=False)

    def test_no_types_ticked_means_all_types(self, *_):
        tomato = self.card(self.client.get("/home/", {"region": "r4a", "types": []}), "tomato")
        self.assertEqual([line.kind for line in tomato.lines], ["farmgate", "wholesale", "retail"])

    def test_complete_and_gap_use_only_the_selected_types(self, *_):
        only_retail = self.client.get("/home/", {"region": "", "types": ["retail"], "show": "complete"})
        self.assertEqual(sorted(card.slug for card in only_retail.context["page"].object_list), ["cabbage", "tomato"])
        gap = self.client.get("/home/", {"region": "r4a", "types": ["retail", "wholesale"], "sort": "gap"})
        self.assertEqual(self.card(gap, "tomato").gap, Decimal("25.00"))

    def test_trend_banner_shows_monthly_lines_per_price_type(self, *_):
        self.snapshot("wholesale", "0052M4AWB05.px", {"27": "..REGION IV-A (CALABARZON)"}, {"t": "Tomato, ripe"},
                      [["t", "27", "2026-07-01", "70.00"], ["t", "27", "2026-08-01", "75.00"]])
        response = self.client.get("/home/", {"region": "r4a", "chart": "tomato"})
        chart = response.context["chart"]
        # The axis runs to the current month; months after the last PSA average are "not published yet".
        self.assertEqual(chart["labels"], ["Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026", "Oct 2026"])
        wholesale = next(d for d in chart["datasets"] if d["kind"] == "wholesale")
        self.assertEqual(wholesale["values"], [None, 70.0, 75.0, None, None])
        self.assertEqual(chart["publishedUntil"], 2)
        retail_marker = next(m for m in chart["markers"] if m["kind"] == "retail")
        self.assertEqual((retail_marker["index"], retail_marker["value"], retail_marker["text"]), (4, 100.0, "₱100.00 Oct 8"))
        self.assertContains(response, 'data-chart="trend-overview"')

    def test_freshness_spread_and_summary(self, *_):
        response = self.client.get("/home/", {"region": "r4a", "chart": "tomato"})
        tomato = self.card(response, "tomato")
        fresh = {line.kind: line.fresh for line in tomato.lines}
        # Today is Oct 8: retail Oct 8 is new, wholesale Aug is 1–3 months old, farmgate Jun is older.
        self.assertEqual(fresh, {"retail": "new", "wholesale": "aging", "farmgate": "old"})
        self.assertEqual((tomato.spread, tomato.spread_note), (Decimal("77.00"), "Jun vs Oct data"))
        self.assertContains(response, "+₱77.00")
        self.assertEqual(response.context["insight"], "Retail is ₱25.00 above wholesale (Oct vs Aug reports).")
        self.assertContains(response, "Crop prices")
        self.assertContains(response, "Within 30 days")

    def test_range_switch_limits_the_months(self, *_):
        self.snapshot("wholesale", "0052M4AWB05.px", {"27": "..REGION IV-A (CALABARZON)"}, {"t": "Tomato, ripe"},
                      [["t", "27", f"2025-{m:02d}-01", "60.00"] for m in range(1, 13)] + [["t", "27", "2026-08-01", "75.00"]])
        six = self.client.get("/home/", {"region": "r4a", "chart": "tomato", "range": "6"}).context["chart"]
        everything = self.client.get("/home/", {"region": "r4a", "chart": "tomato", "range": "all"}).context["chart"]
        self.assertEqual(six["labels"][0], "May 2026")
        self.assertEqual(everything["labels"][0], "Jan 2025")


    def test_published_ranges_are_shown_in_full(self, *_):
        store("DA", "REGION IV-A (CALABARZON)", "Crops", TODAY,
              [Quote("Tomato", "Grade A", "Market", Decimal("90"), Decimal("110"), "Tomato")], b"evidence", "https://example.org/c")
        response = self.client.get("/home/", {"region": "r4a", "chart": "tomato"})
        retail = self.card(response, "tomato").line("retail")
        self.assertEqual((retail.value, retail.high, retail.ranged), (Decimal("90.00"), Decimal("110.00"), True))
        self.assertContains(response, "₱90.00<span class=\"cp-range\">–₱110.00</span>", html=False)

    def test_retail_minus_farmgate_stays_when_farmgate_is_hidden(self, *_):
        response = self.client.get("/home/", {"region": "r4a", "types": ["retail", "wholesale"]})
        self.assertTrue(response.context["show_spread"])
        self.assertEqual(self.card(response, "tomato").spread, Decimal("77.00"))
        self.assertContains(response, "Retail minus farmgate")

    def test_last_price_type_cannot_be_turned_off(self, *_):
        response = self.client.get("/home/", {"region": "r4a", "types": ["retail"]})
        self.assertContains(response, 'class="cp-type is-locked"', html=False)
        self.assertContains(response, '<input type="hidden" name="types" value="retail">', html=False)
        self.assertContains(response, '<span class="cp-type-mark" aria-hidden="true">✕</span>Farmgate', html=False)

    def test_trend_follows_one_product_instead_of_averaging(self, *_):
        self.snapshot("wholesale", "0052M4AWB05.px", {"27": "..REGION IV-A (CALABARZON)"},
                      {"t": "Tomato, ripe", "c": "Tomato, cherry"},
                      [["t", "27", "2026-07-01", "70.00"], ["t", "27", "2026-08-01", "75.00"],
                       ["c", "27", "2026-07-01", "200.00"], ["c", "27", "2026-08-01", "210.00"]])
        response = self.client.get("/home/", {"region": "r4a", "chart": "tomato"})
        wholesale = self.card(response, "tomato").line("wholesale")
        self.assertEqual((wholesale.value, wholesale.source_note), (Decimal("75.00"), "Tomato, ripe · PSA monthly average"))
        line = next(d for d in response.context["chart"]["datasets"] if d["kind"] == "wholesale")
        self.assertEqual(line["values"][1:3], [70.0, 75.0])  # not (70+200)/2

    def test_crop_page_averages_every_dataset_and_highlights_the_newest(self, *_):
        from datetime import timedelta
        store("LGU", "REGION IV-A (CALABARZON)", "Crops", TODAY - timedelta(days=3),
              [Quote("Tomato", "Grade A", "Market", Decimal("80"), Decimal("90"), "Tomato")], b"evidence", "https://example.org/d")
        response = self.client.get("/crops/family/tomato/", {"region": "r4a"})
        retail = response.context["retail"]
        self.assertEqual((retail["average"], retail["reports"]), (Decimal("92.50"), 2))  # (100 + 85) / 2
        self.assertEqual((retail["newest"]["source"], retail["newest"]["low"]), ("DA", Decimal("100.00")))
        self.assertEqual([(s["source"], s["average"], s.get("newest", False)) for s in retail["sources"]],
                         [("DA", Decimal("100.00"), True), ("LGU", Decimal("85.00"), False)])
        self.assertContains(response, "cf-tag-new\">New<")
        self.assertContains(response, 'data-chart="trend-overview"')

    def test_crop_page_switches_between_markets_and_regions(self, *_):
        markets = self.client.get("/crops/family/tomato/compare/", {"region": "r4a"})
        self.assertEqual(markets.context["view"], "markets")
        self.assertEqual([row.price.market.location for row in markets.context["page"].object_list], ["REGION IV-A (CALABARZON)"])
        self.assertContains(markets, "Markets in CALABARZON (Region IV-A)")
        regions = self.client.get("/crops/family/tomato/compare/", {"region": "r4a", "view": "regions"})
        rows = {row["key"]: row for row in regions.context["region_rows"]}
        self.assertEqual(rows["ncr"]["retail"]["average"], Decimal("120.00"))
        self.assertEqual(rows[""]["retail"]["average"], Decimal("110.00"))
        self.assertTrue(rows["r4a"]["current"])
        self.assertIn("region=ncr", rows["ncr"]["markets_link"])
        self.assertIn("view=markets", rows["ncr"]["markets_link"])
        # The crop page links to both views and ends with a snapshot of where the crop is cheapest.
        page = self.client.get("/crops/family/tomato/", {"region": "r4a"})
        self.assertIn("/crops/family/tomato/compare/", page.context["compare_regions_link"])
        self.assertIn("view=regions", page.context["compare_regions_link"])
        snapshot = page.context["snapshot"]
        cards = {card["title"]: card for card in snapshot["cards"]}
        self.assertEqual(cards["Cheapest region"]["value"], min(r["retail"]["average"] for r in rows.values() if r["key"] and r["retail"]))
        self.assertEqual(snapshot["of"], len([r for r in rows.values() if r["key"] and r["retail"]]))
        self.assertIn("Lowest in CALABARZON", cards)
        # A market link from the home page (?location=) opens the page on that region.
        self.assertEqual(self.client.get("/crops/family/tomato/", {"location": "NCR"}).context["region"], "ncr")

    def test_farmgate_matches_psa_names_uses_palay_for_rice_and_falls_back_to_the_country(self, *_):
        from core.crop_families import identify_family
        self.assertEqual(identify_family("Pepper, bell").slug, identify_family("Bell Pepper").slug)
        self.assertEqual(identify_family("Guayabano [Soursop]").slug, identify_family("Guyabano").slug)
        self.assertEqual(identify_family("Starapple").slug, identify_family("Star Apple").slug)
        store("DA", "NCR", "Crops", TODAY, [Quote("Tomato", "Grade A", "Market", Decimal("120"), Decimal("120"), "Tomato"),
                                           Quote("Rice", "Well milled", "Market", Decimal("50"), Decimal("50"), "Rice")],
              b"evidence", "https://example.org/e")
        self.snapshot("farmgate", "0032M4AFN01.px", {"0": "PHILIPPINES"}, {"p": "Palay [Paddy] Other Variety, dry"},
                      [["p", "0", "2026-08-01", "18.50"]])
        response = self.client.get("/home/", {"region": "ncr"})
        tomato, rice = self.card(response, "tomato"), self.card(response, "rice")
        # NCR has no farmgate prices: the whole-country figure is shown and labelled.
        self.assertEqual((tomato.line("farmgate").value, tomato.line("farmgate").national), (Decimal("20.00"), True))
        self.assertEqual(rice.line("farmgate").value, Decimal("18.50"))
        self.assertIn("Palay", rice.line("farmgate").source_note)
        self.assertContains(response, " · PH")

    def test_leeks_are_not_counted_as_onions(self, *_):
        from core.crop_families import identify_family
        self.assertEqual(identify_family("Onion Leeks").slug, "leeks")
        self.assertEqual(identify_family("Sitao [Stringbeans]").slug, identify_family("Stringbeans").slug)
        self.assertEqual(identify_family("Onion, red").slug, "onion")

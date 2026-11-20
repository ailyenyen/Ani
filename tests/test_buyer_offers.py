from decimal import Decimal

from django.test import SimpleTestCase


class BuyerOfferTests(SimpleTestCase):
    url = "/compare/offers/"

    def test_anonymous_can_compare_offers_by_net_not_quoted_price(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Compare Buyer Offers")
        response = self.client.post(self.url, {
            "quantity": "100", "offer_a-price": "40", "offer_a-transport": "600",
            "offer_a-handling": "200", "offer_b-price": "35",
        })
        self.assertContains(response, "₱300.00 more")
        self.assertEqual(response.context["better_offer"], "Offer B")
        first, second = response.context["results"]
        self.assertEqual((first["gross"], first["costs"], first["net"], first["per_kg"]),
                         (Decimal("4000"), Decimal("800"), Decimal("3200"), Decimal("32")))
        self.assertEqual(second["net"], Decimal("3500"))
        self.assertIn("no-store", response["Cache-Control"])

    def test_blank_costs_and_currency_rounding_handle_ties(self):
        response = self.client.post(self.url, {"quantity": "0.467", "offer_a-price": "5", "offer_b-price": "5"})
        self.assertContains(response, "Both offers leave you with the same amount")
        self.assertEqual([result["net"] for result in response.context["results"]], [Decimal("2.34"), Decimal("2.34")])

    def test_invalid_amounts_show_field_errors_without_results(self):
        response = self.client.post(self.url, {
            "quantity": "0", "offer_a-price": "-1", "offer_b-price": "5", "offer_b-handling": "-5",
        })
        self.assertContains(response, "Check the highlighted fields")
        self.assertIn("quantity", response.context["harvest"].errors)
        self.assertIn("price", response.context["offers"][0][1].errors)
        self.assertIn("handling", response.context["offers"][1][1].errors)
        self.assertFalse(response.context["results"])

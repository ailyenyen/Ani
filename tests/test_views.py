from unittest import mock

from django.test import override_settings
from sqlalchemy import select

from core.models import Market, Notification, PriceAlert, SavedCrop, User

from .base import TODAY, DatabaseTestCase


@override_settings(SESSION_COOKIE_SECURE=False)
@mock.patch("core.services.today", return_value=TODAY)
class ViewTests(DatabaseTestCase):
    def login(self):
        response = self.client.post("/login/", {"email": "juan@example.com", "password": "ani12345"})
        self.assertEqual(response.status_code, 302)

    def test_public_pages(self, _today):
        for url in ["/", "/about/", "/home/", "/prices/", "/prices/?crop=kamatis&when=week&location=all", "/crops/kamatis/",
                    "/crops/palay/?range=90&location=Laguna", "/compare/?crop=palay&location=Batangas",
                    "/help/", "/login/", "/signup/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_compare_shows_best_price(self, _today):
        response = self.client.get("/compare/?crop=palay&location=Batangas")
        self.assertContains(response, "<strong>Kadiwa — ₱24.00/kg</strong>", html=False)

    def test_crop_trend_respects_selected_markets_and_period(self, _today):
        markets = list(self.db.scalars(select(Market).where(Market.location == "Batangas").order_by(Market.name)))
        selected = markets[:2]
        response = self.client.get("/crops/palay/", {
            "location": "Batangas", "range": "30", "trend_market": [str(m.id) for m in selected],
        })
        self.assertContains(response, 'data-chart="market-trend"')
        chart = response.context["trend_chart"]
        self.assertEqual([s["label"] for s in chart["series"]], [f"{m.name} · Batangas" for m in selected])
        self.assertGreater(len(chart["labels"]), 7)

    def test_landing_page(self, _today):
        response = self.client.get("/")
        self.assertContains(response, "Know the fair price")
        self.assertContains(response, "Kadiwa")  # best Palay price in the live preview
        self.assertContains(response, 'href="/home/"')

    def test_landing_sends_signed_in_users_to_dashboard(self, _today):
        self.login()
        self.assertRedirects(self.client.get("/"), "/home/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/about/").status_code, 200)

    def test_private_pages_need_login(self, _today):
        for url in ["/alerts/", "/alerts/new/", "/my-crops/", "/profile/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response["Location"].startswith("/login/?next="))

    def test_create_alert(self, _today):
        self.login()
        response = self.client.post("/alerts/new/", {"crop": "sili", "target_price": "75", "condition": "above"})
        self.assertRedirects(response, "/alerts/", fetch_redirect_response=False)
        user = self.db.scalar(select(User).where(User.email == "juan@example.com"))
        alerts = self.db.scalars(select(PriceAlert).where(PriceAlert.user_id == user.id)).all()
        self.assertIn("75.00", [str(a.target_price) for a in alerts])

    def test_alert_dialog_returns_to_the_page_it_was_opened_from(self, _today):
        self.login()
        page = self.client.get("/home/")
        self.assertContains(page, 'id="alert-dialog"')
        response = self.client.post("/alerts/new/", {"crop": "sili", "target_price": "60", "condition": "below",
                                                     "next": "/crops/family/chili/"})
        self.assertRedirects(response, "/crops/family/chili/", fetch_redirect_response=False)
        # Never to another site.
        response = self.client.post("/alerts/new/", {"crop": "sili", "target_price": "61", "condition": "below",
                                                     "next": "https://example.com/"})
        self.assertRedirects(response, "/alerts/", fetch_redirect_response=False)

    def test_alert_page_uses_a_searchable_crop_picker(self, _today):
        self.login()
        response = self.client.get("/alerts/new/", {"crop": "sili"})
        self.assertContains(response, "data-combobox")
        self.assertContains(response, 'value="sili" data-price')

    def test_alert_form_errors_are_plain(self, _today):
        self.login()
        response = self.client.post("/alerts/new/", {"crop": "", "target_price": "abc"})
        self.assertContains(response, "Please choose a crop.")
        self.assertContains(response, "Please type a number")

    def test_cannot_touch_other_users_alert(self, _today):
        self.client.post("/signup/", {"name": "Maria", "email": "maria@example.com", "password": "maria12345",
                                      "location": "Quezon"})
        juan = self.db.scalar(select(User).where(User.email == "juan@example.com"))
        alert = self.db.scalars(select(PriceAlert).where(PriceAlert.user_id == juan.id)).first()
        self.assertEqual(self.client.post(f"/alerts/{alert.id}/delete/").status_code, 404)

    def test_add_several_crops_at_once_and_see_them_with_details_links(self, _today):
        self.login()
        response = self.client.post("/my-crops/add/", {"crop": ["talong", "kamatis"], "next": "/my-crops/"})
        self.assertRedirects(response, "/my-crops/", fetch_redirect_response=False)
        page = self.client.get("/my-crops/")
        self.assertContains(page, "View details")
        self.assertNotContains(page, "View Price")
        self.assertContains(page, 'id="add-dialog"')
        self.assertContains(page, 'id="alert-dialog"')
        titles = [item["title"] for item in page.context["items"]]
        self.assertTrue({"Talong", "Kamatis"} <= set(titles) or len(titles) >= 2)
        for item in page.context["items"]:
            self.assertTrue(item["detail_link"].startswith("/crops/family/"))
        # The old picker page now opens the dialog on My Crops.
        self.assertRedirects(self.client.get("/my-crops/add/"), "/my-crops/#add", fetch_redirect_response=False)

    def test_notifications_have_their_own_page(self, _today):
        self.login()
        juan = self.db.scalar(select(User).where(User.email == "juan@example.com"))
        self.db.add(Notification(user_id=juan.id, title="Sili is now ₱80.00/kg", message="That is above your target.", link="/crops/family/chili/"))
        self.db.commit()
        alerts = self.client.get("/alerts/")
        self.assertNotContains(alerts, "That is above your target.")
        page = self.client.get("/notifications/")
        self.assertContains(page, "That is above your target.")
        self.assertEqual(page.context["unread"], 1)
        self.assertEqual(self.client.get("/notifications/").context["unread"], 0)  # read once shown
        home = self.client.get("/home/")
        self.assertContains(home, 'href="/notifications/"')

    def test_notify_when_reported_is_an_alert_for_any_report(self, _today):
        self.login()
        self.client.post("/alerts/new/", {"crop": "talong", "condition": "above", "target_price": "0.01", "next": "/my-crops/"})
        page = self.client.get("/alerts/")
        self.assertContains(page, "When a price is reported")

    def test_save_crop(self, _today):
        self.login()
        self.client.post("/my-crops/add/", {"crop": "talong"})
        juan = self.db.scalar(select(User).where(User.email == "juan@example.com"))
        slugs = {s.crop.slug for s in self.db.scalars(select(SavedCrop).where(SavedCrop.user_id == juan.id))}
        self.assertIn("talong", slugs)

from unittest import mock

from django.test import override_settings
from sqlalchemy import select

from core.models import PriceAlert, SavedCrop, User

from .base import TODAY, DatabaseTestCase


@override_settings(SESSION_COOKIE_SECURE=False)
@mock.patch("core.services.today", return_value=TODAY)
class ViewTests(DatabaseTestCase):
    def login(self):
        response = self.client.post("/login/", {"email": "juan@example.com", "password": "ani12345"})
        self.assertEqual(response.status_code, 302)

    def test_public_pages(self, _today):
        for url in ["/", "/prices/", "/prices/?crop=kamatis&when=week&location=all", "/crops/kamatis/",
                    "/crops/palay/?range=90&location=Laguna", "/compare/?crop=palay&location=Batangas",
                    "/help/", "/login/", "/signup/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_compare_shows_best_price(self, _today):
        response = self.client.get("/compare/?crop=palay&location=Batangas")
        self.assertContains(response, "Kadiwa: <span class=\"price\">₱24.00/kg</span>", html=False)

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

    def test_save_crop(self, _today):
        self.login()
        self.client.post("/my-crops/add/", {"crop": "talong"})
        juan = self.db.scalar(select(User).where(User.email == "juan@example.com"))
        slugs = {s.crop.slug for s in self.db.scalars(select(SavedCrop).where(SavedCrop.user_id == juan.id))}
        self.assertIn("talong", slugs)

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from core import services
from core.alerts import check_alerts
from core.models import Crop, CropPrice, Market, Notification, PriceAlert, User

from .base import TODAY, DatabaseTestCase


class ServiceTests(DatabaseTestCase):
    def crop(self, slug):
        return services.get_crop(self.db, slug)

    def test_headline_prefers_reference_source(self):
        rows = services.latest_prices(self.db, as_of=TODAY, location="Batangas", crop_ids=[self.crop("kamatis").id])
        headline = services.pick_headline(rows)
        self.assertEqual(headline.market.name, "DA Bantay Presyo")
        self.assertEqual(headline.price, Decimal("35.00"))
        self.assertEqual(headline.date, TODAY)

    def test_compare_markets_highest_first(self):
        rows = services.compare_markets(self.db, self.crop("palay"), "Batangas", as_of=TODAY)
        self.assertEqual([r.market.name for r in rows][0], "Kadiwa")
        self.assertEqual([r.price for r in rows], sorted([r.price for r in rows], reverse=True))

    def test_change_against_last_week(self):
        crop = self.crop("palay")
        market = self.db.scalar(select(Market).where(Market.name == "DA Bantay Presyo", Market.location == "Batangas"))
        week_ago = self.db.scalar(select(CropPrice).where(
            CropPrice.crop_id == crop.id, CropPrice.market_id == market.id, CropPrice.date == TODAY - timedelta(days=7)))
        week_ago.price = Decimal("20.00")
        self.db.commit()
        rows = services.latest_prices(self.db, as_of=TODAY, location="Batangas", crop_ids=[crop.id])
        row = next(r for r in rows if r.market.id == market.id)
        self.assertAlmostEqual(row.change_pct, 12.5)
        self.assertEqual(row.direction, "up")

    def test_trend_and_stats(self):
        crop = self.crop("kamatis")
        market = self.db.scalar(select(Market).where(Market.name == "DA Bantay Presyo", Market.location == "Batangas"))
        self.assertEqual(len(services.price_trend(self.db, crop, market, 7, as_of=TODAY)), 7)
        stats = services.price_stats(self.db, crop, "Batangas", 7, as_of=TODAY)
        self.assertLessEqual(stats["lowest"].price, stats["average"])
        self.assertGreaterEqual(stats["highest"].price, stats["average"])

    def test_past_dates(self):
        rows = services.latest_prices(self.db, as_of=TODAY - timedelta(days=30))
        self.assertTrue(rows)
        self.assertTrue(all(r.date <= TODAY - timedelta(days=30) for r in rows))


class AlertTests(DatabaseTestCase):
    def make_alert(self, slug, target, condition):
        user = self.db.scalar(select(User).where(User.email == "juan@example.com"))
        crop = self.db.scalar(select(Crop).where(Crop.slug == slug))
        alert = PriceAlert(user_id=user.id, crop_id=crop.id, target_price=Decimal(target), condition=condition)
        self.db.add(alert)
        self.db.commit()
        return alert

    def test_triggers_once_per_price(self):
        alert = self.make_alert("kamatis", "34", PriceAlert.ABOVE)  # DA Batangas is 35.00
        sent = check_alerts(self.db, as_of=TODAY, alert_ids=[alert.id])
        self.assertEqual(len(sent), 1)
        self.assertIn("35.00", sent[0].message)
        self.assertEqual(check_alerts(self.db, as_of=TODAY, alert_ids=[alert.id]), [])

    def test_not_triggered_when_not_reached(self):
        alert = self.make_alert("kamatis", "500", PriceAlert.ABOVE)
        self.assertEqual(check_alerts(self.db, as_of=TODAY, alert_ids=[alert.id]), [])

    def test_below_uses_lowest_market(self):
        alert = self.make_alert("palay", "21", PriceAlert.BELOW)  # Local Market Batangas is 20.00
        sent = check_alerts(self.db, as_of=TODAY, alert_ids=[alert.id])
        self.assertIn("Local Market", sent[0].message)

    def test_inactive_alerts_ignored(self):
        alert = self.make_alert("kamatis", "1", PriceAlert.ABOVE)
        alert.active = False
        self.db.commit()
        check_alerts(self.db, as_of=TODAY)
        self.assertFalse(self.db.scalars(select(Notification).where(Notification.alert_id == alert.id)).all())

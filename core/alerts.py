"""
Checks price alerts against the latest prices and notifies users.

Runs after every scraper run (see ``scrapers.pipeline``), from the
``check_alerts`` management command, and right after a user creates an alert.
"""
import logging

from django.conf import settings
from django.urls import reverse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .models import Notification, PriceAlert, User, utcnow
from .notifications import send_push
from .services import latest_prices
from .templatetags.ani_tags import peso

logger = logging.getLogger("core.alerts")


def _site_link(path):
    base = getattr(settings, "ANI_SITE_URL", "")
    return f"{base}{path}" if base else path


def describe_alert(alert):
    word = "above" if alert.condition == PriceAlert.ABOVE else "below"
    return f"Notify me when the price is {word} {peso(alert.target_price)}/{alert.crop.unit}."


def check_alerts(db, as_of=None, alert_ids=None):
    """Create a notification for every active alert whose target was reached."""
    stmt = (
        select(PriceAlert)
        .where(PriceAlert.active.is_(True))
        .options(
            selectinload(PriceAlert.crop),
            selectinload(PriceAlert.user).selectinload(User.devices),
        )
    )
    if alert_ids is not None:
        stmt = stmt.where(PriceAlert.id.in_(alert_ids))

    created = []
    cache = {}
    for alert in db.scalars(stmt):
        location = alert.user.location or None
        key = (alert.crop_id, location)
        if key not in cache:
            cache[key] = latest_prices(db, as_of=as_of, location=location, crop_ids=[alert.crop_id])
        matches = [row for row in cache[key] if alert.is_met_by(row.price)]
        if not matches:
            continue

        pick = max if alert.condition == PriceAlert.ABOVE else min
        best = pick(matches, key=lambda r: r.price)
        if alert.last_notified_on and best.date <= alert.last_notified_on:
            continue  # already told the user about this price

        crop = alert.crop
        word = "above" if alert.condition == PriceAlert.ABOVE else "below"
        title = f"{crop.icon} {crop.name} is now {peso(best.price)}/{crop.unit}"
        message = (
            f"{crop.name} is {peso(best.price)}/{crop.unit} at {best.market.name} "
            f"({best.market.location}). That is {word} your target of "
            f"{peso(alert.target_price)}/{crop.unit}."
        )
        link = _site_link(reverse("crop_detail", args=[crop.slug]))
        notification = Notification(
            user=alert.user, alert_id=alert.id, title=title, message=message, link=link
        )
        db.add(notification)
        notification.push_sent = send_push(db, alert.user, title, message, link) > 0

        alert.last_notified_on = best.date
        alert.last_triggered_at = utcnow()
        created.append(notification)

    db.commit()
    if created:
        logger.info("Sent %d price alert notification(s)", len(created))
    return created

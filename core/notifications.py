"""
Push notifications through Firebase Cloud Messaging (HTTP v1 API).

If FCM is not configured, alerts are still saved as in-app notifications and
shown on the Price Alerts page; push delivery is simply skipped.
"""
import logging

from django.conf import settings
from sqlalchemy import delete

from .models import DeviceToken

logger = logging.getLogger("core.notifications")

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_authed_session = None


def fcm_configured():
    return bool(settings.FCM_PROJECT_ID and settings.FCM_SERVICE_ACCOUNT_FILE)


def web_push_configured():
    config = settings.FIREBASE_WEB_CONFIG
    return bool(config.get("apiKey") and config.get("projectId") and settings.FIREBASE_VAPID_KEY)


def _session():
    global _authed_session
    if _authed_session is None:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            settings.FCM_SERVICE_ACCOUNT_FILE, scopes=[FCM_SCOPE]
        )
        _authed_session = AuthorizedSession(credentials)
    return _authed_session


def send_push(db, user, title, body, link=""):
    """Send a push message to all of a user's devices. Returns how many were delivered."""
    if not user.push_enabled or not user.devices:
        return 0
    if not fcm_configured():
        logger.info("FCM not configured; skipping push for user %s", user.id)
        return 0

    url = f"https://fcm.googleapis.com/v1/projects/{settings.FCM_PROJECT_ID}/messages:send"
    delivered = 0
    expired = []
    for device in user.devices:
        message = {
            "message": {
                "token": device.token,
                "notification": {"title": title, "body": body},
                "webpush": {"fcm_options": {"link": link}} if link.startswith("https://") else {},
                "data": {"link": link},
            }
        }
        try:
            response = _session().post(url, json=message, timeout=10)
        except Exception:
            logger.exception("FCM request failed for device %s", device.id)
            continue
        if response.status_code == 200:
            delivered += 1
        elif response.status_code == 404 or "UNREGISTERED" in response.text:
            expired.append(device.token)
        else:
            logger.warning("FCM error %s: %s", response.status_code, response.text[:300])

    if expired:
        db.execute(delete(DeviceToken).where(DeviceToken.token.in_(expired)))
        logger.info("Removed %d expired device token(s)", len(expired))
    return delivered

from pathlib import Path

from django.conf import settings
from sqlalchemy import func, select

from .models import Notification
from .notifications import web_push_configured


_STATIC_DIR = Path(__file__).resolve().parent / "static" / "core"


def asset_version():
    """Changes whenever a CSS/JS file changes, so browsers fetch the new file instead of a cached one."""
    try:
        return str(int(max(f.stat().st_mtime for f in _STATIC_DIR.glob("*/*.*") if f.suffix in {".css", ".js"})))
    except ValueError:
        return "1"


def ani(request):
    user = getattr(request, "ani_user", None)
    unread = 0
    db = getattr(request, "db", None)
    if user is not None and db is not None:
        unread = db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id, Notification.is_read.is_(False)
            )
        )
    return {
        "current_user": user,
        "unread_count": unread,
        "show_sample_notice": settings.ANI_SAMPLE_DATA_NOTICE,
        "live_reports": not settings.ANI_SAMPLE_DATA_NOTICE,
        "reference_source": settings.ANI_REFERENCE_SOURCE,
        "support_email": settings.ANI_SUPPORT_EMAIL,
        "web_push_enabled": web_push_configured(),
        "asset_version": asset_version(),
    }

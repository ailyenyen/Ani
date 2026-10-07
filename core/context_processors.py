from django.conf import settings
from sqlalchemy import func, select

from .models import Notification
from .notifications import web_push_configured


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
        "reference_source": settings.ANI_REFERENCE_SOURCE,
        "support_email": settings.ANI_SUPPORT_EMAIL,
        "web_push_enabled": web_push_configured(),
    }

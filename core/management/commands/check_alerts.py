from django.core.management.base import BaseCommand

from core.alerts import check_alerts
from core.db import session_scope


class Command(BaseCommand):
    help = "Notify users whose price alerts have been reached."

    def handle(self, *args, **options):
        with session_scope() as db:
            sent = check_alerts(db)
        self.stdout.write(self.style.SUCCESS(f"Price alerts sent: {len(sent)}"))

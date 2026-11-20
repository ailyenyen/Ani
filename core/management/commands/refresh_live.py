from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from sqlalchemy import select

from core.db import create_tables, session_scope
from core.models import CropPrice


class Command(BaseCommand):
    help = "Refresh weekly and regional crop prices, then evaluate price alerts."

    def add_arguments(self, parser):
        parser.add_argument("--no-alerts", action="store_true", help="Import without notifying users.")

    def handle(self, *args, no_alerts, **options):
        if settings.ANI_SAMPLE_DATA_NOTICE:
            raise CommandError("Configure a dedicated live database before running this job.")
        create_tables()
        with session_scope() as db:
            unsupported_price = select(CropPrice.id).where(~CropPrice.evidence.has()).limit(1)
            if db.scalar(unsupported_price) is not None:
                raise CommandError("Database contains prices without live evidence. Use a dedicated live database.")

        failures = []
        streams = {"stdout": self.stdout, "stderr": self.stderr}
        for command in ("sync_live", "sync_regions"):
            try:
                call_command(command, **streams)
            except CommandError as exc:
                failures.append(command)
                self.stderr.write(f"{command}: {exc}")

        if len(failures) < 2 and not no_alerts:
            call_command("check_alerts", **streams)

        if failures:
            raise CommandError("Refresh reported errors in " + ", ".join(failures) + ". See the import logs.")

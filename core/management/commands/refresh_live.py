from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from sqlalchemy import select

from core.db import create_tables, session_scope
from core.models import CropPrice


class Command(BaseCommand):
    help = ("Refresh real-time retail prices (weekly DA reports and regional sources), then evaluate price alerts. "
            "Add --monthly to also refresh the PSA farmgate, wholesale and monthly retail series.")

    REALTIME = ("sync_live", "sync_regions")
    MONTHLY = ("sync_farmgate", "sync_wholesale", "sync_psa_retail")

    def add_arguments(self, parser):
        parser.add_argument("--no-alerts", action="store_true", help="Import without notifying users.")
        parser.add_argument("--monthly", action="store_true",
                            help="Also refresh the PSA monthly farmgate, wholesale and retail snapshots.")

    def handle(self, *args, no_alerts, monthly=False, **options):
        if settings.ANI_SAMPLE_DATA_NOTICE:
            raise CommandError("Configure a dedicated live database before running this job.")
        create_tables()
        with session_scope() as db:
            unsupported_price = select(CropPrice.id).where(~CropPrice.evidence.has()).limit(1)
            if db.scalar(unsupported_price) is not None:
                raise CommandError("Database contains prices without live evidence. Use a dedicated live database.")

        failures = []
        streams = {"stdout": self.stdout, "stderr": self.stderr}
        for command in self.REALTIME:
            try:
                call_command(command, **streams)
            except CommandError as exc:
                failures.append(command)
                self.stderr.write(f"{command}: {exc}")

        realtime_failures = len(failures)
        if realtime_failures < len(self.REALTIME) and not no_alerts:
            call_command("check_alerts", **streams)

        # Monthly PSA series are a separate reference; a failure here never blocks real-time prices or alerts.
        for command in (self.MONTHLY if monthly else ()):
            try:
                call_command(command, **streams)
            except CommandError as exc:
                failures.append(command)
                self.stderr.write(f"{command}: {exc}")

        if failures:
            raise CommandError("Refresh reported errors in " + ", ".join(failures) + ". See the import logs.")

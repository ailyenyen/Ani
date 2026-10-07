from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.alerts import check_alerts
from core.db import create_tables, session_scope
from core.services import today
from scrapers.pipeline import run_scrapers
from scrapers.registry import SCRAPERS, build_scrapers


class Command(BaseCommand):
    help = "Collect crop prices from public sources, store them, then check price alerts."

    def add_arguments(self, parser):
        parser.add_argument(
            "sources", nargs="*", help=f"Sources to run (default: all). Choices: {', '.join(SCRAPERS)}"
        )
        parser.add_argument(
            "--offline", action="store_true",
            help="Read the sample pages in scrapers/fixtures/ instead of the live websites.",
        )
        parser.add_argument("--no-alerts", action="store_true", help="Don't check price alerts afterwards.")

    def handle(self, *args, sources, offline, no_alerts, **options):
        try:
            scrapers = build_scrapers(
                sources,
                offline=offline,
                urls=settings.ANI_SCRAPER_URLS,
                timeout=settings.ANI_SCRAPER_TIMEOUT,
                user_agent=settings.ANI_SCRAPER_USER_AGENT,
            )
        except KeyError as exc:
            raise CommandError(exc.args[0])

        create_tables()
        with session_scope() as db:
            runs = run_scrapers(db, scrapers, today=today())
            for run in runs:
                line = (
                    f"{run.source}: {run.status} - found {run.records_found}, saved {run.records_saved}, "
                    f"updated {run.records_updated}, unchanged {run.records_skipped}, rejected {run.records_rejected}"
                )
                if run.error_message:
                    line += f" ({run.error_message})"
                style = self.style.ERROR if run.status == "failed" else self.style.SUCCESS
                self.stdout.write(style(line))

            if not no_alerts:
                sent = check_alerts(db)
                self.stdout.write(f"Price alerts sent: {len(sent)}")

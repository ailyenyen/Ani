"""Shared import command for the PSA OpenSTAT monthly price series (see scrapers/psa_openstat.py)."""
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services import today
from scrapers.base import ScraperError
from scrapers.psa_openstat import fetch_table


class PsaSyncCommand(BaseCommand):
    """Subclasses set ``series`` (a PsaSeries) and ``help``."""

    series = None

    def add_arguments(self, parser):
        parser.add_argument("--table", action="append", choices=list(self.series.tables),
                            help="Refresh only this OpenSTAT table. Repeat for more tables.")

    def handle(self, *args, table, **options):
        folder = Path(settings.BASE_DIR) / "data" / self.series.kind
        folder.mkdir(parents=True, exist_ok=True)
        failures = []
        as_of = today()
        with requests.Session() as session:
            for name in (table or self.series.tables):
                category = self.series.tables[name]
                try:
                    snapshot = self.fetch(session, name, as_of)
                    self.write_snapshot(folder / (Path(name).stem + ".json"), snapshot)
                except (ScraperError, requests.RequestException, OSError) as exc:
                    failures.append(name)
                    self.stderr.write(f"{category}: {exc}. Prior snapshot kept.")
                    continue
                self.stdout.write(self.style.SUCCESS(f"{category}: saved {len(snapshot['observations'])} published prices."))
                self.stdout.flush()
        if failures:
            raise CommandError("Could not refresh " + ", ".join(failures) + ".")

    def fetch(self, session, table, as_of):
        return fetch_table(session, self.series, table, as_of)

    @staticmethod
    def write_snapshot(destination, snapshot):
        folder = destination.parent
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as temp:
            temporary_path = Path(temp.name)
            try:
                json.dump(snapshot, temp, separators=(",", ":"), ensure_ascii=False)
                temp.write("\n")
            except Exception:
                temp.close()
                temporary_path.unlink(missing_ok=True)
                raise
        try:
            temporary_path.replace(destination)
        finally:
            temporary_path.unlink(missing_ok=True)

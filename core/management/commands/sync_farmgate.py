import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services import today
from scrapers.base import ScraperError
from scrapers.psa_farmgate import CROP_TABLES, fetch_crop_farmgate


class Command(BaseCommand):
    help = "Refresh official PSA crop farmgate prices for all published Philippine locations."

    def add_arguments(self, parser):
        parser.add_argument("--table", action="append", choices=list(CROP_TABLES), help="Refresh only this OpenSTAT crop table. Repeat for more tables.")

    def handle(self, *args, table, **options):
        folder = Path(settings.BASE_DIR) / "data" / "farmgate"
        folder.mkdir(parents=True, exist_ok=True)
        failures = []
        as_of = today()
        with requests.Session() as session:
            for series in (table or CROP_TABLES):
                try:
                    snapshot = fetch_crop_farmgate(session, series, as_of)
                    self.write_snapshot(folder / (Path(series).stem + ".json"), snapshot)
                except (ScraperError, requests.RequestException, OSError) as exc:
                    failures.append(series)
                    self.stderr.write(f"{CROP_TABLES[series]}: {exc}. Prior snapshot kept.")
                    continue
                self.stdout.write(self.style.SUCCESS(f"{CROP_TABLES[series]}: saved {len(snapshot['observations'])} published prices."))
                self.stdout.flush()
        if failures:
            raise CommandError("Could not refresh " + ", ".join(failures) + ".")

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

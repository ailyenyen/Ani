import hashlib
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from sqlalchemy import delete

from core.db import create_tables, session_scope
from core.catalog import publish, remove_batch
from core.models import RegionalQuote, RegionalImport, utcnow
from core.services import today
from scrapers.base import ScraperError
from scrapers.regional import (PORTAL, INFANTA, DA_SOURCE, LGU_SOURCE, CATEGORIES,
                              discover_regions, fetch_da, fetch, parse_infanta, product_key)


def store(source, region, category, report_date, quotes, archive, url, warning=""):
    sha = hashlib.sha256(archive).hexdigest()
    directory = Path(settings.BASE_DIR) / "data" / "regional"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{sha}.json").write_bytes(archive)
    # A complete source batch is committed atomically. Same-day corrections replace
    # that batch, including prices withdrawn by the publisher.
    with session_scope() as db:
        if quotes:
            remove_batch(db, source, region, category, report_date)
            db.execute(delete(RegionalQuote).where(RegionalQuote.source == source, RegionalQuote.region == region,
                RegionalQuote.category == category, RegionalQuote.date == report_date))
        identities = set()
        batch = []
        for row in quotes:
            key = product_key(row.product, row.specification, row.unit)
            identity = (key, row.market)
            if identity in identities:
                raise ScraperError("Duplicate product/market in source batch.")
            identities.add(identity)
            batch.append(RegionalQuote(source=source, region=region, market=row.market, category=category, product_key=key, product=row.product,
                specification=row.specification, unit=row.unit, low=row.low, high=row.high, date=report_date,
                source_url=url, sha256=sha, raw_row=row.raw))
        db.add_all(batch)
        db.flush()
        publish(db, batch)
        db.add(RegionalImport(source=source, region=region, category=category, status=("partial" if warning else "success") if quotes else "empty", count=len(quotes), error=warning))


class Command(BaseCommand):
    help = "Collect regional market crop prices from Bantay Presyo and Infanta LGU."

    def add_arguments(self, parser):
        parser.add_argument("--regions", nargs="*", help="Portal region codes; default: all published options.")
        parser.add_argument("--categories", nargs="+", default=list(CATEGORIES), choices=list(CATEGORIES))
        parser.add_argument("--source", choices=["all", "da", "infanta"], default="all")

    def handle(self, *args, regions, categories, source, **options):
        if settings.ANI_SAMPLE_DATA_NOTICE:
            raise CommandError("Use the live database configuration for real regional imports.")
        create_tables()
        failures = 0
        session = requests.Session()
        session.headers["User-Agent"] = "AniPriceBot/1.0"
        def failed(name, region, category, exc):
            nonlocal failures
            failures += 1
            with session_scope() as db:
                db.add(RegionalImport(source=name, region=region, category=category, status="failed", error=str(exc)))
            self.stderr.write(f"{name} / {region} / {category}: {exc}")
        try:
            if source in {"all", "da"}:
                try:
                    available = discover_regions(session)
                except ScraperError as exc:
                    available = []
                    failed(DA_SOURCE, "All regions", "Discovery", exc)
                unknown = set(regions or []) - {code for code, _ in available}
                if unknown:
                    raise CommandError("Unknown region codes: " + ", ".join(sorted(unknown)))
                for code, region in available:
                    if regions and code not in regions:
                        continue
                    for category in categories:
                        try:
                            day, quotes, archive, warning = fetch_da(session, code, category, today())
                            store(DA_SOURCE, region, CATEGORIES[category], day, quotes, archive, PORTAL + "tbl_rice.php", warning)
                            self.stdout.write(f"{region} / {CATEGORIES[category]} / {day}: {len(quotes)} prices", ending="\n")
                            self.stdout.flush()
                            if warning:
                                self.stderr.write(warning)
                        except (ScraperError, OSError) as exc:
                            failed(DA_SOURCE, region, CATEGORIES[category], exc)
            if source in {"all", "infanta"}:
                try:
                    content = fetch(session, INFANTA)
                    day, quotes = parse_infanta(content, today())
                    store(LGU_SOURCE, "REGION IV-A (CALABARZON)", "Crops", day, quotes, content, INFANTA)
                    self.stdout.write(f"Infanta / {day}: {len(quotes)} prices")
                except (ScraperError, OSError) as exc:
                    failed(LGU_SOURCE, "REGION IV-A (CALABARZON)", "Crops", exc)
        finally:
            session.close()
        if failures:
            raise CommandError(f"{failures} source batches failed; prior data retained. See Regional Report for coverage.")

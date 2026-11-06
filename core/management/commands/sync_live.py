"""Import real reports into a dedicated database; never seed example prices."""
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from sqlalchemy import select

from core.db import create_tables, session_scope
from core.models import Crop, CropPrice, Market, PriceEvidence, ScrapeRun
from core.services import today
from scrapers.base import ScraperError
from scrapers.da_reports import discover_reports, download, parse_pdf, digest


class Command(BaseCommand):
    help = "Import official DA weekly retail reports and their Kadiwa program rice entries."

    def add_arguments(self, parser):
        parser.add_argument("--reports", type=int, default=4, help="Newest weekly reports (1-12).")

    def handle(self, *args, reports, **options):
        if settings.ANI_SAMPLE_DATA_NOTICE:
            raise CommandError("Use a separate live database and ANI_SAMPLE_DATA_NOTICE=false before importing.")
        if not 1 <= reports <= 12:
            raise CommandError("--reports must be between 1 and 12.")
        create_tables()
        with session_scope() as db:
            if db.scalar(select(CropPrice.id).where(~CropPrice.id.in_(select(PriceEvidence.price_id))).limit(1)):
                raise CommandError("Database contains prices without live evidence. Use a fresh live database.")
        try:
            urls = discover_reports(reports)
        except ScraperError as exc:
            raise CommandError(str(exc)) from exc
        failures = 0
        for url in reversed(urls):
            started = datetime.now(timezone.utc)
            try:
                content = download(url)
                report = parse_pdf(content, today())
                sha = digest(content)
                archive = Path(settings.BASE_DIR) / "data" / "reports"
                archive.mkdir(parents=True, exist_ok=True)
                (archive / f"{sha}.pdf").write_bytes(content)
                # Full extracted text retains footnotes and report restrictions.
                (archive / f"{sha}.txt").write_text(report.text, encoding="utf-8")
                with session_scope() as db:
                    saved = 0
                    counts = {}
                    for row in report.observations:
                        counter = counts.setdefault(row.source, {"new": 0, "updated": 0, "skipped": 0})
                        crop = db.scalar(select(Crop).where(Crop.slug == row.slug))
                        if crop is None:
                            crop = Crop(name=row.name, slug=row.slug, category="Grains" if "rice" in row.slug or row.slug == "bigas" else "Crops")
                            db.add(crop)
                            db.flush()
                        market_name = "Kadiwa program (selected NCR markets)" if row.note else "DA NCR weekly retail average"
                        market = db.scalar(select(Market).where(Market.name == market_name, Market.location == "NCR"))
                        if market is None:
                            market = Market(name=market_name, location="NCR", source=row.source, source_url=url)
                            db.add(market)
                            db.flush()
                        price = db.scalar(select(CropPrice).where(CropPrice.crop_id == crop.id, CropPrice.market_id == market.id, CropPrice.date == report.end, CropPrice.source == row.source))
                        if price is None:
                            price = CropPrice(crop_id=crop.id, market_id=market.id, date=report.end, source=row.source, price=row.price)
                            db.add(price)
                            db.flush()
                            saved += 1
                            counter["new"] += 1
                        elif price.price != row.price:
                            counter["updated"] += 1
                        else:
                            counter["skipped"] += 1
                        price.price = row.price
                        price.collected_at = datetime.now(timezone.utc)
                        evidence = db.get(PriceEvidence, price.id)
                        if evidence is None:
                            evidence = PriceEvidence(price_id=price.id)
                            db.add(evidence)
                        evidence.source_url = url
                        evidence.report_start, evidence.report_end = report.start, report.end
                        evidence.sha256, evidence.raw_row, evidence.note = sha, row.raw, row.note
                    for source in sorted({r.source for r in report.observations}):
                        count = sum(r.source == source for r in report.observations)
                        counter = counts[source]
                        db.add(ScrapeRun(source=source, started_at=started, finished_at=datetime.now(timezone.utc), status="success", records_found=count, records_saved=counter["new"], records_updated=counter["updated"], records_skipped=counter["skipped"]))
                self.stdout.write(self.style.SUCCESS(f"{report.start} to {report.end}: {len(report.observations)} verified observations ({saved} new). {url}"))
                if not any(r.note for r in report.observations):
                    self.stderr.write("No Kadiwa program price in this report; no Kadiwa price invented.")
            except (ScraperError, OSError) as exc:
                failures += 1
                with session_scope() as db:
                    db.add(ScrapeRun(source="DA official reports", started_at=started, finished_at=datetime.now(timezone.utc), status="failed", error_message=f"{url}: {exc}"))
                self.stderr.write(str(exc))
        if failures:
            raise CommandError(f"{failures} report import(s) failed. Previous verified prices were retained.")

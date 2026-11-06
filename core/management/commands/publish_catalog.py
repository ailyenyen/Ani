from django.core.management.base import BaseCommand
from core.catalog import backfill
from core.db import create_tables, session_scope


class Command(BaseCommand):
    help = "Publish already downloaded regional observations into the shared catalog."
    def handle(self, *args, **options):
        create_tables()
        with session_scope() as db:
            count = backfill(db)
        self.stdout.write(f"Published {count} observations.")

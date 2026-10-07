from django.core.management.base import BaseCommand

from core import seed as seed_data
from core.db import create_tables, session_scope


class Command(BaseCommand):
    help = "Load sample crops, markets, price history and a demo account (not real prices)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=120, help="Days of price history to generate.")
        parser.add_argument("--reset", action="store_true", help="Delete all existing data first.")
        parser.add_argument("--no-demo-user", action="store_true", help="Don't create the demo account.")

    def handle(self, *args, days, reset, no_demo_user, **options):
        create_tables()
        with session_scope() as db:
            if reset:
                seed_data.reset(db)
                self.stdout.write("Deleted existing data.")
            count = seed_data.seed(db, days=days, with_demo_user=not no_demo_user)
        self.stdout.write(self.style.SUCCESS(f"Loaded {count} sample prices over {days} days."))
        if not no_demo_user:
            self.stdout.write(f"Demo account: {seed_data.DEMO_EMAIL} / {seed_data.DEMO_PASSWORD}")

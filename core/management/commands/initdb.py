from django.core.management.base import BaseCommand

from core.db import create_tables, drop_tables, get_engine


class Command(BaseCommand):
    help = "Create Ani's database tables (SQLAlchemy models)."

    def add_arguments(self, parser):
        parser.add_argument("--drop", action="store_true", help="Delete all tables and data first.")

    def handle(self, *args, drop=False, **options):
        if drop:
            drop_tables()
            self.stdout.write("Dropped all tables.")
        create_tables()
        self.stdout.write(self.style.SUCCESS(f"Tables ready in {get_engine().url.render_as_string(hide_password=True)}"))

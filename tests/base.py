import tempfile
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase

from core import db as core_db
from core.seed import seed

# A fixed "today" that matches the sample scraper pages (dated 2026-10-07).
TODAY = date(2026, 10, 8)


class DatabaseTestCase(SimpleTestCase):
    """Each test gets a fresh SQLite database seeded with sample data."""

    seed_data = True

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        core_db.configure(f"sqlite:///{Path(self._tmp.name) / 'test.sqlite3'}")
        core_db.create_tables()
        self.db = core_db.get_session()
        if self.seed_data:
            seed(self.db, days=40, as_of=TODAY)

    def tearDown(self):
        self.db.close()
        core_db.get_engine().dispose()
        self._tmp.cleanup()

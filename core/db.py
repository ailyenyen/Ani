"""
SQLAlchemy engine and session management.

The web app gets one session per request from ``core.middleware``; management
commands and scrapers use ``session_scope()``.
"""
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .models import Base

_engine = None
_SessionFactory = None


def configure(url=None, echo=None):
    """Create (or re-create) the engine. Tests call this with their own URL."""
    global _engine, _SessionFactory
    from django.conf import settings

    url = url or settings.ANI_DATABASE_URL
    echo = settings.ANI_DATABASE_ECHO if echo is None else echo

    if _engine is not None:
        _engine.dispose()

    kwargs = {"echo": echo, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine():
    if _engine is None:
        configure()
    return _engine


def get_session():
    if _SessionFactory is None:
        configure()
    return _SessionFactory()


@contextmanager
def session_scope():
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_tables():
    Base.metadata.create_all(get_engine())


def drop_tables():
    Base.metadata.drop_all(get_engine())

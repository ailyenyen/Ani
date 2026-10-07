"""
Django settings for Ani.

Django is used for routing, templates, forms, CSRF protection and sessions.
All application data (users, crops, markets, prices, alerts) lives in
PostgreSQL and is accessed through SQLAlchemy -- see ``core/db.py`` and
``core/models.py``. Django's own ORM is intentionally not used, so
``DATABASES`` is empty and sessions are stored in signed cookies.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --- Core -------------------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "dev-only-insecure-key-change-me" if DEBUG else None
)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.AniMiddleware",
]

ROOT_URLCONF = "ani.urls"
WSGI_APPLICATION = "ani.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.ani",
            ],
        },
    },
]

# Django's ORM is not used; the data layer is SQLAlchemy (core/db.py).
DATABASES = {}

SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 60  # stay signed in for 60 days
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
X_FRAME_OPTIONS = "SAMEORIGIN"
MESSAGE_STORAGE = "django.contrib.messages.storage.cookie.CookieStorage"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Ani: data layer --------------------------------------------------------

# PostgreSQL is the intended database, e.g.
#   postgresql+psycopg2://ani:ani@localhost:5432/ani
# A local SQLite file is used only when nothing is configured, so the UI can
# be tried without setting up a database server.
ANI_DATABASE_URL = os.environ.get("ANI_DATABASE_URL") or f"sqlite:///{BASE_DIR / 'ani_dev.sqlite3'}"
ANI_DATABASE_ECHO = env_bool("ANI_DATABASE_ECHO", False)

# Prices from this source are shown as the main ("headline") price of a crop.
ANI_REFERENCE_SOURCE = os.environ.get("ANI_REFERENCE_SOURCE", "DA Bantay Presyo")

# Shows a small notice that prices are sample data. Turn off once real
# scraped data is in the database.
ANI_SAMPLE_DATA_NOTICE = env_bool("ANI_SAMPLE_DATA_NOTICE", True)

# Public address of the site, used for links inside push notifications.
ANI_SITE_URL = os.environ.get("ANI_SITE_URL", "").rstrip("/")

ANI_SUPPORT_EMAIL = os.environ.get("ANI_SUPPORT_EMAIL", "support@ani.example")

# --- Ani: scrapers ----------------------------------------------------------

# Source URLs are configurable because public pages move. Verify each URL and
# its HTML structure before relying on a scraper in production.
ANI_SCRAPER_URLS = {
    "da_bantay_presyo": os.environ.get("ANI_SCRAPER_DA_URL", "http://www.bantaypresyo.da.gov.ph/"),
    "kadiwa": os.environ.get("ANI_SCRAPER_KADIWA_URL", "https://www.da.gov.ph/kadiwa/"),
    "local_market": os.environ.get("ANI_SCRAPER_LOCAL_URL", ""),
}
ANI_SCRAPER_TIMEOUT = int(os.environ.get("ANI_SCRAPER_TIMEOUT", "20"))
ANI_SCRAPER_USER_AGENT = os.environ.get(
    "ANI_SCRAPER_USER_AGENT",
    "AniPriceBot/1.0 (crop price aggregation for farmers; contact: support@ani.example)",
)

# --- Ani: Firebase Cloud Messaging -----------------------------------------

FCM_PROJECT_ID = os.environ.get("FCM_PROJECT_ID", "")
FCM_SERVICE_ACCOUNT_FILE = os.environ.get("FCM_SERVICE_ACCOUNT_FILE", "")
FIREBASE_WEB_CONFIG = {
    "apiKey": os.environ.get("FIREBASE_API_KEY", ""),
    "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN", ""),
    "projectId": FCM_PROJECT_ID,
    "messagingSenderId": os.environ.get("FIREBASE_MESSAGING_SENDER_ID", ""),
    "appId": os.environ.get("FIREBASE_APP_ID", ""),
}
FIREBASE_VAPID_KEY = os.environ.get("FIREBASE_VAPID_KEY", "")

# --- Logging ----------------------------------------------------------------

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "scraper_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "scraper.log"),
            "maxBytes": 1_000_000,
            "backupCount": 3,
            "formatter": "plain",
        },
    },
    "loggers": {
        "scrapers": {"handlers": ["console", "scraper_file"], "level": "INFO", "propagate": False},
        "core": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

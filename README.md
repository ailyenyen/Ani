# Ani: Crop Price Monitoring & Market Comparison

**Better Prices. Stronger Farmers.**

Ani brings crop prices from public sources (DA Bantay Presyo, Kadiwa price lists and local market bulletins) into one simple website for Filipino farmers. A farmer can see today's price, where it comes from, whether it is going up or down, which market pays the most, and get a message when a target price is reached.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env                      # optional; edit as needed

docker compose up -d                      # PostgreSQL (or leave ANI_DATABASE_URL unset to use SQLite)
.venv/bin/python manage.py initdb         # create tables
.venv/bin/python manage.py seed           # sample crops, markets, 120 days of prices, demo account
.venv/bin/python manage.py runserver
```

Open http://localhost:8000. Demo account: **juan@example.com / ani12345**.

> The seeded prices are **sample data for development**, not real market prices. A notice says so on every page until `ANI_SAMPLE_DATA_NOTICE=false`.

## Commands

| Command | What it does |
|---|---|
| `manage.py initdb [--drop]` | Create the database tables |
| `manage.py seed [--reset] [--days N]` | Load sample data and the demo account |
| `manage.py scrape [sources...] [--offline] [--no-alerts]` | Collect prices, store them, then check price alerts |
| `manage.py check_alerts` | Send notifications for alerts whose target was reached |
| `manage.py test tests` | Run the test suite |

`scrape --offline` reads the sample pages in `scrapers/fixtures/` instead of the live websites, so the whole pipeline can be tested without internet access. In production, run `manage.py scrape` on a schedule (e.g. cron, once or twice a day).

## Architecture

| Layer | Technology | Where |
|---|---|---|
| Web framework | Django 4.2 (routing, templates, forms, CSRF, sessions) | `ani/`, `core/views.py`, `core/templates/` |
| Database | PostgreSQL | `ANI_DATABASE_URL` |
| ORM / data layer | SQLAlchemy 2.0 | `core/models.py`, `core/db.py`, `core/services.py` |
| Data collection | BeautifulSoup (bs4) + requests | `scrapers/` |
| Charts | Chart.js | `core/static/core/js/charts.js` |
| Notifications | Firebase Cloud Messaging (HTTP v1) | `core/notifications.py`, `core/alerts.py` |

Django's own ORM is not used: `DATABASES` is empty, and sessions use signed cookies. Each request gets a SQLAlchemy session from `core.middleware.AniMiddleware`. Tables are created with `Base.metadata.create_all`. For schema changes after deployment, add Alembic.

### Data model (`core/models.py`)

`User`, `Crop`, `Market`, `CropPrice` (price history: one row per crop, market, date and source, with a unique constraint against duplicates), `SavedCrop`, `PriceAlert`, plus `Notification` (in-app alert messages), `DeviceToken` (FCM tokens) and `ScrapeRun` (scraper log).

### Scrapers (`scrapers/`)

```
scrapers/
    base.py               shared fetch → parse → normalize → validate flow
    normalize.py          crop name aliases, price/unit/date parsing, validation rules
    da_bantay_presyo.py   wide table: commodity × location
    kadiwa.py             long table: one row per product and location
    local_market.py       bulletin blocks per market
    pipeline.py           stores results, prevents duplicates, logs runs
    registry.py           list of available sources
    fixtures/             sample pages for offline development and tests
```

Each source only implements `parse()`. Everything is normalised into the same `PriceRecord` format. Because sites change their HTML, the scrapers:

- find tables by header words (e.g. "Commodity", "Price") instead of CSS classes;
- reject and log rows with unknown crops, missing or out-of-range prices, non-kilogram units, or bad dates;
- skip prices that jump more than 4× from the last known value (usually a sign the wrong column was read);
- update a stored price only if the source corrected it; otherwise unchanged rows are skipped;
- record every run (`ScrapeRun`) and log to `logs/scraper.log`; one failing source never stops the others.

**Before using live sources:** the source URLs are settings (`ANI_SCRAPER_*_URL`), and each parser follows the layout shown in its fixture. Check each real page's current structure (some DA price reports are published as PDFs) and adjust the adapter's `parse()` if it differs. Respect each site's terms of use and robots.txt.

### Price alerts and FCM

After each scrape, `check_alerts` compares active alerts with the latest prices in the user's province. When a target is reached, Ani saves a `Notification` (shown on the Price Alerts page) and, if FCM is configured, sends a push message to the user's registered devices. Each price triggers an alert only once.

To turn on push notifications: create a Firebase project, download a service-account JSON, set `FCM_PROJECT_ID` and `FCM_SERVICE_ACCOUNT_FILE`, and set the `FIREBASE_*` web config and `FIREBASE_VAPID_KEY` for browser registration (Profile → Notification Settings).

## Design notes

- Mobile first: bottom navigation (Home, Prices, Compare, Alerts, Profile), cards instead of wide tables, large touch targets (≥ 44px; main buttons 52–60px), 17px base text.
- Every important action has a text label; every price shows its source and how recent it is.
- Charts are only used where they help (7-day/30-day/3-month line chart, market comparison bars), each with a plain title. The numbers are always shown as text too, so pages stay useful if Chart.js cannot load on a slow connection.
- Scope: price aggregation and comparison only. No trading, marketplace, payments or price prediction.

## Production checklist

- `DJANGO_DEBUG=false`, a strong `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, HTTPS.
- `manage.py collectstatic` and serve `staticfiles/` (e.g. WhiteNoise or the web server).
- PostgreSQL via `ANI_DATABASE_URL`; schedule `manage.py scrape`.
- `ANI_SAMPLE_DATA_NOTICE=false` once real data is flowing.

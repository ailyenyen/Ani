# ANI

ANI helps Filipino farmers look up published crop retail prices, compare markets and track prices for saved crops. Each live observation carries its source and reporting date.

## Run with published prices

From the repository root in Windows PowerShell, create the Python environment and install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For a new checkout, copy `.env.live.example` to `.env` and edit `ANI_DATABASE_URL` to point to a dedicated SQLite file or PostgreSQL database. On an existing installation, keep the configured `.env`. Then run:

```powershell
.\Refresh-LiveData.ps1
.\.venv\Scripts\python.exe -X utf8 manage.py runserver 127.0.0.1:8000
```

Open [Home](http://127.0.0.1:8000/home/) to browse the latest prices. In [Compare Markets](http://127.0.0.1:8000/compare/), select a crop and expand the region, date and specification filters. The page identifies the lowest published price for comparable observations, shows tied markets, and exports the filtered observations to CSV. Sign up to save crops and create alerts.

## Run the offline demo

Use a separate checkout or configuration with `ANI_SAMPLE_DATA_NOTICE=true`. Leaving `ANI_DATABASE_URL` unset selects the local `ani_dev.sqlite3` file. With the dependencies installed:

```powershell
.\.venv\Scripts\python.exe manage.py seed
.\.venv\Scripts\python.exe manage.py runserver
```

The seed command creates the tables, 120 days of generated prices and the local demo account (`juan@example.com` / `ani12345`). The sample banner identifies these prices. Use `manage.py scrape --offline --no-alerts` to exercise the sample HTML pipeline.

## Data and architecture

| Component | Implementation |
|---|---|
| Web application | Python, Django 4.2, server-rendered templates, CSS, JavaScript and Chart.js |
| Storage | SQLAlchemy 2.0, SQLite for local use or PostgreSQL with psycopg2. Docker Compose provides an optional PostgreSQL 16 instance. |
| Collection | Requests and BeautifulSoup read regional market tables and Infanta bulletins. pdfplumber extracts weekly DA-AMAS reports. |
| Catalog | Weekly and regional importers populate the shared crops, markets, prices and evidence used throughout the app. Regional quotes preserve both endpoints of a price range. |
| Accounts and alerts | Django signed-cookie sessions and application-managed accounts. Alerts are stored in ANI and optional Firebase Cloud Messaging delivers push notifications. |

See the [live data guide](LIVE_DATA.md) for source coverage, refresh commands, upgrade steps, ranking rules and archive locations.

## Verification and deployment

Run Django's checks and the test suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -X utf8 manage.py check
.\.venv\Scripts\python.exe -X utf8 manage.py test tests
```

For deployment, configure HTTPS, a strong `DJANGO_SECRET_KEY`, allowed hosts and `DJANGO_DEBUG=false`. Serve collected static files and schedule the live imports. The app creates tables with SQLAlchemy metadata. Existing deployments need an explicit migration for changes to existing columns.

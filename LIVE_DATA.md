# Live data operations

## Source coverage

| Publication | Imported data | Reporting period |
|---|---|---|
| [DA Bantay Presyo portal](http://www.bantaypresyo.da.gov.ph/tbl_rice.php) | Market columns for rice, fruits, highland vegetables, lowland vegetables and spices in regions offered by the portal | The date supplied for each region and commodity category |
| [Infanta Commercial Center](https://infanta.gov.ph/icc) | Kilogram-denominated crop prices and ranges at the municipal market in Infanta, Quezon | The date printed on the LGU bulletin |
| [DA-AMAS price monitoring](https://www.da.gov.ph/price-monitoring/) | NCR average retail crop prices and separately identified Kadiwa program rice entries where published | A reporting week with start and end dates |

Kadiwa program coverage follows the restrictions in the source report. Each source publishes on its own schedule. Collection time records when ANI retrieved the publication. Use its reporting date to judge the age of the price.

## Import and refresh

Follow the [README setup](README.md#run-with-published-prices) first. The live example enables live mode through `ANI_SAMPLE_DATA_NOTICE=false`. Give live prices their own database. The local database, environment file, downloaded reports and scraper logs are excluded from Git.

The following commands use the project environment's Python interpreter:

| Command | Scope |
|---|---|
| `python manage.py sync_live --reports 4` | Discover and import the four newest weekly DA reports. Accepts 1–12 reports. |
| `python manage.py sync_regions` | Collect the five supported portal categories across its listed regions, then import Infanta. |
| `python manage.py sync_regions --source da --regions 040000000 --categories 1` | Refresh CALABARZON rice only. |
| `python manage.py sync_regions --source infanta` | Refresh the municipal bulletin only. |
| `python manage.py publish_catalog` | After upgrading an installation with existing regional quotes, publish unlinked observations into the shared catalog. Safe to rerun. |
| `python manage.py check_alerts` | Evaluate active alerts against the shared price catalog. |

On Windows, `Refresh-LiveData.ps1` runs both imports without sending notifications. It returns a nonzero exit code if either command fails. Run it manually or schedule it in Windows Task Scheduler. To send alerts after a successful refresh, run `check_alerts` separately. In live mode, `manage.py scrape` processes the weekly publications and checks alerts unless `--no-alerts` is supplied.

## Comparisons and evidence

Compare Markets ranks the latest available observation per market, source and product within the selected reporting window. It groups observations by product, specification, unit and source-reported date. If a source publishes a range, the lowest-price ranking uses its lower endpoint. All markets tied at that endpoint share the rank. The source comparison summarizes coverage and published ranges across the selected crop. NCR weekly series appear as benchmarks. The older `/reports/regions/` URL remains available.

Home, Market Prices, crop details, saved crops and alerts use the shared catalog. Regional imports update the source records and catalog within one transaction. For a range, an above-target alert uses the lower endpoint and a below-target alert uses the upper endpoint.

Each published catalog price has a source URL, original row, reporting period and SHA-256 linking it to archived evidence. Weekly PDFs and extracted text are stored in `data/reports/`. Regional response snapshots are stored in `data/regional/`. Back up the database **and** these directories to retain the full evidence trail.

Use the collection history in Compare Markets to inspect regional batches. It records partial coverage, ambiguous duplicate market columns, empty results and failures. A failed batch preserves earlier observations with their original dates. A subsequent successful run can pick up source corrections.

## Test fixtures

The weekly parser fixture is extracted from the [October 26–November 1, 2026 DA report](https://www.da.gov.ph/wp-content/uploads/2026/11/Weekly-Average-Prices-October-26-November-1-2026.pdf). Regional fixtures under `scrapers/fixtures/regional/` capture CALABARZON portal rows and selected Infanta bulletin rows used for regression tests. The live importers fetch their publications directly. Use the test commands in the README to check parsing, persistence, ranking, exports and alert behavior.

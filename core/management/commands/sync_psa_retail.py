from scrapers.psa_openstat import RETAIL

from ._psa_sync import PsaSyncCommand


class Command(PsaSyncCommand):
    help = ("Refresh official PSA monthly retail price averages for all published Philippine locations. "
            "Real-time retail prices are refreshed separately by sync_live and sync_regions.")
    series = RETAIL

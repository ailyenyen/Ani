from scrapers.psa_openstat import WHOLESALE

from ._psa_sync import PsaSyncCommand


class Command(PsaSyncCommand):
    help = "Refresh official PSA crop wholesale selling prices for all published Philippine locations."
    series = WHOLESALE

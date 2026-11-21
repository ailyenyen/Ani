from scrapers.psa_farmgate import fetch_crop_farmgate
from scrapers.psa_openstat import FARMGATE

from ._psa_sync import PsaSyncCommand


class Command(PsaSyncCommand):
    help = "Refresh official PSA crop farmgate prices for all published Philippine locations."
    series = FARMGATE

    def fetch(self, session, table, as_of):
        return fetch_crop_farmgate(session, table, as_of)

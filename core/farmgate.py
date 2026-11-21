"""Farmgate prices: the PSA farmgate series, read with the shared PSA monthly price reader."""
from scrapers.psa_openstat import FARMGATE

from .psa_prices import FARMGATE_PAGE, PsaPrice, catalog, crop_preview, latest_rows, series_prices

FarmgatePrice = PsaPrice

__all__ = ["FarmgatePrice", "farmgate_catalog", "latest_rows", "crop_farmgate_preview", "farmgate_prices"]


def farmgate_catalog(family=""):
    return catalog(FARMGATE, family)


def crop_farmgate_preview(family, variety=""):
    return crop_preview(FARMGATE, family, variety)


def farmgate_prices(request):
    return series_prices(request, FARMGATE_PAGE)

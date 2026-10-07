"""All available source adapters. Add a new source by writing a scraper and listing it here."""
from .da_bantay_presyo import DABantayPresyoScraper
from .kadiwa import KadiwaScraper
from .local_market import LocalMarketScraper

SCRAPERS = {
    scraper.slug: scraper
    for scraper in (DABantayPresyoScraper, KadiwaScraper, LocalMarketScraper)
}


def build_scrapers(names=None, offline=False, urls=None, timeout=20, user_agent="AniPriceBot/1.0"):
    urls = urls or {}
    names = names or list(SCRAPERS)
    unknown = [n for n in names if n not in SCRAPERS]
    if unknown:
        raise KeyError(f"Unknown source(s): {', '.join(unknown)}. Available: {', '.join(SCRAPERS)}")
    return [
        SCRAPERS[name](url=urls.get(name, ""), offline=offline, timeout=timeout, user_agent=user_agent)
        for name in names
    ]

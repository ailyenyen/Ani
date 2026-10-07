"""
Local market bulletins (municipal agriculture office / public market boards).

Expected layout: one block per market, each with a list of items:

    <article class="bulletin" data-market="Local Market" data-location="Batangas">
      <h2>Lipa City Public Market</h2>
      <time datetime="2026-10-07">October 7, 2026</time>
      <ul><li><span class="item">Kamatis</span> <span class="price">₱28.00 / kilo</span></li></ul>
    </article>
"""
import re

from .base import BaseScraper, RawRecord, ScraperError, cell_text

UNIT_IN_PRICE = re.compile(r"/\s*([A-Za-z]+)")


class LocalMarketScraper(BaseScraper):
    slug = "local_market"
    source_name = "Local market bulletin"
    default_market = "Local Market"
    fixture_name = "local_market.html"

    def parse(self, soup):
        bulletins = soup.select("article.bulletin, section.bulletin, div.bulletin")
        if not bulletins:
            raise ScraperError("No market bulletins found on the page.")

        for bulletin in bulletins:
            market = bulletin.get("data-market") or self._heading(bulletin)
            location = bulletin.get("data-location") or ""
            time_tag = bulletin.find("time")
            price_date = (time_tag.get("datetime") or cell_text(time_tag)) if time_tag else None

            for item in bulletin.select("li"):
                name = item.select_one(".item")
                price = item.select_one(".price")
                if name is None or price is None:
                    continue
                price_text = cell_text(price)
                unit_match = UNIT_IN_PRICE.search(price_text)
                yield RawRecord(
                    crop=cell_text(name),
                    price=price_text.split("/")[0],
                    unit=unit_match.group(1) if unit_match else "kg",
                    market=market,
                    location=location,
                    date=price_date,
                )

    @staticmethod
    def _heading(bulletin):
        heading = bulletin.find(["h2", "h3"])
        return cell_text(heading) if heading else ""

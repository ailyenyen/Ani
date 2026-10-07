"""
Crop price scrapers.

Each public source has its own adapter module (da_bantay_presyo.py, kadiwa.py,
local_market.py). Adapters only parse HTML; base.py and normalize.py turn their
output into one shared PriceRecord format, and pipeline.py stores it.
"""

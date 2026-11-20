"""Names used for browsing prices. Published product identities stay in the catalog."""
import re
from dataclasses import dataclass
from functools import lru_cache

from django.utils.text import slugify


@dataclass(frozen=True)
class CropFamily:
    slug: str
    name: str
    aliases: tuple[str, ...] = ()


FAMILIES = (
    CropFamily("banana-blossom", "Banana Blossom / Puso ng Saging", ("banana blossom", "puso ng saging")),
    CropFamily("banana-leaves", "Banana Leaves / Dahon ng Saging", ("banana leaves", "dahon ng saging")),
    CropFamily("banana", "Banana / Saging", ("banana", "bananas", "saging", "lakatan", "latundan", "saba", "señorita", "senorita", "cavendish", "cardaba")),
    CropFamily("palay", "Palay / Unmilled Rice", ("palay", "unmilled rice", "rough rice", "paddy rice")),
    CropFamily("rice", "Rice / Bigas", ("rice", "bigas", "commercial (local)", "commercial (imported)", "nfa")),
    CropFamily("sweet-potato", "Sweet Potato / Kamote", ("sweet potato", "kamote", "camote")),
    CropFamily("spring-onion", "Spring Onion", ("spring onion", "green onion", "scallion")),
    CropFamily("bell-pepper", "Bell Pepper", ("bell pepper",)),
    CropFamily("black-pepper", "Black Pepper", ("black pepper",)),
    CropFamily("tomato", "Tomato / Kamatis", ("tomato", "tomatoes", "kamatis")),
    CropFamily("eggplant", "Eggplant / Talong", ("eggplant", "talong")),
    CropFamily("garlic", "Garlic / Bawang", ("garlic", "bawang")),
    CropFamily("calamansi", "Calamansi / Kalamansi", ("calamansi", "kalamansi", "calamondin")),
    CropFamily("carrot", "Carrot / Karot", ("carrot", "carrots", "karot")),
    CropFamily("onion", "Onion / Sibuyas", ("onion", "onions", "sibuyas")),
    CropFamily("potato", "Potato / Patatas", ("potato", "potatoes", "patatas")),
    CropFamily("cabbage", "Cabbage / Repolyo", ("cabbage", "repolyo")),
    CropFamily("mango", "Mango / Mangga", ("mango", "mangga", "manggang kalabaw")),
    CropFamily("chili", "Chili / Sili", ("chili", "chilli", "sili", "siling labuyo")),
    CropFamily("corn", "Corn / Mais", ("corn", "mais", "maize", "corngrain")),
    CropFamily("cucumber", "Cucumber / Pipino", ("cucumber", "pipino")),
    CropFamily("ginger", "Ginger / Luya", ("ginger", "luya")),
    CropFamily("squash", "Squash / Kalabasa", ("squash", "kalabasa")),
    CropFamily("baguio-beans", "Baguio Beans / Habichuelas", ("baguio beans", "baguio bean", "habichuelas", "habitchuelas", "snap beans")),
    CropFamily("watermelon", "Watermelon / Pakwan", ("watermelon", "water melon", "pakwan")),
    CropFamily("pomelo", "Pomelo / Suha", ("pomelo", "suha")),
    CropFamily("papaya", "Papaya", ("papaya", "papayang")),
    CropFamily("lettuce", "Lettuce", ("lettuce",)),
    CropFamily("pechay", "Pechay / Bok Choy", ("pechay", "bokchoy", "bok choy")),
    CropFamily("grape", "Grapes / Ubas", ("grapes", "grape", "ubas")),
    CropFamily("broccoli", "Broccoli", ("broccoli", "broccolli")),
    CropFamily("cauliflower", "Cauliflower", ("cauliflower", "couliflower")),
    CropFamily("bitter-gourd", "Bitter Gourd / Ampalaya", ("bitter gourd", "bitter melon", "ampalaya")),
    CropFamily("chayote", "Chayote / Sayote", ("chayote", "sayote")),
    CropFamily("cassava", "Cassava / Kamoteng Kahoy", ("cassava", "kamoteng kahoy")),
    CropFamily("pineapple", "Pineapple / Pinya", ("pineapple", "pinya")),
    CropFamily("radish", "Radish / Labanos", ("radish", "labanos")),
    CropFamily("guava", "Guava / Bayabas", ("guava", "bayabas")),
    CropFamily("longan", "Longan", ("longan", "longgan")),
    CropFamily("taro", "Taro / Gabi", ("taro", "gabi")),
    CropFamily("coconut", "Coconut / Niyog", ("coconut", "niyog")),
    CropFamily("coffee", "Coffee / Kape", ("coffee", "kape")),
    CropFamily("mungbean", "Mung Bean / Monggo", ("mung bean", "mungbean", "monggo", "mongo", "munggo")),
)


def _words(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


def _has_phrase(text, phrase):
    return f" {_words(phrase)} " in f" {text} "


@lru_cache(maxsize=2048)
def identify_family(product):
    text = _words(product)
    for group in FAMILIES:
        if any(_has_phrase(text, alias) for alias in group.aliases):
            return group
    return CropFamily(slugify(product, allow_unicode=False), product.strip().title())


def variety_name(group, product, specification=""):
    text = _words(f"{product} {specification}")
    if group.slug == "banana":
        for labels in (("lakatan",), ("latundan",), ("saba",), ("señorita", "senorita"), ("cavendish",), ("cardaba",)):
            if any(_has_phrase(text, label) for label in labels):
                return labels[0].title()
    if group.slug == "rice":
        for label, aliases in (
            ("Kadiwa program rice", ("kadiwa",)), ("NFA rice", ("nfa",)),
            ("Regular milled", ("regular milled", "regular")), ("Well milled", ("well milled",)),
            ("Premium", ("premium",)), ("Special", ("special",)),
            ("Glutinous rice / Malagkit", ("glutinous", "malagkit")),
        ):
            if any(_has_phrase(text, alias) for alias in aliases):
                return label
    if group.slug == "onion":
        for label, aliases in (("Red", ("red", "pula")), ("White", ("white", "puti"))):
            if any(_has_phrase(text, alias) for alias in aliases):
                return label
    if group.slug == "mango" and any(_has_phrase(text, label) for label in ("carabao", "kalabaw")):
        return "Carabao"
    if _words(product) in {_words(a) for a in group.aliases} or not group.aliases:
        return "Unspecified variety"
    return product.title()

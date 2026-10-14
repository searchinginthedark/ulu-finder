"""Deterministic category assignment. Same listing in, same category out; no LLM.

Order of evidence: the listing's own template (eat/drink/buy/see/do), then keywords in
the NAME, then keywords early in the description. Name beats description because
descriptions mention neighbours ("next to the beach").
"""
import re

CATEGORIES = [
    ("dine", "Dine"), ("markets", "Markets & Hawkers"), ("cafes", "Cafes & Bars"),
    ("shopping", "Shopping"), ("nature", "Nature"), ("culture", "Temples & Heritage"),
    ("sights", "Sights"), ("activities", "Activities"),
]

SKIP = {"sleep", "go", "listing"}
SECTION_TYPE = {"see": "see", "do": "do", "buy": "buy", "eat": "eat", "drink": "drink"}


def _rx(words):
    return re.compile(r"(?<![\w])(?:" + "|".join(words) + r")(?![\w])", re.I)


# Local-language words matter: pasar (MS/ID market), chợ (VI), talat (TH), air terjun (waterfall).
MARKET = _rx([r"night ?markets?", r"markets?", r"hawker(?: centre| center)?s?", r"food ?(?:court|centre|center|street|hall)s?",
              r"pasar(?: malam| pagi)?", r"chợ(?: đêm)?", r"cho dem", r"talat", r"talad", r"walking street", r"bazaa?r",
              r"kopitiams? complex", r"floating market", r"tamu", r"pasar seni"])
NATURE = _rx([r"beach(?:es)?", r"waterfalls?", r"falls", r"national park", r"nature (?:park|reserve|trail)", r"forest(?: reserve| park)?",
              r"mount", r"mt\.?", r"mountains?", r"hills?", r"lakes?", r"islands?", r"islets?", r"caves?", r"rivers?", r"reserve",
              r"botanic(?:al)? gardens?", r"hot springs?", r"volcano", r"crater", r"rice (?:terraces?|fields?|paddies)", r"bay",
              r"lagoon", r"mangroves?", r"wetlands?", r"jungle", r"reef", r"canopy walk", r"gorge", r"valley", r"peak",
              r"pulau", r"gunung", r"bukit", r"pantai", r"danau", r"tasik", r"air terjun", r"gua", r"ko", r"koh", r"doi",
              r"nam tok", r"thác", r"núi", r"hồ", r"vịnh", r"đảo", r"bãi", r"taman negara", r"wildlife", r"sanctuary",
              r"safari", r"zoo", r"bird park", r"aquarium", r"wetland park", r"eco ?park", r"parks?", r"gardens?"])
# Malaysian and Indonesian place names start with Bukit/Gunung/Mount (Bukit Jalil, Mount Austin),
# so a building or business in the NAME vetoes nature from name AND description.
NOT_NATURE = _rx([r"theme park", r"water ?park", r"car ?park", r"memorial park", r"amusement park", r"business park",
                  r"industrial park", r"hotel", r"resort", r"mall", r"bar", r"restaurant", r"stadium", r"sports?",
                  r"tower", r"city", r"cent(?:re|er)", r"club", r"shop", r"school", r"station",
                  r"adventures?", r"tours?", r"div(?:e|ing)", r"scuba", r"golf"])
EATERY = _rx([r"restaurants?", r"restoran", r"seafood", r"kitchen", r"eatery", r"nasi", r"mee", r"noodles?",
              r"steamboat", r"dim sum", r"kopitiam"])
CULTURE = _rx([r"temples?", r"wat", r"mosques?", r"masjid", r"churche?s?", r"cathedral", r"chapel", r"basilica", r"shrines?",
               r"pagodas?", r"stupa", r"chedi", r"museums?", r"palace", r"fort", r"fortress", r"citadel", r"heritage", r"monument",
               r"memorial", r"tombs?", r"mausoleum", r"kuil", r"pura", r"candi", r"vihara", r"clan (?:house|jetty|jetties)",
               r"kongsi", r"monastery", r"gallery", r"galleries", r"old town", r"historic", r"ruins?", r"prasat", r"angkor",
               r"istana", r"kampung", r"đền", r"chùa", r"lăng", r"phra", r"gurdwara", r"synagogue", r"colonial",
               r"cemetery", r"war memorial", r"mansion", r"house museum", r"cultural (?:village|centre|center)", r"wayang"])
SHOP_NOT_MARKET = _rx([r"mall", r"plaza", r"shopping cent(?:re|er)", r"department store", r"supermarket", r"hypermarket", r"outlet"])


def _type(listing):
    t = listing["template"]
    if t in ("listing",):
        sec = (listing.get("section") or "").strip().lower()
        return SECTION_TYPE.get(sec, "skip")
    return t


def classify(listing, name, desc):
    """Return a category id, or None to drop the listing (accommodation, transport)."""
    t = _type(listing)
    if t in SKIP or t == "skip":
        return None
    head = (desc or "")[:160]
    if t == "eat":
        return "markets" if MARKET.search(name) else "dine"
    if t == "drink":
        return "dine" if EATERY.search(name) else "cafes"
    if t == "buy":
        if SHOP_NOT_MARKET.search(name):
            return "shopping"
        return "markets" if MARKET.search(name) else "shopping"
    if t in ("see", "do"):
        nature = bool(NATURE.search(name)) and not NOT_NATURE.search(name)
        culture = bool(CULTURE.search(name))
        if culture and nature:
            # "Batu Caves temple", "Wat Tham Suea (Tiger Cave Temple)": the temple is the point
            return "culture"
        if culture:
            return "culture"
        if nature:
            return "nature"
        if MARKET.search(name) and not SHOP_NOT_MARKET.search(name):
            return "markets"
        dn, dc = len(NATURE.findall(head)), len(CULTURE.findall(head))
        if NOT_NATURE.search(name) or NOT_NATURE.search(head):
            dn = 0
        if dc > dn and dc:
            return "culture"
        if dn > dc and dn:
            return "nature"
        return "sights" if t == "see" else "activities"
    return None

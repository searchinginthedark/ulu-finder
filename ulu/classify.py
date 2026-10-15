"""Deterministic category assignment. Same listing in, same category out; no LLM.

Order of evidence: the listing's own template (eat/drink/buy/see/do), then keywords in
the NAME, then keywords early in the description. Name beats description because
descriptions mention neighbours ("next to the beach").
"""
import re

CATEGORIES = [
    ("dine", "Dine"), ("markets", "Markets & Hawkers"), ("cafes", "Cafes & Desserts"),
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
NOT_HERITAGE = _rx([r"resorts?", r"stadium", r"sports?", r"golf", r"adventures?", r"tours?", r"div(?:e|ing)", r"scuba",
                    r"theme park", r"water ?park", r"amusement park", r"swimming pool", r"circuit", r"race ?track",
                    r"speedway", r"hotel", r"mall"])
EATERY = _rx([r"restaurants?", r"restoran", r"seafood", r"kitchen", r"eatery", r"nasi", r"mee", r"noodles?",
              r"steamboat", r"dim sum"])
# Kopitiam / kedai kopi / kaya toast are Cafes (user ruling 2026-10-15: kopi and toast is the point),
# except the food-court kind ("Kopitiam" the SG food-court chain), which is Markets.
KOPITIAM = _rx([r"kopitiams?", r"kedai kopi", r"kaya toast"])
# "Cafes & Desserts" means coffee, tea, bakes and sweets (user ruling 2026-10-15). Wikivoyage's Drink
# section is mostly nightlife, and most real cafes sit under Eat, so the NAME decides, in both.
# Not "cake"/"pastry" alone: Chinese "oyster cakes" and "scallion pork pastry" are savoury snacks.
CAFE = _rx([r"caf[eé]s?", r"kafe", r"coffee", r"kopi", r"kopitiams?", r"kedai kopi", r"kaya toast", r"espresso", r"roaster(?:y|s)?", r"c[aà] ph[eê]",
            r"bakery", r"bakeries", r"bakehouse", r"boulangerie", r"p[aâ]tisserie", r"cake ?(?:shop|house)s?", r"cakery",
            r"desserts?", r"gelato", r"gelateria", r"ice ?cream", r"bingsu", r"patbingsu", r"tea ?(?:house|room|bar)s?",
            r"teahouse", r"bubble tea", r"boba", r"milk tea", r"chè", r"kuih", r"kueh", r"toko roti", r"donuts?",
            r"doughnuts?", r"waffles?", r"cr[eê]pes?", r"confectioner(?:y|s)?", r"chocolatier", r"macarons?", r"brunch",
            r"es (?:teler|campur|cendol|doger|kelapa|buah)", r"cendol", r"halo[- ]halo", r"taho", r"tong sui"])
# Scripts without word boundaries (\w covers CJK, so _rx would never match inside a longer name).
CAFE_CJK = re.compile(r"咖啡|珈琲|カフェ|喫茶|甜品|甜點|甜点|蛋糕|ケーキ|スイーツ|ベーカリー|パン屋|甘味|茶館|茶馆|"
                      r"카페|커피|베이커리|빵집|디저트|กาแฟ|คาเฟ่|เบเกอรี่|ขนม")
NIGHTLIFE = _rx([r"bars?", r"pubs?", r"clubs?", r"night ?clubs?", r"lounges?", r"brew(?:ery|eries|pub)s?", r"beers?",
                 r"wines?", r"cocktails?", r"disco", r"karaoke", r"taverns?", r"speakeasy", r"izakaya", r"sake",
                 r"whisk(?:e)?y", r"gin", r"gastrobar", r"live music"])
# A tea bar or juice bar is a cafe, not nightlife.
SOFT_BAR = _rx([r"(?:tea|juice|coffee|espresso|dessert|milk|smoothie|snack|salad) bars?"])


# In Malaysia and Indonesia "Cafe"/"Kafe" in a NAME often means an eatery (Dann's Cafe: laksa and
# biryani). A cafe-named listing whose description talks meals and never coffee or bakes is Dine.
MEAL = _rx([r"restaurants?", r"hawker", r"food court", r"cuisine", r"food", r"biryani", r"laksas?", r"nasi", r"mee",
            r"rice", r"noodles?", r"burgers?", r"pizzas?", r"steaks?", r"seafood", r"buffet", r"dim sum", r"ramen",
            r"sushi", r"curry", r"banana leaf", r"mamak", r"char siew", r"pao", r"roti(?: canai)?", r"wan ?ton",
            r"satay", r"lunch", r"dinner", r"meals?"])
# In a DESCRIPTION the bare word "cafe" proves nothing in MY/ID ("a small cafe that does lunch");
# coffee, bakes and sweets do.
CAFE_STRONG = _rx([r"coffee", r"kopi", r"kaya", r"toast", r"espresso", r"roaster(?:y|s)?", r"c[aà] ph[eê]", r"bakery", r"bakeries",
                   r"bakehouse", r"boulangerie", r"p[aâ]tisserie", r"cakes?", r"desserts?", r"gelato", r"ice ?cream",
                   r"bingsu", r"tea", r"bubble tea", r"boba", r"chè", r"kuih", r"kueh", r"pastr(?:y|ies)", r"scones?",
                   r"donuts?", r"doughnuts?", r"waffles?", r"cr[eê]pes?", r"brunch", r"smoothies?", r"juices?"])
# "Exodus Lounge (Formerly Known As Krabau Rock Cafe)": an old name is not evidence.
FORMERLY = re.compile(r"\(\s*(?:formerly|previously|was)\b[^)]*\)|\b(?:formerly|previously)(?: known as| called)?\s[^,.;)]*",
                      re.I)
# Not one place: "Various cafes in Bandar Sunway", "Several stalls along the beach".
# A plural noun must follow within three words: "Many Coffee" (Sam Neua) is one real cafe.
GENERIC = re.compile(r"^\W*(?:various|several|many|numerous|other|assorted|lots of|plenty of)\s+(?:\S+\s+){0,2}\S+s\b", re.I)


def is_cafe(text):
    return bool(CAFE.search(text) or CAFE_CJK.search(text))


def strip_formerly(text):
    return FORMERLY.sub(" ", text or "")


def cafe_named(head):
    """For a listing whose NAME says cafe: 'cafes', 'dine' (the description talks meals) or
    'night' (it talks bars: "Yellow Cafe: Beach bar."). Coffee or bakes in the description win."""
    if CAFE_STRONG.search(head) or CAFE_CJK.search(head):
        return "cafes"
    if is_nightlife(head):
        return "night"
    return "dine" if MEAL.search(head) else "cafes"


def is_nightlife(text):
    return bool(NIGHTLIFE.search(SOFT_BAR.sub(" ", text)))
CULTURE = _rx([r"temples?", r"wat", r"mosques?", r"masjid", r"churche?s?", r"cathedral", r"chapel", r"basilica", r"shrines?",
               r"pagodas?", r"stupa", r"chedi", r"museums?", r"palace", r"fort", r"fortress", r"citadel", r"heritage", r"monument",
               r"memorial", r"tombs?", r"mausoleum", r"kuil", r"pura", r"candi", r"vihara", r"clan (?:house|jetty|jetties)",
               r"kongsi", r"monastery", r"gallery", r"galleries", r"old town", r"historic", r"ruins?", r"prasat", r"angkor",
               r"istana", r"kampung", r"đền", r"chùa", r"lăng", r"phra", r"gurdwara", r"synagogue", r"colonial",
               r"cemetery", r"war memorial", r"mansion", r"house museum", r"cultural (?:village|centre|center)", r"wayang"])
SHOP_NOT_MARKET = _rx([r"mall", r"plaza", r"shopping cent(?:re|er)", r"department store", r"supermarket", r"hypermarket", r"outlet"])


FOOD = {"dine", "markets", "cafes"}

# Closure, only where the listing says it about ITSELF. "since Tacos and Salsa closed down" and
# "the now-defunct Monkey Club" describe a neighbour, so bare "closed down"/"defunct" mid-text never count.
CLOSED_NAME = re.compile(r"\(\s*(?:permanently\s+)?closed\b[^)]*\)|^\W*closed\b|\bclosed\s*[:!]", re.I)
# Measured on every cached page 2026-10-15: "closed in 1991" / "closed since 2012" mid-text is almost
# always history ("the sugar factory closed in 1991, now a culture park") or a neighbour ("after the
# Starbucks branch closed in 2007"), so a year never counts on its own; only phrases a listing uses
# about itself, or a pronoun subject ("this place has been closed since COVID").
CLOSED_ANY = re.compile(
    r"\bpermanently closed\b|\bclosed permanently\b|\bclosed for good\b|\bpossibly closed\b|"
    r"\bmay (?:have|be) (?:permanently )?closed (?:down|permanently)\b|"
    # not "it" (usually a neighbour: "a museum across the river, but it is closed") and not "was"
    # (history: "this trail was closed in 2017, but it is open")
    r"\bthis (?:place|restaurant|cafe|café|shop|bar|venue|stall|museum|park|trail|attraction) "
    r"(?:has|is) (?:now )?(?:unfortunately )?(?:been )?(?:permanently )?closed(?: down)?"
    r"(?! on| from| for| during| until| between| every| at| daily| weekly| till| to| the)\b", re.I)
# "Closed on Mondays" / "Closed 12:00-14:00" are opening hours, not closure.
_HOURS_AFTER = (r"(?!\s*(?:on|from|for|during|until|till|between|every|at|daily|weekly|except|over|public|to|the|"
                r"most|some|certain|temporarily|mon|tue|wed|thu|fri|sat|sun|lunch|noon|midday|in the|"
                r"\d{1,2}[:.h]|\d{1,2}\s*(?:am|pm)|[-–(]))")
CLOSED_START = re.compile(r"^\W*(?:closed\b" + _HOURS_AFTER + r"|no longer (?:open|operating|operational|in business|exists?)\b|"
                          r"out of business\b|defunct\b|shut down\b|(?:it )?has (?:\w+ )?been closed\b)", re.I)
# International brands only (user ruling 2026-10-15): home-grown chains (Jollibee, Mang Inasal,
# OldTown White Coffee, Highlands Coffee, Secret Recipe) are what locals eat and stay.
INTL_CHAIN = _rx([r"mcdonald'?s", r"kfc", r"kentucky fried chicken", r"burger king", r"subway", r"pizza hut",
                  r"domino'?s(?: pizza)?", r"papa john'?s", r"wendy'?s", r"popeyes", r"carl'?s jr\.?", r"shake shack",
                  r"five guys", r"texas chicken", r"church'?s chicken", r"a ?& ?w", r"starbucks", r"costa coffee",
                  r"(?:the )?coffee bean(?: (?:&|and) tea leaf)?", r"tim hortons", r"dunkin'?(?: donuts)?",
                  r"krispy kreme", r"baskin[- ]?robbins", r"dairy queen", r"cold stone(?: creamery)?",
                  r"h[aä]agen[- ]?dazs", r"swensen'?s", r"auntie anne'?s", r"cinnabon", r"tgi friday'?s",
                  r"chili'?s", r"outback steakhouse", r"tony roma'?s", r"texas roadhouse", r"sizzler", r"johnny rockets",
                  r"bubba gump", r"hard rock(?: cafe| café)?", r"planet hollywood", r"gloria jean'?s(?: coffees?)?",
                  r"dome caf[eé]"])
AIRPORT = re.compile(r"\bairport\b|機場|机场|空港|공항|\bsân bay\b|\bbandara\b|\blapangan terbang\b", re.I)
# Airports locals go to for food (user ruling 2026-10-15): Changi and Jewel are a Singapore outing.
LOCAL_AIRPORT = re.compile(r"\bchangi\b", re.I)


def excluded(cat, name, desc, dest):
    """Why a classified listing is left out of the app, or None. Deterministic, like classify()."""
    desc = desc or ""
    if GENERIC.search(name):
        return "generic"
    if CLOSED_NAME.search(name) or CLOSED_ANY.search(desc) or CLOSED_START.search(desc):
        return "closed"
    if cat in FOOD and INTL_CHAIN.search(name):
        return "chain"
    if cat in FOOD and AIRPORT.search(dest or "") and not LOCAL_AIRPORT.search(dest or ""):
        return "airport"
    return None


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
    if t in ("eat", "drink"):
        fname, fhead = strip_formerly(name), strip_formerly(head)
    if t == "eat":
        if MARKET.search(name):
            return "markets"
        if KOPITIAM.search(fname) and MARKET.search(fhead):
            return "markets"
        if EATERY.search(fname):
            return "dine"
        # an Eat-section listing is there for its food, so a bar-sounding one stays in Dine
        return ("cafes" if cafe_named(fhead) == "cafes" else "dine") if is_cafe(fname) else "dine"
    if t == "drink":
        if EATERY.search(fname):
            return "dine"
        if is_cafe(fname):
            v = cafe_named(fhead)
            return None if v == "night" else v
        # Nightlife is out of the app (user ruling 2026-10-15). A Drink listing with no cafe word
        # in its name stays only when its description says cafe and says nothing of a bar.
        if is_cafe(fhead) and not is_nightlife(fname + " " + fhead):
            return "cafes"
        return None
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
        # A leisure venue in the NAME is the point; its description's museum is a feature of it
        # ("Mobility Resort Motegi ... the museum of Honda" is a race track, not heritage).
        # Narrower than NOT_NATURE: "city", "centre", "tower", "station" name heritage too
        # (Imperial City of Hue, Old Tutuban Train Station).
        if NOT_HERITAGE.search(name):
            dc = 0
        if dc > dn and dc:
            return "culture"
        if dn > dc and dn:
            return "nature"
        return "sights" if t == "see" else "activities"
    return None

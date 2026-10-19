"""Signal D: how carefully local mappers have recorded a food spot on OpenStreetMap.

    python -m ulu.osm [--only TH,VN] [--dir .cache/osm] [--keep]

Runs in its own weekly workflow (osm.yml), BEFORE the main build, and writes data/osm/<CC>.json.
The main build only reads those files (attach()), so a slow or failed OSM run can never time out
or thin out the Wikivoyage build: the previous week's file simply stays, with its own date.

Licence (ODbL, decided 2026-10-14, docs/handover-ulu-score.md 3.D): OpenStreetMap only ADDS
osm_* signals to spots Ulu already has. It never writes a Wikivoyage field and never adds a spot;
either would pull the CC BY-SA listings under ODbL share-alike. That includes coordinates: a food
spot found by area_match() gets osm_local, never the OSM place's lat/lon.

Exit 0 = every country written; 1 = some kept last week's file; 2 = none written.
"""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import net

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOFABRIK = "https://download.geofabrik.de/{path}-latest.osm.pbf"
# Temples and parks are mapped bare (73 of 244 matched TH culture spots had any detail tag), so
# a detail count there measures nothing; signal A covers them. D is a food signal.
FOOD = ("dine", "cafes", "markets")
RADIUS = 150.0          # metres; measured on TH: 562 of 960 coord spots matched within it
SIM = 0.85              # name similarity floor; 30 of 30 sampled matches above it were correct
CELL = 0.005            # ~550 m grid for the proximity index
MAX_EXTRACT_AGE = 8     # days: Geofabrik rebuilds daily, so older means its pipeline is stuck
MAX_FILE_AGE = 35       # days: older than this, attach() drops D rather than show stale detail
COVERAGE_FLOOR = 0.7    # a fall below 70% of last week's matches is an outage, not a real change
POI_KEYS = ("amenity", "shop", "tourism", "leisure", "craft")

# Detail groups local mappers fill in. One point per group, however many of its tags are set.
GROUPS = {
    "hours": ("opening_hours",),
    "cuisine": ("cuisine",),
    "phone": ("phone", "contact:phone", "contact:mobile"),
    "web": ("website", "contact:website", "url", "contact:facebook", "contact:instagram"),
    "addr": ("addr:street", "addr:housenumber", "addr:full"),
    "diet": ("diet:",),        # prefix: diet:vegetarian, diet:halal, ...
    "service": ("takeaway", "delivery", "outdoor_seating", "reservation", "drive_through"),
    "survey": ("check_date", "survey:date", "check_date:opening_hours"),
}
LOCAL_NAME_POINTS = 2
FORMAT = 2              # data/osm/<CC>.json: 2 = "has" carries "local_primary", names checked by script
CHAIN = ("brand", "brand:wikidata")   # NOT operator: temples and parks carry one too


class OsmError(RuntimeError):
    pass


# ---------- pure helpers (tested without pyosmium) ----------

def spot_key(spot):
    """Stable across rebuilds: the id embeds the category, which the classifier may change."""
    return hashlib.sha1(f"{spot['src']}|{spot['name']}".encode()).hexdigest()[:12]


def norm(s):
    """Lowercase, punctuation to spaces, accents off LATIN letters only ("Café" == "Cafe").
    Thai, Khmer, Burmese and Lao vowel signs are combining marks too; stripping them turned
    ทองพูน into ทองพน and would merge different names."""
    out, base = [], ""
    for c in unicodedata.normalize("NFKD", s or ""):
        if unicodedata.combining(c):
            if base and ord(base) < 0x250:   # Basic Latin .. Latin Extended-B
                continue
        else:
            base = c
        out.append(c)
    s = unicodedata.normalize("NFC", "".join(out)).lower()
    # not re's [^\w\s]: \w excludes combining marks, so it would turn every Thai vowel into a space
    s = "".join(c if c.isalnum() or c == "_" or c.isspace() or unicodedata.combining(c) else " " for c in s)
    return re.sub(r"\s+", " ", s).strip()


def similarity(a, b):
    """1.0 equal; 0.9 when the shorter (>= 5 chars) is a whole-word part of the longer
    ("Norden" in "Norden Restaurant Chiang Mai"); else difflib's ratio."""
    import difflib
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 5 and re.search(r"\b" + re.escape(short) + r"\b", long_):
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def metres(a_lat, a_lon, b_lat, b_lon):
    p = math.pi / 180
    x = (b_lon - a_lon) * p * math.cos((a_lat + b_lat) * p / 2)
    return 6371000 * math.hypot(x, (b_lat - a_lat) * p)


def poi_names(tags):
    return {norm(v) for k, v in tags.items()
            if k == "name" or k.startswith("name:") or k in ("alt_name", "old_name", "official_name", "short_name")} - {""}


# The local language's own script. "Any non-ASCII letter" read "Zum grünen Baum", "Dé Van" and
# "CaveCave 洞洞" as Thai (TH, 2026-10-15). Vietnamese is Latin, so it is the letters only
# Vietnamese uses ("Café" is not one); a language not listed falls back to any non-ASCII letter.
_CJK = "㐀-䶿一-鿿豈-﫿"
SCRIPT = {
    "th": "฀-๿", "lo": "຀-໿", "km": "ក-៿", "my": "က-႟",
    "ja": "぀-ヿｦ-ﾟ" + _CJK, "zh": _CJK,
    "ko": "가-힯ᄀ-ᇿ㄰-㆏",
    "vi": "ăâđêôơưĂÂĐÊÔƠƯạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴỶỸ",
}


def in_local_script(text, lang):
    chars = SCRIPT.get((lang or "").split("-")[0])
    if chars:
        return bool(re.search(f"[{chars}]", text or ""))
    return any(ord(c) > 127 and c.isalpha() for c in text or "")


def local_name_tags(tags, lang):
    """Which names are in the local language: "local_primary" when `name` itself (what the sign
    says, as local mappers record it) is in the local script, "local_name" when any name is.
    An explicit name:<lang> counts only in that script (Wombat & Kiwi Bar carried a Latin
    name:th), except for a Latin-script language with no SCRIPT entry (name:ms)."""
    base = (lang or "").split("-")[0]
    primary = in_local_script(tags.get("name", ""), lang)
    named = (tags.get(f"name:{lang}") or tags.get(f"name:{base}")) if lang else ""
    other = bool(named) and (in_local_script(named, lang) or base not in SCRIPT)
    if primary:
        return ["local_name", "local_primary"]
    return ["local_name"] if other else []


def has_local_name(tags, lang):
    """Constant across a pool where every name is local (Japan), so it moves no percentile there."""
    return bool(local_name_tags(tags, lang))


def detail(tags, lang):
    """(d, has, chain) for data/osm/<CC>.json. attach() scores only "local_name"/"local_primary" in has; `d` and the
    other groups are kept for diagnosis (they ran the wrong way as a locality signal on TH).
    A chain is mapped from brand data, not by locals."""
    if any(tags.get(k) for k in CHAIN):
        return 0, [], True
    has = []
    for group, keys in GROUPS.items():
        for k in keys:
            if (k.endswith(":") and any(t.startswith(k) for t in tags)) or tags.get(k):
                has.append(group)
                break
    points = len(has)
    names = local_name_tags(tags, lang)
    if names:
        has += names
        points += LOCAL_NAME_POINTS
    return points, has, False


def match(spots, pois, radius=RADIUS, floor=SIM):
    """{spot_key: poi} for food spots with coords. Best candidate by (similarity, -distance)."""
    grid = defaultdict(list)
    for p in pois:
        grid[(int(p["lat"] // CELL), int(p["lon"] // CELL))].append(p)
    out = {}
    for s in spots:
        if s.get("cat") not in FOOD or s.get("lat") is None or s.get("lon") is None:
            continue
        names = {n for n in (norm(s.get("name")), norm(s.get("local"))) if n}
        gy, gx = int(s["lat"] // CELL), int(s["lon"] // CELL)
        best = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for p in grid.get((gy + dy, gx + dx), ()):
                    d = metres(s["lat"], s["lon"], p["lat"], p["lon"])
                    if d > radius:
                        continue
                    sim = max((similarity(a, b) for a in names for b in p["names"]), default=0.0)
                    if sim >= floor and (best is None or (sim, -d) > best[0]):
                        best = ((sim, -d), p)
        if best:
            out[spot_key(s)] = best[1]
    return out


# ---------- area match: food spots WITHOUT coords ----------
# Half of TH's food listings have no coordinates, so match() never sees them. Here the anchor is
# the spot's destination: the area its own geolocated listings cover. A whole town holds far more
# namesakes than 150 m does, so the rules are stricter than match()'s (measured on TH 2026-10-15
# by hiding the coords of geolocated food spots: plain match() rules picked a POI more than
# 300 m from the true place 15% of the time, mostly through words like "Market" or "Restaurant").
# The result is used for the osm_local SCORE only; it never gives a spot coordinates.
AREA_MIN_R, AREA_MAX_R = 2000.0, 10000.0   # metres around the destination's median listing
AREA_SPREAD = 1.5       # radius = 1.5 x the 90th-percentile distance of its listings, clamped
AREA_MIN_SPOTS = 3      # fewer geolocated listings than this cannot outline an area
AREA_CORE = 4           # distinctive characters left once type words are removed
AREA_SOLO = 6           # ... and a ONE-word core needs this many: "Suria" and "Lucky" each named a
                        # second, different place in the same town (TH/MY holdout). 7 lost a
                        # third of TH's matches for half a point of precision.
WORD_SIM = 0.85         # per-word floor inside area_similarity(): "Shang"/"Huang" is exactly 0.80
SAME_PLACE = 150.0      # candidates closer than this are one place mapped twice (node + building)
# Type words: they say what a place is, not which one. "Minburi Market" must not match a stall
# mapped as "Market" 18 km away.
GENERIC = frozenset("""
a an the and of at by on in de del la le les el di da du
restaurant restaurants resto ristorante eatery diner canteen kitchen bistro brasserie cafeteria
cafe caffe coffee coffeeshop kopi tea teahouse bakery bakeshop patisserie dessert desserts
bar bars pub pubs tavern lounge club beer brewery taproom wine
market markets bazaar night floating fresh wet morning weekend walking street food foods
court centre center hall plaza square mall complex
shop store house home garden corner place spot stall stalls hawker hawkers kiosk
grill bbq barbecue steakhouse seafood noodle noodles rice vegetarian vegan halal
thai vietnamese malay chinese japanese korean indian italian western local original
hotel inn resort guesthouse branch new old
restoran rumah makan kedai warung gerai pasar medan selera kafe kopitiam mamak
quan nha hang tiem cho
krua raan ran talat talad
izakaya shokudo
""".split())   # last four lines: Malay/Indonesian, Vietnamese (accents off), Thai, Japanese


# Only places that serve food or drink. Across a town, "Kinnaree" also names a massage parlour and
# "Moei" a resort; the measured wrong picks were a hotel, a ferry pier, a studio, a vending machine.
FOOD_AMENITY = frozenset(("restaurant", "cafe", "bar", "pub", "fast_food", "food_court", "marketplace",
                          "ice_cream", "biergarten", "nightclub"))
FOOD_SHOP = frozenset(("bakery", "coffee", "tea", "deli", "confectionery", "pastry", "beverages"))


def is_food_poi(tags):
    return tags.get("amenity") in FOOD_AMENITY or tags.get("shop") in FOOD_SHOP


def core(name, drop=frozenset()):
    """The distinctive part of a normalised name: type words (and `drop`, the destination's own
    place-name words) removed. '' when nothing is left."""
    return " ".join(w for w in name.split() if w not in GENERIC and w not in drop)


def place_words(spot):
    """Words of the spot's destination and the articles above it: in "Ao Nang Mosque Market" only
    "mosque" says which market; "Ao Nang Night Market" shares the town, not the place."""
    return frozenset(w for n in [spot.get("dest") or ""] + list(spot.get("up") or ()) for w in norm(n).split())


def distinctive(c):
    """Enough of a name left to identify one place in a town (AREA_CORE, AREA_SOLO)."""
    n = len(c.replace(" ", ""))
    return n >= AREA_CORE and (" " in c or n >= AREA_SOLO)


def area_similarity(a, b):
    """similarity() without its whole-word containment, and fuzzy only word by word.

    Cores have already shed "Restaurant" and the town name, so what containment still catches
    across a town is one shared word ("Sinthorn Steak" / "Steak", "Big C Extra" / "Big C").
    A whole-string ratio passes names that differ in their only distinctive word ("Shang Ji" /
    "Huang Ji" 0.88, "Ngoc Huong" / "Ngoc Phung"), so each word of the shorter core must also
    match a word of the other at WORD_SIM ("Cha Arnon" / "Cha Anon" still passes)."""
    import difflib
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    short, long_ = sorted((a.split(), b.split()), key=lambda t: (len(t), len("".join(t))))
    for w in short:
        if not any(difflib.SequenceMatcher(None, w, v).ratio() >= WORD_SIM for v in long_):
            return min(r, WORD_SIM - 0.01)
    return r


def area_key(spot):
    return spot.get("dest") or "", tuple(spot.get("up") or ())


def areas(spots):
    """{area_key: (lat, lon, radius)} from each destination's geolocated listings, any category."""
    pts = defaultdict(list)
    for s in spots:
        if s.get("lat") is not None and s.get("lon") is not None:
            pts[area_key(s)].append((s["lat"], s["lon"]))
    out = {}
    for k, ll in pts.items():
        if len(ll) < AREA_MIN_SPOTS:
            continue
        lat = sorted(a for a, _ in ll)[len(ll) // 2]
        lon = sorted(b for _, b in ll)[len(ll) // 2]
        ds = sorted(metres(lat, lon, a, b) for a, b in ll)
        p90 = ds[int(0.9 * (len(ds) - 1))]
        out[k] = (lat, lon, max(AREA_MIN_R, min(AREA_MAX_R, AREA_SPREAD * p90)))
    return out


def area_cells(area_list):
    """Grid cells (match()'s CELL size) covering every area's bounding box."""
    cells = set()
    for lat, lon, r in area_list:
        dy = r / 111_320.0
        dx = dy / max(0.2, math.cos(lat * math.pi / 180))
        for gy in range(int((lat - dy) // CELL), int((lat + dy) // CELL) + 1):
            for gx in range(int((lon - dx) // CELL), int((lon + dx) // CELL) + 1):
                cells.add((gy, gx))
    return cells


def area_match(spots, pois, floor=SIM, area=None):
    """{spot_key: poi} for food spots WITHOUT coords, by name inside their destination's area.

    Names are compared on their cores (type words removed), each core needs AREA_CORE distinctive
    characters, and every candidate at or above the floor must be ONE place: two namesakes more
    than SAME_PLACE apart (branches, a chain, a common name) mean we cannot tell which, so no match."""
    area = areas(spots) if area is None else area
    index = defaultdict(list)       # name token -> [poi]; cores are cut per spot (place words differ)
    for p in pois:
        if not is_food_poi(p["tags"]):
            continue
        for tok in {t for n in p["names"] for t in core(n).split()}:
            index[tok].append(p)
    out = {}
    for s in spots:
        if s.get("cat") not in FOOD or (s.get("lat") is not None and s.get("lon") is not None):
            continue
        a = area.get(area_key(s))
        if not a:
            continue
        drop = place_words(s)
        names = {c for c in (core(norm(s.get("name")), drop), core(norm(s.get("local")), drop)) if distinctive(c)}
        if not names:
            continue
        seen, cands = set(), []
        for tok in {t for c in names for t in c.split()}:
            for p in index.get(tok, ()):
                if id(p) in seen:
                    continue
                seen.add(id(p))
                if metres(a[0], a[1], p["lat"], p["lon"]) > a[2]:
                    continue
                cores = {c for c in (core(n, drop) for n in p["names"]) if distinctive(c)}
                sim = max((area_similarity(x, y) for x in names for y in cores), default=0.0)
                if sim >= floor:
                    cands.append(p)
        if cands and all(metres(cands[0]["lat"], cands[0]["lon"], p["lat"], p["lon"]) <= SAME_PLACE
                         for p in cands[1:]):
            out[spot_key(s)] = cands[0]
    return out


# The area match measures itself every run, per country: hide the coords of geolocated food
# spots, area-match them, and count picks within HOLDOUT_OK of the listing's own coords. First
# run (2026-10-15): TH 94%, VN 95%, TW 90%, MY 90%, KR 71% (Korean names repeat across unbranded
# branches). The 300 m test undercounts: by hand, most TH "misses" were the right restaurant with
# off listing coords. Below the bar, or with too few picks to judge, a country gets none.
HOLDOUT_OK = 300.0
AREA_MIN_PRECISION = 0.85
AREA_MIN_HOLDOUT = 30


def area_holdout(spots, pois):
    """(picks, picks within HOLDOUT_OK of the truth) for geolocated food spots matched as if
    they had no coords. Areas are drawn from the untouched list, as they would be for real."""
    area = areas(spots)
    truth, hidden = {}, []
    for s in spots:
        if s.get("cat") in FOOD and s.get("lat") is not None and s.get("lon") is not None:
            truth[spot_key(s)] = (s["lat"], s["lon"])
            hidden.append(dict(s, lat=None, lon=None))
    got = area_match(hidden, pois, area=area)
    ok = sum(1 for k, p in got.items() if metres(truth[k][0], truth[k][1], p["lat"], p["lon"]) <= HOLDOUT_OK)
    return len(got), ok


def area_trusted(picks, ok):
    return picks >= AREA_MIN_HOLDOUT and ok >= AREA_MIN_PRECISION * picks


def accept(new_matched, prev_matched, food_spots=0):
    """Coverage guard: a sudden collapse is an outage (a truncated extract, a renamed tag), not a
    week in which half the restaurants closed. Small pools are too noisy to judge. Zero matches
    among many food spots means the extract does not cover the country at all (TH matched ~56%)."""
    if new_matched == 0 and food_spots >= 50:
        return False
    if prev_matched is None or prev_matched < 20:
        return True
    return new_matched >= COVERAGE_FLOOR * prev_matched


def fresh(as_of, now=None, max_days=MAX_EXTRACT_AGE):
    now = now or datetime.now(timezone.utc)
    return as_of is not None and now - as_of <= timedelta(days=max_days)


def parse_md5(text):
    m = re.match(r"\s*([0-9a-fA-F]{32})\b", text or "")
    if not m:
        raise OsmError(f"unreadable md5 file: {text[:60]!r}")
    return m.group(1).lower()


# ---------- the build reads this (no pyosmium needed) ----------

def attach(spots, cc, root=ROOT, today=None, log=print, use_area=True, use_nb=True):
    """Add osm_* signals from data/osm/<CC>.json. Returns the extract date, or None when there is
    no usable file. A missing or too-old file means the build simply has no D this week; it never
    reads as 'matched nothing', and it never touches any other field.
    use_area=False skips area matches (countries.json `osm_area: false`): the holdout says WHICH
    place, tools/osm_check.py says whether scoring it ranks local food higher; both must pass.
    use_nb=False (countries.json `osm_nb: false`) leaves out the osm_nb_local tie-break."""
    path = os.path.join(root, "data", "osm", f"{cc}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    as_of = doc.get("as_of")
    today = today or datetime.now(timezone.utc).date()
    try:
        age = (today - datetime.strptime(as_of, "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        log(f"  osm: {cc} file has no valid as_of; not used")
        return None
    if age > MAX_FILE_AGE:
        log(f"  osm: {cc} extract is {age} days old (limit {MAX_FILE_AGE}); not used")
        return None
    entries = doc.get("spots") or {}
    # Tie-break only (neighbourhood()); absent from files written before 2026-10-19 = no data.
    nb = (doc.get("nb") or {}) if use_nb else {}
    nb_area = set(doc.get("nb_area") or ())
    n = 0
    for s in spots:
        if s.get("cat") not in FOOD:
            continue
        key = spot_key(s)
        share = nb.get(key)
        if share is not None and (use_area or key not in nb_area):
            s.setdefault("signals", {})["osm_nb_local"] = share
        e = entries.get(key)
        if not e or (not use_area and e.get("via") == "area"):
            continue
        sig = s.setdefault("signals", {})
        # The score uses ONLY the local-language name. Measured on 330 matched TH food spots
        # (2026-10-14): 59% of local-sounding places carry a Thai name vs 15% of expat/foreign
        # ones, while the detail-tag count ran the WRONG way (1.89 foreign vs 1.16 local:
        # expats map their own haunts thoroughly). The file keeps `d`/`has` for diagnosis only.
        # Graded since 2026-10-15 to break ties: 1 = the main name is in the local script, 0.5 =
        # only a name:<lang> translation is (Ristr8to, The Hungry Wolf). On TH the main name was
        # local for 91% of local-sounding vs 54% of foreign-sounding spots. A file written before
        # "local_primary" existed (no FORMAT) keeps the old binary reading.
        chain = bool(e.get("chain"))
        has = e.get("has") or ()
        if chain or "local_name" not in has:
            sig["osm_local"] = 0
        elif "local_primary" in has or doc.get("format", 1) < FORMAT:
            sig["osm_local"] = 1
        else:
            sig["osm_local"] = 0.5
        if chain:
            sig["osm_chain"] = True
        n += 1
    log(f"  osm: {cc} {n} spots carry OSM detail (extract {as_of}, {age} days old)")
    return as_of


# ---------- download, verify, extract (osm.yml only) ----------

def download(url, dest, tries=3):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": net.UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest + ".part", "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
                modified = r.headers.get("Last-Modified")
            os.replace(dest + ".part", dest)
            return modified
        except OSError as e:
            last = e
            time.sleep(30 * (attempt + 1))
    raise OsmError(f"download failed: {url}: {last}")


def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": net.UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_date(path, last_modified=None):
    """The data's own timestamp from the PBF header; the HTTP Last-Modified only as a fallback.
    Neither -> None, which fresh() rejects: an unknown age is not a fresh one."""
    import osmium
    r = osmium.io.Reader(path, osmium.osm.osm_entity_bits.NOTHING)
    try:
        ts = r.header().get("osmosis_replication_timestamp")
    finally:
        r.close()
    for raw, fmt in ((ts, "%Y-%m-%dT%H:%M:%SZ"), (last_modified, "%a, %d %b %Y %H:%M:%S GMT")):
        if raw:
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return None


def prefilter(src, log):
    """Shrink the extract to POI-tagged objects (and the nodes their ways need) with osmium-tool,
    when it is installed (osm.yml installs it). Japan is 2.4 GB; pyosmium on the whole file needs
    a node-location index the runner's memory may not hold."""
    tool = shutil.which("osmium")
    if not tool:
        log("  osmium-tool not on PATH; reading the full extract")
        return src
    out = src.replace(".osm.pbf", ".pois.osm.pbf")
    subprocess.run([tool, "tags-filter", src] + [f"nwr/{k}" for k in POI_KEYS] + ["-o", out, "--overwrite"],
                   check=True)
    return out


def read_pois(path, spots):
    """Named POIs within one grid cell of any food spot with coords (keeps memory small)."""
    import osmium

    cells = set()
    for s in spots:
        if s.get("cat") in FOOD and s.get("lat") is not None and s.get("lon") is not None:
            gy, gx = int(s["lat"] // CELL), int(s["lon"] // CELL)
            cells.update((gy + dy, gx + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1))
    # and the areas of destinations holding food spots without coords (area_match)
    area = areas(spots)
    wanted = {area_key(s) for s in spots if s.get("cat") in FOOD and (s.get("lat") is None or s.get("lon") is None)}
    # padded by one cell: an area-matched place near the edge still needs its NB_RADIUS ring read
    cells |= {(gy + dy, gx + dx) for gy, gx in area_cells([area[k] for k in wanted if k in area])
              for dy in (-1, 0, 1) for dx in (-1, 0, 1)}

    def keep(tags, lat, lon):
        if (int(lat // CELL), int(lon // CELL)) not in cells:
            return None
        t = {tag.k: tag.v for tag in tags}
        if not any(k in t for k in POI_KEYS):
            return None
        names = poi_names(t)
        if not names:
            return None
        return {"lat": lat, "lon": lon, "names": names, "tags": t}

    class H(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.out = []

        def node(self, n):
            if n.tags and n.location.valid():
                p = keep(n.tags, n.location.lat, n.location.lon)
                if p:
                    self.out.append(p)

        def way(self, w):
            if not w.tags:
                return
            pts = [(nd.lat, nd.lon) for nd in w.nodes if nd.location.valid()]
            if pts:
                p = keep(w.tags, sum(a for a, _ in pts) / len(pts), sum(b for _, b in pts) / len(pts))
                if p:
                    self.out.append(p)

    h = H()
    h.apply_file(path, locations=True, idx="flex_mem")
    return h.out


def find(spots, pois, use_area=True):
    """[(spot_key, poi, via)]: point matches, then area matches when the holdout trusts them."""
    found = [(k, p, None) for k, p in match(spots, pois).items()]
    if use_area:
        found += [(k, p, "area") for k, p in area_match(spots, pois).items()]
    return found


# ---------- neighbourhood local-name share: a TIE-BREAK for "Most local", never a score ----------
# Ruled 2026-10-15. On TH, local-described food sits among 24% local main names, foreign-described
# among 13%, so inside a tie of equal Ulu scores this orders the local-looking street first. It
# was rejected as a score WEIGHT (TH top-30 foreign 3% -> 10%): score.WEIGHTS never reads it.
NB_RADIUS = 300.0       # metres around the spot
NB_MIN = 5              # fewer named food places than this around it is no measurement


def neighbourhood(spots, pois, lang, found=()):
    """({spot_key: share}, {spot_keys located by an area match}) for food spots.

    share = named food POIs within NB_RADIUS whose MAIN `name` is in the local script, over all
    named food POIs there, the spot's own matched POI left out (its name is already osm_local).
    A spot is located by its own coords, else by its area-matched POI: used for this number only,
    never written as coordinates (ODbL, see the module docstring)."""
    grid = defaultdict(list)
    for p in pois:
        if is_food_poi(p["tags"]):
            grid[(int(p["lat"] // CELL), int(p["lon"] // CELL))].append(p)
    own = {k: (p, via) for k, p, via in found}
    out, via_area = {}, set()
    for s in spots:
        if s.get("cat") not in FOOD:
            continue
        key = spot_key(s)
        p, via = own.get(key, (None, None))
        if s.get("lat") is not None and s.get("lon") is not None:
            lat, lon = s["lat"], s["lon"]
        elif p is not None and via == "area":
            lat, lon = p["lat"], p["lon"]
        else:
            continue
        gy, gx = int(lat // CELL), int(lon // CELL)
        n = local = 0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for q in grid.get((gy + dy, gx + dx), ()):
                    if q is p or metres(lat, lon, q["lat"], q["lon"]) > NB_RADIUS:
                        continue
                    n += 1
                    local += in_local_script(q["tags"].get("name", ""), lang)
        if n >= NB_MIN:
            out[key] = round(local / n, 3)
            if s.get("lat") is None or s.get("lon") is None:
                via_area.add(key)
    return out, via_area


def build_entries(spots, pois, lang, use_area=True, found=None):
    """Point matches for geolocated food spots; area matches (via "area") for the rest when the
    country's holdout trusts them."""
    entries = {}
    found = find(spots, pois, use_area) if found is None else found
    for key, p, via in found:
        d, has, chain = detail(p["tags"], lang)
        e = {"d": d}
        if has:
            e["has"] = has
        if chain:
            e["chain"] = True
        if via:
            e["via"] = via
        entries[key] = e
    return entries


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, path)


def run_extract(osm_path, countries, workdir, keep_file, log):
    """Download + verify one Geofabrik extract and write data/osm/<CC>.json for each country on it.
    Returns {cc: error} for the countries that kept last week's file."""
    url = GEOFABRIK.format(path=osm_path)
    pbf = os.path.join(workdir, osm_path.replace("/", "_") + ".osm.pbf")
    os.makedirs(workdir, exist_ok=True)
    t0 = time.time()
    want = parse_md5(fetch_text(url + ".md5"))
    have = file_md5(pbf) if os.path.exists(pbf) else None
    modified = None
    if have != want:
        modified = download(url, pbf)
        have = file_md5(pbf)
        if have != want:
            # Geofabrik may publish the next daily file between our md5 read and the download.
            want = parse_md5(fetch_text(url + ".md5"))
    if have != want:
        raise OsmError(f"{osm_path}: md5 mismatch (got {have}, Geofabrik says {want})")
    size = os.path.getsize(pbf)
    log(f"{osm_path}: {size / 1e6:.0f} MB verified in {time.time() - t0:.0f}s")
    as_of = extract_date(pbf, modified)
    if not fresh(as_of):
        raise OsmError(f"{osm_path}: extract dated {as_of} is older than {MAX_EXTRACT_AGE} days or undated")
    t1 = time.time()
    src = prefilter(pbf, log)
    by_cc = {}
    for c in countries:
        doc = load_json(os.path.join(ROOT, "public", "data", f"{c['cc']}.json"))
        by_cc[c["cc"]] = doc["spots"] if doc else []
    pois = read_pois(src, [s for v in by_cc.values() for s in v])
    log(f"{osm_path}: {len(pois)} candidate POIs in {time.time() - t1:.0f}s")
    failed = {}
    for c in countries:
        cc, spots = c["cc"], by_cc[c["cc"]]
        out = os.path.join(ROOT, "data", "osm", f"{cc}.json")
        if not spots:
            failed[cc] = "no published spots to match"
            continue
        picks, ok = area_holdout(spots, pois)
        use_area = area_trusted(picks, ok)
        log(f"{cc}: area holdout {ok}/{picks} within {HOLDOUT_OK:.0f} m -> area match {'ON' if use_area else 'off'}")
        found = find(spots, pois, use_area)
        entries = build_entries(spots, pois, c.get("lang"), use_area, found=found)
        nb, nb_area = neighbourhood(spots, pois, c.get("lang"), found)
        prev = load_json(out)
        prev_n = prev.get("matched") if prev else None
        food = sum(1 for s in spots if s.get("cat") in FOOD and s.get("lat") is not None)
        if not accept(len(entries), prev_n, food):
            failed[cc] = f"matched {len(entries)} vs {prev_n} last time: kept last week's file"
            log(f"{cc}: COVERAGE GUARD {failed[cc]}")
            continue
        write_json(out, {"cc": cc, "format": FORMAT, "as_of": as_of.strftime("%Y-%m-%d"), "source": url,
                         "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "food_spots_with_coords": food, "matched": len(entries),
                         "area": {"holdout_picks": picks, "holdout_within_300m": ok, "used": use_area},
                         "spots": entries, "nb": nb, "nb_area": sorted(nb_area)})
        area_n = sum(1 for e in entries.values() if e.get("via") == "area")
        log(f"{cc}: matched {len(entries) - area_n} of {food} food spots with coords, {area_n} without "
            f"by area ({sum(1 for e in entries.values() if e.get('chain'))} chains); "
            f"neighbourhood share for {len(nb)} ({len(nb_area)} located by area)")
    if not keep_file:
        for p in {pbf, src}:
            if os.path.exists(p):
                os.remove(p)
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--dir", default=os.path.join(ROOT, ".cache", "osm"))
    ap.add_argument("--keep", action="store_true", help="keep downloaded extracts (local testing)")
    a = ap.parse_args(argv)
    log = lambda m: print(m, flush=True)
    with open(os.path.join(ROOT, "config", "countries.json"), encoding="utf-8") as f:
        countries = json.load(f)["countries"]
    only = {x.strip().upper() for x in a.only.split(",") if x.strip()}
    groups = defaultdict(list)
    for c in countries:
        if c.get("enabled") and c.get("osm") and (not only or c["cc"] in only):
            groups[c["osm"]].append(c)
    ok, failed = [], {}
    for osm_path, members in groups.items():
        try:
            bad = run_extract(osm_path, members, a.dir, a.keep, log)
        except Exception as e:  # one extract failing must not take the others down
            bad = {c["cc"]: f"{type(e).__name__}: {e}" for c in members}
            log(f"{osm_path}: FAILED {type(e).__name__}: {e}")
        failed.update(bad)
        ok += [c["cc"] for c in members if c["cc"] not in bad]
    write_json(os.path.join(ROOT, "data", "osm", "_state.json"),
               {"built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ok": sorted(ok), "failed": failed})
    if not ok:
        log("nothing written; every country keeps its previous file")
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

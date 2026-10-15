"""Per-country coverage of the two things Nearby, the map and "Most local" depend on.

    python tools/coverage.py [--json out.json]

coords = share of ALL spots with lat/lon. food ulu = share of food spots (dine, markets, cafes)
with a numeric Ulu score. Also shows how many coord-less spots carry a Wikidata item (the only
permitted coordinate source besides Wikivoyage itself: OSM may never write lat/lon).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOOD = ("dine", "cafes", "markets")


def osm_split(cc):
    """(point matches, area matches, area used) from data/osm/<CC>.json, or None."""
    path = os.path.join(ROOT, "data", "osm", f"{cc}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    area = sum(1 for e in d["spots"].values() if e.get("via") == "area")
    return len(d["spots"]) - area, area, (d.get("area") or {})


def row(doc):
    spots = doc["spots"]
    food = [s for s in spots if s["cat"] in FOOD]
    nocoord = [s for s in spots if s["lat"] is None]
    return {
        "spots": len(spots),
        "coords": sum(1 for s in spots if s["lat"] is not None),
        "food": len(food),
        "food_coords": sum(1 for s in food if s["lat"] is not None),
        "food_ulu": sum(1 for s in food if s.get("ulu") is not None),
        "ulu": sum(1 for s in spots if s.get("ulu") is not None),
        "nocoord_wd": sum(1 for s in nocoord if "sitelinks" in (s.get("signals") or {})),
    }


def pct(a, b):
    return f"{100 * a / b:5.1f}%" if b else "    -"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with open(os.path.join(ROOT, "public", "data", "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    out = {}
    print(f"{'cc':3} {'spots':>6} {'coords':>7} {'food':>5} {'f.coord':>7} {'f.ulu':>7} {'ulu':>6} {'nocoord+wd':>10}  osm point/area (holdout)")
    for c in index["countries"]:
        if not c.get("file"):
            continue
        with open(os.path.join(ROOT, "public", c["file"]), encoding="utf-8") as f:
            r = row(json.load(f))
        out[c["cc"]] = r
        o = osm_split(c["cc"])
        osm_txt = ""
        if o:
            h = o[2]
            held = f" ({h['holdout_within_300m']}/{h['holdout_picks']}{', used' if h.get('used') else ', off'})" if h else ""
            osm_txt = f"  {o[0]}/{o[1]}{held}"
        print(f"{c['cc']:3} {r['spots']:6} {pct(r['coords'], r['spots']):>7} {r['food']:5} "
              f"{pct(r['food_coords'], r['food']):>7} {pct(r['food_ulu'], r['food']):>7} {r['ulu']:6} {r['nocoord_wd']:10}{osm_txt}")
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()

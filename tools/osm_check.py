"""Should signal D (osm_local) count toward the Ulu score in a country? Re-run before flipping
`osm_score` in config/countries.json, and after any change to the matcher or the metric.

    python tools/osm_check.py            (PYTHONIOENCODING=utf-8 on Windows)

For each country it scores the published spots AS IF D were on (data/osm/<CC>.json), then
labels food spots by their own Wikivoyage description: "foreign" (expat, western, pizza, Irish
pub...) or "local" (noodles, hawker, izakaya...). The label is a rough proxy, so the verdict
needs >= 20 labelled spots, local-sounding spots scoring >= 5 points higher on average, and no
more foreign-sounding spots in the top 30 than their base share + 5 points.
First run 2026-10-14: ON for TH VN MY JP KR TW CN; PH KH LA MM ran backwards.
"""
import copy
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ulu import osm, score  # noqa: E402

FOREIGN = re.compile(r"\b(expat|expats|western|farang|backpacker|backpackers|tourist|tourists|irish|english pub|"
                     r"british|german|italian|pizza|pizzeria|burger|burgers|sports bar|steak|mexican|french|swiss|"
                     r"australian|american|hash browns|full english)\b", re.I)
LOCALISH = re.compile(r"\b(noodle|noodles|street food|locals|local favourite|local favorite|hawker|stall|stalls|"
                      r"vendors|market|rice|curry|dumpling|dumplings|izakaya|ramen|udon|soba|sushi|pho|banh|bun|"
                      r"nasi|mee|laksa|kopitiam|warung|lechon|adobo|sisig|carinderia|bbq|barbecue|kimchi|bibimbap|"
                      r"hotpot|dim sum|khao|isaan|lanna)\b", re.I)
A_KEYS = ("local_views", "local_share", "local_only", "sitelinks")


def verdict(rows):
    lab = [r for r in rows if r[0] in "LF"]
    if len(lab) < 20:
        return "too few"
    def mean(lbl):
        u = [r[1] for r in rows if r[0] == lbl and r[1] is not None]
        return sum(u) / len(u) if u else None
    loc, forn = mean("L"), mean("F")
    # the app's "Most local" order: score, then osm_nb_local (missing after present), then file order
    top = sorted((r for r in rows if r[1] is not None),
                 key=lambda r: (-r[1], r[2] is None, -(r[2] or 0)))[:30]
    base = sum(1 for r in rows if r[0] == "F") / len(rows)
    top_share = sum(1 for r in top if r[0] == "F") / len(top) if top else 1
    ok = loc is not None and forn is not None and loc - forn >= 5 and top_share <= base + 0.05
    return f"{'ON ' if ok else 'OFF'} local {loc or 0:.0f} vs foreign {forn or 0:.0f}, top30 foreign {100 * top_share:.0f}% (base {100 * base:.0f}%)"


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "config", "countries.json"), encoding="utf-8") as f:
        conf = json.load(f)["countries"]
    flags = {c["cc"]: bool(c.get("osm_score")) for c in conf}
    areas = {c["cc"]: c.get("osm_area", True) for c in conf}  # as the build applies it
    if "--no-area" in sys.argv:  # what the verdict would be with point matches only
        areas = {cc: False for cc in areas}
    if "--area" in sys.argv:     # ... and with every area match counted
        areas = {cc: True for cc in areas}
    # the osm_nb_local tie-break inside the top 30, as the build applies it (countries.json osm_nb);
    # --no-nb = ties in file order only, --nb = tie-break everywhere: compare the two before flipping it
    nbs = {c["cc"]: c.get("osm_nb", True) for c in conf}
    if "--no-nb" in sys.argv:
        nbs = {cc: False for cc in nbs}
    if "--nb" in sys.argv:
        nbs = {cc: True for cc in nbs}
    for cc in sorted(flags):
        path = os.path.join(root, "public", "data", f"{cc}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            spots = copy.deepcopy(json.load(f)["spots"])
        for s in spots:  # rebuild signals as the build would with D on: A + sitelinks, then D
            s["signals"] = {k: v for k, v in (s.get("signals") or {}).items() if k in A_KEYS}
        if not osm.attach(spots, cc, root, log=lambda m: None, use_area=areas.get(cc, True), use_nb=nbs.get(cc, True)):
            print(f"{cc}: no usable data/osm file")
            continue
        score.ulu_scores(spots)
        rows = []
        for s in spots:
            if s["cat"] in osm.FOOD and "osm_local" in s["signals"]:
                f, l = bool(FOREIGN.search(s["desc"])), bool(LOCALISH.search(s["desc"]))
                rows.append(("F" if f and not l else "L" if l and not f else "?", s["ulu"],
                             s["signals"].get("osm_nb_local")))
        print(f"{cc}: config {'on ' if flags[cc] else 'off'}{'' if areas.get(cc, True) else ' (no area)'}"
              f"{'' if nbs.get(cc, True) else ' (no nb)'} | {verdict(rows)}")


if __name__ == "__main__":
    main()

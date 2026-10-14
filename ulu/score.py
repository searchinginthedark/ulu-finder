"""The Ulu score: a 0-100 blend of per-(country, category) percentiles of the signals a spot has.

A missing signal is excluded and the weights renormalise; it is never read as 0, or every spot
without a Wikidata item would be punished for a gap in our sources. Fame (sitelinks) only adjusts
a score: a spot with no locality evidence at all gets null, so "Most local" never silently
becomes "Most famous".
"""
import bisect
from collections import defaultdict

# signals key -> weight. D is osm_local (local-language name on OpenStreetMap); B is parked.
WEIGHTS = {"local_share": 0.40, "mentions": 0.30, "osm_local": 0.15, "sitelinks": 0.15}
LOCALITY = ("local_share", "mentions", "osm_local")
# A percentile among a handful of spots is noise: with 4 scored TH Activities, a 32% Thai share
# ranked RamaYana Water Park 80. Below this many locality-scored spots, the whole pool stays null.
MIN_POOL = 10


def percentiles(values):
    """Mid-rank percentile in [0, 1] for each value: ties share a rank, a lone value is 0.5."""
    s = sorted(values)
    out = {}
    for v in set(values):
        lo, hi = bisect.bisect_left(s, v), bisect.bisect_right(s, v)
        out[v] = (lo + 0.5 * (hi - lo)) / len(s)
    return out


def ulu_scores(spots, min_pool=MIN_POOL):
    """Set spot["ulu"] in place from spot["signals"]; percentiles are taken per category.

    A category with fewer than min_pool spots carrying locality evidence scores nobody."""
    by_cat = defaultdict(list)
    for s in spots:
        by_cat[s["cat"]].append(s)
    for pool in by_cat.values():
        # A locality signal with one value across the whole pool tells its spots nothing apart:
        # in Japan every OSM name is Japanese, so osm_local = 1 everywhere. It must not turn
        # "matched on OSM" into a score, so it is ignored in that pool.
        dead = set()
        for k in LOCALITY:
            vals = [(s.get("signals") or {}).get(k) for s in pool]
            vals = [v for v in vals if v is not None]
            if len(vals) >= 2 and len(set(vals)) == 1:
                dead.add(k)
        keys = [k for k in WEIGHTS if k not in dead]
        live = [k for k in LOCALITY if k not in dead]
        local = sum(1 for s in pool if any((s.get("signals") or {}).get(k) is not None for k in live))
        if local < min_pool:
            for s in pool:
                s["ulu"] = None
            continue
        pct = {}
        for key in keys:
            vals = [s["signals"][key] for s in pool if s.get("signals", {}).get(key) is not None]
            pct[key] = percentiles(vals) if vals else {}
        for s in pool:
            sig = s.get("signals") or {}
            have = [k for k in keys if sig.get(k) is not None]
            if not any(k in LOCALITY for k in have):
                s["ulu"] = None
                continue
            total = sum(WEIGHTS[k] for k in have)
            s["ulu"] = round(100 * sum(WEIGHTS[k] * pct[k][sig[k]] for k in have) / total)

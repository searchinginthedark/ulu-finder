"""The Ulu score: a 0-100 blend of per-(country, category) percentiles of the signals a spot has.

A missing signal is excluded and the weights renormalise; it is never read as 0, or every spot
without a Wikidata item would be punished for a gap in our sources. Fame (sitelinks) only adjusts
a score: a spot with no locality evidence at all gets null, so "Most local" never silently
becomes "Most famous".
"""
import bisect
from collections import defaultdict

# signals key -> weight. B (mentions) and D (osm_detail) join here when they are built.
WEIGHTS = {"local_share": 0.40, "mentions": 0.30, "osm_detail": 0.15, "sitelinks": 0.15}
LOCALITY = ("local_share", "mentions", "osm_detail")


def percentiles(values):
    """Mid-rank percentile in [0, 1] for each value: ties share a rank, a lone value is 0.5."""
    s = sorted(values)
    out = {}
    for v in set(values):
        lo, hi = bisect.bisect_left(s, v), bisect.bisect_right(s, v)
        out[v] = (lo + 0.5 * (hi - lo)) / len(s)
    return out


def ulu_scores(spots):
    """Set spot["ulu"] in place from spot["signals"]; percentiles are taken per category."""
    by_cat = defaultdict(list)
    for s in spots:
        by_cat[s["cat"]].append(s)
    for pool in by_cat.values():
        pct = {}
        for key in WEIGHTS:
            vals = [s["signals"][key] for s in pool if s.get("signals", {}).get(key) is not None]
            pct[key] = percentiles(vals) if vals else {}
        for s in pool:
            sig = s.get("signals") or {}
            have = [k for k in WEIGHTS if sig.get(k) is not None]
            if not any(k in LOCALITY for k in have):
                s["ulu"] = None
                continue
            total = sum(WEIGHTS[k] for k in have)
            s["ulu"] = round(100 * sum(WEIGHTS[k] * pct[k][sig[k]] for k in have) / total)

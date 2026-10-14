"""Quality report for one built country file: categories, regions, samples, gaps.

    python tools/inspect_country.py MY [--samples 8]
"""
import collections
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    cc = sys.argv[1].upper()
    n = int(sys.argv[sys.argv.index("--samples") + 1]) if "--samples" in sys.argv else 8
    with open(os.path.join(ROOT, "public", "data", f"{cc}.json"), encoding="utf-8") as f:
        d = json.load(f)
    spots = d["spots"]
    print(f"{cc}: {len(spots)} spots, {len(d['regions'])} regions")
    print("categories:", collections.Counter(s["cat"] for s in spots).most_common())
    print("coords:", sum(1 for s in spots if s["lat"] is not None), "img:", sum(1 for s in spots if s["img"]),
          "local:", sum(1 for s in spots if s["local"]), "desc:", sum(1 for s in spots if s["desc"]))
    names = {r["id"]: r["name"] for r in d["regions"]}
    for r in d["regions"]:
        if r["level"] == 1:
            kids = [f"{x['name']}({x['count']})" for x in d["regions"] if x["parent"] == r["id"]]
            print(f"  L1 {r['name']} ({r['count']}): {', '.join(kids)}")
    orphans = [s for s in spots if s["r1"] not in names]
    print("spots whose r1 is not a listed region:", len(orphans))
    print("top 12:", [(s["name"], s["cat"], s["score"]) for s in spots[:12]])
    rnd = random.Random(1)
    for cat in sorted({s["cat"] for s in spots}):
        pool = [s for s in spots if s["cat"] == cat]
        print(f"\n[{cat}] sample:")
        for s in rnd.sample(pool, min(n, len(pool))):
            print(f"   {s['name'][:50]:50} | {s['dest'][:18]:18} | {s['desc'][:70]}")


if __name__ == "__main__":
    main()

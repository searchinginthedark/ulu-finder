"""Re-apply config/platforms.json to the built public/data/<CC>.json files.

Platform links are copied into every country file at build time, so a link fix would
otherwise wait for the weekly collect. This touches only `platforms` and `why`; spots,
scores and dates are left byte-for-byte as built.

    python tools/refresh_platforms.py [--check]
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ulu.build import load_config, resolve_platforms, write_json  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if any file is stale, write nothing")
    a = ap.parse_args()
    _, platforms = load_config()
    data_dir = os.path.join(ROOT, "public", "data")
    stale = []
    for name in sorted(os.listdir(data_dir)):
        if name == "index.json" or not name.endswith(".json"):
            continue
        path = os.path.join(data_dir, name)
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        plats, why = resolve_platforms(obj["cc"], platforms)
        if obj.get("platforms") == plats and obj.get("why") == why:
            continue
        stale.append(obj["cc"])
        if not a.check:
            obj["platforms"] = plats
            obj["why"] = why
            write_json(path, obj)
    print(("stale: " if a.check else "refreshed: ") + (", ".join(stale) or "none"))
    return 1 if (a.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())

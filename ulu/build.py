"""Build public/data/*.json from Wikivoyage + Wikidata.

    python -m ulu.build [--only MY,TH] [--cache .cache] [--out public/data]

Exit 0 = every enabled country built; 1 = some failed (their previous files are kept);
2 = none built, nothing written. A failure is never written as an empty country.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone

from . import net, osm, score, signals, wikitext
from .classify import CATEGORIES, classify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/"
# Allowlist, not denylist: Wikivoyage also files dive guides, events, airports and phrasebooks
# under places, and a denylist missed "usablediveguide" on its first run.
# Airports stay: Changi's Jewel is one of Singapore's top sights.
PLACE_STATUS = re.compile(r"(?:city|district|region|park|country|ruralarea|continent|airport)$")


def not_place(status):
    return bool(status) and not PLACE_STATUS.search(status)


def load_config():
    with open(os.path.join(ROOT, "config", "countries.json"), encoding="utf-8") as f:
        countries = json.load(f)["countries"]
    with open(os.path.join(ROOT, "config", "platforms.json"), encoding="utf-8") as f:
        platforms = json.load(f)
    return countries, platforms


# ---------- Wikivoyage geography ----------

def geocrumb_tree():
    """{pageid: (title, parent_pageid)} for every article with a breadcrumb parent."""
    tree = {}
    for doc in net.wv_query({"list": "pageswithprop", "pwppropname": "geocrumb-is-in",
                             "pwpprop": "ids|title|value", "pwplimit": "max"}):
        for row in doc["query"]["pageswithprop"]:
            if row.get("ns") == 0:
                tree[str(row["pageid"])] = (row["title"], str(row["value"]))
    if len(tree) < 10000:
        # The full tree is ~30k articles; a short read is an outage, not a smaller world.
        raise net.FetchError(f"geocrumb tree has only {len(tree)} pages")
    return tree


def page_id(title):
    for doc in net.wv_query({"titles": title, "redirects": 1}):
        p = doc["query"]["pages"][0]
        if "missing" in p:
            raise net.FetchError(f"no Wikivoyage article {title!r}")
        return str(p["pageid"]), p["title"]


def descendants(tree, root):
    """{pageid: [ancestor ids from the root's child down to the page itself]}"""
    children = defaultdict(list)
    for pid, (_t, parent) in tree.items():
        children[parent].append(pid)
    out, stack, seen = {}, [(root, [])], {root}
    while stack:
        pid, path = stack.pop()
        for c in children.get(pid, []):
            if c in seen:
                continue  # breadcrumb loops exist on a wiki; never trust it to be a tree
            seen.add(c)
            out[c] = path + [c]
            stack.append((c, path + [c]))
    return out


def fetch_pages(pageids, cache_dir=None):
    """{pageid: {title, text, wd, image, lat, lon}} in batches of 50."""
    pages, todo = {}, []
    for pid in pageids:
        hit = _cache_get(cache_dir, pid)
        if hit is not None:
            pages[pid] = hit
        else:
            todo.append(pid)
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        params = {"pageids": "|".join(batch), "prop": "revisions|pageprops|coordinates",
                  "rvprop": "content", "rvslots": "main", "coprimary": "primary", "colimit": "max"}
        for doc in net.wv_query(params):
            for p in doc["query"].get("pages", []):
                pid = str(p["pageid"])
                rev = (p.get("revisions") or [{}])[0]
                text = rev.get("slots", {}).get("main", {}).get("content")
                if text is None:
                    continue  # continuation may deliver content on a later page of results
                props = p.get("pageprops") or {}
                coord = (p.get("coordinates") or [{}])[0]
                pages[pid] = {"title": p["title"], "text": text, "wd": props.get("wikibase_item", ""),
                              "image": props.get("page_image_free", ""), "lat": coord.get("lat"), "lon": coord.get("lon")}
                _cache_put(cache_dir, pid, pages[pid])
        time.sleep(0.5)
    missing = [p for p in pageids if p not in pages]
    if missing:
        raise net.FetchError(f"{len(missing)} pages came back without content, e.g. {missing[:3]}")
    return pages


def _cache_get(d, pid):
    if not d:
        return None
    p = os.path.join(d, f"{pid}.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def _cache_put(d, pid, val):
    if d:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{pid}.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(val, f, ensure_ascii=False)


# ---------- spots ----------

def display_name(title):
    """'West Coast (Malaysia)' -> 'West Coast'; 'Singapore/Chinatown' -> 'Chinatown'."""
    t = title.rsplit("/", 1)[-1]
    return re.sub(r"\s*\([^)]*\)$", "", t).strip()


def num(v):
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x if -180 <= x <= 180 and x != 0 else None


def commons_url(filename):
    f = re.sub(r"^(?:File|Image):", "", (filename or "").strip(), flags=re.I).strip()
    if not f or "{" in f or "[" in f:
        return None
    return COMMONS + urllib.parse.quote(f.replace(" ", "_")) + "?width=640"


def norm(s):
    return re.sub(r"[^\w]+", " ", s.lower()).strip()


def page_spots(pid, page, path, titles):
    title = page["title"]
    dest = display_name(title)
    up = [display_name(titles[a]) for a in reversed(path[:-1])]
    r1 = path[0]
    r2 = path[1] if len(path) > 1 else None
    base_src = "https://en.wikivoyage.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
    out = []
    status = wikitext.status_template(page["text"])
    if status.endswith("park"):
        out.append({"name": dest, "alt": "", "cat": "nature", "lat": page["lat"], "lon": page["lon"],
                    "desc": wikitext.lede(page["text"]), "hours": "", "price": "", "addr": "",
                    "img": commons_url(page["image"]), "wd": page["wd"], "src": base_src})
    for l in wikitext.listings(page["text"]):
        p = l["params"]
        name = wikitext.clean(p.get("name", ""))
        if not name or len(name) > 120:
            continue
        desc = wikitext.clean(p.get("content", "") or p.get("description", ""), 400)
        cat = classify(l, name, desc)
        if not cat:
            continue
        wd = (p.get("wikidata") or "").strip()
        out.append({
            "name": name, "alt": wikitext.clean(p.get("alt", "")), "cat": cat,
            "lat": num(p.get("lat")), "lon": num(p.get("long") or p.get("lon")),
            "desc": desc, "hours": wikitext.clean(p.get("hours", ""), 120),
            "price": wikitext.clean(p.get("price", ""), 120), "addr": wikitext.clean(p.get("address", ""), 160),
            "img": commons_url(p.get("image", "")), "wd": wd if re.fullmatch(r"Q\d+", wd) else "",
            "src": base_src + ("#" + urllib.parse.quote(l["section"].replace(" ", "_")) if l["section"] else ""),
        })
    for s in out:
        s.update({"dest": dest, "up": up, "r1": r1, "r2": r2, "dest_wd": page["wd"],
                  "dest_ll": (page["lat"], page["lon"]) if page["lat"] is not None and page["lon"] is not None else None,
                  "id": hashlib.sha1(f"{title}|{s['cat']}|{s['name']}".encode()).hexdigest()[:10]})
    return out


def dedupe(spots):
    """The same place is often listed on a city page and on its district page, sometimes
    under another name ("Mt. Apo" / "Mount Apo"); a shared Wikidata item settles it."""
    seen, out = set(), []
    for s in spots:
        if s.get("wd"):
            key = ("wd", s["wd"])
        elif s["lat"] is not None and s["lon"] is not None:
            key = (norm(s["name"]), round(s["lat"], 3), round(s["lon"], 3))
        else:
            key = (norm(s["name"]), s["r1"], s["dest"])
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


# ---------- Wikidata ----------

def parse_point(wkt):
    """'Point(100.49 13.75)' -> (13.75, 100.49). Items on another globe carry an IRI prefix
    ('<http://www.wikidata.org/entity/Q405> Point(...)', the Moon): not a place on Earth."""
    m = re.fullmatch(r"\s*Point\(\s*(-?[\d.]+(?:[eE]-?\d+)?)\s+(-?[\d.]+(?:[eE]-?\d+)?)\s*\)\s*", wkt or "")
    if not m:
        return None
    lon, lat = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return lat, lon


def wikidata_facts(qids, lang):
    """{qid: {links, img, label, coord}} via SPARQL, 250 ids per query."""
    facts = {}
    qids = sorted(set(q for q in qids if q))
    langs = [lang] if lang else []
    for i in range(0, len(qids), 250):
        values = " ".join("wd:" + q for q in qids[i:i + 250])
        lab = ""
        if langs:
            lab = f'OPTIONAL {{ ?item rdfs:label ?lab FILTER(LANG(?lab) = "{langs[0]}") }}'
        q = f"""SELECT ?item ?links (SAMPLE(?img) AS ?img) (SAMPLE(?lab) AS ?lab) (SAMPLE(?coord) AS ?coord) WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item wikibase:sitelinks ?links }}
  OPTIONAL {{ ?item wdt:P18 ?img }}
  OPTIONAL {{ ?item wdt:P625 ?coord }}
  {lab}
}} GROUP BY ?item ?links"""
        for row in net.sparql(q):
            qid = row["item"]["value"].rsplit("/", 1)[-1]
            img = row.get("img", {}).get("value")
            if img:
                img = img.replace("http://", "https://", 1) + "?width=640"
            facts[qid] = {"links": int(row.get("links", {}).get("value", 0)), "img": img,
                          "label": row.get("lab", {}).get("value", ""),
                          "coord": parse_point(row.get("coord", {}).get("value"))}
        time.sleep(1)
    return facts


def has_non_ascii_letters(s):
    return any(ord(c) > 127 and c.isalpha() for c in s)


# A listing's Wikidata item is editor-chosen; one far from its destination is the wrong item
# (a namesake), and its coordinates would put the spot in another province.
WD_COORD_MAX_KM = 50


def enrich(spots, facts):
    """Wikidata adds fame, photo and local label; and coordinates (P625, CC0) only to a listing
    that has none of its own. OpenStreetMap never supplies coordinates (ODbL, see osm.py)."""
    for s in spots:
        f = facts.get(s["wd"], {})
        s["score"] = f.get("links", 0)
        if (s["lat"] is None or s["lon"] is None) and f.get("coord"):
            lat, lon = f["coord"]
            a = s.get("dest_ll")
            if a is None or osm.metres(a[0], a[1], lat, lon) <= WD_COORD_MAX_KM * 1000:
                s["lat"], s["lon"] = lat, lon
        if not s["img"] and f.get("img"):
            s["img"] = f["img"]
        label = f.get("label", "")
        alt = s.pop("alt", "")
        if label and norm(label) != norm(s["name"]):
            s["local"] = label
        elif alt and has_non_ascii_letters(alt) and norm(alt) != norm(s["name"]):
            s["local"] = alt
        else:
            s["local"] = ""


def attach_signals(spots, looks):
    """spot["signals"] holds only what was measured; an absent key means 'no data', never 0."""
    for s in spots:
        sig = {}
        if s["wd"]:
            sig["sitelinks"] = s["score"]
        a = looks.get(s["wd"]) if s["wd"] else None
        if a:
            sig["local_views"] = a["local_views"]
            if a["local_share"] is not None:
                sig["local_share"] = a["local_share"]
            if a.get("local_only"):
                sig["local_only"] = True
        s["signals"] = sig
        s["listed_by"] = "wikivoyage"


A_KEYS = ("local_views", "local_share", "local_only")


def previous_lookups(prev):
    """Signal A values from last week's published file, by stable spot key, and their date.
    Used only when this week's pageview read fails: stale-and-dated beats silently unscored."""
    if not prev:
        return None, None
    carry = {}
    for s in prev.get("spots", []):
        sig = s.get("signals") or {}
        a = {k: sig[k] for k in A_KEYS if k in sig}
        if a:
            carry[osm.spot_key(s)] = a
    as_of = (prev.get("signals_as_of") or {}).get("lookups") or (prev.get("generated") or "")[:10] or None
    return carry, as_of


def carry_lookups(spots, carry):
    """Put last week's A values back on the spots that still exist; A keys only, nothing else."""
    for s in spots:
        a = carry.get(osm.spot_key(s))
        if a:
            s["signals"].update(a)


def rank_key(s, facts, order):
    """Most food listings have no Wikidata item, so their own score is 0 and ties are the norm.
    Break them by how well-known the destination is (George Town before Butterworth), then by
    whether a Wikivoyage editor bothered to describe the place, then by photo."""
    dest_links = facts.get(s["dest_wd"], {}).get("links", 0)
    described = len(s["desc"]) >= 60
    return (-s["score"], -min(dest_links, 60) // 10, not described, s["img"] is None, order)


# ---------- assembly ----------

def resolve_platforms(cc, platforms):
    reg = platforms["platforms"]
    conf = platforms["countries"].get(cc) or {"dine": ["gmaps"], "any": ["gmaps"], "why": ""}

    def one(pid):
        p = reg[pid]
        return {"id": pid, "name": p["name"], "url": p["url"], "query": p["query"],
                "verified": p["verified"], "cities": p.get("cities"), "mobile": p.get("mobile")}
    return {"dine": [one(p) for p in conf["dine"]], "any": [one(p) for p in conf["any"]]}, conf.get("why", "")


def load_previous(out_dir, cc):
    path = os.path.join(out_dir, f"{cc}.json") if out_dir else None
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_country(c, tree, platforms, cache_dir, log, out_dir=None):
    root, _ = page_id(c["wv"])
    desc = descendants(tree, root)
    if not desc:
        raise net.FetchError(f"{c['wv']} has no sub-articles in the breadcrumb tree")
    titles = {pid: tree[pid][0] for pid in desc}
    pages = fetch_pages(sorted(desc), cache_dir)
    # Topic and itinerary articles ("Diving in Thailand") hang off the breadcrumb tree too;
    # they are not places, so neither they nor anything under them becomes a region.
    skip = {pid for pid in desc if not_place(wikitext.status_template(pages[pid]["text"]))}
    desc = {pid: path for pid, path in desc.items() if not skip.intersection(path)}
    spots = []
    # depth-first by breadcrumb path keeps each article's listings together, regions in Wikivoyage order
    for pid in sorted(desc, key=lambda p: [titles[a] for a in desc[p]]):
        spots.extend(page_spots(pid, pages[pid], desc[pid], titles))
    spots = dedupe(spots)
    facts = wikidata_facts([s["wd"] for s in spots] + [s["dest_wd"] for s in spots], c.get("lang"))
    enrich(spots, facts)
    lookup = c.get("lookup") or {}
    as_of, carry = {}, None
    try:
        looks = signals.lookups([s["wd"] for s in spots], lookup.get("wikis", []), cache_dir, log=log)
        if lookup.get("wikis"):
            as_of["lookups"] = now()[:10]
    except net.FetchError as e:
        # Fail the SIGNAL, not the country: keep this week's listings and reuse last week's A,
        # dated. Only a country with no previous file still fails (nothing honest to show).
        carry, prev_date = previous_lookups(load_previous(out_dir, c["cc"]))
        if carry is None:
            raise
        log(f"{c['cc']}: lookups failed ({e}); reusing {len(carry)} values from {prev_date}")
        looks = {}
        if prev_date:
            as_of["lookups"] = prev_date
    attach_signals(spots, looks)
    if carry:
        carry_lookups(spots, carry)
    # Only where tools/osm_check.py showed the signal favours local food; elsewhere it ran
    # backwards (PH, KH, LA, MM) or had nothing to measure (ID, SG). See countries.json _doc.
    osm_date = osm.attach(spots, c["cc"], log=log) if c.get("osm_score") else None
    if osm_date:
        as_of["osm"] = osm_date
    score.ulu_scores(spots)
    order ={id(s): i for i, s in enumerate(spots)}
    spots.sort(key=lambda s: rank_key(s, facts, order[id(s)]))

    counts = defaultdict(int)
    for s in spots:
        counts[s["r1"]] += 1
        if s["r2"]:
            counts[s["r2"]] += 1
    regions = []
    for pid in sorted(desc, key=lambda p: titles[p]):
        if counts.get(pid) and len(desc[pid]) <= 2:
            parent = desc[pid][0] if len(desc[pid]) == 2 else None
            regions.append({"id": pid, "name": display_name(titles[pid]), "parent": parent,
                            "level": len(desc[pid]), "count": counts[pid]})
    plats, why = resolve_platforms(c["cc"], platforms)
    keep = ("id", "name", "local", "cat", "r1", "r2", "dest", "up", "lat", "lon", "desc",
            "hours", "price", "addr", "img", "score", "ulu", "signals", "listed_by", "src")
    log(f"{c['cc']}: {len(desc)} articles, {len(spots)} spots, {sum(1 for s in spots if s['img'])} with image, "
        f"{len(facts)} wikidata items, {sum(1 for s in spots if s['ulu'] is not None)} with an Ulu score")
    return {"cc": c["cc"], "name": c["name"], "generated": now(), "why": why,
            "lookup_lang": lookup.get("label"), "signals_as_of": as_of, "regions": regions,
            "platforms": plats, "spots": [{k: s[k] for k in keep} for s in spots]}


OSM_ATTRIBUTION = {
    "text": "Local map detail © OpenStreetMap contributors, available under the Open Database License (ODbL)",
    "url": "https://www.openstreetmap.org/copyright",
    "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows only: a scanner or indexer briefly holding the target fails the rename
            # (TW.json, 2026-10-15), which threw away a 45-minute build at the write step.
            if attempt == 4:
                raise
            time.sleep(2)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--cache", default="")
    ap.add_argument("--out", default=os.path.join(ROOT, "public", "data"))
    a = ap.parse_args(argv)
    log = lambda m: print(m, flush=True)
    countries, platforms = load_config()
    only = {x.strip().upper() for x in a.only.split(",") if x.strip()}
    todo = [c for c in countries if c["enabled"] and (not only or c["cc"] in only)]
    tree = geocrumb_tree()
    log(f"breadcrumb tree: {len(tree)} articles")
    built, failed = {}, {}
    for c in todo:
        try:
            built[c["cc"]] = build_country(c, tree, platforms, a.cache or None, log, a.out)
        except Exception as e:  # one country failing must not take the others down
            failed[c["cc"]] = f"{type(e).__name__}: {e}"
            log(f"{c['cc']}: FAILED {failed[c['cc']]}")
    if not built:
        log("nothing built; leaving every file untouched")
        return 2
    os.makedirs(a.out, exist_ok=True)
    for cc, doc in built.items():
        write_json(os.path.join(a.out, f"{cc}.json"), doc)
    index = {"generated": now(),
             "attribution": {"text": "Listings from Wikivoyage (CC BY-SA 4.0) and Wikidata (CC0)",
                             "url": "https://en.wikivoyage.org/"},
             "categories": [{"id": i, "label": l} for i, l in CATEGORIES], "countries": []}
    uses_osm = False
    for c in countries:
        path = os.path.join(a.out, f"{c['cc']}.json")
        entry = {"cc": c["cc"], "name": c["name"], "flag": c["flag"], "count": 0, "file": None,
                 "bytes": 0, "enabled": c["enabled"]}
        if c["enabled"] and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            entry["count"] = len(doc["spots"])
            uses_osm = uses_osm or "osm" in (doc.get("signals_as_of") or {})
            entry.update(file=f"data/{c['cc']}.json", bytes=os.path.getsize(path))
        elif c["enabled"]:
            entry["enabled"] = False  # never built successfully: show as coming soon, never a broken fetch
        index["countries"].append(entry)
    if uses_osm:  # ODbL 4.2/4.3 notice, required whenever any published file carries OSM signals
        index["attribution"]["osm"] = OSM_ATTRIBUTION
    write_json(os.path.join(a.out, "index.json"), index)
    state = {"built": now(), "ok": sorted(built), "failed": failed}
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "state.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, indent=1)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

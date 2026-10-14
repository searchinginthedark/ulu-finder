"""Signal A: who reads about a place, measured by which Wikipedia they read it in.

For each spot with a Wikidata item, sum 12 full months of human pageviews of its article on the
country's local-language Wikipedia(s) and on English Wikipedia. local_share = local / (local + en).
Pageviews cannot be split by reader country, so a language only counts as "local" when its readers
are mostly in that country: that is why zhwiki is NOT used for Malaysia or Singapore (mainland and
Taiwanese tourists read it too) and ptwiki is not used for Timor-Leste (Brazil dominates it).
"""
import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from . import net

PV = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/{title}/monthly/{start}/{end}"
# Below this many views a year the share is a coin toss (a handful of readers either way).
SHARE_FLOOR = 300
# More failed lookups than this and the signal is unreliable for the whole country: fail it,
# so the build keeps last week's file instead of publishing a thinner signal as if it were real.
MAX_FAILED = 0.05
# Serial and paced: 4 parallel workers drew HTTP 429 within seconds (measured 2026-10-14).
PACE = 0.12


def window(today=None):
    """Last 12 FULL months as (YYYYMMDD, YYYYMMDD): a partial month would under-count."""
    today = today or date.today()
    end = today.replace(day=1) - timedelta(days=1)
    y, m = end.year, end.month - 11
    if m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}{m:02d}01", end.strftime("%Y%m%d")


def share(local_views, en_views, floor=SHARE_FLOOR):
    """local_share, or None when the total is too small to mean anything."""
    total = local_views + en_views
    if total < floor:
        return None
    return round(local_views / total, 2)


def sitelinks(qids, wikis):
    """{qid: {wiki: title}} for 'en' plus each local wiki code, via SPARQL, 250 ids per query."""
    sites = " ".join(f"<https://{w}.wikipedia.org/>" for w in ["en"] + list(wikis))
    out = {}
    qids = sorted(set(q for q in qids if q))
    for i in range(0, len(qids), 250):
        values = " ".join("wd:" + q for q in qids[i:i + 250])
        q = f"""SELECT ?item ?site ?title WHERE {{
  VALUES ?item {{ {values} }}
  VALUES ?site {{ {sites} }}
  ?article schema:about ?item; schema:isPartOf ?site; schema:name ?title.
}}"""
        for row in net.sparql(q):
            qid = row["item"]["value"].rsplit("/", 1)[-1]
            wiki = row["site"]["value"].split("//", 1)[1].split(".", 1)[0]
            out.setdefault(qid, {})[wiki] = row["title"]["value"]
        time.sleep(1)
    return out


def pv_url(wiki, title, start, end):
    t = urllib.parse.quote(title.replace(" ", "_"), safe="")  # '/' in a title must be encoded too
    return PV.format(project=f"{wiki}.wikipedia", title=t, start=start, end=end)


def fetch_views(url, tries=5):
    """Total views, or raise. A 404 means the API has no rows for the article in the window,
    which for an article we know exists is zero views, not an error."""
    last = None
    for attempt in range(tries):
        time.sleep(PACE)
        req = urllib.request.Request(url, headers={"User-Agent": net.UA, "Accept-Encoding": "gzip"})
        wait = 2 * (attempt + 1)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            return sum(int(i.get("views", 0)) for i in json.loads(raw).get("items", []))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 0
            last = e
            if 400 <= e.code < 500 and e.code != 429:
                break
            if e.code == 429:
                ra = e.headers.get("Retry-After", "")
                wait = int(ra) if ra.isdigit() else 10 * (attempt + 1)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
        time.sleep(min(wait, 60))
    raise net.FetchError(f"{url[:140]}: {last}")


def _cached_views(url, cache_dir):
    path = None
    if cache_dir:
        path = os.path.join(cache_dir, "pv", hashlib.sha1(url.encode()).hexdigest() + ".json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)["views"]
    v = fetch_views(url)
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"url": url, "views": v}, f)
    return v


def lookups(qids, wikis, cache_dir=None, today=None, log=print):
    """{qid: {"local_views": n, "en_views": n, "local_share": x|None}} for items with an article
    on at least one of the wikis. Items whose views could not be read are absent (missing, not 0)."""
    if not wikis:
        return {}
    links = sitelinks(qids, wikis)
    start, end = window(today)
    jobs = {}
    for qid, titles in links.items():
        for wiki, title in titles.items():
            jobs[(qid, wiki)] = pv_url(wiki, title, start, end)
    views, failed = {}, set()
    for key, url in jobs.items():
        try:
            views[key] = _cached_views(url, cache_dir)
        except net.FetchError as e:
            failed.add(key[0])
            log(f"  pageviews failed: {e}")
    if jobs and len(failed) > MAX_FAILED * len(links):
        raise net.FetchError(f"pageviews failed for {len(failed)} of {len(links)} items")
    out = {}
    for qid, titles in links.items():
        if qid in failed:
            continue
        local = sum(views.get((qid, w), 0) for w in wikis)
        en = views.get((qid, "en"), 0)
        # No English article is not the same as no English readers: Erawan Falls has none because
        # English covers it under Erawan National Park. Flag it so the app can say so.
        out[qid] = {"local_views": local, "en_views": en, "local_share": share(local, en),
                    "local_only": "en" not in titles}
    log(f"  lookups: {len(links)} items with articles, {len(jobs)} pageview series, {len(failed)} failed")
    return out

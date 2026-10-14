"""HTTP for Wikimedia APIs. Wikimedia's policy asks for a descriptive User-Agent and
serial requests; maxlag makes us back off when their replicas are behind."""
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "UluFinder/1.0 (https://github.com/Zhiyang123/ulu-finder; weekly travel-spot build)"
WV_API = "https://en.wikivoyage.org/w/api.php"
WD_SPARQL = "https://query.wikidata.org/sparql"


class FetchError(RuntimeError):
    pass


def get_json(url, params=None, data=None, tries=4):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    body = urllib.parse.urlencode(data).encode() if data else None
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                doc = json.loads(raw)
            err = doc.get("error") if isinstance(doc, dict) else None
            if err and err.get("code") == "maxlag":
                last = FetchError("maxlag")
                time.sleep(5 * (attempt + 1))
                continue
            if err:
                raise FetchError(f"{err.get('code')}: {err.get('info')}")
            return doc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            code = getattr(e, "code", None)
            if code and 400 <= code < 500 and code != 429:
                break
            time.sleep(3 * (attempt + 1))
    raise FetchError(f"{url[:120]}: {last}")


def wv_query(params):
    """One Wikivoyage API query, continuation followed. Yields each result page."""
    base = {"action": "query", "format": "json", "formatversion": 2, "maxlag": 5}
    base.update(params)
    cont = {}
    while True:
        doc = get_json(WV_API, data={**base, **cont})
        yield doc
        if "continue" not in doc:
            return
        cont = doc["continue"]


def sparql(query):
    doc = get_json(WD_SPARQL, data={"query": query, "format": "json"})
    return doc["results"]["bindings"]

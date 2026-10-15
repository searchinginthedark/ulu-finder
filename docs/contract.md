# Data contract: collector -> app

The app reads ONLY `public/data/index.json` and `public/data/<CC>.json`. The collector
(`python -m ulu.build`) writes both. Change this file before changing either side.

## `public/data/index.json`

```json
{
  "generated": "2026-10-14T03:00:00Z",
  "attribution": {"text": "Listings from Wikivoyage (CC BY-SA 4.0) and Wikidata (CC0)", "url": "https://en.wikivoyage.org/",
                  "osm": {"text": "Local map detail © OpenStreetMap contributors, available under the Open Database License (ODbL)",
                          "url": "https://www.openstreetmap.org/copyright", "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/"}},
  "categories": [
    {"id": "dine", "label": "Dine"}, {"id": "markets", "label": "Markets & Hawkers"},
    {"id": "cafes", "label": "Cafes & Bars"}, {"id": "shopping", "label": "Shopping"},
    {"id": "nature", "label": "Nature"}, {"id": "culture", "label": "Temples & Heritage"},
    {"id": "sights", "label": "Sights"}, {"id": "activities", "label": "Activities"}
  ],
  "countries": [
    {"cc": "MY", "name": "Malaysia", "flag": "🇲🇾", "count": 2140, "file": "data/MY.json", "bytes": 812345, "enabled": true}
  ]
}
```

- `attribution.osm` is REQUIRED whenever any country carries OSM signals (ODbL 4.2/4.3): the app
  shows its text with both links. The fields it covers are listed under `signals` below.
- `countries` lists every configured country. `enabled: false` (East Asia, for now) has `count: 0`
  and NO file: show it greyed as "coming soon", never fetch it.
- Category order above is display order.

## `public/data/<CC>.json`

```json
{
  "cc": "MY", "name": "Malaysia", "generated": "2026-10-14T03:00:00Z",
  "why": "Google Maps reviews dominate; ...",
  "lookup_lang": "Malay",
  "signals_as_of": {"lookups": "2026-10-14", "osm": "2026-10-17"},
  "regions": [
    {"id": "38881", "name": "West Coast", "parent": null, "level": 1, "count": 900},
    {"id": "27188", "name": "Penang", "parent": "38881", "level": 2, "count": 310}
  ],
  "platforms": {
    "dine": [{"id": "gmaps", "name": "Google Maps", "url": "https://...{q}", "query": "en", "verified": "ok", "cities": null, "mobile": null}],
    "any":  [...]
  },
  "spots": [
    {
      "id": "a1b2c3d4",
      "name": "EE Beng Vegetarian Food",
      "local": "怡明素食",
      "cat": "dine",
      "r1": "38881", "r2": "27188",
      "dest": "George Town",
      "lat": 5.418988, "lon": 100.330762,
      "desc": "A small self-serve buffet style vegetarian restaurant...",
      "hours": "", "price": "", "addr": "Lebuh Dickens",
      "img": "https://commons.wikimedia.org/wiki/Special:FilePath/X.jpg?width=640",
      "score": 12,
      "ulu": 74,
      "signals": {"local_share": 0.82, "local_views": 12400, "sitelinks": 12},
      "listed_by": "wikivoyage",
      "src": "https://en.wikivoyage.org/wiki/George_Town_(Malaysia)#Eat"
    }
  ]
}
```

Field rules (the app must cope with every one being empty):
- `region` names drop Wikivoyage's disambiguator: "West Coast (Malaysia)" -> "West Coast".
- `level` 1 = direct child of the country; 2 = its child. Deeper Wikivoyage levels fold into level 2.
  A spot always has `r1`; `r2` may be `null` (spot sits directly in a level-1 region, or the country
  has no level 2 there). Singapore-sized countries may have only level 1.
- `local`: local-script name, `""` when unknown.
- `up`: names of the Wikivoyage articles above `dest`, nearest first, country excluded
  (`["Penang", "West Coast"]`). District pages put their city here ("District 1" -> `["Ho Chi Minh City", ...]`).
  Used only for `{city}` lookup; not displayed.
- `lat`/`lon`: `null` when the listing has no coordinates (about a third do not).
- `img`: `null` for most food listings. Never hotlink anything but `commons.wikimedia.org`.
- `score`: popularity, higher first. Wikidata sitelink count where the listing is on Wikidata, else 0.
  Ties keep collector order (Wikivoyage's own order). Spots arrive pre-sorted by score desc.
- `ulu`: the Ulu score, 0-100, or `null` when the spot has no locality evidence (no signal A/B/D),
  OR when fewer than 10 spots in its (country, category) have locality evidence (`MIN_POOL`): a
  percentile among a handful is noise. The app tells the two apart by whether `signals` holds a locality key.
  Fame (`sitelinks`) alone never produces a score. Percentiles are per category within the country,
  so 74 means "more local-skewed than most Sights in Malaysia", not an absolute rating.
  Spots are NOT sorted by it; the app sorts ("Most local" = ulu desc, nulls last).
- `signals`: only what was measured; an ABSENT key means no data, never zero. Show measurements, never
  a verdict ("82% of Wikipedia lookups are in Malay", not "locals love this").
  - `local_views`: human pageviews of the spot's article on the `lookup_lang` Wikipedia, last 12 full months.
  - `local_share`: local_views / (local + English Wikipedia views), 0-1. Omitted under 300 views/yr (noise).
  - `local_only`: `true` when the spot has NO English Wikipedia article (so `local_share` is 1.0 by
    construction). Say "only on Thai Wikipedia", never "100% of lookups": English readers may be reading
    a parent article instead (Erawan Falls is covered under Erawan National Park).
  - `sitelinks`: Wikidata sitelink count (same number as `score`), present only for spots with an item.
  - `osm_local`: `1` or `0`, food categories only (`dine`, `cafes`, `markets`), present when the spot
    matched an OpenStreetMap place (same name, within 150 m). `1` = the place is named in the local
    language there (a `name:<lang>` tag, or a name in non-ASCII letters: Thai script, Vietnamese
    diacritics). A chain brand is `0`. NOT a detail count: on TH, foreign places carried MORE detail
    tags than local ones, while 59% of local-sounding vs 15% of foreign ones had a Thai name.
    In a pool where every matched place has the same value (Japan: all names Japanese) the score
    ignores it. Say "Named in Thai on OpenStreetMap" / "No Thai name on OpenStreetMap".
  - `osm_chain`: `true` when the OpenStreetMap place carries a `brand` tag. Say "part of a chain".
  - `osm_local`, `osm_chain` and `ulu` (partly computed from them) are OpenStreetMap-derived
    and available under the ODbL; every other field is not, and OpenStreetMap NEVER changes `name`,
    `lat`/`lon`, `cat`, `desc` or any other Wikivoyage field (licence: docs/handover-ulu-score.md 3.D).
  - Planned, not yet emitted: `mentions` + `mention_url` (local subreddits; parked).
- `signals_as_of` (country level): date each signal was measured, `YYYY-MM-DD`. `lookups` = signal A
  (an outage reuses the previous week's values and keeps their older date); `osm` = the OpenStreetMap
  extract date, absent when the country has no OSM signals. Show the date next to the evidence it dates.
- `lookup_lang` (country level): display name of the local-language Wikipedia behind `local_*`, or `null`
  when the country has none we trust (Singapore: its local reading is in English) and signal A is skipped.
- `listed_by`: who listed the spot. Always `"wikivoyage"` today.
- `desc`: plain text, wiki markup stripped, at most 400 chars.
- `src`: the Wikivoyage section the listing came from. CC BY-SA requires a visible link to it.

## Building a platform link (app side)

For a spot in category `dine`, `markets` or `cafes` use `platforms.dine`; otherwise `platforms.any`.
For each platform:
1. query = `local` if `platform.query == "local"` and `spot.local` is non-empty, else `spot.name`.
   Append `" " + spot.dest` for platforms whose `query` is `en` and that have no `{city}`
   (keeps "Central Market" from matching the wrong city).
2. If the URL has `{city}`: look up `spot.dest`, then each name in `spot.up` in order, in
   `platform.cities`. No match -> omit this platform for this spot.
0. On a phone (UA says Android/iPhone/iPad), use `platform.mobile` instead of `platform.url` when it is set.
3. Replace `{q}` with `encodeURIComponent(query)` and `{slug}` with `encodeURIComponent(slug)`,
   slug = query lowercased, each run of non-letter/mark/digit characters turned into `-`.
Only `https://` links and the `xhsdiscover://` app scheme are rendered; an app link opens in place
(no new window) and gets a small "app" hint.
`verified: "login"` platforms get a small "sign-in" hint; `"challenge"` platforms render normally.

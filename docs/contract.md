# Data contract: collector -> app

The app reads ONLY `public/data/index.json` and `public/data/<CC>.json`. The collector
(`python -m ulu.build`) writes both. Change this file before changing either side.

## `public/data/index.json`

```json
{
  "generated": "2026-10-14T03:00:00Z",
  "attribution": {"text": "Listings from Wikivoyage (CC BY-SA 4.0) and Wikidata (CC0)", "url": "https://en.wikivoyage.org/"},
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

- `countries` lists every configured country. `enabled: false` (East Asia, for now) has `count: 0`
  and NO file: show it greyed as "coming soon", never fetch it.
- Category order above is display order.

## `public/data/<CC>.json`

```json
{
  "cc": "MY", "name": "Malaysia", "generated": "2026-10-14T03:00:00Z",
  "why": "Google Maps reviews dominate; ...",
  "regions": [
    {"id": "38881", "name": "West Coast", "parent": null, "level": 1, "count": 900},
    {"id": "27188", "name": "Penang", "parent": "38881", "level": 2, "count": 310}
  ],
  "platforms": {
    "dine": [{"id": "gmaps", "name": "Google Maps", "url": "https://...{q}", "query": "en", "verified": "ok", "cities": null}],
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
3. Replace `{q}` with `encodeURIComponent(query)`.
`verified: "login"` platforms get a small "sign-in" hint; `"challenge"` platforms render normally.

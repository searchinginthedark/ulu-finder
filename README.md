# Ulu

Scroll travel spots across Southeast Asia by country, region, province and category
(Dine, Markets & Hawkers, Cafes & Bars, Shopping, Nature, Temples & Heritage, Sights,
Activities). Each spot links out to the platforms locals use in that country: Wongnai in
Thailand, Foody in Vietnam, Burpple and Eatbook in Singapore, Tabelog in Japan, Dianping in
China, Naver and Kakao in Korea.

## How it works

- `python -m ulu.build` reads Wikivoyage's breadcrumb tree (every article's parent), pulls
  the listings under each country, classifies them deterministically, adds Wikidata
  popularity and photos, and writes `public/data/<CC>.json` plus `public/data/index.json`.
  No API keys. Contract: `docs/contract.md`.
- `public/` is a static PWA with no build step.
- `.github/workflows/collect.yml` rebuilds the data weekly and commits it.

## Commands

```
python -m unittest discover -s tests -t .
python -m ulu.build [--only MY,TH] [--cache .cache]
python tools/inspect_country.py MY
python -m http.server 8775 --directory public
```

## Data and licences

Listings: Wikivoyage, CC BY-SA 4.0 (every card links to its source section).
Popularity, local names and photos: Wikidata (CC0) and Wikimedia Commons.
Local platforms are only linked to, never scraped.

Adding a country: one row in `config/countries.json` (set `enabled`), one entry in
`config/platforms.json` `countries`.

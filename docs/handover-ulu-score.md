# Handover: the "Ulu score" (locals' picks, with visible evidence)

Written 2026-10-14 for a fresh session. Read this, then `CLAUDE.md` (brief) and `docs/contract.md`.
Nothing here is built yet. Live app: https://ulu-finder.vercel.app (code `2963f97`).

## 1. The problem this solves

The user wants Ulu to surface **hidden spots that locals recommend**, not mainstream picks.
v1 does not deliver that, and the app should not claim it does:

- The spine is **Wikivoyage**, written mostly by travellers, in English. It is a good map of
  regions and categories but skews toward places tourists already know.
- "Top" sorts by **Wikidata sitelink count**, which measures fame. That is close to the
  opposite of hidden.
- Most food listings have no Wikidata item, so their order is mostly by how well-known their
  city is (`ulu/build.py` `rank_key`).

Goal: replace "Top" with a **Ulu score** built only from sources we are allowed to use, and show
the evidence behind it on every card, so a user can judge "locals' pick" for themselves.

## 2. Hard constraint: no scraping, no blended platform scores (user agreed 2026-10-14)

Local platforms (Tabelog, Dianping, Wongnai, Foody, OpenRice, Naver, Kakao...) stay **linked by
search URL only** (`config/platforms.json`). Do not scrape them, even politely and rate-limited.
The reasons, as discussed with the user:

- **Terms bind regardless of request rate.** Their terms prohibit automated collection; being
  non-commercial and gentle lowers the odds they care, it does not make it permitted.
  (The exact clauses were NOT re-read in that session. If the question comes back, pull the
  actual wording before asserting it.)
- **Republishing is the larger risk.** Scores and reviews are their product. Dianping sued Baidu
  (2016) for showing Dianping reviews in Baidu Maps and won; the issue was substitution, not load.
- **A blended score does not fix it.** You still have to collect the scores, and a number built
  from their data still substitutes for visiting them. The EU database right covers substantial
  extraction even when transformed. Google Places and Yelp terms explicitly forbid mixing their
  ratings with other sources. (Not legal advice; this is risk direction.)
- **Tabelog and Dianping sit behind Cloudflare challenges.** Getting past one is circumvention.
  Never build it.
- **Facts are fine, opinions are not.** Name, address, coordinates are facts. Scores, reviews,
  photos are the platform's.

The user-facing answer stays: the card's "Tabelog / Wongnai / Foody" button opens the
platform's own page, where the rating lives.

## 3. The four signals (all permitted)

| # | Signal | Source | Key? | Covers |
|---|---|---|---|---|
| A | Locals' lookups: share of Wikipedia views in the local language | Wikimedia REST pageviews | none | sights, nature, heritage (items with Wikidata) |
| B | Locals' chatter: mentions in local subreddits | Reddit Data API | free account | food especially |
| C | Recognition: Wikidata sitelinks | Wikidata SPARQL (already fetched) | none | everything with an item |
| D | Presence on the ground: OSM detail by local mappers | OpenStreetMap (Overpass or Geofabrik) | none | long tail of eateries |

### A. Locals vs tourists, from Wikipedia reading habits (build FIRST)
- For each spot with a Wikidata id, get its sitelinks for the country's local wiki and enwiki.
  Map: TH->thwiki, VN->viwiki, ID->idwiki, MY->mswiki (also zhwiki: large Malaysian Chinese
  readership), PH->tlwiki (also cebwiki, but ceb is bot-generated, ignore it), KH->kmwiki, LA->lowiki,
  MM->mywiki, SG->enwiki is local (see the open question below), BN->mswiki, TL->tetwiki/ptwiki.
  Sitelinks: SPARQL `?article schema:about ?item; schema:isPartOf <https://th.wikipedia.org/>; schema:name ?title`,
  batched like `wikidata_facts` in `ulu/build.py`.
- Views: `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/{title}/monthly/{start}/{end}`
  (probed 200 on 2026-10-14). Use the last 12 full months, `user` agent only (excludes bots).
- `local_share = local_views / (local_views + en_views)`. A place with a local article and NO
  English article is a strong "local" marker in its own right.
- Volume: about 3.6k spots have Wikidata ids today; with 2 wikis that is about 7k calls a week.
  Serial at about 10/s with the existing UA is polite. Cache results in `.cache/` like pages.
- Pitfalls to check before trusting it: very low totals (under ~300 views/yr) make the share
  noise, so require a floor. Singapore's local language is largely English, so this signal is
  weak there (use zhwiki + mswiki share, or skip A for SG and say so in the UI).

### B. Local subreddit mentions (build SECOND)
- Subreddits: r/singapore, r/SingaporeEats, r/malaysia, r/Thailand, r/VietNam, r/indonesia,
  r/Philippines, r/cambodia, r/laos, r/myanmar, r/Brunei. Check each exists and is active before use.
- Do NOT search per spot (20k spots x subs is far too many calls). Harvest food/recommendation
  threads (search "food", "eat", "recommend", "where to" within each sub, top of the past year,
  plus their comments) into a local corpus, then match spot names offline.
  Name matching needs care: short or generic names ("Central Market") will false-match. Require
  name + city/area co-occurrence, or a minimum name length, and add fixtures for misfires.
- Auth: Reddit OAuth app (free), 100 queries/min. Credentials go in a GitHub Actions secret;
  `collect.yml` must skip B cleanly when the secret is missing (skipped, never failed).
- PARKED 2026-10-14 (user ruling) after reading the terms (Data API Terms rev. 2026-07-20,
  Developer Terms rev. 2026-03-24, Responsible Builder Policy). Blockers, by section:
  - RBP intro: explicit approval is required BEFORE any API access; a free app + secret is no
    longer enough. Non-Devvit non-commercial use means filing a ticket with the exact use case.
  - RBP "Other Prohibited Practices": bans non-commercial "mining" without written approval;
    a mention-count corpus may fall under it, so only Reddit's approval settles it.
  - Developer 3.3: deleted/removed posts must be deleted from our data too. Weekly commits keep
    thread links in git history, so publish counts only, no `mention_url`.
  - Developer 3.1/6 + Data API 6: derived data (our counts) must be deleted on revocation; keep
    B removable by one rebuild. Developer 4.1: Ulu must stay unmonetised while B is in it.
  - Data API 2.9: rate limits at Reddit's discretion; the 100/min figure above is 2023-era and
    unconfirmed. Read the rate-limit response headers, never hardcode a number.
  - The connected Reddit MCP is Reddit data access too; same approval question.
- A Reddit MCP is connected in Claude sessions (`mcp__reddit__*`); use it to explore subs and
  test matching, but the weekly build cannot depend on it.

### C. Wikidata sitelinks
Already in the data as `score`. It becomes one input, and a high value should NOT dominate:
fame is the thing we are trying not to over-reward.

### D. OpenStreetMap
- Shows the long tail (warung, kopitiam, hawker stalls) no guidebook lists. No ratings.
- Option 1: Overpass per country for `amenity=restaurant|cafe|food_court|marketplace` with a
  name. Large countries (TH, ID, PH) are heavy; Overpass fair use discourages that at weekly scale.
- Option 2: Geofabrik country extracts (keyless .pbf) filtered locally. Needs osmium or pyosmium
  in the GHA job. Probably the right answer; decide after measuring one country.
- Use: match existing spots to OSM nodes (name + 150 m) and count local detail tags
  (`opening_hours`, `cuisine`, `name:th`...) as "mapped carefully by locals".
- LICENCE: DECIDED 2026-10-14 (user approved). Score only, as an ODbL "Collective Database":
  - OSM only ADDS `osm_detail` to spots Ulu already has. It NEVER writes a Wikivoyage field
    (name, coords, category, text). Enforce with a test. Mixing a property pulls the CC BY-SA
    listings under ODbL share-alike, which ODbL 4.4(d) forbids.
  - NO OSM-only "Local eats" layer: per the OSMF Horizontal Map Layers guideline, adding
    restaurants "not already listed" makes the whole restaurant type share-alike.
  - `osm_detail` and `ulu` (partly OSM-derived; its other inputs are CC0) are labelled ODbL in
    `index.json` attribution, `docs/contract.md` and the app credits: "© OpenStreetMap
    contributors" linking https://www.openstreetmap.org/copyright.
  - Weekly per-country extraction is "Substantial" under the OSMF guideline, so ODbL fully applies.
  - Reasoning and clause list: memory archive 2026-10-14-1558.md.
- MEASURED 2026-10-14 (TH, 960 of 1,822 coord spots; public Overpass failed before the rest,
  user called it done). Matcher: normalised name or name:en, SequenceMatcher >= 0.85 or
  whole-word containment (>= 5 chars), within 150 m, best candidate.
  - Match rate 562/960 = 59%: dine 104/185, cafes 49/88, markets 29/54, culture 244/307.
  - Precision: 30 of 30 sampled matches correct. Near-misses at 0.60-0.85 hold real matches
    ("Maeyaa"/"Mae-Ya", "Naka Weekend Market"/"Naka Market") AND wrong ones ("Friendly Bar"/
    "Kalae Bar", "Central Plaza"/"Central Udon"): loosen only with fixtures for both kinds.
  - Detail is a FOOD signal: 83/104 matched dine carry >= 1 detail tag; culture 73/244 (temples
    are mapped bare). Signal A already covers culture.
  - FLAW to fix in the design: chains score high ("Hard Rock Cafe" = 5 tags) because brands are
    mapped from brand data, not by locals. Drop `brand`/`operator` from the count and consider
    them a negative; consider a local-script name (`name` in Thai script, `name:th`) as the
    stronger "mapped by locals" marker.
  - Ceiling = coordinates: only 629 of TH's 1,337 food spots have lat/lon, so expect ~350 food
    spots scored in TH. No-coord matching (name within 10 km of the destination's spot centroid)
    was not measured.
  - Most common detail tags on matches: opening_hours, website, addr:street, cuisine,
    addr:housenumber, phone, wheelchair.
- RELIABILITY (required in the build, not optional):
  - Source = Geofabrik country extracts only; never public Overpass (measured: 32 failures in an
    hour on 3 servers, then a hard stop). Download in CI, verify against Geofabrik's published
    `.md5`, and read the extract's timestamp; reject one older than 8 days.
  - Geofabrik from this PC ran ~21 KB/s (Cloudflare 2.4 MB/s on the same line): measure the
    download time IN CI before planning the timeout. Run D as its own job or workflow so a slow
    extract cannot time out the A build.
  - A failed or stale OSM read must NEVER read as "no match": the absent-key-means-no-data rule
    would silently unscore every food spot. On failure keep last week's `osm_detail` values
    with their own `osm_as_of` date, and mark the run degraded.
  - Coverage guard, like `geocrumb_tree`'s < 10k check: if a country's matched count drops more
    than 30% against last week, treat it as an outage (keep last week's), not a real change.
  - Show freshness: `index.json` carries per-signal as-of dates; the app's credits line shows
    the OSM date.

## 4. Score and transparency

- Normalise each signal to a 0-1 percentile within (country, category), so food is ranked
  against food and Thailand against Thailand.
- Starting weights (tune against real output, then pin with fixtures): A 0.40, B 0.30, D 0.15, C 0.15.
  A missing signal is EXCLUDED and the weights renormalise. Never treat a missing value as 0;
  that would punish every spot without a Wikidata item. Same rule as the workspace's
  "a read failure must never be representable as empty".
- Contract change (edit `docs/contract.md` FIRST): add per spot
  `"ulu": 0-100 | null` and `"signals": {"local_share": 0.82, "local_views": 12400, "mentions": 14,
  "mention_url": "...", "sitelinks": 9, "osm_detail": 3}` (omit absent keys), and `"listed_by": "wikivoyage"`.
- UI (public/app.js): sort tabs become "Most local" (ulu desc, nulls last) / "Famous" (old score) /
  "Nearby". Card detail shows the evidence in plain words:
  "82% of Wikipedia lookups are in Thai · mentioned 14× on r/Thailand · Listed by Wikivoyage travellers".
  A spot with no evidence says so instead of showing a score.
- Wording rule: never write "locals love this". Show the measurement, let the user judge.

## 5. Deferred: award badges
"Tabelog Hyakumeiten (Top 100)" or "Michelin Bib Gourmand" is a fact about a restaurant, so a
badge is lower risk than a copied score, BUT only if sourced from news coverage or official
announcements, never by scraping the platform's award page. Leave until A to D ship.

## 6. Suggested order and checks
1. A only: collector + contract + `inspect_country.py` showing the top 15 "most local" per country
   for TH and VN. Eyeball that they are genuinely local-skewed before any UI work.
2. UI: "Most local" sort + evidence line. Bump `sw.js` CACHE. Verify in the pane at 375x600.
3. B, behind a missing-secret skip; fixtures for false name matches.
4. D after the licence decision.
Every misfire goes into tests with a near-miss, as `tests/test_classify.py` does now.

Model: Opus for the score design and name matching (correctness); Sonnet for the UI changes
against the updated contract, then review its output.

## 7. Still open from v1 (not this feature)
- User phone test: install to Home Screen, Saved, Nearby, offline reopen.
- East Asia (JP KR CN TW HK MO): flip `enabled` in `config/countries.json`, rebuild with
  `--cache .cache`, check JP file size and the `lang` labels.
- Batu Caves classifies as Nature (it is a temple site); fix only with a test and a near-miss.

## 8. Gotchas already paid for
- Inline `python -c`, `node -e` and heredocs containing backslashes are blocked by the workspace
  shell-guard: write a file and run it.
- A header-only change in `vercel.json` (CSP) does not reach returning visitors. Change a byte in
  `public/index.html` (`<meta name="ulu-csp">`) and bump the sw `CACHE` too.
- Check a deploy by hashing live `sw.js` against `git show HEAD:public/sw.js`, not by a 200.
- Browser pane: close stale tabs, unregister the service worker and clear caches before trusting
  a post-edit check; stub alert/confirm/prompt.

# The Everything Map

Live: https://joshgreenman1973.github.io/nyc-everything-map/

Pick any point in the five boroughs of New York City, by address or by clicking the map, and get a report on it in ten chapters: the place (neighborhood, community district, what the city's gazetteer calls the spot, hurricane zone, flooding, air quality, street trees), who represents it (every elected official, plus how its election district voted in 2024 and 2025), living here (transit, groceries, restaurants, parks, schools, hospitals, worship, arts, 311, rats), safety (CompStat, crime complaints, crashes), the tax lot and housing, what's changing (new restaurants, building filings, licenses, film shoots), landmarks and lore, the neighborhood's census numbers and ranks, two-factor comparisons, and links to news and Reddit.

The full recipe, every source and every caveat is in [`docs/methodology.html`](docs/methodology.html). This file covers how the site is built and kept current.

## How it works

The site is one static page, [`docs/index.html`](docs/index.html), on GitHub Pages. There is no server.

- **Boundary lookups run in the browser.** Seventeen boundary layers (neighborhoods, council, Congress, State Senate and Assembly, precincts, school districts and zones, sanitation, hurricane zones, historic districts, election districts, census tracts and two alternate neighborhood maps) are tested against the point with a point-in-polygon check.
- **The download comes in two waves.** A report opens once the 13 district layers, the officials list and the neighborhood table arrive (about 1.6 MB compressed). Restaurants, named places, election districts, census tracts and the other nearby lists follow at low priority (about 2.1 MB) and fill in their sections as they land. The `later()` helper in index.html handles that.
- **Boundary layers ship as TopoJSON** (`docs/data/<layer>.topo.json`): shared borders stored once, coordinates on a half-meter grid. The GeoJSON files beside them are the pipeline's working copies; the page never loads them.
- **More than 20 live feeds** are queried at click time: NYC Open Data (property, 311, crime, crashes, trees, inspections, building filings, licenses, evictions, affordable housing, film permits, sales, housing violations, flood layers, ZIP outlines), Josh's weekly CompStat scrape, Citi Bike, Wikipedia and the federal elevation service. The lower chapters load as they scroll into view.
- **Counting areas.** As the reader scrolls, the map draws the area behind the block at the reading line (the 500 meter crime circle, the precinct, the neighborhood, the ZIP code). Blocks declare it with a `data-area` attribute; see the comment above `showArea()`.

## Layout

- `docs/` is the deployed site: `index.html`, `methodology.html`, `og.png` (the link-preview card) and `data/`.
- `data/raw/` holds downloaded sources (not committed). `data/out/` holds the simplified boundary layers before they are copied into `docs/data/`.
- `scripts/`:
  - `build_data.sh` runs the whole pipeline, end to end.
  - `extract_officials.py` builds `officials.json`. Citywide and borough officials are entered by hand in this file.
  - `extract_demographics.py` builds the old ACS 2016-2020 base; `refresh_acs2024.py` then rebuilds every neighborhood figure on ACS 2020-2024.
  - `bake_extras.py` bakes the point files and extras: schools and school quality, landmarks, air quality, heat vulnerability, bus stops, election results (`elections()`, which ends by merging the 2024 presidential results in `pres24()`), the "Two factors" indicators (`nta_indicators()`), hospitals, The Neighborhoods links.
  - `bake_rankings.py` copies neighborhood ranks from the sibling `nyc-nta-rankings` project (a local clone next to this one).
  - `refresh_askingrents.py` rebakes StreetEasy median asking rents.
  - `build_restaurants.py` / `refresh_restaurants.py` and `build_commonplace.py` rebuild the restaurant and named-place files.
  - `validate_lookups.py` is the accuracy gate: it checks the simplified boundaries against live police and 311 records and blocks a deploy above 1% simplification error.
  - `build_topo.mjs` writes the TopoJSON copies and fails if the conversion moved any lookup that isn't on a boundary line.
- `.github/workflows/` runs two monthly jobs on GitHub, so they don't need the laptop: restaurants on the 1st, CommonPlace named places on the 2nd. Each commits only if the data changed.

## Refreshing the data

```bash
export CENSUS_API_KEY=...   # free key from api.census.gov
bash scripts/build_data.sh
```

Before running it, recheck the hand-entered citywide and borough officials in `scripts/extract_officials.py` (mayor, public advocate, comptroller, borough presidents, district attorneys). The pipeline asserts a named officeholder for all 51 council, 13 congressional, 28 State Senate and 65 Assembly districts.

After any change to `docs/data/`, bump `DATA_VERSION` in `docs/index.html` so browsers drop their cached copies.

Things that bite:

- The "Two factors" eviction and new-building windows are frozen constants at the top of `nta_indicators()` in `bake_extras.py`. Move them on purpose, and update the methodology page when you do.
- New-building counts use DOB NOW initial filings only (job numbers ending `-I1`). Every job also has a row per amendment and work type, so counting rows overstates construction about eightfold. The live panel and the baked indicator both follow this rule.
- The Board of Elections CSV writes tallies over 999 with a comma ("1,020"). `pres24()` handles it; a June 2026 one-off parse didn't, and 37 districts were wrong until October 2026.
- Some city feeds stall for months (business licenses, film permits, crashes), and the crime complaint file is quarterly. The page checks each feed's newest record and says when it lags; nothing to fix on this end.
- Hospital emergency-room status is a hand-checked list in `bake_extras.py hospitals()`. Emergency departments open and close.
- The languages block (`bake_languages.py`) reads City Planning's NYC Language Explorer layers on ArcGIS Online. City Planning names them by release (`PUMAData_Language_Mar2026`), so a new edition will likely live at a new URL: find it in the Explorer's app config (`arcgis.com/sharing/rest/content/items/0da08a1596574ec78cbaa5bef6a04b3e/data?f=json`) and update the constants. The long table's district numbers have errors; the script joins on names.

## Refresh calendar

| When | What |
|---|---|
| Monthly (automatic) | Restaurants (1st) and CommonPlace named places (2nd), by GitHub Actions |
| After the Nov. 3, 2026 election | Every State Senate, Assembly and House seat is on the ballot. Nothing on the map changes until the winners take office, but line up the new names then |
| December 2026 | The Census Bureau releases the ACS 2021-2025 five-year estimates (usually in December): rerun `refresh_acs2024.py` against the new vintage and update the vintage labels |
| Late 2026 | Once the Board of Elections certifies the November results, the governor's race by election district could join the 2024 and 2025 rows |
| Jan. 1, 2027 | The new State Legislature takes office, including a senator for District 12 (vacant since Aug. 7, 2026). Update `officials.json`, the "verified" date in the representation chapter and the methodology page |
| Jan. 3, 2027 | The new Congress takes office; recheck the House members |
| Weekly, optional | `bake_extras.py neighborhoods_project()` picks up new posts from Rob Stephenson's The Neighborhoods |
| When City Planning updates the Language Explorer | Probably after the ACS 2021-2025 microdata come out (usually January): rerun `bake_languages.py` and `build_topo.mjs`, update the vintage in the block's note and the methodology page |
| Each refresh | Recheck the hospital emergency-room list and the feed lag notes |

## Serving locally

```bash
python3 -m http.server 8201 --directory docs
```

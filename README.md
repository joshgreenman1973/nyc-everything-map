# The Everything Map

Pick any point in the five boroughs of New York City — type an address or click the map — and get a full report on it: neighborhood, community district, every elected official who represents it, police precinct, sanitation district, school district and zoned schools, hurricane evacuation zone, historic district status, live property records (zoning, year built, owner, floor area ratio), live 311 and crime activity nearby, restaurant inspection grades, nearest subway stations and an American Community Survey demographic profile compared against citywide figures.

A single static page; all boundary lookups run in the browser, four NYC Open Data feeds are queried live at click time.

## Structure

- `docs/` — the deployable site (`index.html`, `methodology.html`, `data/`)
- `data/raw/` — downloaded source files (not deployed)
- `data/out/` — simplified boundary layers (copied into `docs/data/`)
- `scripts/build_data.sh` — full data pipeline, end to end
- `scripts/validate_lookups.py` — accuracy gate, run before any deploy

## Refreshing the data

```bash
export CENSUS_API_KEY=...   # free key from api.census.gov
bash scripts/build_data.sh
```

Before rerunning, re-verify the hand-entered citywide and borough officials in `scripts/extract_officials.py` (mayor, public advocate, comptroller, borough presidents, district attorneys) — everything else updates automatically. The pipeline asserts full officeholder coverage for all 51 council, 13 congressional, 28 State Senate and 65 Assembly districts, and the validator blocks deployment if boundary simplification errors exceed 1% against live city records.

Full sources, accuracy methodology and known limitations: `docs/methodology.html`.

## Serving locally

```bash
python3 -m http.server 8201 --directory docs
```

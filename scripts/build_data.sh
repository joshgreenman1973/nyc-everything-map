#!/bin/bash
# The Everything Map — data pipeline
# Rebuilds everything in docs/data/ from primary sources.
# Run from the project root: bash scripts/build_data.sh
# Requires: curl, python3 (openpyxl, shapely), node (for npx mapshaper)
# CENSUS_API_KEY must be set in the environment for the comparison-values step.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/raw data/out docs/data

# ---------------------------------------------------------------- 1. boundaries
# Dataset IDs are documented in docs/methodology.html
cd data/raw
declare -a LAYERS=(
  "nta:9nt8-h7nd" "community_districts:5crt-au7u" "council:872g-cjhh"
  "precincts:y76i-bdw7" "school_districts:8ugf-3d8u" "es_zones:cmjf-yawu"
  "ms_zones:t26j-jbq7" "dsny:i6mn-amj2" "congress:j3u5-usz2"
  "assembly:5yfv-9hkp" "senate:afns-vxeu" "hurricane:epne-qv9x" "historic:skyk-mpzq"
)
for pair in "${LAYERS[@]}"; do
  name="${pair%%:*}"; id="${pair##*:}"
  curl -sL "https://data.cityofnewyork.us/api/geospatial/${id}?method=export&format=GeoJSON" -o "${name}.geojson"
done

# Simplify (2 m weighted Visvalingam — validated at 99.8% agreement vs city records)
declare -a SPECS=(
  "nta:nta2020,ntaname,boroname,ntatype,cdtaname:nta"
  "community_districts:boro_cd:cd" "council:coundist:council"
  "precincts:precinct:precinct" "school_districts:schooldist:schooldist"
  "es_zones:dbn,label:eszones" "ms_zones:dbn,label:mszones"
  "dsny:district:dsny" "congress:cong_dist:congress"
  "assembly:assembly_district:assembly" "senate:st_sen_dist:senate"
  "hurricane:hurricane_:hurricane"
)
for spec in "${SPECS[@]}"; do
  src="${spec%%:*}"; rest="${spec#*:}"; fields="${rest%%:*}"; out="${rest##*:}"
  npx -y mapshaper "${src}.geojson" -simplify weighted interval=2 keep-shapes \
    -filter-fields "$fields" -o force precision=0.000001 "../out/${out}.json"
done
# historic districts: designated only, keep name + LP number
npx -y mapshaper historic.geojson -filter '"DESIGNATED" == status_of_' \
  -simplify weighted interval=2 keep-shapes -filter-fields area_name,lp_number \
  -o force precision=0.000001 ../out/historic.json

# ---------------------------------------------------------------- 2. officials
curl -sL "https://unitedstates.github.io/congress-legislators/legislators-current.json" -o legislators.json
curl -sL "https://data.openstates.org/people/current/ny.csv" -o ny_legislators.csv
curl -sL "https://council.nyc.gov/districts/" -o council_page.html
python3 ../../scripts/extract_officials.py   # writes officials.json
# NOTE: citywide + borough officials (mayor, public advocate, comptroller,
# borough presidents, district attorneys) are hand-verified constants inside
# extract_officials.py — re-verify them against official sources when refreshing.

# ---------------------------------------------------------------- 3. demographics
for f in demo econ soc hous; do
  curl -s -A "Mozilla/5.0" -L \
    "https://www1.nyc.gov/assets/planning/download/office/planning-level/nyc-population/acs/${f}_20162020_acs5yr_nta.xlsx" \
    -o ${f}_nta.xlsx
done
python3 ../../scripts/extract_demographics.py  # writes nta_demographics.json + compare_geos.json (needs CENSUS_API_KEY)

# ---------------------------------------------------------------- 4. subway
curl -s "https://data.ny.gov/resource/39hk-dx4f.json?\$select=stop_name,daytime_routes,gtfs_latitude,gtfs_longitude&\$limit=600" -o subway_raw.json
python3 - <<'PY'
import json
d = json.load(open('subway_raw.json'))
out = [[s['stop_name'], s['daytime_routes'], round(float(s['gtfs_latitude']),5), round(float(s['gtfs_longitude']),5)] for s in d]
json.dump(out, open('subway.json','w'), ensure_ascii=False)
PY

# ------------------------------------------------- 4b. schools, landmarks, environment
python3 ../../scripts/bake_extras.py

# ---------------------------------------------------------------- 5. publish
cd ../..
cp data/out/*.json docs/data/
cp data/raw/officials.json data/raw/nta_demographics.json data/raw/compare_geos.json data/raw/subway.json docs/data/

# ---------------------------------------------------------------- 6. validate
python3 scripts/validate_lookups.py
echo "Done. Review validation output above before deploying."

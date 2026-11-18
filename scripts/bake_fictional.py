#!/usr/bin/env python3
"""Bake docs/data/fictional.json from the Fictional New Yorkers at home map.

Source: https://joshgreenman1973.github.io/nyc-fictional-homes/ (repo
joshgreenman1973/nyc-fictional-homes). Reads the published data/homes.json, so the
Everything Map shows exactly what that map shows. Rerun after the homes map is
rebuilt, then bump DATA_VERSION in docs/index.html.

Each row: [id, character, work, medium, creator, work_year, lat, lon, radius_m,
precision, kind]. The id is the homes map's record id, which it opens from #<id>.
"""
import json, urllib.request

SRC = 'https://joshgreenman1973.github.io/nyc-fictional-homes/data/homes.json'
OUT = 'docs/data/fictional.json'
PRECISIONS = {'address_in_work', 'building_in_work', 'creator_stated', 'screen_exterior',
              'block_inferred', 'neighborhood', 'invented'}
MEDIA = {'book', 'theater', 'film', 'tv', 'comics'}

rows = json.load(urllib.request.urlopen(SRC))
out = []
for r in rows:
    # the homes map shows only records with a known precision and medium; match it
    if r.get('outside_nyc') or r['precision'] not in PRECISIONS or r['medium'] not in MEDIA:
        continue
    out.append([r['id'], r['character'], r['work'], r['medium'], r.get('creator') or '',
                r.get('work_year'), round(r['lat'], 6), round(r['lon'], 6),
                r.get('radius_m') or 0, r['precision'], r['kind']])
assert len(out) > 700, f'only {len(out)} records; the source may have changed shape'
json.dump(out, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))
print(f'fictional: {len(out)} of {len(rows)} records written')

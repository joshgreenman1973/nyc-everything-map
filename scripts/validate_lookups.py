#!/usr/bin/env python3
"""Validate the simplified boundary files against city records that carry both
coordinates and an official district label.

- Police precincts: NYPD complaint records (addr_pct_cd vs point-in-polygon)
- Community districts: 311 records (community_board vs point-in-polygon)

Run from the project root. Mismatches are split into label disagreements
(the city record disagrees with the city's own boundary file — not our error)
and simplification errors (the raw boundary file disagrees with our simplified
one — our error). Simplification errors above 1% should block a deploy.
"""
import json, urllib.request, urllib.parse, datetime, sys
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

def fetch(base, params):
    return json.load(urllib.request.urlopen(base + '?' + urllib.parse.urlencode(params)))

def build(path, prop):
    feats = json.load(open(path))['features']
    geoms = [shape(f['geometry']) for f in feats]
    vals = [f['properties'][prop] for f in feats]
    return STRtree(geoms), geoms, vals

def lookup(tree, geoms, vals, lat, lng):
    p = Point(lng, lat)
    for i in tree.query(p):
        if geoms[i].covers(p):
            return vals[i]
    return None

def run(name, simp_path, raw_path, prop, sample_fn, n_offsets=(0, 12345, 40000)):
    tree, geoms, vals = build(simp_path, prop)
    raw = [(shape(f['geometry']), f['properties'][prop])
           for f in json.load(open(raw_path))['features']]
    ok = label_miss = simp_miss = 0
    for off in n_offsets:
        for lat, lng, truth in sample_fn(off):
            got = lookup(tree, geoms, vals, lat, lng)
            got = int(got) if got is not None else None
            if got == truth:
                ok += 1
                continue
            p = Point(lng, lat)
            rawhit = [int(v) for g, v in raw if g.covers(p)]
            if rawhit and rawhit[0] != got:
                simp_miss += 1
            else:
                label_miss += 1
    total = ok + label_miss + simp_miss
    rate = simp_miss / total * 100
    print(f'{name}: n={total}, {ok} agree, {label_miss} label disagreements, '
          f'{simp_miss} simplification errors ({rate:.2f}%)')
    return rate

def precinct_sample(off):
    rows = fetch('https://data.cityofnewyork.us/resource/5uac-w243.json',
                 {'$select': 'addr_pct_cd,latitude,longitude',
                  '$where': 'latitude IS NOT NULL', '$limit': 300, '$offset': off})
    for r in rows:
        try:
            yield float(r['latitude']), float(r['longitude']), int(r['addr_pct_cd'])
        except (KeyError, ValueError):
            continue

def cd_sample(off):
    since = (datetime.date.today() - datetime.timedelta(days=40)).isoformat()
    rows = fetch('https://data.cityofnewyork.us/resource/erm2-nwe9.json',
                 {'$select': 'community_board,borough,latitude,longitude',
                  '$where': f"latitude IS NOT NULL AND created_date>'{since}T00:00:00'",
                  '$limit': 300, '$offset': off})
    boro = {'MANHATTAN': 1, 'BRONX': 2, 'BROOKLYN': 3, 'QUEENS': 4, 'STATEN ISLAND': 5}
    for r in rows:
        parts = r.get('community_board', '').split()
        if not parts or not parts[0].isdigit() or r.get('borough') not in boro:
            continue
        n = int(parts[0])
        if n == 0 or n >= 26:   # "Unspecified" pseudo-boards
            continue
        yield float(r['latitude']), float(r['longitude']), boro[r['borough']] * 100 + n

if __name__ == '__main__':
    r1 = run('precincts', 'docs/data/precinct.json', 'data/raw/precincts.geojson',
             'precinct', precinct_sample)
    r2 = run('community districts', 'docs/data/cd.json', 'data/raw/community_districts.geojson',
             'boro_cd', cd_sample)
    if max(r1, r2) > 1.0:
        sys.exit('Simplification error rate above 1% — do not deploy')
    print('Validation passed.')

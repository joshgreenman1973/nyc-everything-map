#!/usr/bin/env python3
"""Bake the v2 static files: schools, landmarks, air quality, heat
vulnerability, density fields and the city outline mask.

Run from data/raw/ after build_data.sh's earlier steps (it needs
nta.geojson and nta_demographics.json in place). Writes directly into
docs/data/. See docs/methodology.html for dataset documentation.
"""
import json, urllib.request, urllib.parse, subprocess, os

OUT = '../../docs/data'

def soda(dataset, params):
    u = f'https://data.cityofnewyork.us/resource/{dataset}.json?' + urllib.parse.urlencode(params)
    return json.load(urllib.request.urlopen(u))

def schools():
    locs = soda('a3nt-yts4', {'$select': 'ats_code,loc_name,the_geom', '$limit': 3000})
    enr = {r['dbn']: r for r in soda('c7ru-d68s', {
        '$select': 'dbn,total_enrollment,grade_3k,grade_pk_half_day_full_day,grade_k,grade_1,grade_2,grade_3,grade_4,grade_5,grade_6,grade_7,grade_8,grade_9,grade_10,grade_11,grade_12',
        'year': '2021-22', '$limit': 3000})}
    grades = [('grade_3k','3K'),('grade_pk_half_day_full_day','PK'),('grade_k','K')] + \
             [(f'grade_{i}', str(i)) for i in range(1, 13)]
    out = []
    for s in locs:
        g = s.get('the_geom')
        if not g:
            continue
        lng, lat = g['coordinates']
        e = enr.get(s['ats_code'])
        span, total = '', None
        if e:
            total = int(e.get('total_enrollment') or 0)
            served = [lab for col, lab in grades if int(e.get(col) or 0) > 0]
            if served:
                span = served[0] + ('-' + served[-1] if len(served) > 1 else '')
        out.append([s['ats_code'], s['loc_name'], round(lat, 5), round(lng, 5), total, span])
    json.dump(out, open(f'{OUT}/schools.json', 'w'), ensure_ascii=False)
    print(len(out), 'schools')

def landmarks():
    from shapely.geometry import shape
    url = 'https://data.cityofnewyork.us/api/geospatial/buis-pvji?method=export&format=GeoJSON'
    d = json.load(urllib.request.urlopen(url))
    seen = {}
    for f in d['features']:
        p = f['properties']
        if p.get('lpc_sitest') != 'Designated' or not p.get('lpc_name') or p['lpc_lpnumb'] in seen:
            continue
        c = shape(f['geometry']).representative_point()
        seen[p['lpc_lpnumb']] = [p['lpc_name'], round(c.y, 5), round(c.x, 5),
                                 (p.get('desdate') or '')[:4], p.get('url_report') or '']
    json.dump(list(seen.values()), open(f'{OUT}/landmarks.json', 'w'), ensure_ascii=False)
    print(len(seen), 'landmarks')

def airquality(year=2023):
    out = {'cd': {}, 'city': {}}
    for name, key in [('Fine particles (PM 2.5)', 'pm25'), ('Nitrogen dioxide (NO2)', 'no2')]:
        for r in soda('c3uy-2p5r', {'$select': 'geo_join_id,data_value',
                '$where': f"name='{name}' AND geo_type_name='CD' AND time_period='Annual Average {year}'", '$limit': 100}):
            out['cd'].setdefault(r['geo_join_id'], {})[key] = round(float(r['data_value']), 1)
        c = soda('c3uy-2p5r', {'$select': 'data_value',
                '$where': f"name='{name}' AND geo_type_name='Citywide' AND time_period='Annual Average {year}'", '$limit': 5})
        out['city'][key] = round(float(c[0]['data_value']), 1)
    json.dump(out, open(f'{OUT}/airquality.json', 'w'))
    print(len(out['cd']), 'community districts with air quality')

def hvi():
    d = {r['zcta20']: int(r['hvi']) for r in soda('4mhf-duep', {'$limit': 300})}
    json.dump(d, open(f'{OUT}/hvi.json', 'w'))
    print(len(d), 'ZIPs with heat vulnerability')

def density_fields():
    """Add land area, density and derived age shares to nta_demographics."""
    SQFT_PER_SQMI = 27878400
    nta = json.load(open('nta.geojson'))
    demo = json.load(open('nta_demographics.json'))
    for f in nta['features']:
        p = f['properties']
        if p['nta2020'] in demo:
            demo[p['nta2020']]['land_sqmi'] = round(float(p['shape_area']) / SQFT_PER_SQMI, 4)
    for d in demo.values():
        pop = d.get('pop')
        if pop and d.get('land_sqmi'):
            d['density'] = round(pop / d['land_sqmi'])
            for src, dst in [('under18', 'under18_pct_calc'), ('age65pl', 'senior_pct_calc')]:
                if d.get(src) is not None and src + '_pct' not in d:
                    d[dst] = round(d[src] / pop * 100, 1)
    json.dump(demo, open('nta_demographics.json', 'w'))
    json.dump(demo, open(f'{OUT}/nta_demographics.json', 'w'))
    print('density fields added')
    # NOTE: citywide/borough density + under18/senior comparison values are
    # added to compare_geos.json by extract_demographics.py's census pull plus
    # DP05_0019PE (under 18) and DP05_0024PE (65 and over); see git history.

def cityoutline():
    subprocess.run(['npx', '-y', 'mapshaper', 'nta.geojson', '-dissolve',
                    '-simplify', 'weighted', 'interval=30', 'keep-shapes',
                    '-o', 'force', 'precision=0.0001', 'format=geojson', f'{OUT}/cityoutline.json'], check=True)
    d = json.load(open(f'{OUT}/cityoutline.json'))
    if d.get('type') == 'GeometryCollection':
        d = {'type': 'FeatureCollection',
             'features': [{'type': 'Feature', 'properties': {}, 'geometry': g} for g in d['geometries']]}
        json.dump(d, open(f'{OUT}/cityoutline.json', 'w'))
    print('city outline written')

def school_quality():
    """Append 2023 ELA/math proficiency and 4-year grad rate to schools.json."""
    def numify(v):
        try: return round(float(v), 1)
        except (TypeError, ValueError): return None
    w = "year='2023' AND report_category='School' AND grade='All Grades'"
    ela = {r['geographic_subdivision']: numify(r.get('level_3_4_1'))
           for r in soda('iebs-5yhr', {'$select': 'geographic_subdivision,level_3_4_1',
               '$where': w + " AND category='All Students'", '$limit': 3000})}
    math = {r['geographic_division']: numify(r.get('pct_level_3_and_4'))
            for r in soda('74kb-55u9', {'$select': 'geographic_division,pct_level_3_and_4',
                '$where': w.replace('category', 'student_category') + " AND student_category='All Students'", '$limit': 3000})}
    grad = {r['geographic_subdivision']: numify(r.get('grads_1'))
            for r in soda('mjm3-8dw8', {'$select': 'geographic_subdivision,cohort,grads_1',
                '$where': "cohort_year='2019' AND report_category='School' AND category='All Students'", '$limit': 6000})
            if r.get('cohort') == '4 year June'}
    schools = [s[:6] for s in json.load(open(f'{OUT}/schools.json'))]
    for s in schools:
        s.extend([ela.get(s[0]), math.get(s[0]), grad.get(s[0])])
    json.dump(schools, open(f'{OUT}/schools.json', 'w'), ensure_ascii=False)
    print('school quality metrics appended')

def busstops():
    rows = json.load(urllib.request.urlopen(
        'https://data.ny.gov/resource/2ucp-7wg5.json?' + urllib.parse.urlencode(
            {'$select': 'stop_name,route_short_name,latitude,longitude',
             '$where': "in_effect='true' AND revenue_stop='1'", '$limit': 25000})))
    stops = {}
    for r in rows:
        try: lat, lng = round(float(r['latitude']), 5), round(float(r['longitude']), 5)
        except (TypeError, ValueError, KeyError): continue
        s = stops.setdefault((r['stop_name'], round(lat, 4), round(lng, 4)),
                             {'name': r['stop_name'], 'lat': lat, 'lng': lng, 'routes': set()})
        s['routes'].add(r['route_short_name'])
    out = [[s['name'], ' '.join(sorted(s['routes'])), s['lat'], s['lng']] for s in stops.values()]
    json.dump(out, open(f'{OUT}/busstops.json', 'w'), ensure_ascii=False)
    print(len(out), 'bus stops')

def elections():
    """Merge the election archive's 2025 general + primary ED results and simplify.
    Requires a local clone of nyc-election-archive next to this project."""
    base = '/Users/joshgreenman/Experiments/nyc-election-archive/docs'
    gen = json.load(open(f'{base}/results_2025_general_mayor.geojson'))
    pri = {f['properties']['ed']: f['properties']
           for f in json.load(open(f'{base}/results_2025.geojson'))['features']}
    feats = []
    for f in gen['features']:
        g = f['properties']
        props = {'ed': g['ed'], 'g_win': g.get('final_winner'), 'g_pct': g.get('final_winner_pct'),
                 'g_ballots': g.get('ballots'), 'g_mamdani': g.get('fc_mamdani'),
                 'g_cuomo': g.get('fc_cuomo'), 'g_sliwa': g.get('fc_sliwa')}
        p = pri.get(g['ed'])
        if p:
            props.update({'p_win': p.get('final_winner'), 'p_pct': p.get('final_winner_pct'),
                          'p_ballots': p.get('ballots'), 'p_mamdani': p.get('fr_mamdani'),
                          'p_cuomo': p.get('fr_cuomo')})
        feats.append({'type': 'Feature', 'properties': props, 'geometry': f['geometry']})
    json.dump({'type': 'FeatureCollection', 'features': feats}, open('elections_merged.geojson', 'w'))
    subprocess.run(['npx', '-y', 'mapshaper', 'elections_merged.geojson',
                    '-simplify', 'weighted', 'interval=6', 'keep-shapes',
                    '-o', 'force', 'precision=0.00001', 'format=geojson', f'{OUT}/elections.json'], check=True)
    d = json.load(open(f'{OUT}/elections.json'))
    d['features'] = [f for f in d['features'] if f.get('geometry')]
    json.dump(d, open(f'{OUT}/elections.json', 'w'))
    print(len(d['features']), 'election districts')

if __name__ == '__main__':
    schools(); school_quality(); landmarks(); airquality(); hvi(); density_fields(); cityoutline(); busstops(); elections()

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

def airquality(year=2024):
    # in 2026 the dataset relabeled time_period from 'Annual Average 2023' to plain '2024' and split each year into
    # Annual/Summer/Winter mean rows, so the measure filter is now required; match either label
    out = {'cd': {}, 'city': {}}
    for name, key in [('Fine particles (PM 2.5)', 'pm25'), ('Nitrogen dioxide (NO2)', 'no2')]:
        for r in soda('c3uy-2p5r', {'$select': 'geo_join_id,data_value',
                '$where': f"name='{name}' AND geo_type_name='CD' AND measure='Annual mean' AND time_period in ('{year}','Annual Average {year}')", '$limit': 100}):
            out['cd'].setdefault(r['geo_join_id'], {})[key] = round(float(r['data_value']), 1)
        c = soda('c3uy-2p5r', {'$select': 'data_value',
                '$where': f"name='{name}' AND geo_type_name='Citywide' AND measure='Annual mean' AND time_period in ('{year}','Annual Average {year}')", '$limit': 5})
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
    """Merge the election archive's 2025 general + primary ED results and simplify,
    then attach the 2024 presidential fields (pres24 below).
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
    pres24()

PRES24_CSV = ('https://vote.nyc/sites/default/files/pdf/election_results/2024/20241105General%20Election/'
              '00000100000Citywide%20President%20Vice%20President%20Citywide%20EDLevel.csv')

def pres24():
    """2024 presidential by election district, merged into elections.json as
    x_harris / x_trump (percent of the two-party vote) and x_total (Harris +
    Trump votes; write-ins and blanks excluded), keyed on AD*1000+ED.
    Source: the Board of Elections' certified citywide ED-level CSV (PRES24_CSV),
    cached as pres2024.csv. Fusion lines are summed: Working Families into
    Harris, Conservative into Trump. Tallies of 1,000 or more carry a thousands
    comma ("1,020"); the June 2026 one-off parse dropped those, which zeroed the
    Democratic or Republican line in 37 districts.
    The board counted 232 small districts jointly with a neighbor (EDAD Status
    'COMBINED INTO ED/AD', no tally of their own). A district with no tally of
    its own takes its partner's joint tally and records the partner in x_joint.
    Districts still unresolved get no x_ fields; the app says so."""
    import csv, re
    if not os.path.exists('pres2024.csv'):
        req = urllib.request.Request(PRES24_CSV, headers={'User-Agent': 'Mozilla/5.0'})
        open('pres2024.csv', 'wb').write(urllib.request.urlopen(req).read())
    tally, combined = {}, {}
    for r in csv.reader(open('pres2024.csv', encoding='utf-8-sig')):
        v = r[11:] if len(r) == 22 else r  # the BOE file repeats the 11 header names on every row
        if v[0] == 'AD':
            continue
        ed = int(v[0]) * 1000 + int(v[1])
        m = re.match(r'COMBINED INTO (\d+)/(\d+)', v[3])
        if m:
            combined[ed] = int(m.group(2)) * 1000 + int(m.group(1))
            continue
        n = int(v[10].replace(',', '') or 0)
        t = tally.setdefault(ed, [0, 0])
        if v[9].startswith('Kamala D. Harris'):
            t[0] += n
        elif v[9].startswith('Donald J. Trump'):
            t[1] += n
    tally = {ed: t for ed, t in tally.items() if sum(t)}
    d = json.load(open(f'{OUT}/elections.json'))
    n_own = n_joint = 0
    for f in d['features']:
        p = f['properties']
        for k in ('x_harris', 'x_trump', 'x_total', 'x_joint'):
            p.pop(k, None)
        src = p['ed'] if p['ed'] in tally else combined.get(p['ed'])
        if src not in tally:
            continue
        h, t = tally[src]
        p.update({'x_harris': round(h / (h + t) * 100, 1), 'x_trump': round(t / (h + t) * 100, 1), 'x_total': h + t})
        if src != p['ed']:
            p['x_joint'] = src
            n_joint += 1
        else:
            n_own += 1
    json.dump(d, open(f'{OUT}/elections.json', 'w'))
    H, T = sum(t[0] for t in tally.values()), sum(t[1] for t in tally.values())
    print(n_own, 'districts with a 2024 presidential tally,', n_joint, 'more counted jointly;',
          f'citywide two-party Harris {H / (H + T) * 100:.1f}')

def neighborhoods_project():
    """Map Rob Stephenson's The Neighborhoods Substack posts to neighborhoods.
    He publishes weekly; rerun to pick up new profiles."""
    import re, unicodedata
    posts, offset = [], 0
    while offset <= 600:
        req = urllib.request.Request(
            f'https://theneighborhoods.substack.com/api/v1/archive?sort=new&limit=50&offset={offset}',
            headers={'User-Agent': 'Mozilla/5.0'})
        batch = json.load(urllib.request.urlopen(req))
        if not batch: break
        posts.extend(batch); offset += 50
    boros = {'manhattan': 'Manhattan', 'brooklyn': 'Brooklyn', 'queens': 'Queens',
             'the bronx': 'Bronx', 'bronx': 'Bronx', 'staten island': 'Staten Island'}
    def norm(s):
        s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
        return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()
    out = {}
    for p in posts:  # newest first, so the oldest (Part I) wins on overwrite
        if p.get('audience') != 'everyone' or not p.get('title'): continue
        m = re.match(r'^(.*?)\s*[-–—]\s*(Manhattan|Brooklyn|Queens|The Bronx|Bronx|Staten Island)\s*(?:\(Part\s+[IVX\d]+\))?\s*$',
                     p['title'].strip(), re.I)
        if not m: continue
        name = m.group(1).strip()
        out.setdefault(boros[m.group(2).lower()], {})[norm(name)] = [p['canonical_url'], name]
    json.dump(out, open(f'{OUT}/neighborhoods_project.json', 'w'), ensure_ascii=False)
    print(sum(len(v) for v in out.values()), 'neighborhood profiles mapped')

def hospitals():
    """Campus-level NYC hospitals + freestanding emergency departments from the
    state health department facility file (vn5v-hh5r on health.data.ny.gov),
    which lists every licensed site separately — unlike the federal CMS file,
    where multi-campus systems collapse into one entry (NYP Brooklyn Methodist,
    NYU Langone Brooklyn etc. disappear). Per-campus emergency-room status is a
    hand-verified classification (NO_ER below) — re-verify when rerunning,
    since emergency departments do open and close."""
    q = urllib.parse.urlencode({
        '$select': 'facility_name,description,latitude,longitude',
        '$where': "county in('New York','Kings','Queens','Bronx','Richmond') AND "
                  "(fac_desc_short='HOSP' OR description='Off-Campus Emergency Department')",
        '$limit': 200})
    rows = json.load(urllib.request.urlopen('https://health.data.ny.gov/resource/vn5v-hh5r.json?' + q))
    # name prefix -> note (anything matched here is flagged as having no general ER)
    NO_ER = {
        'Hospital for Special Surgery': 'orthopedic specialty hospital',
        'New York Eye and Ear': 'has a walk-in eye and ear emergency clinic only',
        'Memorial Hospital for Cancer': 'cancer center; urgent care for its patients only',
        'David H. Koch Center For Cancer': 'outpatient cancer center',
        'New York-Presbyterian David H. Koch': 'outpatient surgery center',
        'Rockefeller University Hospital': 'clinical research hospital',
        'Calvary Hospital': 'palliative and hospice care',
        'Henry J. Carter': 'long-term specialty care',
        'Kingsbrook Jewish': 'post-acute campus; its emergency department closed in 2021',
        'Mount Sinai -  Behavioral': 'behavioral health',
        "Montefiore Einstein Children's Center": "children's mental health",
        'NYU Langone Hospital - Joseph S.': 'ambulatory care',
        'NYU Langone Orthopedic': 'orthopedic specialty; no general emergency room',
        'RUMC-Bayley Seton': 'behavioral health and outpatient campus',
    }
    RENAME = {
        'Memorial Hospital for Cancer and Allied Diseases': 'Memorial Sloan Kettering Cancer Center',
        'Northwell Greenwich Village Hospital': 'Lenox Health Greenwich Village (freestanding ER)',
        'Maimonides Health Bay Ridge Emergency Department': 'Maimonides Bay Ridge (freestanding ER)',
        'Montefiore Med Center - Jack D Weiler Hosp of A Einstein College Div': 'Montefiore Weiler Hospital',
        'Montefiore Medical Center - Henry & Lucy Moses Div': 'Montefiore Moses Campus',
        'Montefiore Medical Center - Montefiore Westchester Square': 'Montefiore Westchester Square (freestanding ER)',
        'Montefiore Medical Center-Wakefield Hospital': 'Montefiore Wakefield Hospital',
        'New York-Presbyterian Hospital - Columbia Presbyterian Center': 'NewYork-Presbyterian / Columbia',
        'New York-Presbyterian Hospital - New York Weill Cornell Center': 'NewYork-Presbyterian / Weill Cornell',
        'New York-Presbyterian Hospital - Allen Hospital': 'NewYork-Presbyterian Allen Hospital',
        'Mount Sinai Hospital - Mount Sinai Hospital of Queens': 'Mount Sinai Queens',
        'University Hospital of Brooklyn': 'SUNY Downstate University Hospital',
        'South Brooklyn Health': 'South Brooklyn Health (Coney Island Hospital)',
        'SBH Health System': 'St. Barnabas Hospital (SBH)',
        'St Johns Episcopal Hospital So Shore': "St. John's Episcopal Hospital",
        'Staten Island University Hosp-North': 'Staten Island University Hospital - North',
        "Staten Island University Hospital Prince's Bay": "Staten Island University Hospital - Prince's Bay",
    }
    seen, out = set(), []
    for r in rows:
        if not r.get('latitude'): continue
        name = r['facility_name']
        lat, lng = round(float(r['latitude']), 5), round(float(r['longitude']), 5)
        key = (name, round(lat, 3), round(lng, 3))
        if key in seen: continue
        seen.add(key)
        note = next((v for k, v in NO_ER.items() if name.startswith(k)), None)
        disp = RENAME.get(name, name)
        if 'freestanding ER' in disp:
            note_out, er = 'freestanding emergency department, no inpatient beds', 1
        else:
            note_out, er = (note or '', 0 if note else 1)
        out.append([disp, lat, lng, er, note_out])
    out.sort(key=lambda x: x[0])
    json.dump(out, open(f'{OUT}/hospitals.json', 'w'), ensure_ascii=False)
    print(len(out), 'hospital campuses,', sum(1 for h in out if h[3]), 'with an emergency room')

def lightcrime():
    """Compact lookup of the bivariate lighting-crime map's hex classes.
    Source: the live hexes file behind vitalcity-nyc.github.io/bivariate-lighting-crime."""
    d = json.load(urllib.request.urlopen('https://vitalcity-nyc.github.io/bivariate-lighting-crime/hexes.geojson'))
    hexes = {}
    for f in d['features']:
        p = f['properties']
        hexes[p['h']] = [p.get('light_n', 0), p.get('crime_n', 0), p.get('crime_night_n', 0),
                         p.get('light_t', 0), p.get('crime_t', 0), p.get('crime_night_t', 0)]
    meta = d['meta']
    json.dump({'meta': {'crime_window': [meta['crime']['first_date'], meta['crime']['last_date']],
                        'outage_window': [meta['outages']['first_date'], meta['outages']['last_date']],
                        'method': meta['percentile_method']},
               'hexes': hexes}, open(f'{OUT}/lightcrime.json', 'w'))
    print(len(hexes), 'lighting-crime hexes')

# Neighborhood indicators for the "Two factors at once" presets. The windows are
# frozen at the ones first published (June 2026) so a rebake reproduces the site;
# move them deliberately, and update the methodology page when you do.
EVIC_WINDOW = ('2024-06-01', '2026-06-04')      # executed_date, inclusive
NEWBUILD_WINDOW = ('2025-06-11', '2026-06-08')  # filing_date, inclusive
PM25_YEAR = 2023

def vcrime_by_nta(names):
    """Outdoor violent crime points summed from the bivariate lighting-crime hexes,
    which carry an NTA name (crime window: see the hexes file's meta)."""
    d = json.load(urllib.request.urlopen('https://vitalcity-nyc.github.io/bivariate-lighting-crime/hexes.geojson'))
    out = {}
    for f in d['features']:
        code = names.get(f['properties'].get('nta'))
        if code:
            out[code] = out.get(code, 0) + f['properties'].get('crime_n', 0)
    return out

def evictions_by_nta(nta, start=EVIC_WINDOW[0], end=EVIC_WINDOW[1]):
    """Marshal-executed evictions (6z8x-wfk4, residential and commercial),
    assigned to NTAs by point location. The dataset's own nta field mostly
    carries 2010 NTA names, so it is not used."""
    from shapely.geometry import shape, Point
    from shapely.strtree import STRtree
    geoms = [shape(f['geometry']) for f in nta['features']]
    codes = [f['properties']['nta2020'] for f in nta['features']]
    tree = STRtree(geoms)
    rows = soda('6z8x-wfk4', {'$select': 'latitude,longitude',
        '$where': f"executed_date between '{start}' and '{end}' AND latitude IS NOT NULL", '$limit': 200000})
    out = {}
    for r in rows:
        try: pt = Point(float(r['longitude']), float(r['latitude']))
        except (KeyError, TypeError, ValueError): continue
        code = next((codes[i] for i in tree.query(pt) if geoms[i].contains(pt)), None)
        if code:
            out[code] = out.get(code, 0) + 1
    return out

def newbuild_by_nta(names, start=NEWBUILD_WINDOW[0], end=NEWBUILD_WINDOW[1]):
    """New building jobs filed in DOB NOW (w9ak-ipjd), by the dataset's NTA name.
    One row per filing, and a job has many: -I1 is the initial filing, -S1, -S2...
    are subsequent filings and -P1, -P2... post-approval amendments, so only -I1
    rows count, dated by the job's initial filing. Counting every row (the June
    2026 one-off) inflated the figure about eightfold. As of Oct. 2026, 9,757 of
    the 9,764 New Building jobs have exactly one -I1 row; the other 7 have no
    filing inside the window."""
    rows = soda('w9ak-ipjd', {'$select': 'nta,count(*) AS n', '$group': 'nta', '$limit': 1000,
        '$where': f"job_type='New Building' AND job_filing_number like '%-I1' "
                  f"AND filing_date between '{start}T00:00:00' and '{end}T23:59:59'"})
    return {names[r['nta']]: int(r['n']) for r in rows if r.get('nta') in names}

def pm25_by_nta(nta, year=PM25_YEAR):
    """Community district annual-average PM2.5 (c3uy-2p5r), joined through each
    NTA's CDTA code (BK01 -> 301). Parks, airports and other joint interest
    areas (BK55, QN80...) are not community districts and get no value."""
    rows = soda('c3uy-2p5r', {'$select': 'geo_join_id,data_value', '$limit': 100,
        '$where': f"name='Fine particles (PM 2.5)' AND geo_type_name='CD' AND measure='Annual mean' "
                  f"AND time_period in ('{year}','Annual Average {year}')"})
    cd = {r['geo_join_id']: round(float(r['data_value']), 1) for r in rows}
    boro = {'MN': '1', 'BX': '2', 'BK': '3', 'QN': '4', 'SI': '5'}
    out = {}
    for f in nta['features']:
        c = f['properties']['cdta2020']
        if boro[c[:2]] + c[2:] in cd:
            out[f['properties']['nta2020']] = cd[boro[c[:2]] + c[2:]]
    return out

def nta_indicators():
    """Add vcrime_n, evic_n, newbuild_n and pm25 to nta_demographics (raw and
    published copies, like density_fields). NTAs with no events get 0."""
    nta = json.load(open('nta.geojson'))
    names = {f['properties']['ntaname']: f['properties']['nta2020'] for f in nta['features']}
    vc, ev, nb, pm = vcrime_by_nta(names), evictions_by_nta(nta), newbuild_by_nta(names), pm25_by_nta(nta)
    demo = json.load(open('nta_demographics.json'))
    for code, d in demo.items():
        d['vcrime_n'], d['evic_n'], d['newbuild_n'] = vc.get(code, 0), ev.get(code, 0), nb.get(code, 0)
        if code in pm:
            d['pm25'] = pm[code]
        else:
            d.pop('pm25', None)
    json.dump(demo, open('nta_demographics.json', 'w'))
    json.dump(demo, open(f'{OUT}/nta_demographics.json', 'w'))
    print('NTA indicators added:', sum(vc.values()), 'violent crimes,', sum(ev.values()), 'evictions,',
          sum(nb.values()), 'new building jobs,', len(pm), 'NTAs with PM2.5')

if __name__ == '__main__':
    schools(); school_quality(); landmarks(); airquality(); hvi(); density_fields(); nta_indicators(); cityoutline(); busstops(); elections(); neighborhoods_project(); hospitals(); lightcrime()

# NOTE: the two June 2026 one-off merges became functions in Oct. 2026: pres24()
# (called at the end of elections()) and nta_indicators() (called after
# density_fields()). Their code was never committed; both were rebuilt from the
# baked values (for pres24, also from the pres24_*.json intermediates in data/raw/).
# - pres24() reproduces the June elections.json byte for byte when tallies with a
#   thousands comma are zeroed, as the June parse did. Parsed correctly, 37
#   districts change (those whose Democratic or Republican line was 1,000 or more)
#   and the citywide two-party Harris share is 69.4, not 69.0. elections.json was
#   rebaked with the corrected parse.
# - vcrime_n and pm25 reproduce for all 262 NTAs. evic_n reproduces for 210 of 262
#   (33,968 vs 33,979 citywide, no NTA off by more than 4): the eviction feed has
#   been revised since June, so the committed evic_n values were left alone.
# - newbuild_n was rebaked with initial filings only (see newbuild_by_nta): 1,897
#   jobs citywide, down from 15,353 filing rows.

"""Languages block: bakes the Department of City Planning's NYC Language Explorer data.

DCP launched the Language Explorer in July 2026 (press release pr-20260706). It
tabulates the American Community Survey 2020-2024 public-use microdata (PUMS) for
the city, the five boroughs and the 55 Public Use Microdata Areas (PUMAs) that
DCP uses as community district equivalents. PUMS is published no finer than the
PUMA, so these figures cover a larger area than the neighborhood (NTA) figures in
the rest of the numbers chapter.

Sources: DCP's public hosted layers behind the Explorer (owner DCP_POP):
  PUMAData_Language_Mar2026/FeatureServer/0  55 PUMA polygons + totals (people 5+,
                                             speak another language, limited English)
  BoroData_Language_Final/FeatureServer/14   the same totals for the five boroughs
  Table_View_2/FeatureServer/0               long table: every language DCP could
                                             estimate, per geography, with margin of
                                             error, coefficient of variation and DCP's
                                             reliability flag

Writes docs/data/languages.json and docs/data/puma.json (the boundary working
copy; build_topo.mjs makes puma.topo.json, which is what the page loads).

Run from the repo root: python3 scripts/bake_languages.py
"""
import json, math, subprocess, sys, urllib.parse, urllib.request
from datetime import date

BASE = 'https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services'
PUMA_LAYER = f'{BASE}/PUMAData_Language_Mar2026/FeatureServer/0'
BORO_LAYER = f'{BASE}/BoroData_Language_Final/FeatureServer/14'
TABLE = f'{BASE}/Table_View_2/FeatureServer/0'
EXPLORER = 'https://experience.arcgis.com/experience/0da08a1596574ec78cbaa5bef6a04b3e'
Z90 = 1.645  # ACS margins of error are at the 90 percent confidence level

def query(layer, **params):
    p = {'where': '1=1', 'outFields': '*', 'returnGeometry': 'false', 'f': 'json', **params}
    with urllib.request.urlopen(f'{layer}/query?{urllib.parse.urlencode(p)}', timeout=60) as r:
        j = json.load(r)
    if 'error' in j: sys.exit(f'{layer}: {j["error"]}')
    return j

def totals(a):
    """The headline counts DCP publishes for a geography (people age 5 and older)."""
    return {
        'pop5': round(a['Pop5PlusE']),
        'other': round(a['SpksOtherE']), 'other_pct': round(a['SpksOtherP'], 1),
        'lep': round(a['LEPE']), 'lep_moe': round(a['LEPM']), 'lep_pct': round(a['LEPP'], 1),
    }

pumas = [f['attributes'] for f in query(PUMA_LAYER)['features']]
boros = [f['attributes'] for f in query(BORO_LAYER)['features']]
rows = [f['attributes'] for f in query(TABLE, resultRecordCount=2000, orderByFields='FID')['features']]
if len(pumas) != 55 or len(boros) != 5 or len(rows) < 1000:
    sys.exit(f'unexpected counts: {len(pumas)} PUMAs, {len(boros)} boroughs, {len(rows)} table rows')

# The long table's CD column is wrong for two districts (it labels Upper West Side
# "5" and Queens Village "12"), so rows are matched to PUMAs by borough + name.
by_geo = {}
for r in rows:
    by_geo.setdefault((r['Boro'], r['Name']), []).append(r)

def languages(key):
    rs = by_geo.get(key)
    if not rs: sys.exit(f'no language rows for {key}')
    total = next(r for r in rs if r['Language'].startswith('0.'))
    # DCP's charts leave out languages whose margin of error is as large as the estimate
    langs = [r for r in rs if not r['Language'].startswith('0.') and r['EstMoe'] < r['Estimate']]
    langs.sort(key=lambda r: -r['Estimate'])
    return total, langs

out = {
    'source': 'NYC Department of City Planning, NYC Language Explorer (June 2026), '
              'from American Community Survey 2020-2024 five-year public-use microdata',
    'explorer': EXPLORER, 'fetched': date.today().isoformat(),
    'city': None, 'boro': {}, 'puma': {},
}

# citywide: DCP publishes no citywide totals layer, so sum the boroughs (same survey, additive counts)
city = {k: sum(round(b[k]) for b in boros) for k in ('Pop5PlusE', 'SpksOtherE', 'LEPE')}
ctot, clangs = languages(('New York City', 'New York City'))
if abs(city['LEPE'] - ctot['Estimate']) > 2:
    sys.exit(f'borough limited-English sum {city["LEPE"]} != citywide row {ctot["Estimate"]}')
out['city'] = {
    'pop5': city['Pop5PlusE'], 'other': city['SpksOtherE'],
    'other_pct': round(100 * city['SpksOtherE'] / city['Pop5PlusE'], 1),
    'lep': ctot['Estimate'], 'lep_moe': ctot['EstMoe'],
    'lep_pct': round(100 * ctot['Estimate'] / city['Pop5PlusE'], 1),
    'share': {r['Language']: r['Percent_'] for r in clangs},
}
for b in boros:
    out['boro'][b['BoroName']] = totals(b)

# the district with the most limited-English speakers of each language, kept only
# when it beats the runner-up by more than sampling error (90 percent test)
lead = {}
for a in pumas:
    _, langs = languages((a['BoroName'], a['PUMAName']))
    for r in langs:
        lead.setdefault(r['Language'], []).append((r['Estimate'], r['EstMoe'], r['Reliable'] == 'Yes', a['PUMA2020']))
most = {}
for lang, xs in lead.items():
    xs.sort(reverse=True)
    if len(xs) < 2 or not xs[0][2]: continue
    (e1, m1, _, p1), (e2, m2, _, _) = xs[0], xs[1]
    z = (e1 - e2) / math.sqrt((m1 / Z90) ** 2 + (m2 / Z90) ** 2)
    if z > Z90: most[(p1, lang)] = True

for a in pumas:
    code = a['PUMA2020']
    _, langs = languages((a['BoroName'], a['PUMAName']))
    t = totals(a)
    t.update({
        'name': a['PUMAName'], 'boro': a['BoroName'],
        'cds': a['CDNum'],                                   # "4", or "1 & 2" where a PUMA spans two
        'exact': a['CDEquiv'].endswith('Equivalent'),      # DCP: "Equivalent" vs "Approximation"
        # [language, estimate, margin of error, reliable (CV under 20%), share of limited-English speakers, most of any district]
        'langs': [[r['Language'], r['Estimate'], r['EstMoe'], int(r['Reliable'] == 'Yes'),
                   r['Percent_'], int((code, r['Language']) in most)] for r in langs],
    })
    out['puma'][code] = t

json.dump(out, open('docs/data/languages.json', 'w'), ensure_ascii=False, separators=(',', ':'))
print(f'languages.json: {len(out["puma"])} districts, {len(lead)} languages, '
      f'{ctot["Estimate"]:,} limited-English residents citywide; '
      f'clear citywide leaders: ' + ', '.join(f'{l} ({p})' for p, l in sorted(most, key=lambda x: x[1])))

# boundaries: DCP's PUMA polygons (shoreline-clipped), simplified like the other layers
p = {'where': '1=1', 'outFields': 'PUMA2020', 'outSR': 4326, 'geometryPrecision': 6, 'f': 'geojson'}
raw = 'data/raw/puma_language.geojson'
urllib.request.urlretrieve(f'{PUMA_LAYER}/query?{urllib.parse.urlencode(p)}', raw)
subprocess.run(['npx', '-y', 'mapshaper', raw, '-rename-fields', 'puma=PUMA2020',
                '-simplify', 'weighted', 'interval=2', 'keep-shapes', '-filter-fields', 'puma',
                '-o', 'force', 'precision=0.000001', 'docs/data/puma.json'], check=True)
print('puma.json written; run node scripts/build_topo.mjs for puma.topo.json')

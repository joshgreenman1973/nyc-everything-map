#!/usr/bin/env python3
"""Rebuild the neighborhood indicator base on ACS 2020-2024 (vintage 2024),
aggregated from census tracts — the architecture agreed with Josh June 2026:

- Counts (population, age, race, foreign born, education, poverty, tenure,
  rent burden, unemployment, broadband) sum cleanly from tracts to NTAs.
- Medians (income, rent, home value) are NOT averaged: the underlying ACS
  bracket distributions (B19001, B25063, B25075) are pooled across each
  neighborhood's tracts and the median re-interpolated — the same way the
  bureau computes them, so they are true neighborhood medians.
- Tract-level ACS estimates are too noisy for tercile/bivariate ranking and
  are exported only for display-with-margin-of-error (tract_context.json).
- Rent-stabilized units (administrative full counts, via the population
  map's JustFix-derived file) are reliable at any level and added per NTA.

Writes: updates docs/data/nta_demographics.json in place (same keys, fresh
values), docs/data/compare_geos.json, and new docs/data/tract_context.json.
Run from the project root with CENSUS_API_KEY set.
"""
import json, os, sys, urllib.request, urllib.parse
from collections import defaultdict

KEY = os.environ.get('CENSUS_API_KEY') or sys.exit('CENSUS_API_KEY not set')
COUNTIES = ['005', '047', '061', '081', '085']
BORO = {'005': 'Bronx', '047': 'Brooklyn', '061': 'Manhattan', '081': 'Queens', '085': 'Staten Island'}

# ---- variable sets ----------------------------------------------------------
# age (B01001): under-18 = male 003-006 + female 027-030; 65+ = male 020-025 + female 044-049
AGE_U18 = [f'B01001_{i:03d}E' for i in (3, 4, 5, 6, 27, 28, 29, 30)]
AGE_65 = [f'B01001_{i:03d}E' for i in (20, 21, 22, 23, 24, 25, 44, 45, 46, 47, 48, 49)]
COUNTS = {
    'pop': ['B01001_001E'],
    'u18': AGE_U18, 's65': AGE_65,
    'race_tot': ['B03002_001E'], 'hisp': ['B03002_012E'],
    'wnh': ['B03002_003E'], 'bnh': ['B03002_004E'], 'anh': ['B03002_006E'],
    'fb_tot': ['B05002_001E'], 'fb': ['B05002_013E'],
    'ed_tot': ['B15003_001E'], 'ba': ['B15003_022E', 'B15003_023E', 'B15003_024E', 'B15003_025E'],
    'pov_tot': ['B17001_001E'], 'pov': ['B17001_002E'],
    'occ': ['B25003_001E'], 'rent_occ': ['B25003_003E'],
    'hh_pop': ['B25008_001E'],
    'grapi_tot': ['B25070_001E'], 'grapi_nc': ['B25070_011E'],
    'grapi_30': ['B25070_007E', 'B25070_008E', 'B25070_009E', 'B25070_010E'],
    'lf': ['B23025_003E'], 'unemp': ['B23025_005E'],
    'agg_inc': ['B19313_001E'],
    'commute_min': ['B08013_001E'], 'commuters': ['B08303_001E'],
    'lep_tot': ['B06007_001E'], 'lep': ['B06007_005E', 'B06007_008E'],
}
# median-by-interpolation brackets: (table prefix, count, upper bounds)
INC_BOUNDS = [10000, 15000, 20000, 25000, 30000, 35000, 40000, 45000, 50000,
              60000, 75000, 100000, 125000, 150000, 200000, None]
INC_VARS = [f'B19001_{i:03d}E' for i in range(2, 18)]
RENT_BOUNDS = [100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750,
               800, 900, 1000, 1250, 1500, 2000, 2500, 3000, 3500, None]
RENT_VARS = [f'B25063_{i:03d}E' for i in range(3, 27)]
VAL_BOUNDS = [10000, 15000, 20000, 25000, 30000, 35000, 40000, 50000, 60000, 70000,
              80000, 90000, 100000, 125000, 150000, 175000, 200000, 250000, 300000,
              400000, 500000, 750000, 1000000, 1500000, 2000000, None]
VAL_VARS = [f'B25075_{i:03d}E' for i in range(2, 28)]

ALL_VARS = sorted({v for vs in COUNTS.values() for v in vs} | set(INC_VARS) | set(RENT_VARS) | set(VAL_VARS))

def fetch(vars_, geo):
    out = {}
    for i in range(0, len(vars_), 45):
        chunk = vars_[i:i + 45]
        u = (f'https://api.census.gov/data/2024/acs/acs5?get={",".join(chunk)}'
             f'&{geo}&key={KEY}')
        data = json.load(urllib.request.urlopen(u))
        hdr = data[0]
        for row in data[1:]:
            rec = dict(zip(hdr, row))
            gid = ''.join(rec[g] for g in ('state', 'county', 'tract') if g in rec) or rec.get('place', 'X')
            d = out.setdefault(gid, {})
            for v in chunk:
                x = rec.get(v)
                d[v] = float(x) if x not in (None, '', 'null') and float(x) > -1e8 else 0.0
    return out

def pooled_median(counts, bounds):
    total = sum(counts)
    if total < 50:
        return None
    half, c, lo = total / 2.0, 0.0, 0.0
    for n, hi in zip(counts, bounds):
        if c + n >= half:
            width = (hi - lo) if hi else lo  # open top bracket: extend by lower bound
            hi2 = hi if hi else lo * 2
            return round(lo + (half - c) / n * (hi2 - lo)) if n else round(lo)
        c += n
        lo = hi
    return None

def derive(d):
    """Turn summed raw variables into the panel's field names."""
    g = lambda k: sum(d.get(v, 0) for v in COUNTS[k])
    pop = g('pop')
    out = {'pop': round(pop)}
    if not pop:
        return out
    pct = lambda num, den: round(num / den * 100, 1) if den else None
    out['under18_pct'] = pct(g('u18'), pop)
    out['age65pl_pct'] = pct(g('s65'), pop)
    out['hispanic_pct'] = pct(g('hisp'), g('race_tot'))
    out['white_nh_pct'] = pct(g('wnh'), g('race_tot'))
    out['black_nh_pct'] = pct(g('bnh'), g('race_tot'))
    out['asian_nh_pct'] = pct(g('anh'), g('race_tot'))
    out['foreign_born_pct'] = pct(g('fb'), g('fb_tot'))
    out['bachelors_plus_pct'] = pct(g('ba'), g('ed_tot'))
    out['poverty_pct'] = pct(g('pov'), g('pov_tot'))
    out['limited_english_pct'] = pct(g('lep'), g('lep_tot'))
    occ = g('occ')
    out['renter_occ'] = round(g('rent_occ'))
    out['renter_occ_pct'] = pct(g('rent_occ'), occ)
    out['avg_hh_size'] = round(g('hh_pop') / occ, 2) if occ else None
    gr_den = g('grapi_tot') - g('grapi_nc')
    out['rent_burdened_pct'] = pct(g('grapi_30'), gr_den)
    out['unemployed_pct'] = pct(g('unemp'), g('lf'))
    out['per_capita_income'] = round(g('agg_inc') / pop) if pop else None
    out['mean_commute'] = round(g('commute_min') / g('commuters'), 1) if g('commuters') else None
    out['median_hh_income'] = pooled_median([d.get(v, 0) for v in INC_VARS], INC_BOUNDS)
    out['median_rent'] = pooled_median([d.get(v, 0) for v in RENT_VARS], RENT_BOUNDS)
    out['median_home_value'] = pooled_median([d.get(v, 0) for v in VAL_VARS], VAL_BOUNDS)
    return out

def main():
    # tract -> NTA equivalency
    eq = {}
    rows = json.load(urllib.request.urlopen(
        'https://data.cityofnewyork.us/resource/hm78-6dwm.json?$limit=3000'))
    for r in rows:
        eq[r['geoid']] = r['ntacode']
    print(len(eq), 'tracts mapped to NTAs')

    # tract pulls, summed into NTAs
    nta_raw = defaultdict(lambda: defaultdict(float))
    tract_inc = {}
    for c in COUNTIES:
        tr = fetch(ALL_VARS, f'for=tract:*&in=state:36%20county:{c}')
        med = fetch(['B19013_001E', 'B19013_001M'], f'for=tract:*&in=state:36%20county:{c}')
        for gid, d in tr.items():
            nta = eq.get(gid)
            if not nta:
                continue
            for v, x in d.items():
                nta_raw[nta][v] += x
            m = med.get(gid, {})
            inc, moe = m.get('B19013_001E'), m.get('B19013_001M')
            if inc and inc > 0:
                tract_inc[gid] = [round(inc), round(moe) if moe and moe > 0 else None,
                                  round(d.get('B01001_001E', 0))]
        print('county', c, 'done')

    # rent-stabilized units per tract -> NTA (administrative full counts)
    rs = json.load(open('/Users/joshgreenman/Experiments/nyc-population-map/docs/rentstab_by_tract.json'))['by_tract']
    rs_nta = defaultdict(float)
    for gid, v in rs.items():
        nta = eq.get(gid)
        if nta:
            rs_nta[nta] += v.get('rs_units_2024', 0) or 0

    demo = json.load(open('docs/data/nta_demographics.json'))
    updated = 0
    for code, d in demo.items():
        raw = nta_raw.get(code)
        if not raw:
            continue
        fresh = derive(raw)
        d.update({k: v for k, v in fresh.items() if v is not None})
        if d.get('pop') and d.get('land_sqmi'):
            d['density'] = round(d['pop'] / d['land_sqmi'])
        d['rs_units'] = round(rs_nta.get(code, 0))
        if d.get('renter_occ'):
            d['rs_share_pct'] = round(d['rs_units'] / d['renter_occ'] * 100, 1)
        updated += 1
    json.dump(demo, open('docs/data/nta_demographics.json', 'w'))
    print(updated, 'NTAs refreshed to ACS 2020-2024')

    # citywide + borough comparison values, same vintage
    cg = {}
    for label, geo in [('NYC', 'for=place:51000&in=state:36')] + \
                      [(BORO[c], f'for=county:{c}&in=state:36') for c in COUNTIES]:
        d = list(fetch(ALL_VARS, geo).values())[0]
        cg[label] = derive(d)
    old = json.load(open('docs/data/compare_geos.json'))
    for label, fresh in cg.items():
        merged = old.get(label, {})
        merged.update({k: v for k, v in fresh.items() if v is not None})
        # senior/under18 keys used by snapshot + compare
        merged['under18_pct'] = fresh.get('under18_pct')
        merged['senior_pct'] = fresh.get('age65pl_pct')
        old[label] = merged
    # densities from existing land areas
    land = {'NYC': 302.1}
    boro_land = defaultdict(float)
    for code, d in demo.items():
        b = code[:2]
        names = {'MN': 'Manhattan', 'BX': 'Bronx', 'BK': 'Brooklyn', 'QN': 'Queens', 'SI': 'Staten Island'}
        boro_land[names[b]] += d.get('land_sqmi', 0)
    for label in old:
        area = land.get(label) or boro_land.get(label)
        if area and old[label].get('pop'):
            old[label]['density'] = round(old[label]['pop'] / area)
    json.dump(old, open('docs/data/compare_geos.json', 'w'))
    print('compare_geos refreshed:', {k: old[k].get('median_hh_income') for k in old})

    # tract display context: median income with margin of error + rent-stab share
    ctx = {}
    for gid, (inc, moe, pop) in tract_inc.items():
        rsv = rs.get(gid, {})
        rec = {'inc': inc, 'moe': moe, 'pop': pop}
        if rsv.get('rs_units_2024'):
            rec['rs'] = rsv['rs_units_2024']
        ctx[gid] = rec
    json.dump(ctx, open('docs/data/tract_context.json', 'w'))
    print(len(ctx), 'tracts in display context file')

if __name__ == '__main__':
    main()

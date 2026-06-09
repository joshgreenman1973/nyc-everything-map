#!/usr/bin/env python3
"""Extract per-NTA indicators from City Planning's ACS 2016-2020 Excel files
and pull matching citywide + borough values from the Census Bureau API.

Run from data/raw/ (build_data.sh does this). Needs CENSUS_API_KEY in the
environment for the comparison step. Variable codes were verified against the
files' own Dictionary sheets and the Census API variables endpoint; see
docs/methodology.html.
"""
import openpyxl, json, os, sys, urllib.request

# DCP variable code -> our field name. E suffix = estimate, P = percent.
VARS = {
 'demo': {'Pop_1':'pop','MdAge':'median_age','PopU181':'under18','Pop65pl1':'age65pl',
          'Hsp1':'hispanic','WtNH':'white_nh','BlNH':'black_nh','AsnNH':'asian_nh',
          'Rc2plNH':'two_plus_nh','OthNH':'other_nh'},
 'econ': {'MdHHInc':'median_hh_income','PerCapInc':'per_capita_income','PBwPv':'poverty',
          'CvLFUEm2':'unemployed','MnTrvTm':'mean_commute'},
 'soc':  {'EA_BchDH':'bachelors_plus','Fb1':'foreign_born','LgOEnLEP1':'limited_english',
          'AvgHHSz':'avg_hh_size','HHInt':'broadband'},
 'hous': {'MdGR':'median_rent','MdVl':'median_home_value','ROcHU1':'renter_occ',
          'RntVacRt':'rental_vacancy','GRPI30pl':'rent_burdened'},
}
SHEET = {'demo':'DemData','econ':'EconData','soc':'SocData','hous':'HousData'}

def ntas():
    out = {}
    for f, vmap in VARS.items():
        wb = openpyxl.load_workbook(f'{f}_nta.xlsx', read_only=True)
        ws = wb[SHEET[f]]
        it = ws.iter_rows(values_only=True)
        idx = {h: i for i, h in enumerate(next(it))}
        for row in it:
            if row[idx['GeoType']] != 'NTA2020':
                continue
            rec = out.setdefault(row[idx['GeoID']], {})
            for code, name in vmap.items():
                if code+'E' in idx and row[idx[code+'E']] is not None:
                    rec[name] = row[idx[code+'E']]
                if code+'P' in idx and row[idx[code+'P']] is not None:
                    rec[name+'_pct'] = row[idx[code+'P']]
    assert len(out) == 262, f'expected 262 NTAs, got {len(out)}'
    return out

# Census API profile variables for the same 2016-2020 vintage, verified by label.
CENSUS_VARS = {
 'DP05_0001E':'pop','DP05_0018E':'median_age','DP03_0062E':'median_hh_income',
 'DP03_0128PE':'poverty_pct','DP02_0068PE':'bachelors_plus_pct','DP02_0094PE':'foreign_born_pct',
 'DP02_0115PE':'limited_english_pct','DP04_0134E':'median_rent','DP04_0089E':'median_home_value',
 'DP04_0047PE':'renter_occ_pct','DP03_0025E':'mean_commute','DP05_0071PE':'hispanic_pct',
 'DP05_0077PE':'white_nh_pct','DP05_0078PE':'black_nh_pct','DP05_0080PE':'asian_nh_pct',
 'DP04_0141PE':'grapi3034','DP04_0142PE':'grapi35','DP03_0005PE':'unemployed_pct'}
BORO = {'005':'Bronx','047':'Brooklyn','061':'Manhattan','081':'Queens','085':'Staten Island'}

def compare_geos(key):
    base = 'https://api.census.gov/data/2020/acs/acs5/profile'
    cols = ','.join(CENSUS_VARS)
    out = {}
    for geo, namer in [('for=place:51000&in=state:36', lambda r: 'NYC'),
                       ('for=county:005,047,061,081,085&in=state:36', lambda r: BORO[r['county']])]:
        data = json.load(urllib.request.urlopen(f'{base}?get=NAME,{cols}&{geo}&key={key}'))
        hdr = data[0]
        for raw in data[1:]:
            rec = dict(zip(hdr, raw))
            o = {}
            for cv, name in CENSUS_VARS.items():
                v = rec.get(cv)
                o[name] = float(v) if v and '.' in v else (int(v) if v and v.lstrip('-').isdigit() else None)
            o['rent_burdened_pct'] = round(o.pop('grapi3034') + o.pop('grapi35'), 1)
            out[namer(rec)] = o
    return out

if __name__ == '__main__':
    json.dump(ntas(), open('nta_demographics.json', 'w'))
    print('nta_demographics.json written (262 NTAs)')
    key = os.environ.get('CENSUS_API_KEY')
    if not key:
        sys.exit('CENSUS_API_KEY not set — cannot pull citywide/borough comparison values')
    json.dump(compare_geos(key), open('compare_geos.json', 'w'))
    print('compare_geos.json written (NYC + 5 boroughs)')

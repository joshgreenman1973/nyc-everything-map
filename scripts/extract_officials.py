#!/usr/bin/env python3
"""Build officials.json: current officeholders for every district layer.

Run from data/raw/ (build_data.sh does this). Inputs, fetched by build_data.sh:
  council_page.html  — scraped from https://council.nyc.gov/districts/
  legislators.json   — unitedstates/congress-legislators current members
  ny_legislators.csv — Open States current New York legislators

The CITYWIDE and BOROUGH constants below are hand-verified (see
docs/methodology.html for sources and the as-of date). Re-verify them
whenever this script is rerun.
"""
import re, json, csv, sys

# Hand-verified June 9, 2026 against official office websites and
# coverage of the January 1, 2026 inaugurations.
CITYWIDE = {
    'mayor': {'name': 'Zohran Mamdani', 'party': 'Democrat'},
    'public_advocate': {'name': 'Jumaane Williams', 'party': 'Democrat'},
    'comptroller': {'name': 'Mark Levine', 'party': 'Democrat'},
    'us_senators': [
        {'name': 'Charles E. Schumer', 'party': 'Democrat'},
        {'name': 'Kirsten E. Gillibrand', 'party': 'Democrat'},
    ],
}
BOROUGH = {
    'Manhattan':     {'bp': 'Brad Hoylman-Sigal', 'da': 'Alvin Bragg'},
    'Brooklyn':      {'bp': 'Antonio Reynoso',    'da': 'Eric Gonzalez'},
    'Queens':        {'bp': 'Donovan Richards',   'da': 'Melinda Katz'},
    'Bronx':         {'bp': 'Vanessa Gibson',     'da': 'Darcel Clark'},
    'Staten Island': {'bp': 'Vito Fossella',      'da': 'Michael McMahon'},
}
LEADERSHIP_PREFIXES = ('Speaker ', 'Majority Leader ', 'Majority Whip ',
                       'Minority Leader ', 'Minority Whip ')

def council():
    html = open('council_page.html').read()
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S)
    out = {}
    for r in rows:
        cells = [re.sub(r'<[^>]+>', ' ', c).strip()
                 for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
        if len(cells) < 5 or not cells[0].isdigit():
            continue
        d, name, party = cells[0], cells[1], cells[4]
        role = ''
        for pre in LEADERSHIP_PREFIXES:
            if name.startswith(pre):
                role, name = pre.strip(), name[len(pre):]
        out[d] = {'name': name, 'party': party, 'role': role}
    assert len(out) == 51, f'expected 51 council members, got {len(out)}'
    return out

def congress():
    out = {}
    for l in json.load(open('legislators.json')):
        t = l['terms'][-1]
        if t.get('state') == 'NY' and t['type'] == 'rep':
            out[str(t['district'])] = {'name': l['name']['official_full'], 'party': t['party']}
    return out

def state_chambers():
    senate, assembly = {}, {}
    for row in csv.DictReader(open('ny_legislators.csv')):
        rec = {'name': row['name'], 'party': row['current_party']}
        if row['current_chamber'] == 'upper':
            senate[row['current_district']] = rec
        elif row['current_chamber'] == 'lower':
            assembly[row['current_district']] = rec
    return senate, assembly

def verify_coverage(officials):
    """Every district in every boundary layer must have an officeholder."""
    checks = [('../out/congress.json', 'cong_dist', officials['congress']),
              ('../out/senate.json', 'st_sen_dist', officials['senate']),
              ('../out/assembly.json', 'assembly_district', officials['assembly']),
              ('../out/council.json', 'coundist', officials['council'])]
    ok = True
    for f, prop, table in checks:
        ds = {str(int(float(ft['properties'][prop])))
              for ft in json.load(open(f))['features']}
        missing = sorted(d for d in ds if d not in table)
        if missing:
            ok = False
            print(f'MISSING officials in {f}: {missing}', file=sys.stderr)
    if not ok:
        sys.exit(1)

if __name__ == '__main__':
    sen, asm = state_chambers()
    officials = {'council': council(), 'congress': congress(),
                 'senate': sen, 'assembly': asm,
                 'citywide': CITYWIDE, 'borough': BOROUGH}
    verify_coverage(officials)
    json.dump(officials, open('officials.json', 'w'), ensure_ascii=False)
    print('officials.json written; all district layers fully covered')

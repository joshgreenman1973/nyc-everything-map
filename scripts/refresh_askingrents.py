#!/usr/bin/env python3
"""Rebake docs/data/askingrents.json from StreetEasy's public medianAskingRent_All.zip.

Structure served to the app: {Borough: {npNorm(areaName): [rent, 'YYYY-MM', areaName]}}
- neighborhood rows only (areaType == 'neighborhood')
- each neighborhood carries its own latest non-empty month, so stale areas
  self-label (the UI prints the month next to the dollar figure)
- npNorm mirrors the client-side matcher in docs/index.html: NFKD, strip
  accents, lowercase, non-alphanumerics to single spaces

Run from the project root. No key needed.
"""
import csv, io, json, re, sys, unicodedata, urllib.request, zipfile

URL = 'https://cdn-charts.streeteasy.com/rentals/All/medianAskingRent_All.zip'

def np_norm(s):
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()

def main():
    raw = urllib.request.urlopen(URL).read()
    zf = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in zf.namelist() if n.endswith('.csv'))
    rows = list(csv.reader(io.TextIOWrapper(zf.open(name), encoding='utf-8-sig')))
    hdr = rows[0]
    months = hdr[3:]
    out = {}
    for r in rows[1:]:
        area, boro, kind = r[0], r[1], r[2]
        if kind != 'neighborhood' or not boro:
            continue
        latest = None
        for m, v in zip(months, r[3:]):
            if v not in ('', 'NA', 'null'):
                latest = (round(float(v)), m, area)
        if latest:
            out.setdefault(boro, {})[np_norm(area)] = list(latest)
    if sum(len(v) for v in out.values()) < 100:
        sys.exit('suspiciously few neighborhoods — refusing to overwrite')
    json.dump(out, open('docs/data/askingrents.json', 'w'), ensure_ascii=False)
    latest_month = max(v[1] for b in out.values() for v in b.values())
    n = sum(len(v) for v in out.values())
    cur = sum(1 for b in out.values() for v in b.values() if v[1] == latest_month)
    print(f'{n} neighborhoods baked; latest month {latest_month} ({cur} current)')

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Build docs/data/restaurants.json for the Everything Map's "Eating nearby" feature.

Self-contained: pulls straight from the DOHMH NYC Restaurant Inspection Results
(NYC Open Data / Socrata dataset 43nn-pn8j) so it can run unattended on a
schedule. No third-party packages — standard library only, so the system
python3 can run it under launchd.

Each establishment is counted once (distinct CAMIS), tagged with the city's
self-reported coarse "cuisine" label and its latest A/B/C letter grade.

Output schema (compact, point-based so the map filters by walking radius):
  {
    "cuisines": ["American", "Chinese", ...],   # index lookup
    "city":     [4656, 2276, ...],              # citywide count per cuisine index
    "cityTotal": 30425,
    "pts": [[lat, lng, ci, name, grade], ...],   # one row per restaurant
    "built": "2026-06-22"                         # UTC date the pull ran
  }

Run:  python3 scripts/build_restaurants.py
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "docs", "data", "restaurants.json"))

BASE = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"
PAGE = 50000
NYC = (40.40, 41.00, -74.30, -73.60)  # lat_min, lat_max, lng_min, lng_max
UA = "nyc-everything-map/eating-nearby (github.com/joshgreenman1973)"


def fetch(params):
    """One Socrata request -> list of dict rows (retries on transient errors)."""
    url = BASE + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - transient network/HTTP
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Socrata request failed after retries: {last}\n{url}")


def paginate(params):
    """Yield all rows for a query, paging by $limit/$offset."""
    offset = 0
    while True:
        page = fetch({**params, "$limit": PAGE, "$offset": offset})
        if not page:
            return
        yield from page
        if len(page) < PAGE:
            return
        offset += PAGE


def titlecase(s):
    # Title-case that keeps apostrophes lowercase: "WENDY'S" -> "Wendy's"
    return re.sub(r"[A-Za-z']+",
                  lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(),
                  (s or "").strip())


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def build():
    # 1) Establishments: one row per distinct CAMIS (group collapses the
    #    296k violation rows). Keep the record from the most recent inspection.
    est = {}
    for r in paginate({
        "$select": "camis,dba,cuisine_description,latitude,longitude,"
                   "max(inspection_date) as last_insp",
        "$group": "camis,dba,cuisine_description,latitude,longitude",
    }):
        cm = r.get("camis")
        lat, lng = fnum(r.get("latitude")), fnum(r.get("longitude"))
        if not cm or lat is None or lng is None:
            continue
        if not (NYC[0] < lat < NYC[1] and NYC[2] < lng < NYC[3]):
            continue
        last = r.get("last_insp") or ""
        prev = est.get(cm)
        if prev and prev["last"] >= last:
            continue
        est[cm] = {"lat": round(lat, 5), "lng": round(lng, 5),
                   "name": titlecase(r.get("dba")),
                   "cuisine": (r.get("cuisine_description") or "").strip(),
                   "last": last}

    if len(est) < 20000:  # sanity floor — the city has ~30k; refuse to ship a short pull
        raise RuntimeError(f"only {len(est)} establishments fetched — refusing to write")

    # 2) Latest A/B/C letter grade per CAMIS (best-effort; grades are also shown
    #    live elsewhere in the map, so a miss here is cosmetic).
    grade = {}
    try:
        for r in paginate({
            "$select": "camis,grade,grade_date",
            "$where": "grade in ('A','B','C')",
            "$order": "grade_date DESC",
        }):
            cm = r.get("camis")
            if cm in est and cm not in grade:
                grade[cm] = r.get("grade") or ""
    except Exception as e:  # noqa: BLE001
        print(f"  warning: grade pull failed ({e}); grades left blank", file=sys.stderr)

    # 3) Assemble compact output. Sort everything deterministically so identical
    #    data always serializes byte-for-byte the same way — the API returns rows
    #    in an arbitrary order, and the refresh job only commits on real change.
    cuisines = sorted({e["cuisine"] for e in est.values()})
    ci_idx = {c: i for i, c in enumerate(cuisines)}
    city = [0] * len(cuisines)
    pts = []
    for cm in sorted(est):  # by CAMIS — stable across runs
        e = est[cm]
        ci = ci_idx[e["cuisine"]]
        city[ci] += 1
        pts.append([e["lat"], e["lng"], ci, e["name"], grade.get(cm, "")])

    return {
        "cuisines": cuisines,
        "city": city,
        "cityTotal": len(pts),
        "pts": pts,
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def main():
    out = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, OUT)
    size = os.path.getsize(OUT) / 1024
    graded = sum(1 for p in out["pts"] if p[4])
    print(f"wrote {OUT}")
    print(f"  {out['cityTotal']} restaurants, {len(out['cuisines'])} cuisine "
          f"labels, {graded} with A/B/C grades, {size:.0f} KB, built {out['built']}")


if __name__ == "__main__":
    main()

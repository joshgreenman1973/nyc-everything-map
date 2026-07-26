#!/usr/bin/env python3
"""Build docs/data/commonplace.json — the city's own name for a place.

Source: CommonPlace (NYC Open Data / Socrata t95h-5fsr), published by the
Office of Technology and Innovation. It is the gazetteer behind Geosupport:
the file that lets a city system resolve a *name* ("PS 61", "Rikers Island",
"McGolrick Playground Comfort Station") to a building, a street segment and a
coordinate. Its stated purpose, per the agency's own data dictionary, is "to
help aid dispatch efforts to these points of interest throughout New York
City" — so coverage follows what agencies get called out to, not what is
civically or commercially notable.

Two rules this script enforces, both from that data dictionary
(PointOfInterest.pdf, attached to the dataset):

1. NYPD-sourced rows are dropped unless they are public-safety facilities.
   The metadata states: "NYPD common places, with the exception of precinct
   locations, cannot be distributed." Most NYPD-sourced rows are ordinary
   places (churches, consulates, hotels) that entered via the Sprint/PCAD
   dispatch systems, and the great majority are also carried by another
   source, so the coverage cost of honoring this is small.

2. Only FACILITY_TYPE is decoded, never FACILITY_DOMAINS. The published
   table has 13 categories and FACILITY_TYPE matches it exactly. The column
   named FACILITY_DOMAINS carries 18 distinct values, so the published table
   does not describe it and any mapping would be a guess.

No third-party packages — standard library only, so the system python3 can
run it unattended.

Output schema (compact, point-based; the app filters by walking radius):
  {
    "types": ["Residential", "Education", ...],   # index lookup
    "pts":   [[lat, lng, name, ti, src, bin], ...],  # bin is null when absent
    "counts": {"Education": 3724, ...},
    "dropped": {"nypd_restricted": 1640, "outside_nyc": 4, "no_geom": 0},
    "built": "2026-07-26",
    "modified": "2026-07-17"   # newest MODIFIED_DATE in the source
  }

Run:  python3 scripts/build_commonplace.py
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "docs", "data", "commonplace.json"))

BASE = "https://data.cityofnewyork.us/resource/t95h-5fsr.json"
PAGE = 20000
NYC = (40.40, 41.00, -74.30, -73.60)  # lat_min, lat_max, lng_min, lng_max
UA = "nyc-everything-map/commonplace (github.com/joshgreenman1973)"

# FACILITY TYPE, verbatim from the dataset's own data dictionary. Labels are
# shortened for display; the code -> concept mapping is unchanged.
TYPES = {
    1: "Residential",
    2: "Education",
    3: "Cultural",
    4: "Recreation",
    5: "Social services",
    6: "Transportation",
    7: "Commercial",
    8: "Government",
    9: "Religious",
    10: "Health",
    11: "Public safety",
    12: "Water",
    13: "Miscellaneous",
}
TYPE_ORDER = [TYPES[i] for i in sorted(TYPES)]

# Names arrive shouting in all caps. Title-case them, but never touch a token
# that is a genuine acronym or a school-style designation.
KEEP_UPPER = {
    "NYC", "NYPD", "FDNY", "EMS", "NYCHA", "MTA", "DOT", "DEP", "DOE", "DSNY",
    "HRA", "OCME", "DHS", "DOB", "DOF", "DCP", "OEM", "USA", "US", "UN", "NY",
    "PS", "IS", "MS", "JHS", "HS", "PK", "RC", "JFK", "LGA", "PATH", "BQE",
    "YMCA", "YMHA", "YWCA", "CUNY", "SUNY", "NYU", "PAL", "VA", "TV", "AME",
    "BMT", "IRT", "IND", "LIRR", "FDR", "SI", "II", "III", "IV", "VI", "VII",
    "VIII", "NE", "NW", "SE", "SW", "PL", "SQ", "BLVD", "AVE",
}
SMALL = {"of", "the", "and", "at", "on", "for", "in", "de", "la", "el", "von", "van"}

# Two-letter tokens that are abbreviated words, not initials. "ST" is the hard
# one: it is Street after a number or ordinal ("84 ST") and Saint otherwise
# ("ST MARYS CHURCH"), so it is resolved from the preceding token.
ABBREV = {"FT": "Ft", "MT": "Mt", "DR": "Dr", "JR": "Jr", "SR": "Sr", "RD": "Rd"}


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


def titlecase(name):
    """ALL CAPS -> readable, preserving acronyms and school designations."""
    out = []
    toks = name.split()
    for i, tok in enumerate(toks):
        # Split off surrounding punctuation so "(FDNY)" still matches.
        lead = re.match(r"^\W*", tok).group(0)
        trail = re.search(r"\W*$", tok).group(0)
        core = tok[len(lead):len(tok) - len(trail)] if trail else tok[len(lead):]
        if not core:
            out.append(tok)
            continue
        up = core.upper()
        prev = toks[i - 1] if i else ""
        if up == "ST":
            # Street when it trails a number or ordinal, Saint otherwise.
            new = "ST" if any(ch.isdigit() for ch in prev) else "St"
        elif up in ABBREV:
            new = ABBREV[up]
        elif up in KEEP_UPPER:
            new = up
        elif any(ch.isdigit() for ch in core):
            new = up                      # "PS61", "I-95", "SEC-4"
        elif core.lower() in SMALL and i > 0:
            new = core.lower()
        elif len(core) <= 2 and core.isalpha():
            new = up                      # initials
        else:
            new = core.capitalize()
            # O'BRIEN -> O'Brien, MCGOLRICK stays McGolrick-ish only if obvious
            new = re.sub(r"^(O')(\w)", lambda m: m.group(1) + m.group(2).upper(), new)
            new = re.sub(r"^(Mc)([a-z])", lambda m: m.group(1) + m.group(2).upper(), new)
        out.append(lead + new + trail)
    return " ".join(out)


def main():
    rows = list(paginate({
        "$select": "feature_name,facility_type,source,bin,the_geom,modified_date",
    }))
    if not rows:
        raise RuntimeError("CommonPlace returned zero rows — refusing to write an empty file.")
    if len(rows) < 15000:
        raise RuntimeError(
            f"CommonPlace returned only {len(rows)} rows; the file has carried "
            "roughly 20,000 for years. Refusing to write a suspiciously short build."
        )

    pts = []
    counts = {}
    dropped = {"nypd_restricted": 0, "outside_nyc": 0, "no_geom": 0, "no_type": 0}
    newest = ""

    for r in rows:
        src = (r.get("source") or "").strip()
        try:
            ti = int(float(r.get("facility_type")))
        except (TypeError, ValueError):
            dropped["no_type"] += 1
            continue
        if ti not in TYPES:
            dropped["no_type"] += 1
            continue

        # Rule 1: the data dictionary forbids redistributing NYPD common places
        # other than precinct/public-safety locations.
        if src == "NYPD" and ti != 11:
            dropped["nypd_restricted"] += 1
            continue

        geom = r.get("the_geom") or {}
        coords = geom.get("coordinates") or []
        if len(coords) != 2:
            dropped["no_geom"] += 1
            continue
        lng, lat = float(coords[0]), float(coords[1])
        if not (NYC[0] <= lat <= NYC[1] and NYC[2] <= lng <= NYC[3]):
            dropped["outside_nyc"] += 1
            continue

        name = titlecase((r.get("feature_name") or "").strip())
        if not name:
            continue

        b = r.get("bin")
        try:
            b = int(float(b))
            # 1000000/2000000/... are the city's "unknown building" placeholders.
            if b % 1000000 == 0:
                b = None
        except (TypeError, ValueError):
            b = None

        label = TYPES[ti]
        counts[label] = counts.get(label, 0) + 1
        pts.append([round(lat, 5), round(lng, 5), name, TYPE_ORDER.index(label), src, b])

        md = r.get("modified_date") or ""
        if md > newest:
            newest = md

    if len(pts) < 12000:
        raise RuntimeError(f"Only {len(pts)} points survived filtering — expected well over 12,000.")

    payload = {
        "types": TYPE_ORDER,
        "pts": sorted(pts, key=lambda p: (p[0], p[1])),
        "counts": counts,
        "dropped": dropped,
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "modified": newest[:10],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)

    kb = os.path.getsize(OUT) / 1024
    print(f"wrote {OUT} — {len(pts)} places, {kb:.0f} KB")
    print("  source rows:", len(rows))
    print("  dropped:", dropped)
    print("  newest modified_date:", newest[:10])
    for k in TYPE_ORDER:
        if counts.get(k):
            print(f"    {k:16s} {counts[k]}")


if __name__ == "__main__":
    sys.exit(main())

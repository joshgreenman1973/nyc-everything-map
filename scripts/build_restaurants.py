#!/usr/bin/env python3
"""Build docs/data/restaurants.json for the Everything Map's "Eating nearby" feature.

Source: the NYC restaurant-cuisine map project (sibling repo), which itself
aggregates the DOHMH NYC Restaurant Inspection Results (Socrata 43nn-pn8j),
one distinct establishment per CAMIS, with the city's self-reported coarse
"cuisine" label.

Output schema (compact, point-based so the map can filter by walking radius):
  {
    "cuisines": ["American", "", "Chinese", ...],   # index lookup
    "city":     [4656, 3330, 2276, ...],            # citywide count per cuisine index
    "cityTotal": 30425,
    "pts": [[lat, lng, ci, name, grade], ...]        # one row per restaurant
  }

Run:  python3 scripts/build_restaurants.py
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(
    HERE, "..", "..", "nyc-ethnic-restaurants", "data", "points.json"))
OUT = os.path.normpath(os.path.join(HERE, "..", "docs", "data", "restaurants.json"))

NYC = (40.40, 41.00, -74.30, -73.60)  # lat_min, lat_max, lng_min, lng_max


def main():
    src = json.load(open(SRC))
    cuisines = src["cuisines"]
    by_nta = src["byNta"]

    city = [0] * len(cuisines)
    pts = []
    skipped = 0
    for rows in by_nta.values():
        for r in rows:
            lat, lng, ci, name = r[0], r[1], r[2], r[3]
            grade = r[7] if len(r) > 7 else ""
            if not (NYC[0] < lat < NYC[1] and NYC[2] < lng < NYC[3]):
                skipped += 1
                continue
            city[ci] += 1
            pts.append([round(lat, 5), round(lng, 5), ci,
                        (name or "").strip(), (grade or "").strip()])

    out = {
        "cuisines": cuisines,
        "city": city,
        "cityTotal": len(pts),
        "pts": pts,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

    size = os.path.getsize(OUT) / 1024
    print(f"wrote {OUT}")
    print(f"  {len(pts)} restaurants, {len(cuisines)} cuisine labels, "
          f"{skipped} skipped (bad coords), {size:.0f} KB")


if __name__ == "__main__":
    main()

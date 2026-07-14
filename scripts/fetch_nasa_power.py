#!/usr/bin/env python3
"""Fetch NASA POWER monthly precipitation (PRECTOTCORR, mm/day) for Austria
on the native 0.5 deg grid, 1990-2024, and store as a compact JSON grid.

Output: data/nasa_power_precip.json
  {"grid": [{"lon":..,"lat":..,"monthly":{"YYYYMM": mm_per_day}}, ...]}
Note: POWER monthly API adds a 13th 'month' (YYYY13 = annual avg); we drop it.
"""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/nasa_power_precip.json"

URL = (
    "https://power.larc.nasa.gov/api/temporal/monthly/regional"
    "?parameters=PRECTOTCORR&community=ag"
    "&latitude-min=46.3&latitude-max=49.1"
    "&longitude-min=9.5&longitude-max=17.2"
    "&start=1990&end=2024&format=json"
)


def main():
    print("Fetching NASA POWER regional monthly precipitation...")
    with urllib.request.urlopen(URL, timeout=300) as r:
        d = json.loads(r.read())
    grid = []
    for f in d["features"]:
        lon, lat = f["geometry"]["coordinates"][:2]
        vals = f["properties"]["parameter"]["PRECTOTCORR"]
        monthly = {
            k: v for k, v in vals.items()
            if k[-2:] != "13" and v is not None and v >= 0
        }
        grid.append({"lon": lon, "lat": lat, "monthly": monthly})
    OUT.write_text(json.dumps({"source": "NASA POWER PRECTOTCORR (mm/day, monthly)",
                               "grid": grid}))
    print(f"Wrote {OUT}: {len(grid)} grid cells, "
          f"{len(grid[0]['monthly'])} months each")


if __name__ == "__main__":
    main()

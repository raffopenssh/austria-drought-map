#!/usr/bin/env python3
"""Build the WISE groundwater nitrate layer for Austria.

Data source: EEA Waterbase - Water Quality ICM (WISE-6 disaggregated data),
2026 release (1900-2025). The discodata SQL API deterministically times out on
any filtered/paginated query, so instead we stream-filter the full EU CSV dump
(https://sdi.eea.europa.eu/datashare/s/sptXqwkQr5g7Bp5, folder
eea_t_waterbase-water-quality-icm-2026_p_1900-2025_v01_r00) down to Austrian
groundwater nitrate/ammonium rows. That filtered CSV is checked in-repo-adjacent
at data/water_quality/at_gw_nitrate_ammonium.csv (see --refetch for how to
regenerate it); site coordinates come from the SpatialObjects dump
(data/water_quality/at_wise_spatial.csv) with a fallback to
web/data/wise_monitoring_sites.json.

Output: web/data/nitrate_stations.json(.gz)
"""
import csv
import gzip
import json
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEAS_CSV = ROOT / "data/water_quality/at_gw_nitrate_ammonium.csv.gz"
SPATIAL_CSV = ROOT / "data/water_quality/at_wise_spatial.csv"
SITES_JSON = ROOT / "web/data/wise_monitoring_sites.json"
WEB_OUT = ROOT / "web/data/nitrate_stations.json"

NITRATE = "CAS_14797-55-8"  # mg{NO3}/L

# Max sibling spread (km) accepted when approximating coordinates of sites
# missing from the spatial dumps via co-located sister wells (same GZÜV
# location prefix, i.e. identifier minus the last two digits).
MAX_SIBLING_SPREAD_KM = 10.0

# Manual fixes for sites whose *name* identifies the locality (verified by hand).
MANUAL_COORDS = {
    # "GEMEINDEBRUNNEN WVA LORETTO" -> Loretto, Bez. Eisenstadt-Umgebung, Bgld.
    "ATTG10003872": (47.909, 16.518, "GEMEINDEBRUNNEN WVA LORETTO"),
}

REFETCH_HELP = """To regenerate the filtered CSVs (needs ~2 GB free disk):
  URL='https://sdi.eea.europa.eu/datashare/public.php/webdav/eea_t_waterbase-water-quality-icm-2026_p_1900-2025_v01_r00'
  curl -u 'sptXqwkQr5g7Bp5:' -o /tmp/dis.zip "$URL/WISE6_DisaggregatedData-csv.zip"
  unzip -p /tmp/dis.zip | { head -1; grep -E '^AT,[^,]*,[^,]*,GW,CAS_(14797-55-8|14798-03-9),'; } \\
      | gzip -9 > data/water_quality/at_gw_nitrate_ammonium.csv.gz
  curl -u 'sptXqwkQr5g7Bp5:' -o /tmp/sp.zip "$URL/WISE6_SpatialObjects_DerivedData-csv.zip"
  unzip -p /tmp/sp.zip | { head -1; grep '^AT,'; } > data/water_quality/at_wise_spatial.csv
  rm /tmp/dis.zip /tmp/sp.zip
"""


def load_coords():
    coords = {}
    # Fallback first: WFD monitoring sites GeoJSON (lower priority)
    if SITES_JSON.exists():
        gj = json.loads(SITES_JSON.read_text())
        for ft in gj.get("features", []):
            sid = ft["properties"].get("id")
            lon, lat = ft["geometry"]["coordinates"][:2]
            if sid:
                coords[sid] = (lat, lon, ft["properties"].get("name"))
    # Primary: WISE-6 spatial objects dump
    if SPATIAL_CSV.exists():
        with open(SPATIAL_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                sid = row.get("monitoringSiteIdentifier") or row.get("thematicIdIdentifier")
                try:
                    lat, lon = float(row["lat"]), float(row["lon"])
                except (ValueError, KeyError):
                    continue
                if sid:
                    coords[sid] = (lat, lon, row.get("monitoringSiteName") or None)
    return coords


def approx_from_siblings(sid, coords):
    """Estimate coordinates for a site absent from the spatial dumps using
    sister wells: GZÜV identifiers minus their final two digits denote the
    same measurement location (e.g. ATPG40405012 ~ ATPG40405022/-32/-42).
    Returns (lat, lon, err_km) or None if no siblings / spread too large."""
    import math

    key = sid[:10]
    sibs = [v for k, v in coords.items() if k.startswith(key) and k != sid]
    if not sibs:
        return None
    lat = statistics.median(p[0] for p in sibs)
    lon = statistics.median(p[1] for p in sibs)
    err = max(
        (
            111.3
            * math.hypot(p[0] - lat, (p[1] - lon) * math.cos(math.radians(lat)))
            for p in sibs
        ),
        default=0.0,
    )
    if err > MAX_SIBLING_SPREAD_KM:
        return None
    return lat, lon, max(err, 0.5)


def theil_sen(xs, ys):
    slopes = [
        (ys[j] - ys[i]) / (xs[j] - xs[i])
        for i in range(len(xs))
        for j in range(i + 1, len(xs))
        if xs[j] != xs[i]
    ]
    return statistics.median(slopes) if slopes else None


def main():
    if "--refetch" in sys.argv or not MEAS_CSV.exists():
        print(REFETCH_HELP)
        if not MEAS_CSV.exists():
            sys.exit(f"missing {MEAS_CSV}")
        return

    coords = load_coords()
    print(f"{len(coords)} sites with coordinates")

    # site -> year -> [values]
    per_site = defaultdict(lambda: defaultdict(list))
    latest = {}  # site -> (yyyymmdd, value)
    n_rows = 0
    with gzip.open(MEAS_CSV, "rt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["observedPropertyDeterminandCode"] != NITRATE:
                continue
            v = row["resultObservedValue"]
            d = row["phenomenonTimeSamplingDate"]
            if not v or len(d) < 4:
                continue
            v = float(v)
            if v < 0:
                continue
            if row["resultQualityObservedValueBelowLOQ"] == "1":
                # below limit of quantification: use LOQ/2 convention if LOQ known
                loq = row.get("procedureLOQValue")
                if loq:
                    v = min(v, float(loq) / 2)
            sid = row["monitoringSiteIdentifier"]
            per_site[sid][int(d[:4])].append(v)
            if sid not in latest or d > latest[sid][0]:
                latest[sid] = (d, v)
            n_rows += 1
    print(f"{n_rows} nitrate measurements at {len(per_site)} sites")

    stations = []
    no_coord = 0
    n_approx = 0
    for sid, years in per_site.items():
        approx_err = None
        c = coords.get(sid)
        if not c and sid in MANUAL_COORDS:
            c = MANUAL_COORDS[sid]
            approx_err = 1.0
            n_approx += 1
        if not c:
            est = approx_from_siblings(sid, coords)
            if est is None:
                no_coord += 1
                continue
            c = (est[0], est[1], None)
            approx_err = est[2]
            n_approx += 1
        lat, lon, name = c
        annual = {y: sum(vs) / len(vs) for y, vs in years.items()}
        ys = sorted(annual)
        vals = [annual[y] for y in ys]
        slope = theil_sen(ys, vals) if len(ys) >= 5 else None
        n_samples = sum(len(vs) for vs in years.values())
        st = {
            "id": sid,
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "n_samples": n_samples,
            "n_years": len(ys),
            "first_year": ys[0],
            "last_year": ys[-1],
            "latest": round(annual[ys[-1]], 2),   # latest annual mean
            "latest_year": ys[-1],
            "mean": round(sum(vals) / len(vals), 2),
            "trend_per_yr": round(slope, 4) if slope is not None else None,
        }
        if name and name.upper() != "NO INTERNATIONAL NAME":
            st["name"] = name
        if approx_err is not None:
            st["coord_approx"] = True
            st["coord_err_km"] = round(approx_err, 1)
        stations.append(st)
    stations.sort(key=lambda s: s["id"])
    print(
        f"{len(stations)} stations with coords "
        f"({n_approx} approximated from sibling wells, {no_coord} dropped)"
    )

    out = {
        "generated": date.today().isoformat(),
        "source": "EEA Waterbase Water Quality ICM 2026 (WISE-6 SoE disaggregated data)",
        "unit": "mg/L NO3",
        "thresholds": {"eu_drinking_water_limit": 50, "at_quality_target": 45},
        "stations": stations,
    }
    blob = json.dumps(out, separators=(",", ":"))
    WEB_OUT.write_text(blob)
    with gzip.open(str(WEB_OUT) + ".gz", "wt") as f:
        f.write(blob)
    print(f"wrote {WEB_OUT} ({len(blob)/1e6:.1f} MB) + .gz")

    # report stats
    latest_vals = [s["latest"] for s in stations]
    over50 = sum(1 for v in latest_vals if v > 50)
    print(f"median latest annual mean: {statistics.median(latest_vals):.1f} mg/L")
    print(f">50 mg/L (latest): {over50} ({100*over50/len(stations):.1f}%)")
    print(f"year range: {min(s['first_year'] for s in stations)}-{max(s['last_year'] for s in stations)}")


if __name__ == "__main__":
    main()

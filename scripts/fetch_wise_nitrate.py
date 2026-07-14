#!/usr/bin/env python3
"""Fetch actual groundwater nitrate (and ammonium) measurements for Austria
from the EEA discodata SQL API (WISE SoE / Waterbase WISE6 disaggregated data),
plus monitoring-site coordinates, and build per-station time series.

The discodata endpoint is flaky: identical queries randomly time out after
~30 s. We page with TOP/OFFSET-free `p`/`nrOfHits` pagination and retry each
page until it succeeds.

Outputs:
  data/water_quality/wise_nitrate_raw.json      raw measurements (site,date,value)
  web/data/nitrate_stations.json(.gz)           stations w/ coords, latest value,
                                                annual means, trend
"""
import gzip
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_OUT = ROOT / "data/water_quality/wise_nitrate_raw.json"
WEB_OUT = ROOT / "web/data/nitrate_stations.json"

SQL_URL = "https://discodata.eea.europa.eu/sql"
PAGE = 5000

DETERMINANDS = {
    "nitrate": "CAS_14797-55-8",   # mg{NO3}/L
    "ammonium": "CAS_14798-03-9",  # mg{NH4}/L
}


def sql(query, p=1, n=PAGE, tries=12):
    params = urllib.parse.urlencode({"query": query, "p": p, "nrOfHits": n})
    url = f"{SQL_URL}?{params}"
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                d = json.loads(r.read())
            if "results" in d and not d.get("errors"):
                return d["results"]
            err = d.get("errors")
            print(f"    retry {attempt+1}: {str(err)[:60]}", flush=True)
        except Exception as e:
            print(f"    retry {attempt+1}: {e}", flush=True)
        time.sleep(3 + attempt * 2)
    raise RuntimeError(f"query failed after {tries} tries: {query[:80]}")


def fetch_measurements(code, y0=1990, y1=2025):
    """Query per-year: the discodata server times out on large offset
    pagination, but small per-year result sets (with TOP) usually return."""
    rows = []
    for year in range(y0, y1 + 1):
        q = (
            "SELECT TOP 30000 monitoringSiteIdentifier s, "
            "phenomenonTimeSamplingDate d, "
            "resultObservedValue v, resultQualityObservedValueBelowLOQ loq "
            "FROM [WISE_SOE].[latest].[Waterbase_T_WISE6_DisaggregatedData] "
            f"WHERE countryCode='AT' AND observedPropertyDeterminandCode='{code}' "
            "AND parameterWaterBodyCategory='GW' "
            f"AND phenomenonTimeReferenceYear={year}"
        )
        page = sql(q, p=1, n=30000)
        rows.extend(page)
        print(f"  {year}: +{len(page)} (total {len(rows)})", flush=True)
    return rows


def fetch_sites():
    q = (
        "SELECT monitoringSiteIdentifier s, monitoringSiteName nm, lon, lat "
        "FROM [WISE_SOE].[latest].[Waterbase_S_WISE_SpatialObject_DerivedData] "
        "WHERE countryCode='AT' AND monitoringSiteIdentifier IS NOT NULL"
    )
    rows, p = [], 1
    while True:
        page = sql(q, p=p)
        rows.extend(page)
        print(f"  sites page {p}: +{len(page)}", flush=True)
        if len(page) < PAGE:
            break
        p += 1
    return {r["s"]: r for r in rows}


def theil_sen_ish(years, vals):
    """Simple OLS slope (mg/L per year); enough data points per station is small."""
    n = len(years)
    if n < 3:
        return None
    mx = sum(years) / n
    my = sum(vals) / n
    denom = sum((x - mx) ** 2 for x in years)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(years, vals)) / denom


def main():
    print("Fetching site coordinates...", flush=True)
    sites = fetch_sites()
    print(f"{len(sites)} AT monitoring sites with metadata")

    raw = {}
    for name, code in DETERMINANDS.items():
        print(f"Fetching {name} ({code})...", flush=True)
        raw[name] = fetch_measurements(code)
        print(f"{name}: {len(raw[name])} measurements")

    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(json.dumps(raw))
    print(f"Wrote {RAW_OUT}")

    # Build per-station summary for nitrate (primary) + ammonium latest
    stations = {}
    for name in DETERMINANDS:
        by_site = defaultdict(list)
        for r in raw[name]:
            v = r.get("v")
            if v is None:
                continue
            d = (r.get("d") or "")[:10]
            if not d:
                continue
            by_site[r["s"]].append((d, float(v), bool(r.get("loq"))))
        for sid, meas in by_site.items():
            meas.sort()
            st = stations.setdefault(sid, {"id": sid})
            meta = sites.get(sid)
            if meta:
                st["name"] = meta.get("nm") or sid
                st["lon"] = meta.get("lon")
                st["lat"] = meta.get("lat")
            # annual means
            years = defaultdict(list)
            for d, v, loq in meas:
                years[int(d[:4])].append(v)
            annual = {y: round(sum(vs) / len(vs), 2) for y, vs in sorted(years.items())}
            last_d, last_v, _ = meas[-1]
            yrs = sorted(annual)
            vals = [annual[y] for y in yrs]
            slope = theil_sen_ish(yrs, vals)
            st[name] = {
                "n": len(meas),
                "latest": {"date": last_d, "value": round(last_v, 2)},
                "annual": annual,
                "trend_per_yr": round(slope, 3) if slope is not None else None,
                "mean_recent5": round(
                    sum(vals[-5:]) / len(vals[-5:]), 2
                ) if vals else None,
            }

    out = {
        "source": "EEA WISE SoE (Waterbase WISE6 disaggregated), discodata.eea.europa.eu",
        "units": {"nitrate": "mg NO3/L", "ammonium": "mg NH4/L"},
        "thresholds": {"nitrate_drinking_limit": 50, "nitrate_threshold_at": 45},
        "n_stations": len(stations),
        "stations": [s for s in stations.values() if s.get("lon") is not None],
    }
    WEB_OUT.write_text(json.dumps(out))
    with gzip.open(str(WEB_OUT) + ".gz", "wt") as f:
        f.write(json.dumps(out))
    n_geo = len(out["stations"])
    print(f"Wrote {WEB_OUT}: {len(stations)} stations, {n_geo} with coords")


if __name__ == "__main__":
    main()

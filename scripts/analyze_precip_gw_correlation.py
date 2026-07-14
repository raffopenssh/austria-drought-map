#!/usr/bin/env python3
"""Correlate NASA POWER precipitation with groundwater level changes.

For each GW station with a monthly-mean time series (data/gw/Grundwasserstand-
Monatsmittel/*.csv, eHYD export format), find the nearest NASA POWER 0.5-deg
grid cell and compute:

  - Pearson r between 12-month rolling precipitation sum and GW level
    (both z-scored), at lags 0..24 months (precip leads GW)
  - best lag and r at best lag
  - recent divergence: GW z-score minus precip z-score over the last 5 years
    (positive = GW doing better than precipitation would suggest;
     negative = GW declining faster than precipitation explains,
     hinting at abstraction/structural loss)

Outputs:
  web/data/precip_gw_correlation.json(.gz)  per-station results + national summary
"""
import gzip
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GW_DIR = ROOT / "data/gw/Grundwasserstand-Monatsmittel"
POWER = ROOT / "data/nasa_power_precip.json"
TRENDS = ROOT / "web/data/gw_stations_trends.json"
OUT = ROOT / "web/data/precip_gw_correlation.json"

START, END = 1990, 2024


def parse_gw_csv(path):
    """Return {(year,month): level} from eHYD monthly-mean export."""
    vals = {}
    in_data = False
    with open(path, encoding="iso-8859-1") as f:
        for line in f:
            if not in_data:
                if line.startswith("Werte:"):
                    in_data = True
                continue
            parts = line.split(";")
            if len(parts) < 2:
                continue
            ds = parts[0].strip()
            vs = parts[1].strip().replace(",", ".")
            if not ds or not vs or vs.startswith("L"):  # Lücke
                continue
            try:
                day, mon, rest = ds.split(".")
                year = int(rest.split()[0])
                v = float(vs)
            except ValueError:
                continue
            if START <= year <= END:
                vals[(year, int(mon))] = v
    return vals


def month_range():
    return [(y, m) for y in range(START, END + 1) for m in range(1, 13)]


def zscore(xs):
    valid = [x for x in xs if x is not None]
    if len(valid) < 24:
        return None
    mu = sum(valid) / len(valid)
    sd = math.sqrt(sum((x - mu) ** 2 for x in valid) / len(valid))
    if sd == 0:
        return None
    return [None if x is None else (x - mu) / sd for x in xs]


def pearson(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if n < 36:
        return None, 0
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    if sxx == 0 or syy == 0:
        return None, n
    return sxy / math.sqrt(sxx * syy), n


def main():
    power = json.loads(POWER.read_text())["grid"]
    trends = {s["id"]: s for s in json.loads(TRENDS.read_text())}
    months = month_range()

    # Precompute per-cell 12-month rolling precip sums (mm), z-scored
    days_in = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    cell_roll = []
    for c in power:
        mm = []
        for (y, m) in months:
            v = c["monthly"].get(f"{y}{m:02d}")
            mm.append(None if v is None else v * days_in[m - 1])
        roll = []
        for i in range(len(mm)):
            w = mm[max(0, i - 11): i + 1]
            if len(w) == 12 and all(x is not None for x in w):
                roll.append(sum(w))
            else:
                roll.append(None)
        cell_roll.append({"lon": c["lon"], "lat": c["lat"], "z": zscore(roll)})

    def nearest_cell(lon, lat):
        best, bd = None, 1e9
        for c in cell_roll:
            d = (c["lon"] - lon) ** 2 + ((c["lat"] - lat) * 1.4) ** 2
            if d < bd:
                bd, best = d, c
        return best

    results = []
    files = sorted(GW_DIR.glob("*.csv"))
    print(f"{len(files)} GW station files")
    for i, path in enumerate(files):
        sid = path.stem.split("-")[-1]
        meta = trends.get(sid)
        if not meta or meta.get("lon") is None:
            continue
        gw = parse_gw_csv(path)
        series = [gw.get(ym) for ym in months]
        gz = zscore(series)
        if gz is None:
            continue
        cell = nearest_cell(meta["lon"], meta["lat"])
        if cell is None or cell["z"] is None:
            continue
        pz = cell["z"]
        best_r, best_lag, n_used = None, None, 0
        for lag in range(0, 25):
            # precip leads: correlate pz[t-lag] with gz[t]
            shifted = [None] * lag + pz[: len(pz) - lag]
            r, n = pearson(shifted, gz)
            if r is not None and (best_r is None or r > best_r):
                best_r, best_lag, n_used = r, lag, n
        if best_r is None:
            continue
        # recent divergence (last 60 months, at best lag)
        recent = []
        for t in range(len(months) - 60, len(months)):
            pt = t - best_lag
            if 0 <= pt < len(pz) and pz[pt] is not None and gz[t] is not None:
                recent.append(gz[t] - pz[pt])
        divergence = round(sum(recent) / len(recent), 2) if len(recent) >= 24 else None
        results.append({
            "id": sid,
            "name": meta.get("name"),
            "lon": meta["lon"], "lat": meta["lat"],
            "r": round(best_r, 3),
            "lag_months": best_lag,
            "n_months": n_used,
            "divergence_5yr": divergence,
        })
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(files)} processed, {len(results)} results")

    rs = [s["r"] for s in results]
    lags = [s["lag_months"] for s in results]
    divs = [s["divergence_5yr"] for s in results if s["divergence_5yr"] is not None]
    summary = {
        "n_stations": len(results),
        "median_r": round(sorted(rs)[len(rs) // 2], 3) if rs else None,
        "median_lag_months": sorted(lags)[len(lags) // 2] if lags else None,
        "share_r_above_0.3": round(sum(1 for r in rs if r > 0.3) / len(rs), 3) if rs else None,
        "median_divergence_5yr": round(sorted(divs)[len(divs) // 2], 3) if divs else None,
        "share_negative_divergence": round(
            sum(1 for d in divs if d < -0.25) / len(divs), 3) if divs else None,
    }
    out = {
        "method": ("Pearson r between z-scored 12-month rolling NASA POWER "
                   "precipitation sum (nearest 0.5deg cell) and z-scored monthly "
                   "GW level, best lag 0-24 months (precip leads). "
                   "divergence_5yr = mean(GW z - precip z) over last 60 months; "
                   "negative = GW lower than precipitation explains."),
        "period": f"{START}-{END}",
        "summary": summary,
        "stations": results,
    }
    OUT.write_text(json.dumps(out))
    with gzip.open(str(OUT) + ".gz", "wt") as f:
        f.write(json.dumps(out))
    print(f"Wrote {OUT}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

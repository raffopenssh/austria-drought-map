#!/usr/bin/env python3
"""Latest measured groundwater state per live eHYD station (GW-4 'now' block).

Input : data/gw_aktuell/daily_levels.json + longterm_<year>.json (fetch_ehyd_live.py,
        daily cron), data/gw/messstellen_gw.csv (ground elevation gokmua05).
Output: web/data/gw_now.json  {as_of, stations:{hzb:{lon,lat,name,as_of,level_m,
        anomaly_sigma, percentile, trend_30d_cm, gok_m, depth_m}}}
anomaly_sigma = (latest - day-of-year climatological mean) / sigma, with sigma
estimated from the p5-p95 band ((p95-p5)/3.29). percentile is a piecewise-linear
position of the latest value within min/p5/mean/p95/max of that day (0-100).
"""
import json, gzip, csv, datetime, glob
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AKT = ROOT / "data/gw_aktuell"
OUT = ROOT / "web/data/gw_now.json"


def pct(v, mn, p5, mean, p95, mx):
    pts = [(mn, 0), (p5, 5), (mean, 50), (p95, 95), (mx, 100)]
    pts = [(a, b) for a, b in pts if a is not None]
    if not pts:
        return None
    if v <= pts[0][0]:
        return 0.0
    for (a0, b0), (a1, b1) in zip(pts, pts[1:]):
        if v <= a1:
            return round(b0 + (b1 - b0) * (v - a0) / (a1 - a0), 1) if a1 > a0 else float(b1)
    return 100.0


def main():
    daily = json.load(open(AKT / "daily_levels.json"))
    lt_files = sorted(glob.glob(str(AKT / "longterm_*.json")))
    longterm = json.load(open(lt_files[-1])) if lt_files else {}
    gok = {}
    with open(ROOT / "data/gw/messstellen_gw.csv", encoding="latin-1") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                gok[row["hzbnr01"].strip()] = float(row["gokmua05"].replace(",", "."))
            except (ValueError, KeyError):
                pass
    stations, newest = {}, None
    for hzb, rec in daily.items():
        lv = rec.get("levels") or {}
        if not lv:
            continue
        dates = sorted(lv)
        d_last = dates[-1]
        v = lv[d_last]
        newest = max(newest or d_last, d_last)
        s = {"lon": rec["coords"][0], "lat": rec["coords"][1], "name": rec.get("name"),
             "state": rec.get("bundesland"), "as_of": d_last, "level_m": v}
        # 30-day trend
        d0 = (datetime.date.fromisoformat(d_last) - datetime.timedelta(days=30)).isoformat()
        past = [d for d in dates if d <= d0]
        if past:
            s["trend_30d_cm"] = round((v - lv[past[-1]]) * 100, 1)
        lt = longterm.get(hzb)
        if lt and lt.get("points_in_time_historisch"):
            try:
                i = lt["points_in_time_historisch"].index(d_last)
                g = lambda k: (lt.get(k) or [None])[i] if lt.get(k) and i < len(lt[k]) else None
                mean, p5, p95, mn, mx = g("mit_data"), g("p5_data"), g("p95_data"), g("min_data"), g("max_data")
                if mean is not None and p5 is not None and p95 is not None and p95 > p5:
                    sigma = (p95 - p5) / 3.29
                    s["anomaly_sigma"] = round((v - mean) / sigma, 2)
                    s["percentile"] = pct(v, mn, p5, mean, p95, mx)
                    s["clim_mean_m"] = mean
                s["clim_years"] = [lt.get("data_from"), lt.get("data_till")]
            except ValueError:
                pass
        if hzb in gok:
            s["gok_m"] = gok[hzb]
            s["depth_m"] = round(gok[hzb] - v, 2)
        stations[hzb] = s
    out = {"as_of": newest, "generated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "eHYD GrundwasserAktuell + grundwasserLongtermBgis (daily); climatology = station record",
           "n_stations": len(stations), "stations": stations}
    blob = json.dumps(out, separators=(",", ":"))
    OUT.write_text(blob)
    with gzip.open(str(OUT) + ".gz", "wt") as f:
        f.write(blob)
    n_an = sum(1 for s in stations.values() if "anomaly_sigma" in s)
    print(f"{len(stations)} stations, {n_an} with anomaly, as_of {newest}, {len(blob)/1e3:.0f} KB")


if __name__ == "__main__":
    main()

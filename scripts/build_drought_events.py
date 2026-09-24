#!/usr/bin/env python3
"""Per-Gemeinde drought calendar from the dekadal EDO CDI series (GW-3).

Input : web/data/edo_municipality_timeseries.json (47 MB, 2012-2023, 36 dekads/yr,
        CDI class 0 none, 1 watch, 2 warning, 3 alert, 4-6 recovery classes).
Output: web/data/edo_drought_events.json (compact) with per gemeinde:
  p_drought_year  share of years with >=1 month whose mean CDI class >= 2 (warning)
  worst_year      year with the highest monthly-mean CDI
  season_profile  12 x mean CDI class (0-3, recovery classes count as 0) per month
  events          [{year,start_month,end_month,cdi_max,class}] runs of months >= watch
"""
import json, gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "web/data"
CLS = {1: "watch", 2: "warning", 3: "alert"}


def drought_class(v):
    # recovery classes (4-6) mean the drought is ending -> not a drought class
    return v if v is not None and v <= 3 else 0


def main():
    src = json.load(open(DATA / "edo_municipality_timeseries.json"))
    munis = src["municipalities"]
    out = {}
    for gem, years in munis.items():
        ys = sorted(years)
        # monthly mean class (max of the ~3 dekads' area-mean class, then class-rounded)
        monthly = {}  # (year, month) -> mean dekadal 'mean' value, capped at 3
        for y in ys:
            per_m = {}
            for d in years[y]:
                m = int(d["date"][5:7])
                per_m.setdefault(m, []).append(drought_class(d.get("mean")))
            for m, vals in per_m.items():
                monthly[(int(y), m)] = sum(vals) / len(vals)
        if not monthly:
            continue
        season = [[] for _ in range(12)]
        for (y, m), v in monthly.items():
            season[m - 1].append(v)
        season_profile = [round(sum(s) / len(s), 2) if s else None for s in season]
        year_max = {}
        for (y, m), v in monthly.items():
            year_max[y] = max(year_max.get(y, 0), v)
        n_years = len(year_max)
        p_dry = sum(1 for v in year_max.values() if v >= 1.5) / n_years
        worst = max(year_max, key=year_max.get) if year_max else None
        # events: runs of consecutive months with rounded class >= 1 (watch)
        events, cur = [], None
        for (y, m) in sorted(monthly):
            c = int(round(monthly[(y, m)]))
            if c >= 1:
                if cur and (y, m) == cur["_next"]:
                    cur["end_month"] = m
                    cur["_next"] = (y, m + 1) if m < 12 else (y + 1, 1)
                    cur["cdi_max"] = max(cur["cdi_max"], c)
                    if y != cur["year"]:
                        cur["end_year"] = y
                else:
                    if cur:
                        events.append(cur)
                    cur = {"year": y, "start_month": m, "end_month": m, "cdi_max": c,
                           "_next": (y, m + 1) if m < 12 else (y + 1, 1)}
            else:
                if cur:
                    events.append(cur)
                    cur = None
        if cur:
            events.append(cur)
        for e in events:
            e.pop("_next")
            e["class"] = CLS.get(min(3, e["cdi_max"]), "watch")
        out[gem] = {"years": [int(ys[0]), int(ys[-1])], "p_drought_year": round(p_dry, 3),
                    "worst_year": worst, "season_profile": season_profile,
                    "events": events}
    meta = {"source": src["metadata"].get("source"), "indicator": src["metadata"].get("indicator"),
            "scale": "monthly mean of dekadal CDI class 0 none/1 watch/2 warning/3 alert; recovery classes counted as 0",
            "p_drought_year_rule": "share of years with >=1 month of monthly-mean class >= 1.5 (warning)",
            "period": src["metadata"].get("period")}
    blob = json.dumps({"meta": meta, "gemeinden": out}, separators=(",", ":"))
    (DATA / "edo_drought_events.json").write_text(blob)
    with gzip.open(DATA / "edo_drought_events.json.gz", "wt") as f:
        f.write(blob)
    print(f"{len(out)} gemeinden, {len(blob)/1e6:.2f} MB")
    print(json.dumps(out.get("61611"), indent=None)[:600])


if __name__ == "__main__":
    main()

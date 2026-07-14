#!/usr/bin/env python3
"""Groundwater Status Index (GWI) — the single model behind the GW Power app.

Evaluated at every Katastralgemeinde (KG) centroid and aggregated per Gemeinde
for the choropleth. Higher = more stressed groundwater (0..1).

Components (weights renormalized over available components):

  QUANTITY (50%)
    trend  (35%)  IDW mean of eHYD station 10-yr level trend (m/decade),
                  stations within 12.5 km (fallback: nearest 3 <= 30 km,
                  flagged estimated).  risk = clamp(-trend / 0.50)
                  (-0.50 m/decade or worse = max risk; rising = 0)
    diverg (15%)  IDW mean of 5-yr precip-vs-GW divergence (sigma units,
                  from analyze_precip_gw_correlation.py; negative = level
                  below what precipitation explains -> abstraction /
                  structural loss).  risk = clamp(-div / 1.5)

  QUALITY (35%)
    nitrate (25%) IDW mean of latest annual-mean nitrate (WISE-6, stations
                  reporting since >= 2015, within 12.5 km / nearest 3
                  <= 30 km).  risk = clamp(latest / 50 mg/L)  (EU limit)
    wfd     (10%) WFD 2022 chemical+eco status of water bodies near the
                  Gemeinde (existing wq_risk, 0..1)

  DROUGHT PRESSURE (15%)
    edo           Copernicus EDO Combined Drought Indicator mean class of
                  the Gemeinde, 2012-2023.  risk = clamp(cdi_mean / 2)

Categories: good < 0.30 <= watch < 0.50 <= stressed.
(Trend scale calibrated so the national distribution is ~27/41/32%;
-0.5 m/decade sustained decline is a severe loss for shallow aquifers.)

Outputs:
  web/data/gw_index_kg.json(.gz)   per-KG record (compact keys, see KEYS)
  merges gwi_* fields into web/data/municipalities.json and
  web/data/municipalities_risk.geojson(.gz) for the choropleth.
"""
import gzip
import json
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "web/data"

R_NEAR_KM = 12.5      # primary radius
R_FALLBACK_KM = 30.0  # nearest-3 fallback radius (flagged estimated)
W = {"trend": 0.35, "div": 0.15, "nitrate": 0.25, "wfd": 0.10, "edo": 0.15}
CAT = [(0.30, "good"), (0.50, "watch"), (10, "stressed")]

KEYS = {
    "i": "gwi 0-1 (higher = more stressed)",
    "c": "category good|watch|stressed",
    "q_trend": "quantity: trend sub-risk 0-1",
    "q_div": "quantity: precip-divergence sub-risk 0-1",
    "q_nitrate": "quality: nitrate sub-risk 0-1",
    "q_wfd": "quality: WFD status sub-risk 0-1",
    "q_edo": "drought: EDO CDI sub-risk 0-1",
    "gw_trend": "IDW GW level trend m/decade (neg = declining)",
    "gw_div": "IDW 5-yr divergence sigma (neg = below precip-explained)",
    "no3": "IDW latest nitrate mg/L",
    "n_gw": "# GW stations used", "n_no3": "# nitrate stations used",
    "est": "1 = fallback radius used for >=1 component",
}


def idw(vals, d_km):
    w = 1.0 / (1.0 + d_km)
    return float(np.sum(vals * w) / np.sum(w))


class Field:
    """IDW field over stations: query(latlon) -> (value, n, estimated)|None"""

    def __init__(self, lats, lons, vals):
        self.lat = np.asarray(lats)
        self.lon = np.asarray(lons)
        self.val = np.asarray(vals, dtype=float)

    def query(self, lat, lon):
        coslat = np.cos(np.radians(lat))
        d = np.hypot((self.lat - lat) * 111.32,
                     (self.lon - lon) * 111.32 * coslat)
        near = d <= R_NEAR_KM
        if near.sum() >= 1:
            return idw(self.val[near], d[near]), int(near.sum()), False
        k = np.argsort(d)[:3]
        if d[k[0]] <= R_FALLBACK_KM:
            k = k[d[k] <= R_FALLBACK_KM]
            return idw(self.val[k], d[k]), int(len(k)), True
        return None


def clamp(x):
    return max(0.0, min(1.0, x))


def main():
    kg_reg = json.loads((DATA / "kg_registry.json").read_text())
    munis = json.loads((DATA / "municipalities.json").read_text())
    gem = {str(m["iso"]).zfill(5): m for m in munis}

    gw = [s for s in json.loads((DATA / "gw_stations_trends.json").read_text())
          if s.get("lat") and s.get("trend_m_per_decade") is not None]
    f_trend = Field([s["lat"] for s in gw], [s["lon"] for s in gw],
                    [s["trend_m_per_decade"] for s in gw])

    div = [s for s in json.loads((DATA / "precip_gw_correlation.json").read_text())["stations"]
           if s.get("divergence_5yr") is not None]
    f_div = Field([s["lat"] for s in div], [s["lon"] for s in div],
                  [s["divergence_5yr"] for s in div])

    no3 = [s for s in json.loads((DATA / "nitrate_stations.json").read_text())["stations"]
           if s.get("latest") is not None and s.get("last_year", 0) >= 2015]
    f_no3 = Field([s["lat"] for s in no3], [s["lon"] for s in no3],
                  [s["latest"] for s in no3])

    print(f"fields: {len(gw)} gw-trend, {len(div)} divergence, {len(no3)} nitrate(>=2015)")

    out = {}
    for code, k in kg_reg.items():
        lat, lon = k["lat"], k["lon"]
        m = gem.get(k["g"])
        rec, comps, est = {}, {}, False

        q = f_trend.query(lat, lon)
        if q:
            v, n, e = q
            comps["trend"] = clamp(-v / 0.50)
            rec.update(gw_trend=round(v, 3), n_gw=n)
            est |= e
        q = f_div.query(lat, lon)
        if q:
            v, n, e = q
            comps["div"] = clamp(-v / 1.5)
            rec["gw_div"] = round(v, 2)
            est |= e
        q = f_no3.query(lat, lon)
        if q:
            v, n, e = q
            comps["nitrate"] = clamp(v / 50.0)
            rec.update(no3=round(v, 1), n_no3=n)
            est |= e
        if m and m.get("wq_gw_stations"):          # WFD only where GW bodies monitored
            comps["wfd"] = clamp(m.get("wq_risk", 0.0))
        if m and m.get("edo_cdi_mean") is not None:
            comps["edo"] = clamp(m["edo_cdi_mean"] / 2.0)

        if not comps:
            continue
        wsum = sum(W[c] for c in comps)
        gwi = sum(W[c] * comps[c] for c in comps) / wsum
        rec["i"] = round(gwi, 4)
        rec["c"] = next(name for th, name in CAT if gwi < th)
        for c, v in comps.items():
            rec[f"q_{c}"] = round(v, 3)
        if est:
            rec["est"] = 1
        out[code] = rec

    vals = np.array([r["i"] for r in out.values()])
    print(f"{len(out)} KGs | gwi p10/p50/p90 = "
          f"{np.percentile(vals,10):.3f}/{np.percentile(vals,50):.3f}/{np.percentile(vals,90):.3f}")
    for th, name in CAT:
        print(f"  {name}: {sum(1 for r in out.values() if r['c']==name)}")

    blob = json.dumps({"generated": date.today().isoformat(),
                       "weights": W, "keys": KEYS, "kgs": out},
                      separators=(",", ":"))
    (DATA / "gw_index_kg.json").write_text(blob)
    with gzip.open(DATA / "gw_index_kg.json.gz", "wt") as f:
        f.write(blob)
    print(f"wrote gw_index_kg.json ({len(blob)/1e6:.1f} MB)")

    # ---- Gemeinde aggregation (mean over its KGs) for the choropleth ----
    per_gem = {}
    for code, rec in out.items():
        per_gem.setdefault(kg_reg[code]["g"], []).append(rec)
    n_match = 0
    for gcode, m in gem.items():
        recs = per_gem.get(gcode)
        if not recs:
            for f in ("gwi", "gwi_category"):
                m.pop(f, None)
            continue
        gwi = float(np.mean([r["i"] for r in recs]))
        m["gwi"] = round(gwi, 4)
        m["gwi_category"] = next(name for th, name in CAT if gwi < th)
        for comp in ("q_trend", "q_div", "q_nitrate", "q_wfd", "q_edo"):
            cv = [r[comp] for r in recs if comp in r]
            if cv:
                m["gwi_" + comp] = round(float(np.mean(cv)), 3)
        for raw in ("gw_trend", "gw_div", "no3"):
            cv = [r[raw] for r in recs if raw in r]
            if cv:
                m["gwi_" + raw] = round(float(np.mean(cv)), 3)
        n_match += 1
    (DATA / "municipalities.json").write_text(json.dumps(munis))
    print(f"gemeinden with gwi: {n_match}/{len(gem)}")

    gj = json.loads((DATA / "municipalities_risk.geojson").read_text())
    for feat in gj["features"]:
        p = feat["properties"]
        mm = None
        if p.get("iso"):
            mm = gem.get(str(p["iso"]).zfill(5))
        if mm is None:
            mm = next((m for m in munis if m["name"] == p.get("name")), None)
        if mm:
            for f in ("gwi", "gwi_category", "gwi_q_trend", "gwi_q_div",
                      "gwi_q_nitrate", "gwi_q_wfd", "gwi_q_edo",
                      "gwi_gw_trend", "gwi_no3"):
                if f in mm:
                    p[f] = mm[f]
    blob = json.dumps(gj)
    (DATA / "municipalities_risk.geojson").write_text(blob)
    with gzip.open(DATA / "municipalities_risk.geojson.gz", "wt") as f:
        f.write(blob)
    print("choropleth updated")


if __name__ == "__main__":
    main()

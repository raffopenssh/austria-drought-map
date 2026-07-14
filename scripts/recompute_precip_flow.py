#!/usr/bin/env python3
"""Recompute per-municipality precipitation & flow fields after coordinate fix.

Does NOT touch risk_score/risk_category (final model = GW 35% / Hydro 25% /
EDO 25% / Soil 15%). Only refreshes the display fields that were derived
from mis-projected station coordinates:
  precip_trend_mm, precip_mean_mm, precip_stations, precip_estimated, precip_risk
  flow_trend_pct, flow_mean_m3s, flow_stations, flow_rivers, flow_estimated,
  flow_risk, flow_hydro_mw, flow_sediment_trend
"""
import json, math, gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1); dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def nearby(muni, stations, max_dist_km):
    near = [{**s, 'dist': haversine(muni['lat'], muni['lon'], s['lat'], s['lon'])} for s in stations]
    within = [s for s in near if s['dist'] <= max_dist_km]
    if within:
        return within, False
    near.sort(key=lambda x: x['dist'])
    return near[:3], True

def idw(items, key):
    tw = sum(1/(1+s['dist']) for s in items)
    return sum(s[key]/(1+s['dist']) for s in items) / tw

def main():
    muni = json.loads((ROOT/'web/data/municipalities.json').read_text())
    flow = [f for f in json.loads((ROOT/'data/flow_analysis.json').read_text()) if f.get('lat')]
    precip = [p for p in json.loads((ROOT/'data/precipitation_analysis.json').read_text()) if p.get('lat')]
    plants = json.loads((ROOT/'web/data/powerplants.json').read_text())
    sediment = json.loads((ROOT/'data/sediment_analysis.json').read_text())

    for m in muni:
        # precipitation
        near, est = nearby(m, precip, 25)
        t = idw(near, 'trend_mm_decade'); mean = idw(near, 'mean_annual_mm')
        m['precip_trend_mm'] = round(t, 1)
        m['precip_mean_mm'] = round(mean)
        m['precip_stations'] = len(near)
        m['precip_estimated'] = est
        m['precip_risk'] = round(min(1.0, abs(t)/100), 3) if t < 0 else 0.0

        # flow
        near, est = nearby(m, flow, 30)
        t = idw(near, 'trend_pct_decade'); mf = idw(near, 'mean_flow_m3s')
        rivers = list(dict.fromkeys(f['river'] for f in near if f.get('river')))[:4]
        m['flow_trend_pct'] = round(t, 1)
        m['flow_mean_m3s'] = round(mf, 1)
        m['flow_stations'] = len(near)
        m['flow_rivers'] = rivers
        m['flow_estimated'] = est
        m['flow_risk'] = round(min(1.0, abs(t)/20), 3) if t < 0 else 0.0
        m['flow_hydro_mw'] = sum((p.get('mw') or 0) for p in plants
                                 if p.get('river') in rivers and
                                 haversine(m['lat'], m['lon'], p['lat'], p['lon']) <= 50)
        sed = [s['trend_pct'] for s in sediment if s.get('river') in rivers]
        m['flow_sediment_trend'] = round(sum(sed)/len(sed), 1) if sed else None

    out = ROOT/'web/data/municipalities.json'
    out.write_text(json.dumps(muni, ensure_ascii=False))
    with gzip.open(str(out)+'.gz', 'wt', encoding='utf-8') as f:
        json.dump(muni, f, ensure_ascii=False)
    est_p = sum(1 for m in muni if m['precip_estimated'])
    est_f = sum(1 for m in muni if m['flow_estimated'])
    print(f"Updated {len(muni)} municipalities (precip estimated: {est_p}, flow estimated: {est_f})")

if __name__ == '__main__':
    main()

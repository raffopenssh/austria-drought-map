#!/usr/bin/env python3
"""Build web/data/plant_profiles.json: per-plant detail for the hydropower modal.

Per plant:
  meta        - name, type, MW, river, lat/lon, release source (a73/downscaled), calib_r
  gen         - last 365 days of daily turbined energy (MWh): {d0, vals[]}
                a73 plants: summed unit data; others: downscaled from national
                PSR-type aggregate (same method as analyze_plant_downstream.py)
  gw / pegel  - downstream monitoring points from plant_influence.json, river
                gauges enriched with long-term flow trend (flow_analysis.json,
                OWF Q-Tagesmittel) and sediment-transport trend
                (sediment_analysis.json, OWF Schwebstoff)
Shared:
  reservoir   - ENTSO-E AT-wide reservoir storage (weekly stored energy MWh):
                full weekly series (since 2015) + latest value + this-week
                percentile vs. same calendar week of previous years.
"""
import json, csv, datetime
from collections import defaultdict
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from entsoe_plants import PLANTS, PSR_LABEL, PSR_ENTSOE

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

# ---- releases (same logic as analyze_plant_downstream) ----
plant_day = defaultdict(dict)
for r in csv.DictReader(open('data/plant_daily_mwh.csv')):
    plant_day[r['plant']][r['day']] = float(r['mwh'])
nat = defaultdict(dict)
for r in csv.DictReader(open('data/hydro_daily_mwh.csv')):
    nat[r['psr_type']][r['day']] = float(r['mwh'])

def series_for(pid):
    p = PLANTS[pid]
    live = defaultdict(float)
    for u in p['units']:
        for d, v in plant_day.get(u, {}).items():
            live[d] += v
    if len([d for d in live if d >= '2026-01-01']) > 120:
        return dict(live), 'a73', None
    natser = nat[PSR_ENTSOE[p['psr']]]
    days = sorted(set(live) & set(natser))
    if len(days) >= 180:
        y = np.array([live[d] for d in days]); x = np.array([natser[d] for d in days])
        X = np.column_stack([np.ones(len(x)), x])
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        r = float(np.corrcoef(x, y)[0, 1])
        return {d: max(0.0, b[0] + b[1] * v) for d, v in natser.items()}, 'downscaled', round(r, 3)
    share = p['mw'] / sum(q['mw'] for q in PLANTS.values() if q['psr'] == p['psr'])
    return {d: v * share for d, v in natser.items()}, 'mw_share', None

# ---- downstream context ----
pinf = json.load(open('web/data/plant_influence.json'))
flow = {s['hzb']: s for s in json.load(open('web/data/flow_analysis.json'))}
sed = {s['hzb']: s for s in json.load(open('web/data/sediment_analysis.json'))}

gw_by_plant = defaultdict(list)
for l in pinf['gw_links_sig']:
    gw_by_plant[l['plant']].append({k: l[k] for k in ('station', 'name', 'km', 'partial', 'p', 'beta_sum')})
peg_by_plant = defaultdict(list)
for l in pinf['pegel_links']:
    e = {k: l[k] for k in ('station', 'name', 'river', 'km', 'partial', 'p', 'sig', 'beta_sum')}
    f = flow.get(l['station'])
    if f:
        e['flow'] = {'mean_m3s': f['mean_flow_m3s'], 'trend_pct_decade': f['trend_pct_decade'],
                     'years': f['years_data'], 'catchment_km2': f['catchment_km2']}
    s = sed.get(l['station'])
    if s:
        e['sediment'] = {'mean_daily_t': s['mean_daily_t'], 'trend_pct': s['trend_pct']}
    peg_by_plant[l['plant']].append(e)
for v in peg_by_plant.values():
    v.sort(key=lambda x: x['km'])

# ---- generation series: last 365 days ----
today = datetime.date.today()
d0 = today - datetime.timedelta(days=364)
days = [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(365)]

plants_out = {}
for pid, p in PLANTS.items():
    ser, src, calib = series_for(pid)
    vals = [round(ser[d], 1) if d in ser else None for d in days]
    y26 = [v for d, v in ser.items() if d >= '2026-01-01']
    plants_out[pid] = {
        'name': p['name'], 'lat': p['lat'], 'lon': p['lon'], 'mw': p['mw'],
        'type': PSR_LABEL[p['psr']], 'psr': p['psr'], 'river': p['river'],
        'release_source': src, 'calib_r': calib,
        'mean_mwh_day_2026': round(float(np.mean(y26)), 1) if y26 else None,
        'gen': {'d0': days[0], 'vals': vals},
        'gw': gw_by_plant.get(pid, []),
        'pegel': peg_by_plant.get(pid, []),
    }

# ---- AT reservoir storage (weekly) ----
res_rows = []
for r in csv.DictReader(open('data/reservoir_levels_weekly.csv')):
    res_rows.append((r['timestamp'][:10], float(r['stored_energy_mwh'])))
res_rows.sort()
latest_d, latest_v = res_rows[-1]
# percentile of latest value vs same ISO week in previous years
wk = datetime.date.fromisoformat(latest_d).isocalendar()[1]
hist = [v for d, v in res_rows[:-1]
        if abs(datetime.date.fromisoformat(d).isocalendar()[1] - wk) <= 1
        and d[:4] != latest_d[:4]]
pct = round(100 * sum(1 for v in hist if v < latest_v) / len(hist)) if hist else None
res_max = max(v for _, v in res_rows)
reservoir = {
    'weekly': [[d, round(v / 1000, 1)] for d, v in res_rows],  # GWh
    'unit': 'GWh',
    'latest': {'date': latest_d, 'gwh': round(latest_v / 1000, 1),
               'pct_of_max': round(100 * latest_v / res_max),
               'seasonal_percentile': pct, 'n_ref_years': len(hist)},
    'source': 'ENTSO-E Water Reservoirs & Hydro Storage Plants, AT bidding zone, weekly',
}

out = {
    'generated': datetime.datetime.now().isoformat(timespec='seconds'),
    'plants': plants_out,
    'reservoir': reservoir,
}
with open('web/data/plant_profiles.json', 'w') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
print('plants:', len(plants_out), 'size:', os.path.getsize('web/data/plant_profiles.json'))

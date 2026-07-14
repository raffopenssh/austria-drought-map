#!/usr/bin/env python3
"""
How much of groundwater variation do hydropower operations explain,
once precipitation is accounted for?

Data:
- eHYD live GW stations (227): daily levels for current year
  (data/gw_aktuell/longterm_2026.json, services/Diagram/grundwasserLongtermBgis)
- ENTSO-E AT hourly (15-min) generation via austria-power.exe.xyz:
  daily MWh for Hydro Run-of-river, Reservoir, Pumped Storage gen + consumption
  (data/hydro_daily_mwh.csv)
- NASA POWER daily precipitation per 0.5-deg cell (data/nasa_power_precip_daily.json)
- Power plant registry (data/powerplants.json) for distance stratification

Method (per station, daily first-differences to remove trends/seasonality):
  y_t = ΔGW level (m/day)
  Model A (baseline): y ~ precip_t, precip_{t-1..3}, precip 7-day sum,
                      Δstage(t), Δstage(t-1) of NEAREST live river gauge
                      (data/gw_aktuell/pegel_daily.json, 292 eHYD Pegel)
  Model B: A + run-of-river MWh, reservoir MWh, pumped-storage net MWh (t, t-1)
  partial R² = (R²_B − R²_A) / (1 − R²_A)   … variance uniquely added by power ops
The river-stage control absorbs the shared hydrology pathway (rain/melt ->
river -> bank-connected aquifer), so the power block only gets credit for
signal NOT already visible in the local river.

Output: web/data/power_gw_analysis.json
"""
import json, csv, math, datetime, os
import numpy as np

# ---------- load ----------
gw = json.load(open('data/gw_aktuell/longterm_2026.json'))
precip = json.load(open('data/nasa_power_precip_daily.json'))
pegel = json.load(open('data/gw_aktuell/pegel_daily.json'))  # 292 live river gauges
plants = json.load(open('data/powerplants.json'))['markers']
HYDRO_TYPES = ('Laufkraftwerk', 'Speicherkraftwerk', 'Pumpspeicherkraftwerk')
hydro_plants = [p for p in plants if p.get('type') in HYDRO_TYPES]
# type inventory
types = {}
for p in plants: types[p['type']] = types.get(p['type'],0)+1

# daily hydro series
PLACEBO_SHIFT_DAYS = 100  # power series shifted back 100d: breaks true coupling,
                          # keeps autocorrelation/weekday structure -> null check
series = {}
with open('data/hydro_daily_mwh.csv') as f:
    for row in csv.DictReader(f):
        series.setdefault(row['psr_type'], {})[row['day']] = float(row['mwh'])
ror = series['Hydro Run-of-river and poundage']
res = series['Hydro Water Reservoir']
ps_gen = series['Hydro Pumped Storage']
ps_con = series['Hydro Pumped Storage Consumption']
days_all = sorted(set(ror) & set(res) & set(ps_gen) & set(ps_con))

def cell_key(lat, lon):
    return f"{round((lat//0.5)*0.5+0.25,3)},{round((lon//0.5)*0.5+0.25,3)}"

def hav(lat1, lon1, lat2, lon2):
    R=6371; p=math.pi/180
    a=(math.sin((lat2-lat1)*p/2)**2 +
       math.cos(lat1*p)*math.cos(lat2*p)*math.sin((lon2-lon1)*p/2)**2)
    return 2*R*math.asin(math.sqrt(a))

# precompute gauge daily first-differences (stage units vary; z-scored per gauge)
gauges = []
for gid, g in pegel.items():
    lv = g['levels']
    dts = sorted(lv)
    diffs = {}
    for a, b in zip(dts, dts[1:]):
        if (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days == 1:
            diffs[b] = lv[b] - lv[a]
    if len(diffs) < 60:
        continue
    vals = np.array(list(diffs.values()), float)
    sd = vals.std() or 1.0
    gauges.append({'id': gid, 'lat': g['coords'][1], 'lon': g['coords'][0],
                   'gewasser': g.get('gewasser'), 'diffs': {k: v/sd for k, v in diffs.items()}})

def nearest_gauge(lat, lon):
    best, bd = None, 1e9
    for g in gauges:
        d = hav(lat, lon, g['lat'], g['lon'])
        if d < bd:
            best, bd = g, d
    return best, bd

def ols_r2(X, y):
    X = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    ss_res = float(resid @ resid); ss_tot = float(((y - y.mean())**2).sum())
    return 1 - ss_res/ss_tot if ss_tot > 0 else 0.0, beta

stations_out = []
year = datetime.date.today().year
for hzb, s in gw.items():
    pts = s.get('points_in_time_werte') or []
    vals = s.get('data') or []
    if len(pts) < 60 or len(pts) != len(vals): continue
    lon, lat = s['coords'][:2]
    ck = cell_key(lat, lon)
    pr = precip.get(ck)
    if not pr: continue
    gauge, gauge_km = nearest_gauge(lat, lon)
    gd = gauge['diffs'] if gauge else {}
    # build aligned daily arrays
    level = dict(zip(pts, vals))
    days = [d for d in pts if d in ror]
    days = [d for d in days if (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat() in level]
    rows = []
    for d in days:
        dt = datetime.date.fromisoformat(d)
        prev = (dt - datetime.timedelta(days=1)).isoformat()
        if level.get(d) is None or level.get(prev) is None: continue
        pkey = dt.strftime('%Y%m%d')
        p0 = pr.get(pkey)
        lags = [pr.get((dt - datetime.timedelta(days=k)).strftime('%Y%m%d')) for k in (1,2,3)]
        p7 = [pr.get((dt - datetime.timedelta(days=k)).strftime('%Y%m%d')) for k in range(7)]
        prev_d = (dt - datetime.timedelta(days=1)).isoformat()
        if p0 is None or any(v is None or v < 0 for v in lags+[p0]) or any(v is None or v<0 for v in p7): continue
        if prev_d not in ror: continue
        if d not in gd or prev_d not in gd: continue
        sd_ = (dt - datetime.timedelta(days=PLACEBO_SHIFT_DAYS)).isoformat()
        sp_ = (dt - datetime.timedelta(days=PLACEBO_SHIFT_DAYS+1)).isoformat()
        if sd_ not in ror or sp_ not in ror: continue
        rows.append((
            level[d] - level[prev],                # y: daily change (m)
            p0, lags[0], lags[1], lags[2], sum(p7),
            gd[d], gd[prev_d],                     # nearest river gauge Δstage (z)
            ror[d]/1e3, ror[prev_d]/1e3,           # GWh
            res[d]/1e3, res[prev_d]/1e3,
            (ps_gen[d]-ps_con[d])/1e3, (ps_gen[prev_d]-ps_con[prev_d])/1e3,
            # placebo block: same power series shifted back PLACEBO_SHIFT_DAYS
            ror[sd_]/1e3, ror[sp_]/1e3,
            res[sd_]/1e3, res[sp_]/1e3,
            (ps_gen[sd_]-ps_con[sd_])/1e3, (ps_gen[sp_]-ps_con[sp_])/1e3,
        ))
    if len(rows) < 60: continue
    A = np.array(rows)
    y = A[:,0]
    if float(np.std(y)) == 0: continue
    Xbase = A[:,1:8]        # precip block + nearest-gauge Δstage (t, t-1)
    Xpow = A[:,8:14]        # power block
    Xplac = A[:,14:20]      # placebo power block (shifted -100d)
    r2_p, _ = ols_r2(A[:,1:6], y)          # precip only (reported)
    r2_base, _ = ols_r2(Xbase, y)          # precip + river control
    r2_full, beta_full = ols_r2(np.column_stack([Xbase, Xpow]), y)
    r2_plac, _ = ols_r2(np.column_stack([Xbase, Xplac]), y)
    r2_pow_alone, _ = ols_r2(Xpow, y)
    partial = (r2_full - r2_base) / (1 - r2_base) if r2_base < 1 else 0
    partial_plac = (r2_plac - r2_base) / (1 - r2_base) if r2_base < 1 else 0
    dmin = min(hav(lat, lon, p['latitude'], p['longitude']) for p in hydro_plants) if hydro_plants else None
    stations_out.append({
        'hzbnr': int(hzb), 'name': s['name'], 'bundesland': s['bundesland'],
        'lat': round(lat,5), 'lon': round(lon,5), 'n_days': len(rows),
        'r2_precip': round(r2_p,4), 'r2_base': round(r2_base,4),
        'r2_full': round(r2_full,4),
        'r2_power_alone': round(r2_pow_alone,4),
        'partial_r2_power': round(partial,4),
        'partial_r2_placebo': round(partial_plac,4),
        'dist_hydro_km': round(dmin,1) if dmin is not None else None,
        'nearest_gauge_km': round(gauge_km,1) if gauge else None,
        'nearest_gauge_river': gauge['gewasser'] if gauge else None,
    })

# analytic null: E[ΔR² partial] ≈ k/(n-p_base-1) when adding k noise regressors
K_POWER = 6; P_BASE = 7
for st in stations_out:
    n = st['n_days']
    null = K_POWER/(n - P_BASE - 1)
    st['null_expected_partial'] = round(null, 4)
    st['excess_partial'] = round(st['partial_r2_power'] - null, 4)
    st['excess_placebo'] = round(st['partial_r2_placebo'] - null, 4)

parts = sorted(x['partial_r2_power'] for x in stations_out)
excess = sorted(x['excess_partial'] for x in stations_out)
med = lambda a: a[len(a)//2] if a else None

# distance stratification
near = [x['excess_partial'] for x in stations_out if x['dist_hydro_km'] is not None and x['dist_hydro_km'] <= 5]
far  = [x['excess_partial'] for x in stations_out if x['dist_hydro_km'] is not None and x['dist_hydro_km'] > 5]

# national daily series for charting (GWh)
nat = [{'day': d, 'ror': round(ror[d]/1e3,1), 'res': round(res[d]/1e3,1),
        'ps_gen': round(ps_gen[d]/1e3,1), 'ps_con': round(ps_con[d]/1e3,1)}
       for d in days_all]

out = {
    'generated': datetime.datetime.now().isoformat(timespec='seconds'),
    'method': ('Daily first-difference OLS per station: baseline ΔGW ~ precip(t,t-1..3,'
               '7d-sum) + nearest live river gauge Δstage(t,t-1) [absorbs shared '
               'rain→river→aquifer hydrology], vs + national hydro generation blocks '
               '(run-of-river, reservoir, pumped-storage net; t and t-1, GWh). '
               'Partial R² = variance uniquely added by power terms. Analytic null '
               'k/(n-p-1) subtracted as "excess".'),
    'caveats': [
        'ENTSO-E data is NATIONAL aggregate - no plant-level attribution possible.',
        'Overlap window is current-year daily eHYD data only (~190 days, 2026).',
        'Live eHYD network is 227 stations, a subset of the 3,800 monthly-archive stations.',
        'Pumped storage in AT is mostly high-alpine closed/semi-closed loops; direct aquifer coupling is physically expected to be near zero.',
        'Run-of-river correlates with river discharge which itself drives bank-connected groundwater. We control for this with the nearest live eHYD river gauge (median 5.9 km), but a single gauge cannot capture the full river network; residual shared hydrology may remain. Still: correlation, not causation.',
        'River network coverage: 292 live Pegel gauges; nearest-gauge assignment is straight-line distance, not along-network (a denser network, e.g. OSM/Geofabrik waterways, would allow along-river matching).',
    ],
    'summary': {
        'n_stations': len(stations_out),
        'median_r2_precip': round(med(sorted(x['r2_precip'] for x in stations_out)),4),
        'median_r2_base': round(med(sorted(x['r2_base'] for x in stations_out)),4),
        'median_nearest_gauge_km': round(med(sorted(x['nearest_gauge_km'] for x in stations_out)),1),
        'median_partial_r2_power': round(med(parts),4),
        'median_excess_partial': round(med(excess),4),
        'median_excess_placebo': round(med(sorted(x['excess_placebo'] for x in stations_out)),4),
        'placebo_note': f'Placebo = same national power series shifted back {PLACEBO_SHIFT_DAYS} days (keeps weekday/autocorrelation structure, breaks real-time coupling). Real excess should exceed placebo.',
        'pct_stations_excess_gt_5pct': round(100*sum(1 for e in excess if e>0.05)/len(excess),1),
        'median_excess_near_5km': round(med(sorted(near)),4) if near else None,
        'median_excess_far_5km': round(med(sorted(far)),4) if far else None,
        'n_near_5km': len(near), 'n_far_5km': len(far),
    },
    'entsoe': {
        'source': 'ENTSO-E Transparency via austria-power.exe.xyz (AT bidding zone)',
        'coverage': f'{days_all[0]} .. {days_all[-1]}, 15-min resolution',
        'plant_types_in_registry': types,
    },
    'national_daily_gwh': nat,
    'stations': sorted(stations_out, key=lambda x: -x['excess_partial']),
}
os.makedirs('web/data', exist_ok=True)
json.dump(out, open('web/data/power_gw_analysis.json','w'))
print(json.dumps(out['summary'], indent=1))
print('sizes: stations', len(stations_out), 'file KB', os.path.getsize('web/data/power_gw_analysis.json')//1024)

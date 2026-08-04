#!/usr/bin/env python3
"""How much of Austria's river flow is glacier melt — and where does it end?

Combines
  data/glacier/glacier_downstream.json  (upstream ice + ASTER volume loss)
  web/data/gauge_profiles.json          (annual mean discharge per gauge)
  web/data/snow_reservoir.json          (SNOWGRID 1 Apr SWE trend, optional)
  web/data/gw_index_kg.json             (GWI per KG)

Writes web/data/glacier_context.json:
  gauges: per gauge  ice_km2, ice_pct_catch, melt_mio_m3a, flow_mio_m3a,
          melt_pct_flow (share of annual flow that is net ice loss, i.e. the
          part that stops once the ice is gone), dist_km
  kg:     per KG      ice_km2, melt_mio_m3a, dist_km, snow trend
  summary
Sanity filter: an assignment is dropped when upstream ice exceeds the gauge's
own catchment (mis-snap onto a neighbouring mainstem).
"""
import json, math, os, statistics as st
import numpy as np

gd = json.load(open('data/glacier/glacier_downstream.json'))
prof = json.load(open('web/data/gauge_profiles.json'))['stations']
try: snow = json.load(open('web/data/snow_reservoir.json'))
except Exception: snow = {}

SEC_A = 365.25*86400

gauges = {}
dropped = 0
for gid, v in gd['gauges'].items():
    p = prof.get(gid, {})
    catch = p.get('km2')
    if catch and v['gl_km2'] > catch*1.05:
        dropped += 1; continue          # mis-snap: more ice than catchment
    # A gauge 260 km downstream of ice must drain thousands of km2. If its own
    # catchment is far too small, the snap grabbed a neighbouring mainstem
    # (typical at confluences: a small tributary gauge next to the Danube).
    if catch and v['km'] > 25 and catch < v['km']*15:
        dropped += 1; continue
    rec = {'name': p.get('name'), 'river': p.get('river'), 'lat': p.get('lat'),
           'lon': p.get('lon'), 'catch_km2': catch, 'ice_km2': v['gl_km2'],
           'n_gl': v['n_gl'], 'dist_km': v['km'],
           'melt_mio_m3a': v['melt_mio_m3a'],
           'melt_mio_m3a_long': v['melt_mio_m3a_long'],
           'vol_mio_m3': v.get('vol_mio_m3'),
           'depletion_years': v.get('depletion_years')}
    if catch: rec['ice_pct_catch'] = round(v['gl_km2']/catch*100, 2)
    q = p.get('mean_m3s')
    if q:
        flow = q*SEC_A/1e6
        rec['flow_mio_m3a'] = round(flow, 1)
        rec['melt_pct_flow'] = round(v['melt_mio_m3a']/flow*100, 2)
        rec['melt_pct_flow_long'] = round(v['melt_mio_m3a_long']/flow*100, 2)
    rec['flow_trend_pct_decade'] = p.get('trend_pct_decade')
    s = (snow.get('gauges') or {}).get(gid)
    if s: rec['snow_apr_pct_decade'] = s.get('apr_pct_decade'); rec['snow_apr_mm'] = s.get('apr_mean_last10')
    gauges[gid] = rec

try: corrj = json.load(open('web/data/glacier_corridor.json'))
except Exception: corrj = {'kg': {}, 'gemeinden': {}}

# Observed shape of Austrian glacier melt: the WGMS in-situ annual mass balance
# (mean of all Austrian glaciers measured that year), scaled so that the mean of
# 2014-2019 equals 1.0. Multiplying a glacier's ASTER loss rate by this gives a
# plausible *observed* melt history to put in front of the projection.
import pandas as _pd
_mb = _pd.read_csv('data/glacier/data/mass_balance.csv', low_memory=False)
_mb = _mb[(_mb.country == 'AT') & _mb.annual_balance.notna()]
_per = _mb.groupby('year').annual_balance.mean()
_ref = -_per.loc[2014:2019].mean()
MB_SHAPE = {int(y): round(max(0.0, -v)/_ref, 3) for y, v in _per.items() if y >= 1960}
MB_YEARS = sorted(MB_SHAPE)
print(f'mass-balance shape {MB_YEARS[0]}-{MB_YEARS[-1]}, ref |B| 2014-19 = {_ref:.2f} m w.e.')

def ice_decline(vol_mio, melt_mio):
    """Melt trajectory for the ice upstream, under 'melt scales with remaining
    area' (V = c A^1.375  =>  dV/dt proportional to A = (V/c)^(1/1.375)).
    Integrating gives V(t) shrinking to 0 in tau = V0/(melt0*(1-1/g)) ... in
    practice we step it yearly, which also yields the shape of the melt curve
    (rising slightly, then collapsing) that the literature shows."""
    if not vol_mio or not melt_mio: return None
    g = 1.375
    V, M0, V0 = float(vol_mio), float(melt_mio), float(vol_mio)
    ser = []
    for y in range(2019, 2101):
        if V <= 0: ser.append([y, 0.0]); continue
        m = M0*((V/V0)**(1.0/g))          # melt scales with area
        ser.append([y, round(m, 2)])
        V -= m
    gone = next((y for y, m in ser if m <= 0.05*M0), None)
    half = next((y for y, m in ser if m <= 0.5*M0), None)
    hist = [[y, round(M0*MB_SHAPE[y], 2)] for y in MB_YEARS if y <= 2019]
    return {'hist': hist, 'melt': ser[::2], 'year_half_melt': half,
            'year_gone': gone, 'vol_mio_m3': round(vol_mio, 1),
            'melt_now': round(M0, 2)}

kg = {}
for code, v in (corrj.get('kg') or {}).items():
    kg[code] = {'ice_km2': v['ice_km2'], 'dist_km': v['reach_km'],
                'melt_mio_m3a': v['melt_mio_m3a'],
                'corridor_share': v['corridor_share'],
                'corridor_km2': v['corridor_km2']}
for code, v in gd['kg'].items():
    r = kg.setdefault(code, {})
    r.setdefault('ice_km2', v['gl_km2']); r.setdefault('dist_km', v['km'])
    r.setdefault('melt_mio_m3a', v['melt_mio_m3a'])
    r['n_gl'] = v['n_gl']
    r['vol_mio_m3'] = v.get('vol_mio_m3')
    r['depletion_years'] = v.get('depletion_years')
for code, s in (snow.get('kg') or {}).items():
    r = kg.setdefault(code, {})
    r['snow_apr_mm'] = s.get('apr_mean_last10')
    r['snow_apr_mm_6190'] = s.get('apr_mean_6190')
    r['snow_apr_pct_decade'] = s.get('apr_pct_decade')
    r['snow_jul_mm'] = s.get('jul_mean_last10')
    r['snow_jul_pct_decade'] = s.get('jul_pct_decade')

gw = {}
for h, v in gd['gw'].items():
    gw[h] = {'ice_km2': v['gl_km2'], 'dist_km': v['km'], 'melt_mio_m3a': v['melt_mio_m3a']}
for h, s in (snow.get('gw') or {}).items():
    gw.setdefault(h, {})['snow_apr_pct_decade'] = s.get('apr_pct_decade')

ice_tot = sum(g['area_km2'] for g in gd['glaciers'].values())
melt_tot = sum(g['melt_m3a_recent'] for g in gd['glaciers'].values())/1e6
melt_long = sum(g['melt_m3a_long'] for g in gd['glaciers'].values())/1e6
withflow = [g for g in gauges.values() if g.get('melt_pct_flow') is not None]
summary = {
  'ice_km2': round(ice_tot, 1), 'n_glaciers': len(gd['glaciers']),
  'melt_mio_m3a_2014_19': round(melt_tot, 0),
  'melt_mio_m3a_1999_2019': round(melt_long, 0),
  'gauges_glacier_fed': len(gauges), 'gauges_dropped_missnap': dropped,
  'kg_glacier_fed_point': len(gd['kg']),
  'kg_in_corridor_2km': len(corrj.get('kg') or {}),
  'gemeinden_in_corridor_2km': len(corrj.get('gemeinden') or {}),
  'max_melt_pct_flow': max((g['melt_pct_flow'] for g in withflow), default=None),
  'median_melt_pct_flow': round(st.median([g['melt_pct_flow'] for g in withflow]), 2) if withflow else None,
}
glfed = set(corrj.get('kg') or {}) | set(gd['kg'])
snow_kg = [r['snow_apr_pct_decade'] for c, r in kg.items()
           if c in glfed and r.get('snow_apr_pct_decade') is not None]
if snow_kg: summary['median_snow_apr_pct_decade_glacier_kgs'] = round(st.median(snow_kg), 2)
allsnow = [s.get('apr_pct_decade') for s in (snow.get('kg') or {}).values() if s.get('apr_pct_decade') is not None]
if allsnow: summary['median_snow_apr_pct_decade_all_kgs'] = round(st.median(allsnow), 2)

def project(ser, to_year=2050):
    """Trend + projection for a snow series.
    Fit on the last 40 years (the climate-change era, avoids the 1960s-70s
    high-snow plateau dominating the slope) with a floor at 0, and report the
    year the store reaches 50% / 10% of its 1961-90 baseline. Linear-in-time
    extrapolation is crude but honest and matches the observed shape better
    than exponential over 25 years."""
    if len(ser) < 30: return None
    ys = np.array([p[0] for p in ser], float); vs = np.array([p[1] for p in ser], float)
    sel = ys >= ys.max()-39
    if sel.sum() < 25: return None
    sl, ic = np.polyfit(ys[sel], vs[sel], 1)
    base = vs[(ys >= 1961) & (ys <= 1990)].mean() if (ys <= 1990).sum() >= 10 else np.nan
    proj = [[int(y), max(0.0, round(sl*y+ic, 1))] for y in range(int(ys.max())+1, to_year+1)]
    fitline = [[int(ys[sel].min()), max(0.0, round(sl*ys[sel].min()+ic, 1))],
               [to_year, max(0.0, round(sl*to_year+ic, 1))]]
    out = {'slope_mm_yr': round(float(sl), 3), 'proj': proj, 'fit': fitline,
           'proj_2050': proj[-1][1] if proj else None}
    if sl < 0 and not np.isnan(base) and base > 5:
        for frac, key in ((0.5, 'year_half'), (0.1, 'year_10pct')):
            yr = (frac*base - ic)/sl
            out[key] = int(round(yr)) if 1990 < yr < 2200 else None
        out['baseline_6190'] = round(float(base), 1)
    return out

# compact per-KG snow series for the app's sparklines: only where there is a
# real seasonal store (>=20 mm 1961-90 mean) or the KG is glacier-fed.
snow_ser = {}
for code, sv in (snow.get('kg') or {}).items():
    if code not in glfed and (sv.get('apr_mean_6190') or 0) < 20: continue
    rec = {'apr': [[y, int(round(v))] for y, v in sv['apr']]}
    if sv.get('jul') and (sv.get('jul_mean_6190') or 0) >= 5:
        rec['jul'] = [[y, int(round(v))] for y, v in sv['jul']]
        pj = project(sv['jul'])
        if pj: rec['jul_proj'] = pj
    pa = project(sv['apr'])
    if pa: rec['apr_proj'] = pa
    snow_ser[code] = rec
print(f'{len(snow_ser)} KGs with snow sparkline series')

traj = {}
for code, r in kg.items():
    if not r.get('vol_mio_m3') or not r.get('melt_mio_m3a'): continue
    key = f"{round(r['vol_mio_m3'],1)}_{round(r['melt_mio_m3a'],2)}"
    if key not in traj:
        t = ice_decline(r['vol_mio_m3'], r['melt_mio_m3a'])
        if t: traj[key] = t
    if key in traj: r['ice_traj'] = key
print(f'{len(traj)} distinct ice trajectories')

out = {'source': ('WGMS FoG 2026-02 (mass balance + ASTER dh/dt of Hugonnet et al. 2021), '
                  'RGI 6.0 region 11 outlines, OSM waterway network, '
                  'GeoSphere SNOWGRID-CL v2 SWE, eHYD/OWF discharge'),
       'summary': summary, 'gauges': gauges, 'kg': kg, 'gw': gw,
       'gemeinden': corrj.get('gemeinden', {}), 'snow': snow_ser,
       'ice_traj': traj,
       'analysis': (json.load(open('data/glacier_gw_analysis.json'))
                    if os.path.exists('data/glacier_gw_analysis.json') else None),
       'glaciers': gd['glaciers']}
json.dump(out, open('web/data/glacier_context.json', 'w'))
os.system('gzip -9 -c web/data/glacier_context.json > web/data/glacier_context.json.gz')
print(json.dumps(summary, indent=1))
print('\nTop gauges by melt share of annual flow:')
for g in sorted(withflow, key=lambda x: -x['melt_pct_flow'])[:20]:
    print(f"  {g['name'][:28]:29s} {str(g['river'])[:16]:17s} ice {g['ice_km2']:6.1f} km2 "
          f"({g.get('ice_pct_catch')}% of catch)  melt = {g['melt_pct_flow']:5.2f}% of flow  "
          f"Qtrend {g.get('flow_trend_pct_decade')}%/dec  snowApr {g.get('snow_apr_pct_decade')}%/dec")

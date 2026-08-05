#!/usr/bin/env python3
"""What changes when you use real catchments instead of a network snap?

Our first cryosphere pass attributed glaciers to gauges/KGs by walking the OSM
waterway graph. This one intersects RGI outlines and SNOWGRID SWE with the
MERIT-Hydro catchment actually draining to each gauge (validated against the
official eHYD catchment size). Questions:

  Q1 How different are the ice attributions? (old vs new, per gauge)
  Q2 Snow vs ice vs flow: how much of a basin's annual river flow sits in the
     1 Apr snowpack, and how fast is that store shrinking? Ice is a rounding
     error nationally; snow is the real reservoir.
  Q3 Does catchment snow decline predict the gauge's observed flow trend?
     (network-snap attribution was too noisy to test this honestly)
  Q4 Do GW stations inside heavily snow-fed catchments trend differently from
     those in rain-fed ones, controlling for precipitation divergence?
  Q5 Elevation/ice-share structure of the flow trend: where is melt still
     masking decline?

Out: data/watershed_cryosphere_analysis.json (+ printed report)
"""
import json, math, os, statistics as st
import numpy as np

wc = json.load(open('web/data/watershed_context.json'))
G = {k: v for k, v in wc['gauges'].items() if v['quality'] != 'missnap'}
old = json.load(open('web/data/glacier_context.json'))
res = {'source': wc['source'], 'validation': wc['validation'],
       'n_gauges_used': len(G)}

def lin(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 5: return None
    return float(np.polyfit(x, y, 1)[0])
def pearson(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 5 or x.std() == 0 or y.std() == 0: return None, None
    r = float(np.corrcoef(x, y)[0, 1])
    n = len(x)
    t = r*math.sqrt(max(n-2, 1)/max(1e-12, 1-r*r))
    # two-sided p from a normal approx of t (n is large enough here)
    p = 2*(1 - 0.5*(1+math.erf(abs(t)/math.sqrt(2))))
    return round(r, 3), round(p, 5)

def perm_diff(a, b, n=20000, seed=0):
    """Two-sided permutation p for the difference of medians."""
    import random as _r
    _r.seed(seed)
    a, b = list(a), list(b)
    obs = st.median(a) - st.median(b)
    pool = a + b; na = len(a); hits = 0
    for _ in range(n):
        _r.shuffle(pool)
        d = st.median(pool[:na]) - st.median(pool[na:])
        if abs(d) >= abs(obs) - 1e-12: hits += 1
    return round(obs, 4), (hits+1)/(n+1)

# ------------------------------------------------------- Q1 old vs new
og = old['gauges']
pairs = [(v['ice_km2'], G[k]['ice_km2'], k, v.get('name')) for k, v in og.items() if k in G]
d = [(b-a) for a, b, _, _ in pairs]
worst = sorted(pairs, key=lambda t: -abs(t[1]-t[0]))[:10]
res['q1_old_vs_new'] = {
    'n_common': len(pairs),
    'median_abs_diff_km2': round(st.median(abs(x) for x in d), 3),
    'n_new_ice_where_old_none': sum(1 for a, b, *_ in pairs if a == 0 and b > 0),
    'n_old_ice_where_new_none': sum(1 for a, b, *_ in pairs if a > 0 and b == 0),
    'r_ice_km2': pearson([a for a, *_ in pairs], [b for _, b, *_ in pairs])[0],
    'largest_changes': [{'hzb': k, 'name': n, 'old_km2': a, 'new_km2': b}
                        for a, b, k, n in worst],
    'n_gauges_ice_new': sum(1 for v in G.values() if v['ice_km2'] > 0),
    'n_gauges_ice_old': sum(1 for v in og.values() if v.get('ice_km2', 0) > 0),
}

# ------------------------------------------------- Q2 snow store vs annual flow
sp = [(k, v) for k, v in G.items() if v.get('snow_pct_flow') and v.get('flow_mio_m3a')]
vals = [v['snow_pct_flow'] for _, v in sp]
ice = [v.get('melt_pct_flow', 0) for _, v in sp]
res['q2_store_vs_flow'] = {
    'n': len(sp),
    'snow_pct_flow_median': round(st.median(vals), 1),
    'snow_pct_flow_p90': round(float(np.percentile(vals, 90)), 1),
    'melt_pct_flow_median': round(st.median(ice), 2),
    'snow_over_ice_ratio_median': round(st.median(v/max(i, 1e-6) for v, i in zip(vals, ice) if i > 0), 1),
    'top_snow_basins': [{'hzb': k, 'name': v['name'], 'river': v['river'],
                         'km2': v['km2'], 'snow_pct_flow': v['snow_pct_flow'],
                         'snow_store_mio_m3': v['snow_store_mio_m3'],
                         'apr_pct_dec': v['snow'].get('apr_pct_dec')}
                        for k, v in sorted(sp, key=lambda t: -t[1]['snow_pct_flow'])[:10]],
}
# national: sum of 1 Apr store over the largest non-nested basins vs their flow
lost = [(v['snow_store_6190_mio_m3'] or 0) - (v['snow_store_mio_m3'] or 0)
        for _, v in sp if v.get('snow_store_6190_mio_m3')]
res['q2_store_vs_flow']['median_store_lost_vs_6190_pct'] = round(st.median(
    [(1 - v['snow_store_mio_m3']/v['snow_store_6190_mio_m3'])*100
     for _, v in sp if v.get('snow_store_6190_mio_m3')]), 1)

# ------------------------------------------- Q3 snow trend vs flow trend
xs, ys = [], []
for k, v in G.items():
    t = v.get('trend_pct_decade'); s = (v.get('snow') or {}).get('apr_pct_dec')
    if t is None or s is None: continue
    xs.append(s); ys.append(t)
r, p = pearson(xs, ys)
res['q3_snow_trend_vs_flow_trend'] = {'n': len(xs), 'r': r, 'p': p,
    'median_flow_trend_pct_dec': round(st.median(ys), 2),
    'median_snow_trend_pct_dec': round(st.median(xs), 2)}
# split by ice share: does remaining ice still mask the decline?
for lo, hi, lbl in [(0, 0.01, 'ice_free'), (0.01, 1, 'trace_ice'),
                    (1, 5, 'ice_1_5pct'), (5, 100, 'ice_over_5pct')]:
    sub = [v['trend_pct_decade'] for v in G.values()
           if v.get('trend_pct_decade') is not None and lo <= v['ice_pct'] < hi]
    if len(sub) >= 5:
        res['q3_snow_trend_vs_flow_trend'][f'flow_trend_{lbl}'] = {
            'n': len(sub), 'median_pct_dec': round(st.median(sub), 2)}

# significance of the ice gradient: ice-free vs >=1% ice
icefree = [v['trend_pct_decade'] for v in G.values()
           if v.get('trend_pct_decade') is not None and v['ice_pct'] < 0.01]
icy = [v['trend_pct_decade'] for v in G.values()
       if v.get('trend_pct_decade') is not None and v['ice_pct'] >= 1]
d0, p0 = perm_diff(icy, icefree)
res['q3_snow_trend_vs_flow_trend']['ice_gradient_perm'] = {
    'n_icy': len(icy), 'n_icefree': len(icefree),
    'median_diff_pct_dec': d0, 'p': p0}

# ------------------------------- Q4 GW stations by catchment snow dependence
slim = json.load(open('web/data/gw_stations_slim.json'))   # list of dicts
try:
    precip = {x['id']: x.get('divergence_5yr')
              for x in json.load(open('web/data/precip_gw_correlation.json'))['stations']}
except Exception:
    precip = {}
import geopandas as gpd
from shapely.geometry import Point, shape
cats = []
import glob
for p in glob.glob('data/watersheds/*.json'):
    if p.endswith('.orig.json'): continue
    d0 = json.load(open(p))
    if not d0.get('watershed') or d0['hzb'] not in G: continue
    cats.append({'hzb': d0['hzb'], 'geometry': shape(d0['watershed'])})
cg = gpd.GeoDataFrame(cats, crs=4326)
cg['geometry'] = cg.geometry.buffer(0)
cg['km2'] = cg.to_crs(31287).area/1e6

pts, meta = [], []
for s in slim:
    tr = s.get('trend_m_per_decade')
    if s.get('lat') is None or tr is None: continue
    if (s.get('data_years') or 0) < 15: continue
    pts.append(Point(s['lon'], s['lat']))
    meta.append((s['id'], float(tr), precip.get(s['id'])))
if pts:
    gp = gpd.GeoDataFrame({'i': range(len(pts))}, geometry=pts, crs=4326)
    sj = gpd.sjoin(gp, cg[['hzb', 'km2', 'geometry']], how='inner', predicate='within')
    sj = sj.sort_values('km2').drop_duplicates('i')
    xs, ys, dv = [], [], []
    for _, row in sj.iterrows():
        v = G[row.hzb]
        sp_ = v.get('snow_pct_flow')
        if sp_ is None: continue
        hzb, tr, div = meta[int(row.i)]
        xs.append(sp_); ys.append(tr); dv.append(div)
    r2, p2 = pearson(xs, ys)
    grp, grpd = {}, {}
    for x, y, d0 in zip(xs, ys, dv):
        k = ('snow_rich' if x >= 20 else 'snow_moderate' if x >= 8 else 'rain_fed')
        grp.setdefault(k, []).append(y)
        if d0 is not None: grpd.setdefault(k, []).append(d0)
    res['q4_gw_by_catchment_snow'] = {
        'n': len(xs), 'r_snowshare_vs_gw_trend': r2, 'p': p2,
        'note': ('GW stations assigned to the smallest verified gauged catchment '
                 'containing them; snow_pct_flow = 1 Apr snow store as % of the '
                 "basin's annual river flow"),
        'groups': {k: {'n': len(v), 'median_trend_m_dec': round(st.median(v), 4),
                       'median_precip_divergence_m': (round(st.median(grpd[k]), 3)
                                                      if grpd.get(k) else None)}
                   for k, v in grp.items()}}
    if 'snow_rich' in grp and 'rain_fed' in grp:
        d1, p1 = perm_diff(grp['snow_rich'], grp['rain_fed'])
        res['q4_gw_by_catchment_snow']['snowrich_vs_rainfed_perm'] = {
            'median_diff_m_dec': d1, 'p': p1}
else:
    res['q4_gw_by_catchment_snow'] = {'error': 'no GW station coords/trends found'}

# -------------------------------------- Q5 where does melt still mask decline
melt_masked = [{'hzb': k, 'name': v['name'], 'river': v['river'],
                'ice_pct': v['ice_pct'], 'melt_pct_flow': v.get('melt_pct_flow'),
                'flow_trend_pct_dec': v.get('trend_pct_decade'),
                'depletion_years': v.get('depletion_years')}
               for k, v in G.items()
               if (v.get('melt_pct_flow') or 0) >= 5 and v.get('trend_pct_decade') is not None]
melt_masked.sort(key=lambda d: -(d['melt_pct_flow'] or 0))
res['q5_melt_masked_gauges'] = melt_masked[:20]
res['q5_summary'] = {
    'n_gauges_melt_over_5pct_flow': len(melt_masked),
    'median_flow_trend_there': (round(st.median([d['flow_trend_pct_dec'] for d in melt_masked]), 2)
                                if melt_masked else None),
    'median_depletion_years': (round(st.median([d['depletion_years'] for d in melt_masked
                                                if d['depletion_years']]), 0) if melt_masked else None)}

# --------- national aggregate: the snow store of the non-nested headwaters
# Take the largest verified catchments that do not contain one another, so the
# 1 Apr store is counted once per area.
import glob as _g
from shapely.geometry import shape as _shape
catlist = []
for p in _g.glob('data/watersheds/*.json'):
    if p.endswith('.orig.json'): continue
    d0 = json.load(open(p))
    if not d0.get('watershed') or d0['hzb'] not in G: continue
    catlist.append((G[d0['hzb']]['km2'], d0['hzb'], _shape(d0['watershed'])))
catlist.sort(reverse=True)
chosen, taken = [], []
for km2, hzb, geom in catlist:
    c = geom.representative_point()
    if any(t.contains(c) for t in taken): continue
    taken.append(geom); chosen.append(hzb)
store = sum(G[h].get('snow_store_mio_m3') or 0 for h in chosen)
store90 = sum(G[h].get('snow_store_6190_mio_m3') or 0 for h in chosen)
area = sum(G[h]['km2'] for h in chosen)
melt_tot = sum(G[h]['melt_mio_m3a'] for h in chosen)
res['q6_national'] = {
    'n_independent_basins': len(chosen), 'area_km2': round(area, 0),
    'snow_store_1apr_mio_m3_last10': round(store, 0),
    'snow_store_1apr_mio_m3_6190': round(store90, 0),
    'lost_mio_m3': round(store90-store, 0),
    'lost_pct': round((store90-store)/store90*100, 1) if store90 else None,
    'net_ice_loss_mio_m3a': round(melt_tot, 1),
    'ice_over_snow_pct': round(melt_tot/store*100, 2) if store else None,
    'note': ('the 1 Apr snowpack of these basins holds ~'
             f'{store/max(melt_tot,1e-9):.0f}x the annual net ice loss; '
             'the store lost since 1961-90 alone is '
             f'{ (store90-store)/max(melt_tot,1e-9):.0f}x the annual ice loss')}

json.dump(res, open('data/watershed_cryosphere_analysis.json', 'w'), indent=1)
print(json.dumps(res, indent=1)[:6000])

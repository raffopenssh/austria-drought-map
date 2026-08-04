#!/usr/bin/env python3
"""Does the ice matter for the aquifers? Three tests.

T1 Do GW stations in the glacier-fed corridor behave differently from
   matched non-corridor neighbours (level trend, precip divergence)?
T2 Does upstream ice share explain river-flow trends (glacier-fed gauges
   should still be gaining flow -> "melt subsidy", masking drought)?
T3 Snow: is the 1 Apr SWE decline (SNOWGRID) tied to GW level trends
   in the same KG (the seasonal reservoir, 100x bigger than the ice)?

Out: data/glacier_gw_analysis.json + printed report.
"""
import json, math, statistics as st, random
import numpy as np

gd = json.load(open('data/glacier/glacier_downstream.json'))
gc = json.load(open('web/data/glacier_context.json'))
snow = json.load(open('web/data/snow_reservoir.json'))
trends = json.load(open('web/data/gw_stations_trends.json'))
precip = {x['id']: x.get('divergence_5yr')
          for x in json.load(open('web/data/precip_gw_correlation.json'))['stations']}
random.seed(0)

# --- classify ALL 3,732 trend stations by the buffered glacier-fed corridor
import geopandas as gpd
from shapely.geometry import Point
from shapely.ops import unary_union
BUF_M = 2000
rc = gpd.read_file('data/glacier/glacier_reaches.geojson').to_crs(31287)
corr_geom = unary_union(rc.geometry.buffer(BUF_M))
# melt lookup for corridor stations
rsidx = rc.sindex

st_lat, st_lon, st_tr, st_div, st_melt, st_km = {}, {}, {}, {}, {}, {}
for v in trends:
    h = v['id']
    tr = v.get('trend_10yr')
    if tr is None or v.get('lat') is None: continue
    st_lat[h] = v['lat']; st_lon[h] = v['lon']; st_tr[h] = tr/100.0  # cm->m per decade? see note
    d = precip.get(h)
    if d is not None: st_div[h] = d
# trend_10yr is already m/decade in this dataset -> undo the /100
for h in st_tr: st_tr[h] *= 100.0

pts = gpd.GeoDataFrame(
    {'id': list(st_tr)},
    geometry=[Point(st_lon[h], st_lat[h]) for h in st_tr], crs=4326).to_crs(31287)
inside_mask = pts.within(corr_geom)
corr_ids = set(pts.id[inside_mask.values])
for i, row in pts[inside_mask.values].iterrows():
    cand = list(rsidx.intersection(row.geometry.buffer(BUF_M).bounds))
    m = 0.0
    for c in cand:
        r = rc.iloc[c]
        if r.geometry.distance(row.geometry) <= BUF_M and r.melt_mio_m3a > m:
            m = float(r.melt_mio_m3a)
    st_melt[row.id] = m
    d = None
    for c in cand:
        r = rc.iloc[c]
        if r.geometry.distance(row.geometry) <= BUF_M and (d is None or r.km < d):
            d = float(r.km)
    st_km[row.id] = d

corr = corr_ids
inside = [h for h in st_tr if h in corr]
outside = [h for h in st_tr if h not in corr]
print(f'\nT1: {len(inside)} corridor GW stations, {len(outside)} others')

def hav(a, b, c, d):
    p = math.pi/180
    return 2*6371*math.asin(math.sqrt(math.sin((c-a)*p/2)**2 +
        math.cos(a*p)*math.cos(c*p)*math.sin((d-b)*p/2)**2))

# matched-neighbour excess: each corridor station vs its 15 nearest non-corridor
exc = []
for h in inside:
    ds = sorted((hav(st_lat[h], st_lon[h], st_lat[o], st_lon[o]), o) for o in outside)[:15]
    if len(ds) < 5: continue
    ctrl = [st_tr[o] for _, o in ds]
    exc.append(st_tr[h] - st.median(ctrl))
res = {'t1_n': len(exc)}
if exc:
    res['t1_median_excess_m_dec'] = round(st.median(exc), 4)
    res['t1_mean_excess_m_dec'] = round(st.mean(exc), 4)
    # permutation test
    pool = list(st_tr.values())
    obs = st.mean(exc); cnt = 0
    for _ in range(2000):
        samp = random.sample(pool, len(exc))
        if abs(st.mean(samp) - st.mean(pool)) >= abs(obs): cnt += 1
    res['t1_perm_p'] = round(cnt/2000, 3)
    dexc = []
    for h in inside:
        if h not in st_div: continue
        ds = sorted((hav(st_lat[h], st_lon[h], st_lat[o], st_lon[o]), o)
                    for o in outside if o in st_div)[:15]
        if len(ds) < 5: continue
        dexc.append(st_div[h] - st.median([st_div[o] for _, o in ds]))
    if dexc:
        res['t1_div_n'] = len(dexc)
        res['t1_median_div_excess'] = round(st.median(dexc), 4)
        print(f"  corridor stations' precip-divergence excess: "
              f"{res['t1_median_div_excess']:+.3f} m (median, n={len(dexc)})")
    # dose-response: strong-melt corridor (>=50 mio m3/a) vs weak
    strong = [st_tr[h] for h in inside if st_melt.get(h, 0) >= 50]
    weak = [st_tr[h] for h in inside if st_melt.get(h, 0) < 50]
    if strong and weak:
        res['t1_median_trend_strong_melt'] = round(st.median(strong), 4)
        res['t1_median_trend_weak_melt'] = round(st.median(weak), 4)
        res['t1_n_strong'] = len(strong); res['t1_n_weak'] = len(weak)
        print(f"  dose-response: melt>=50 mio m3/a {res['t1_median_trend_strong_melt']:+.3f} "
              f"(n={len(strong)}) vs <50 {res['t1_median_trend_weak_melt']:+.3f} (n={len(weak)}) m/dec")
    # distance strata: how far downstream does the melt subsidy reach?
    res['t1_strata'] = {}
    for lo_, hi_ in [(0, 25), (25, 75), (75, 150), (150, 1e9)]:
        sel = [h for h in inside if st_km.get(h) is not None and lo_ <= st_km[h] < hi_]
        if len(sel) < 10: continue
        e = []
        for h in sel:
            ds = sorted((hav(st_lat[h], st_lon[h], st_lat[o], st_lon[o]), o) for o in outside)[:15]
            if len(ds) < 5: continue
            e.append(st_tr[h] - st.median([st_tr[o] for _, o in ds]))
        lbl = f'{lo_}-{"inf" if hi_ > 1e8 else int(hi_)}km'
        res['t1_strata'][lbl] = {'n': len(e), 'median_excess_m_dec': round(st.median(e), 4)}
        print(f"  {lbl:12s} n={len(e):4d} excess {st.median(e):+.3f} m/dec")
    print(f"  corridor stations' level trend excess over 15 nearest controls: "
          f"{res['t1_median_excess_m_dec']:+.3f} m/decade (median), "
          f"mean {res['t1_mean_excess_m_dec']:+.3f}, perm p={res['t1_perm_p']}")

# T2 flow trend vs ice share
g = [v for v in gc['gauges'].values()
     if v.get('ice_pct_catch') is not None and v.get('flow_trend_pct_decade') is not None]
allp = json.load(open('web/data/gauge_profiles.json'))['stations']
noice = [v['trend_pct_decade'] for k, v in allp.items()
         if k not in gc['gauges'] and v.get('trend_pct_decade') is not None]
print(f'\nT2: {len(g)} glacier-fed gauges w/ flow trend, {len(noice)} ice-free')
if g:
    x = np.array([v['ice_pct_catch'] for v in g]); y = np.array([v['flow_trend_pct_decade'] for v in g])
    r = float(np.corrcoef(x, y)[0, 1]); sl = float(np.polyfit(x, y, 1)[0])
    hi = [v['flow_trend_pct_decade'] for v in g if v['ice_pct_catch'] >= 10]
    lo = [v['flow_trend_pct_decade'] for v in g if v['ice_pct_catch'] < 2]
    res.update({'t2_n': len(g), 't2_r_icepct_flowtrend': round(r, 3),
                't2_slope_pct_dec_per_icepct': round(sl, 3),
                't2_median_trend_ice_ge10pct': round(st.median(hi), 2) if hi else None,
                't2_n_ice_ge10pct': len(hi),
                't2_median_trend_ice_lt2pct': round(st.median(lo), 2) if lo else None,
                't2_median_trend_ice_free': round(st.median(noice), 2)})
    print(f"  r(ice% of catchment, flow trend %/dec) = {r:+.3f}, slope {sl:+.3f}")
    print(f"  median flow trend: ice>=10% {res['t2_median_trend_ice_ge10pct']}%/dec "
          f"(n={len(hi)}) | ice<2% {res['t2_median_trend_ice_lt2pct']} | "
          f"ice-free {res['t2_median_trend_ice_free']}")

# T3 snow trend vs GW trend, per KG
kg2 = {}
for code, v in snow['kg'].items():
    if v.get('apr_pct_decade') is not None: kg2[code] = v['apr_pct_decade']
# GW station -> KG via point_snap
try: snap = json.load(open('web/data/point_snap.json'))
except Exception: snap = {}
pairs = []
for h, tr in st_tr.items():
    s = snap.get(f'gw:{h}')
    code = (s or {}).get('kg_code')
    if code and code in kg2: pairs.append((kg2[code], tr))
res['t3_n'] = len(pairs)
if len(pairs) > 30:
    a = np.array([p[0] for p in pairs]); b = np.array([p[1] for p in pairs])
    res['t3_r_snowtrend_gwtrend'] = round(float(np.corrcoef(a, b)[0, 1]), 3)
    print(f"\nT3: {len(pairs)} GW stations w/ KG snow trend, "
          f"r(Apr-SWE %/dec, GW trend m/dec) = {res['t3_r_snowtrend_gwtrend']:+.3f}")
else:
    print(f"\nT3: only {len(pairs)} pairs (point_snap keys: {list(snap)[:3]})")

res['snow_national'] = {
    'median_apr_pct_decade': round(st.median([v for v in kg2.values()]), 2),
    'n_kg': len(kg2)}
json.dump(res, open('data/glacier_gw_analysis.json', 'w'), indent=1)
print('\nwrote data/glacier_gw_analysis.json')

#!/usr/bin/env python3
"""Real catchments -> honest cryosphere accounting per river gauge and per KG.

Replaces the OSM-network snap ("how much ice is somewhere upstream along the
waterway graph") with polygon intersection against the actual contributing
area, delineated from MERIT-Hydro by mghydro.com (data/watersheds/*.json,
see scripts/fetch_watersheds.py).

For every gauge catchment:
  ice_km2      RGI 6.0 glacier area *inside* the catchment (real outlines,
               area-weighted by the intersected fraction of each glacier)
  melt_mio_m3a net ice loss inside the catchment (ASTER dh/dt 2014-19,
               Hugonnet et al. 2021 via WGMS FoG, per-glacier, prorated)
  swe_apr      catchment-mean 1 Apr SWE per year 1961-2026 (SNOWGRID-CL v2,
               all 1 km pixels whose centre falls in the polygon) and the
               implied stored volume in mio m3
  melt_pct_flow / snow_pct_flow  share of annual flow (eHYD mean discharge)
               that is net ice loss / that sits in the 1 Apr snowpack
For every KG: the smallest gauge catchment that contains its centroid
  ("your river's catchment") + the same numbers, so the app can say
  "you drink from a 1,278 km2 basin, 0.6% of it is ice, its snowpack on
  1 April holds 3x its annual river flow".

In:  data/watersheds/*.json, data/glacier/11_rgi60_CentralEurope.shp,
     data/glacier/change_at.csv, data/glacier/snowgrid/*.f32,
     web/data/gauge_profiles.json, web/data/kg_registry.json
Out: web/data/watershed_context.json(.gz), web/data/catchments.geojson(.gz)
"""
import json, os, glob, math, sys
import numpy as np
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape, Point
from shapely.ops import unary_union

OUT = 'web/data/watershed_context.json'
GEO = 'web/data/catchments.geojson'
EA = 31287                      # Austria Lambert (equal-ish area for km2)
SNOW = 'data/glacier/snowgrid'

# ----------------------------------------------------------------- catchments
rows = []
for p in sorted(glob.glob('data/watersheds/*.json')):
    d = json.load(open(p))
    if not d.get('watershed'): continue
    rows.append({'hzb': d['hzb'], 'name': d.get('name'), 'river': d.get('river'),
                 'lat': d['lat'], 'lon': d['lon'], 'snap_km': d.get('snap_km'),
                 'km2_merit': d['km2_merit'], 'km2_ehyd': d.get('km2_ehyd'),
                 'geometry': shape(d['watershed'])})
cat = gpd.GeoDataFrame(rows, crs=4326)
cat['geometry'] = cat.geometry.buffer(0)
print(f'{len(cat)} catchments', flush=True)
catm = cat.to_crs(EA)
cat['km2'] = catm.area/1e6
# agreement with the official eHYD catchment size
m = cat.dropna(subset=['km2_ehyd'])
rel = (m.km2 - m.km2_ehyd)/m.km2_ehyd*100
print(f'vs eHYD: median {rel.median():+.1f}%, |err|<10% for '
      f'{(rel.abs()<10).mean()*100:.0f}%, <25% for {(rel.abs()<25).mean()*100:.0f}% '
      f'of {len(m)}', flush=True)

# ------------------------------------------------------------------- glaciers
rgi = gpd.read_file('data/glacier/11_rgi60_CentralEurope.shp')[
    ['RGIId', 'Name', 'Area', 'CenLat', 'CenLon', 'Zmin', 'Zmed', 'geometry']]
rgi = rgi.to_crs(EA)
rgi['a_km2'] = rgi.area/1e6

# per-glacier net volume loss, m3/yr (ASTER dh/dt, prefer 2014-19 then 1999-2019)
ch = pd.read_csv('data/glacier/change_at.csv', low_memory=False)
ch['b'] = pd.to_datetime(ch.begin_date, errors='coerce').dt.year
ch['e'] = pd.to_datetime(ch.end_date, errors='coerce').dt.year
ch = ch.dropna(subset=['b', 'e', 'volume_change', 'begin_outline_id'])
ch['yr'] = ch.e - ch.b
ch = ch[ch.yr > 0]
melt = {}
for pref in [(2014, 2019), (1999, 2019)]:
    sub = ch[(ch.b == pref[0]) & (ch.e == pref[1])]
    for _, r in sub.iterrows():
        rid = str(r.begin_outline_id)
        if rid.startswith('RGI60') and rid not in melt:
            melt[rid] = -float(r.volume_change)/r.yr     # m3/yr, +ve = loss
rgi['melt_m3a'] = rgi.RGIId.map(melt)
print(f'{rgi.melt_m3a.notna().sum()}/{len(rgi)} glaciers with ASTER dh/dt', flush=True)
# fill missing with the area-scaled median specific loss
spec = (rgi.melt_m3a/rgi.a_km2).median()
rgi['melt_m3a'] = rgi.melt_m3a.fillna(rgi.a_km2*spec)

# volume-area scaling (Bahr et al. 1997, c=0.034 km^(3-2g), g=1.375) for horizons
rgi['vol_mio_m3'] = 0.034*rgi.a_km2**1.375*1000

print('intersecting glaciers x catchments...', flush=True)
inter = gpd.overlay(catm[['hzb', 'geometry']], rgi[['RGIId', 'a_km2', 'melt_m3a',
                    'vol_mio_m3', 'geometry']], how='intersection')
inter['part_km2'] = inter.area/1e6
inter['frac'] = (inter.part_km2/inter.a_km2).clip(0, 1)
g = inter.groupby('hzb').apply(lambda d: pd.Series({
        'ice_km2': d.part_km2.sum(),
        'n_gl': len(d),
        'melt_mio_m3a': (d.melt_m3a*d.frac).sum()/1e6,
        'ice_vol_mio_m3': (d.vol_mio_m3*d.frac).sum()}), include_groups=False)
cat = cat.merge(g, left_on='hzb', right_index=True, how='left')
for c in ('ice_km2', 'n_gl', 'melt_mio_m3a', 'ice_vol_mio_m3'):
    cat[c] = cat[c].fillna(0)
cat['ice_pct'] = cat.ice_km2/cat.km2*100
print(f'{(cat.ice_km2>0).sum()} catchments contain ice; '
      f'max ice share {cat.ice_pct.max():.1f}%', flush=True)

# ---------------------------------------------------------------- snow (zonal)
# SNOWGRID-CL v2 grid: ENVI .f32 sidecars written by build_snow_reservoir.py
hdr = open(f'{SNOW}/swe_1961_apr.nc.hdr').read()
W = int([l for l in hdr.splitlines() if l.startswith('samples')][0].split('=')[1])
H = int([l for l in hdr.splitlines() if l.startswith('lines')][0].split('=')[1])
X0, Y0, PX = 112000.0, 585000.0, 1000.0    # map info, EPSG:3416 (ETRS89 AT Lambert)
xs = X0 + (np.arange(W)+0.5)*PX
ys = Y0 - (np.arange(H)+0.5)*PX
XX, YY = np.meshgrid(xs, ys)
pts = gpd.GeoDataFrame({'idx': np.arange(W*H)},
        geometry=gpd.points_from_xy(XX.ravel(), YY.ravel()), crs=3416).to_crs(EA)
print('zonal join of 1 km snow pixels...', flush=True)
sj = gpd.sjoin(pts, catm[['hzb', 'geometry']], how='inner', predicate='within')
# SNOWGRID's rectangular grid extends past the border but is no-data outside
# Austria; keep only cells that actually carry values (checked on one grid).
ref = np.fromfile(f'{SNOW}/swe_2010_apr.nc.f32', dtype='<f4').ravel()
valid = ref > -998
sj = sj[valid[sj.idx.values]]
pix = sj.groupby('hzb').idx.apply(lambda s: np.asarray(s)).to_dict()
print(f'{len(pix)} catchments with snow pixels, '
      f'median {int(np.median([len(v) for v in pix.values()]))} px', flush=True)

def grid(year, key):
    p = f'{SNOW}/swe_{year}_{key}.nc.f32'
    if not os.path.exists(p): return None
    a = np.fromfile(p, dtype='<f4').ravel()
    a[a <= -998] = np.nan
    return a

YEARS = sorted(int(os.path.basename(p).split('_')[1])
               for p in glob.glob(f'{SNOW}/swe_*_apr.nc.f32'))
snow = {k: {} for k in ('apr', 'jul')}
for key in ('apr', 'jul'):
    for y in YEARS:
        a = grid(y, key)
        if a is None: continue
        for hzb, ix in pix.items():
            v = a[ix]
            v = v[~np.isnan(v)]
            if len(v): snow[key].setdefault(hzb, []).append([y, round(float(v.mean()), 1)])
    print(f'  {key}: {len(snow[key])} catchments', flush=True)

def trend(ser):
    if not ser or len(ser) < 20: return {}
    y = np.array([s[0] for s in ser], float); v = np.array([s[1] for s in ser], float)
    sl = float(np.polyfit(y, v, 1)[0]*10)
    base = v[(y >= 1961) & (y <= 1990)].mean()
    last = v[y >= y.max()-9].mean()
    return {'mm_dec': round(sl, 2), 'mean_6190': round(float(base), 1),
            'mean_last10': round(float(last), 1),
            'pct_dec': round(sl/base*100, 1) if base > 5 else None}

# ------------------------------------------------------------------- assemble
prof = json.load(open('web/data/gauge_profiles.json'))['stations']
SEC_A = 365.25*86400
gauges = {}
for _, r in cat.iterrows():
    hzb = r.hzb
    p = prof.get(hzb, {})
    q = p.get('mean_m3s')
    flow = q*SEC_A/1e6 if q else None                     # mio m3/a
    rec = {'name': r['name'], 'river': r.river, 'lat': r.lat, 'lon': r.lon,
           'km2': round(r.km2, 1), 'km2_ehyd': r.km2_ehyd,
           'km2_err_pct': (round((r.km2-r.km2_ehyd)/r.km2_ehyd*100, 1)
                           if r.km2_ehyd else None),
           'snap_km': r.snap_km,
           'ice_km2': round(r.ice_km2, 3), 'ice_pct': round(r.ice_pct, 3),
           'n_gl': int(r.n_gl), 'melt_mio_m3a': round(r.melt_mio_m3a, 2),
           'ice_vol_mio_m3': round(r.ice_vol_mio_m3, 1),
           'flow_mio_m3a': round(flow, 1) if flow else None,
           'trend_pct_decade': p.get('trend_pct_decade')}
    if r.ice_km2 > 0 and r.melt_mio_m3a > 0:
        rec['depletion_years'] = round(r.ice_vol_mio_m3/r.melt_mio_m3a, 1)
    if flow and flow > 0:
        rec['melt_pct_flow'] = round(r.melt_mio_m3a/flow*100, 2)
    ap, ju = snow['apr'].get(hzb), snow['jul'].get(hzb)
    # SNOWGRID covers Austria only: a basin with foreign headwaters (Danube,
    # Rhine, Inn above Finstermünz) is sampled over its Austrian part only.
    # Volumes must therefore use the sampled pixel count (1 km2 each), not the
    # full basin area, and we record the coverage so the app can be honest.
    npx = len(pix.get(hzb, ()))
    rec['snow_px_km2'] = npx
    rec['snow_coverage'] = round(min(1.0, npx/r.km2), 3) if r.km2 else None
    if ap:
        t = trend(ap)
        rec['snow'] = {'apr': ap, **{f'apr_{k}': v for k, v in t.items()}}
        last = t.get('mean_last10'); base = t.get('mean_6190')
        if last is not None and npx:
            # mm w.e. over npx km2 -> mio m3
            rec['snow_store_mio_m3'] = round(last*npx/1000, 1)
            rec['snow_store_6190_mio_m3'] = round(base*npx/1000, 1) if base else None
            # only compare with flow when the basin is essentially all in-grid
            if flow and flow > 0 and (rec['snow_coverage'] or 0) >= 0.9:
                rec['snow_pct_flow'] = round(rec['snow_store_mio_m3']/flow*100, 1)
        if ju:
            tj = trend(ju)
            rec['snow'].update({'jul': ju, **{f'jul_{k}': v for k, v in tj.items()}})
    gauges[hzb] = rec

# ---- snap quality: MERIT can grab the mainstem instead of a small tributary.
# We trust a catchment only if it reproduces the official eHYD catchment size.
# Glacier ice is also only credible if the basin is (nearly) inside Austria,
# but RGI 6.0 region 11 covers the whole Alps, so foreign headwaters are fine
# for ice; only the snow grid is Austria-limited (see snow_coverage).
for hzb, rec in gauges.items():
    e = rec['km2_err_pct']
    if e is not None and (e != e): e = rec['km2_err_pct'] = None
    rec['quality'] = ('unverified' if e is None else
                      'good' if abs(e) <= 10 else
                      'fair' if abs(e) <= 25 else 'missnap')
nbad = sum(1 for v in gauges.values() if v['quality'] == 'missnap')
print(f'{nbad} catchments rejected as mis-snapped (>25% off eHYD size)', flush=True)

# ---- KG -> smallest containing catchment (real basin, not a 2 km line buffer)
kgs = json.load(open('web/data/kg_registry.json'))
kgp = gpd.GeoDataFrame({'code': list(kgs)},
        geometry=[Point(v['lon'], v['lat']) for v in kgs.values()], crs=4326).to_crs(EA)
print('assigning KGs to catchments...', flush=True)
good = [h for h, v in gauges.items() if v['quality'] != 'missnap']
cgood = catm[catm.hzb.isin(good)][['hzb', 'geometry']].copy()
cgood['ckm2'] = cgood.area/1e6
sj = gpd.sjoin(kgp, cgood, how='inner', predicate='within')
kg = {}
for code, d in sj.groupby('code'):
    d = d.sort_values('ckm2')
    small = d.iloc[0]
    gg = gauges[small.hzb]
    # the biggest ice share among the nested basins this KG sits in: the
    # smallest gauged basin may be ice-free while the river passing the KG
    # (a larger, ice-fed basin) is not.
    icy_h = max(d.hzb, key=lambda h: gauges[h]['ice_pct'])
    icy = gauges[icy_h]
    kg[code] = {'hzb': small.hzb, 'basin': gg['name'], 'river': gg['river'],
                'km2': round(float(small.ckm2), 1), 'n_nested': len(d),
                'ice_pct': gg['ice_pct'], 'melt_pct_flow': gg.get('melt_pct_flow'),
                'snow_pct_flow': gg.get('snow_pct_flow'),
                'snow_apr_pct_dec': (gg.get('snow') or {}).get('apr_pct_dec'),
                'snow_store_mio_m3': gg.get('snow_store_mio_m3'),
                'quality': gg['quality']}
    if icy['ice_pct'] > gg['ice_pct']:
        kg[code]['ice_basin'] = {'hzb': icy_h, 'name': icy['name'],
                                 'river': icy['river'], 'km2': icy['km2'],
                                 'ice_pct': icy['ice_pct'],
                                 'melt_pct_flow': icy.get('melt_pct_flow')}
print(f'{len(kg)}/{len(kgs)} KGs inside a verified gauged catchment; '
      f'{sum(1 for v in kg.values() if v["ice_pct"]>0 or "ice_basin" in v)} '
      'have ice in their basin', flush=True)

out = {'source': ('catchments delineated from MERIT-Hydro / MERIT-Basins by '
                  'mghydro.com/watersheds (M. Heberger, CC BY-NC-SA); glaciers '
                  'RGI 6.0 outlines with ASTER dh/dt (Hugonnet et al. 2021 via '
                  'WGMS FoG 2026-02); snow GeoSphere SNOWGRID-CL v2 1 km'),
       'generated': pd.Timestamp.utcnow().isoformat(),
       'validation': {'n_catchments': len(cat),
                      'km2_median_err_pct': round(float(rel.median()), 2),
                      'within_10pct': round(float((rel.abs() < 10).mean()*100), 1),
                      'within_25pct': round(float((rel.abs() < 25).mean()*100), 1)},
       'summary': {'ice_km2_total': round(float(rgi[rgi.RGIId.isin(inter.RGIId)].a_km2.sum()), 1),
                   'catchments_with_ice': int((cat.ice_km2 > 0).sum()),
                   'catchments_missnapped': nbad,
                   'max_melt_pct_flow': max([v.get('melt_pct_flow') or 0 for v in gauges.values()
                                             if v['quality'] != 'missnap']),
                   'kg_in_gauged_catchment': len(kg)},
       'gauges': gauges, 'kg': kg}
def clean(o):
    """NaN/Inf are not valid JSON (the browser's JSON.parse rejects them)."""
    if isinstance(o, float):
        return None if (o != o or o in (float('inf'), float('-inf'))) else o
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, (np.floating, np.integer)): return clean(o.item())
    return o

json.dump(clean(out), open(OUT, 'w'), allow_nan=False)
os.system(f'gzip -9 -c {OUT} > {OUT}.gz')
print('wrote', OUT, os.path.getsize(OUT)//1024, 'KB', flush=True)

# ---- map overlay: the ice-bearing headwater catchments.
# Gauged basins are deeply nested (the Danube at Korneuburg contains almost
# every alpine gauge), so drawing all of them would stack 14 translucent fills
# on top of each other. Keep only the *innermost* ice-bearing basins: those
# that do not contain another ice-bearing basin's outlet. That tiles the icy
# headwaters once each.
cat['quality'] = cat.hzb.map(lambda h: gauges[h]['quality'])
gf = cat[(cat.ice_km2 > 0) & (cat.quality != 'missnap') & (cat.ice_pct >= 0.2)].copy()
gfm = gf.to_crs(EA)
pt = {r.hzb: Point(r.lon, r.lat) for _, r in gf.iterrows()}
ptm = gpd.GeoSeries(list(pt.values()), index=list(pt), crs=4326).to_crs(EA)
inner = []
for (_, r), geom in zip(gf.iterrows(), gfm.geometry):
    contains_other = any(h != r.hzb and geom.contains(ptm[h]) for h in pt)
    if not contains_other: inner.append(r.hzb)
gf = gf[gf.hzb.isin(inner)].copy()
print(f'{len(gf)} innermost ice-bearing catchments for the overlay', flush=True)
gf['geometry'] = gf.to_crs(EA).simplify(150).to_crs(4326).geometry
gf[['hzb', 'name', 'river', 'km2', 'ice_km2', 'ice_pct', 'melt_mio_m3a', 'geometry']] \
    .to_file(GEO, driver='GeoJSON')
os.system(f'gzip -9 -c {GEO} > {GEO}.gz')
print('wrote', GEO, os.path.getsize(GEO)//1024, 'KB')

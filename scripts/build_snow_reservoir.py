#!/usr/bin/env python3
"""Seasonal snow reservoir (SNOWGRID-CL, GeoSphere Austria) per KG and gauge.

Downloads 1 km SWE grids for 1 April (peak-accumulation proxy) of every year
1961..now plus 1 July (high-alpine residual) and samples them at KG centroids,
eHYD river gauges and GW stations. Output: web/data/snow_reservoir.json
  { kg: {code: {apr: [[year, mm], ...], trend_pct_decade, mean_1961_1990,
                mean_last10, jul_trend_pct_decade}}, gauges: {...}, gw: {...} }
mm = kg/m2 SWE.
"""
import json, os, subprocess, sys, math
from osgeo import gdal
import numpy as np

API = 'https://dataset.api.hub.geosphere.at/v1/grid/historical/snowgrid_cl-v2-1d-1km'
CACHE = 'data/glacier/snowgrid'
OUT = 'web/data/snow_reservoir.json'
Y0, Y1 = 1961, 2026
DAYS = {'apr': '04-01', 'jul': '07-01'}
os.makedirs(CACHE, exist_ok=True)
gdal.UseExceptions()

def fetch(year, key):
    p = f'{CACHE}/swe_{year}_{key}.nc'
    if os.path.exists(p) and os.path.getsize(p) > 10000: return p
    d = f'{year}-{DAYS[key]}'
    url = (f'{API}?parameters=swe_tot&start={d}T00:00&end={d}T00:00'
           f'&output_format=netcdf&bbox=46.2,9.4,49.1,17.3')
    r = subprocess.run(['curl', '-sS', '--max-time', '180', '-o', p, url])
    if r.returncode or os.path.getsize(p) < 10000:
        print(f'  fetch failed {d}'); os.path.exists(p) and os.remove(p); return None
    return p

def read_grid(p):
    """gdal's numpy bridge is broken against numpy 2 here -> go via a raw
    float32 ENVI dump and np.fromfile."""
    raw = p + '.f32'
    if not os.path.exists(raw):
        subprocess.run(['gdal_translate', '-q', '-of', 'ENVI', '-ot', 'Float32',
                        p, raw], check=True)
    a = np.fromfile(raw, dtype='<f4').reshape(GH, GW_)
    a[a < -1e30] = np.nan
    if NODATA is not None: a[a == NODATA] = np.nan
    return a

# ---- sample targets
kgs = json.load(open('web/data/kg_registry.json'))
gp = json.load(open('web/data/gauge_profiles.json'))['stations']
gwst = json.load(open('data/gw_aktuell/longterm_2026.json'))
targets = []   # (group, id, lon, lat)
for c, k in kgs.items(): targets.append(('kg', c, k['lon'], k['lat']))
for g, v in gp.items():
    if 'lat' in v: targets.append(('gauges', g, v['lon'], v['lat']))
for h, v in gwst.items(): targets.append(('gw', h, v['coords'][0], v['coords'][1]))
print(f'{len(targets)} sample points', flush=True)

# transform WGS84 -> grid CRS once, using the first grid
first = fetch(2000, 'apr')
ds = gdal.Open(first)
from osgeo import osr
src = osr.SpatialReference(); src.ImportFromEPSG(4326); src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
dst = osr.SpatialReference(); dst.ImportFromWkt(ds.GetProjection())
tr = osr.CoordinateTransformation(src, dst)
gt = ds.GetGeoTransform(); W, H = ds.RasterXSize, ds.RasterYSize
GW_, GH = W, H
NODATA = ds.GetRasterBand(1).GetNoDataValue()
inv = gdal.InvGeoTransform(gt)
px = []
for grp, tid, lon, lat in targets:
    x, y, _ = tr.TransformPoint(lon, lat)
    c, r = gdal.ApplyGeoTransform(inv, x, y)
    c, r = int(c), int(r)
    px.append((c, r) if 0 <= c < W and 0 <= r < H else None)
print(f'{sum(1 for p in px if p)} inside grid', flush=True)
ds = None

series = {k: {g: {} for g in ('kg', 'gauges', 'gw')} for k in DAYS}
for key in DAYS:
    for year in range(Y0, Y1+1):
        p = fetch(year, key)
        if not p: continue
        arr = read_grid(p)
        for (grp, tid, lon, lat), pp in zip(targets, px):
            if not pp: continue
            v = arr[pp[1], pp[0]]
            if not np.isnan(v):
                series[key][grp].setdefault(tid, []).append([year, round(float(v), 1)])
        print(f'  {key} {year}', end='\r', flush=True)
    print()

def trend(ser):
    """mm/decade and %/decade of the 1961-90 baseline."""
    if len(ser) < 20: return None, None, None, None
    y = np.array([s[0] for s in ser], float); v = np.array([s[1] for s in ser], float)
    sl = np.polyfit(y, v, 1)[0]*10
    base = v[(y >= 1961) & (y <= 1990)].mean() if (y <= 1990).sum() >= 10 else np.nan
    last = v[y >= y.max()-9].mean()
    pct = sl/base*100 if base and base > 5 else None
    return (round(sl, 2), None if pct is None else round(pct, 1),
            None if np.isnan(base) else round(base, 1), round(last, 1))

out = {'source': 'GeoSphere Austria SNOWGRID-CL v2 (1 km, 1961-2026), 1 Apr & 1 Jul SWE',
       'note': 'swe_tot in kg/m2 (= mm water equivalent) at KG centroid / station pixel'}
for grp in ('kg', 'gauges', 'gw'):
    o = {}
    for tid, ser in series['apr'][grp].items():
        sl, pct, base, last = trend(ser)
        rec = {'apr': ser, 'apr_mm_decade': sl, 'apr_pct_decade': pct,
               'apr_mean_6190': base, 'apr_mean_last10': last}
        js = series['jul'][grp].get(tid)
        if js:
            jsl, jpct, jbase, jlast = trend(js)
            rec.update({'jul': js, 'jul_mm_decade': jsl, 'jul_pct_decade': jpct,
                        'jul_mean_6190': jbase, 'jul_mean_last10': jlast})
        o[tid] = rec
    out[grp] = o
    print(grp, len(o))
json.dump(out, open(OUT, 'w'))
os.system(f'gzip -9 -c {OUT} > {OUT}.gz')
print('wrote', OUT)

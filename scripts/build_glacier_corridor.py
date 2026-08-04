#!/usr/bin/env python3
"""Glacier-fed corridor: buffer the glacier-fed river reaches and intersect
with KGs / Gemeinden, instead of point-snapping centroids to the network.

A KG counts as glacier-fed to the degree its area overlaps the corridor
(2 km each side of a glacier-fed reach = valley-aquifer influence width), and
its corridor share is weighted by the melt volume of the overlapping reaches.

In:  data/glacier/glacier_reaches.geojson  (from build_glacier_downstream.py)
     data/gemeinden.geojson, web/data/kg_registry.json (bbox proxy for KGs)
Out: web/data/glacier_corridor.json   per KG / Gemeinde overlap stats
     web/data/glacier_corridor.geojson(.gz)  map overlay (dissolved, by melt class)
"""
import json, os
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape, box
from shapely.ops import unary_union

BUF_M = 2000
rc = gpd.read_file('data/glacier/glacier_reaches.geojson')
print(f'{len(rc)} reach segments', flush=True)
rc = rc.to_crs(31287)

# melt classes for the overlay (mio m3/a of net ice loss upstream)
BINS = [0, 5, 20, 50, 100, 1e9]
LBL = ['<5', '5-20', '20-50', '50-100', '>100']
rc['cls'] = pd.cut(rc.melt_mio_m3a, BINS, labels=LBL, include_lowest=True)

print('dissolving overlay (lines, merged per melt class)...', flush=True)
from shapely.ops import linemerge
ov = []
for lbl in LBL:
    sub = rc[rc.cls == lbl]
    if not len(sub): continue
    g = linemerge(unary_union(sub.geometry)).simplify(40)
    ov.append({'cls': lbl, 'geometry': g})
ovg = gpd.GeoDataFrame(ov, crs=31287).to_crs(4326)
ovg.to_file('web/data/glacier_corridor.geojson', driver='GeoJSON')
os.system('gzip -9 -c web/data/glacier_corridor.geojson > web/data/glacier_corridor.geojson.gz')
print('  overlay written', flush=True)

print(f'buffering corridor {BUF_M} m...', flush=True)
corr = rc.copy()
corr['geometry'] = corr.geometry.buffer(BUF_M)
corr = corr[['melt_mio_m3a', 'gl_km2', 'km', 'geometry']]
corr_union = unary_union(corr.geometry)
print('  union done', flush=True)

def overlap(geoms, ids):
    """area-weighted corridor share + melt-weighted mean upstream melt."""
    sidx = corr.sindex
    out = {}
    for i, (gid, g) in enumerate(zip(ids, geoms)):
        if g is None or g.is_empty: continue
        inter = g.intersection(corr_union)
        if inter.is_empty: continue
        share = inter.area/g.area if g.area else 0
        cand = list(sidx.intersection(g.bounds))
        best_melt = 0.0; best_km = None; ice = 0.0
        for c in cand:
            r = corr.iloc[c]
            if not r.geometry.intersects(g): continue
            if r.melt_mio_m3a > best_melt:
                best_melt = float(r.melt_mio_m3a); ice = float(r.gl_km2); best_km = float(r.km)
        out[gid] = {'corridor_share': round(share, 3),
                    'corridor_km2': round(inter.area/1e6, 2),
                    'melt_mio_m3a': round(best_melt, 2), 'ice_km2': round(ice, 2),
                    'reach_km': best_km}
        if i % 500 == 0: print(f'  {i}', end='\r', flush=True)
    print()
    return out

gem = gpd.read_file('data/gemeinden.geojson').to_crs(31287)
gcol = 'iso' if 'iso' in gem.columns else [c for c in gem.columns if 'id' in c.lower() or 'code' in c.lower()][0]
print('gemeinde id col:', gcol, flush=True)
gem_out = overlap(list(gem.geometry), [str(x) for x in gem[gcol]])
print(f'{len(gem_out)} Gemeinden touch the corridor', flush=True)

# KGs: bbox from the registry as a polygon proxy (no KG polygons offline)
kgs = json.load(open('web/data/kg_registry.json'))
ids, geoms = [], []
for c, k in kgs.items():
    bb = k.get('bb')
    if not bb: continue
    ids.append(c); geoms.append(box(*bb))
kgg = gpd.GeoDataFrame({'id': ids}, geometry=geoms, crs=4326).to_crs(31287)
kg_out = overlap(list(kgg.geometry), ids)
print(f'{len(kg_out)} KGs touch the corridor (bbox proxy)', flush=True)

json.dump({'params': {'buffer_m': BUF_M, 'kg_geometry': 'registry bbox proxy'},
           'source': 'glacier-fed reaches (OSM waterways downstream of RGI6 ice) buffered',
           'gemeinden': gem_out, 'kg': kg_out},
          open('web/data/glacier_corridor.json', 'w'))
os.system('gzip -9 -c web/data/glacier_corridor.json > web/data/glacier_corridor.json.gz')
print('wrote web/data/glacier_corridor.json')

#!/usr/bin/env python3
"""Glacier-fed river reaches from MERIT-Basins flow paths.

data/flowpaths/<RGIId>.json (scripts/fetch_glacier_flowpaths.py) holds the
ordered chain of downstream MERIT reaches from each of the 735 Austrian
glaciers, all the way to the Black Sea / North Sea. Union them per reach:

  ice_km2      RGI 6.0 area of all glaciers whose flow path passes this reach
  melt_mio_m3a their net ice loss (ASTER dh/dt 2014-19, Hugonnet et al. 2021)
  dist_km      shortest along-river distance from ice to this reach
  n_gl, sorder

This replaces the OSM waterway walk of build_glacier_downstream.py:
MERIT-Basins reaches are topologically connected by construction (derived from
a hydrologically conditioned DEM), so no direction/tagging errors, no dead
ends, and the chain is guaranteed to reach the sea. Reaches are clipped to
Austria for the map overlay but distances are computed along the full path.

Out: web/data/merit_reaches.geojson(.gz)  overlay, melt-classed
     web/data/merit_reach_kg.json         per-KG nearest glacier-fed reach
"""
import json, os, glob, math
import numpy as np
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, shape
from shapely.ops import linemerge, unary_union

EA = 31287
OUT_GEO = 'web/data/merit_reaches.geojson'
OUT_KG = 'web/data/merit_reach_kg.json'

# per-glacier melt (same source/order as build_watershed_context.py)
ch = pd.read_csv('data/glacier/change_at.csv', low_memory=False)
ch['b'] = pd.to_datetime(ch.begin_date, errors='coerce').dt.year
ch['e'] = pd.to_datetime(ch.end_date, errors='coerce').dt.year
ch = ch.dropna(subset=['b', 'e', 'volume_change']); ch = ch[ch.e > ch.b]
melt = {}
for pref in [(2014, 2019), (1999, 2019)]:
    for _, r in ch[(ch.b == pref[0]) & (ch.e == pref[1])].iterrows():
        rid = str(r.begin_outline_id)
        if rid.startswith('RGI60') and rid not in melt:
            melt[rid] = -float(r.volume_change)/(r.e-r.b)

def seg_km(cs):
    R = 6371.0088; p = math.pi/180; t = 0.0
    for i in range(len(cs)-1):
        x1, y1 = cs[i][:2]; x2, y2 = cs[i+1][:2]
        t += 2*R*math.asin(math.sqrt(math.sin((y2-y1)*p/2)**2 +
             math.cos(y1*p)*math.cos(y2*p)*math.sin((x2-x1)*p/2)**2))
    return t

def order_path(reaches, lat, lon):
    """Deprecated: the API returns a flow path's reaches unordered and with
    mixed linestring direction (some point upstream), so a simple endpoint chain
    breaks. Distances are computed by Dijkstra over the reach graph instead."""
    return reaches

reach = {}     # comid -> dict
files = sorted(glob.glob('data/flowpaths/*.json'))
print(f'{len(files)} glacier flow paths')
GL = {}        # rgi -> (area, melt m3/a, lat, lon)
for p in files:
    d = json.load(open(p))
    rgi = d['rgi_id']; a = d['area_km2']
    GL[rgi] = (a, melt.get(rgi), d['lat'], d['lon'])
    for r in d['reaches']:
        cid = r['comid']
        if cid is None or len(r['coords']) < 2: continue
        e = reach.get(cid)
        if e is None:
            e = reach[cid] = {'ice_km2': 0.0, 'n_gl': 0, 'sorder': r.get('sorder'),
                              'coords': r['coords'], 'melt_known': 0.0, 'a_known': 0.0,
                              'src': set()}
        e['ice_km2'] += a
        e['n_gl'] += 1
        e['src'].add(rgi)
        if melt.get(rgi) is not None:
            e['melt_known'] += melt[rgi]; e['a_known'] += a
print(f'{len(reach)} distinct glacier-fed MERIT reaches')

# ---- river distance from ice: Dijkstra over the reach graph.
# Endpoints are snapped to 4 decimals (~11 m) and treated as undirected, which
# is safe here because every reach in this set already lies on a downstream path
# from some glacier; the shortest network path from the nearest ice is then the
# along-river distance we want, without relying on linestring direction.
import heapq
def node(c): return (round(c[0], 4), round(c[1], 4))
adj = {}
for cid, e in reach.items():
    a, b = node(e['coords'][0]), node(e['coords'][-1])
    L = seg_km(e['coords'])
    e['len_km'] = L
    e['a'], e['b'] = a, b
    adj.setdefault(a, []).append((b, L))
    adj.setdefault(b, []).append((a, L))
nodes = list(adj)
# sources: the graph node nearest each glacier centroid
nn = {}
for rgi, (a, m, glat, glon) in GL.items():
    best = min(nodes, key=lambda n: (n[0]-glon)**2 + (n[1]-glat)**2)
    nn[rgi] = best
dist = {n: math.inf for n in nodes}
pq = []
for n in set(nn.values()):
    dist[n] = 0.0; heapq.heappush(pq, (0.0, n))
while pq:
    d0, n = heapq.heappop(pq)
    if d0 > dist[n] + 1e-9: continue
    for m2, w in adj[n]:
        nd = d0 + w
        if nd < dist[m2] - 1e-9:
            dist[m2] = nd; heapq.heappush(pq, (nd, m2))
for cid, e in reach.items():
    e['dist_km'] = min(dist.get(e['a'], math.inf), dist.get(e['b'], math.inf))
    if not math.isfinite(e['dist_km']): e['dist_km'] = None
reach_dists = [e['dist_km'] for e in reach.values() if e['dist_km'] is not None]
print(f'river distance from ice: median {sorted(reach_dists)[len(reach_dists)//2]:.0f} km, '
      f'max {max(reach_dists):.0f} km, {len(reach)-len(reach_dists)} unreachable')

# fill unmeasured glaciers with the specific loss of the measured ones on that reach
for cid, e in reach.items():
    spec = e['melt_known']/e['a_known'] if e['a_known'] > 0 else 0.0
    e['melt_mio_m3a'] = (e['melt_known'] + spec*(e['ice_km2']-e['a_known']))/1e6

rows = [{'comid': cid, 'ice_km2': round(e['ice_km2'], 2),
         'melt_mio_m3a': round(e['melt_mio_m3a'], 2), 'n_gl': e['n_gl'],
         'dist_km': None if e['dist_km'] is None else round(e['dist_km'], 1),
         'sorder': e['sorder'],
         'geometry': LineString([(c[0], c[1]) for c in e['coords']])}
        for cid, e in reach.items() if len(e['coords']) > 1]
rc = gpd.GeoDataFrame(rows, crs=4326)

# clip to Austria (+10 km) for the overlay
at = gpd.read_file('data/gemeinden.geojson').to_crs(EA).union_all().buffer(10000)
rcm = rc.to_crs(EA)
keep = rcm.geometry.intersects(at)
rc, rcm = rc[keep.values].reset_index(drop=True), rcm[keep.values].reset_index(drop=True)
print(f'{len(rc)} reaches in/near Austria, '
      f'{rc.melt_mio_m3a.max():.0f} Mm3/a max upstream ice loss')

BINS = [0, 5, 20, 50, 100, 1e9]; LBL = ['<5', '5-20', '20-50', '50-100', '>100']
rc['cls'] = pd.cut(rc.melt_mio_m3a, BINS, labels=LBL, include_lowest=True)
ov = []
for lbl in LBL:
    sub = rcm[(rc.cls == lbl).values]
    if not len(sub): continue
    g = unary_union(sub.geometry)
    g = linemerge(g) if g.geom_type != 'LineString' else g
    ov.append({'cls': lbl, 'km': round(sub.length.sum()/1000, 1),
               'geometry': g.simplify(60)})
gpd.GeoDataFrame(ov, crs=EA).to_crs(4326).to_file(OUT_GEO, driver='GeoJSON')
os.system(f'gzip -9 -c {OUT_GEO} > {OUT_GEO}.gz')
print('wrote', OUT_GEO, os.path.getsize(OUT_GEO)//1024, 'KB')

# per-KG nearest glacier-fed reach (<=5 km): "the river beside you carries melt"
kgs = json.load(open('web/data/kg_registry.json'))
kgp = gpd.GeoDataFrame({'code': list(kgs)},
        geometry=[Point(v['lon'], v['lat']) for v in kgs.values()], crs=4326).to_crs(EA)
rcm2 = rcm.copy()
for c in ('comid', 'ice_km2', 'melt_mio_m3a', 'dist_km', 'n_gl', 'sorder'):
    rcm2[c] = rc[c].values
j = gpd.sjoin_nearest(kgp, rcm2, how='left', max_distance=5000,
                      distance_col='d_m')
j = j.sort_values('melt_mio_m3a', ascending=False).drop_duplicates('code')
out = {}
for _, r in j.iterrows():
    if pd.isna(r.get('comid')): continue
    out[r.code] = {'comid': int(r.comid), 'ice_km2': float(r.ice_km2),
                   'melt_mio_m3a': float(r.melt_mio_m3a),
                   'river_km_from_ice': (None if pd.isna(r.dist_km)
                                         else float(r.dist_km)),
                   'n_gl': int(r.n_gl), 'sorder': int(r.sorder) if r.sorder else None,
                   'dist_to_river_m': int(r.d_m)}
json.dump({'source': ('MERIT-Basins downstream flow paths via mghydro.com '
                      '(CC BY-NC-SA); glaciers RGI 6.0 + ASTER dh/dt '
                      'Hugonnet et al. 2021 (WGMS FoG 2026-02)'),
           'n_reaches': len(rc), 'kg': out}, open(OUT_KG, 'w'))
os.system(f'gzip -9 -c {OUT_KG} > {OUT_KG}.gz')
print(f'{len(out)}/{len(kgs)} KGs within 5 km of a glacier-fed reach -> {OUT_KG}')

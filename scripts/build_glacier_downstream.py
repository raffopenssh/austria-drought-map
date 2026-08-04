#!/usr/bin/env python3
"""Glacier -> river -> aquifer connectivity for Austria.

Walk the directed OSM waterway network DOWNSTREAM from every RGI6 glacier
(centroid in AT) and record, for every eHYD river gauge, groundwater station
and Katastralgemeinde centroid, how much glacier area (km2) lies upstream and
how far along the network the nearest glacier ice is.

Inputs
  data/glacier/11_rgi60_CentralEurope.shp  (RGI 6.0 region 11)
  data/osm/waterways.geojsonseq            (flow = linestring direction)
  data/gw_aktuell/pegel_daily.json         river gauges
  data/gw_aktuell/longterm_2026.json       GW stations
  web/data/gauge_profiles.json             gauge catchment km2 (for share)
  web/data/kg_registry.json                KG centroids

Output data/glacier/glacier_downstream.json
  { glaciers: {rgi_id: {name, area_km2, lat, lon, zmin, zmed}},
    pegel: {hzb: {gl_km2, n_gl, km, off_m}},
    gw:    {hzb: {...}}, kg: {code: {...}} }
"""
import json, math, os, sys, heapq
from collections import defaultdict

WATERWAYS = 'data/osm/waterways.geojsonseq'
OUT = 'data/glacier/glacier_downstream.json'
MAX_NET_KM = 400.0
PG_BUF, GW_BUF, KG_BUF = 250.0, 4000.0, 4000.0
CELL = 0.01

def hav_m(lat1, lon1, lat2, lon2):
    R = 6371000.0; p = math.pi/180
    a = (math.sin((lat2-lat1)*p/2)**2 +
         math.cos(lat1*p)*math.cos(lat2*p)*math.sin((lon2-lon1)*p/2)**2)
    return 2*R*math.asin(math.sqrt(a))
def key(lon, lat): return (round(lon, 6), round(lat, 6))
def cell(lon, lat): return (int(lon/CELL), int(lat/CELL))

# ---------------------------------------------------------------- glaciers
import geopandas as gpd
from shapely.prepared import prep
rgi = gpd.read_file('data/glacier/11_rgi60_CentralEurope.shp')
gem = gpd.read_file('data/gemeinden.geojson')
at = gem.union_all()
cen = gpd.points_from_xy(rgi.CenLon, rgi.CenLat)
mask = gpd.GeoSeries(cen, crs=4326).within(at)
gl = rgi[mask.values].reset_index(drop=True)
print(f'{len(gl)} glaciers in AT, {gl.Area.sum():.1f} km2', flush=True)
GL = {}
for i, r in gl.iterrows():
    GL[r.RGIId] = {'name': r.Name, 'area_km2': float(r.Area), 'lat': float(r.CenLat),
                   'lon': float(r.CenLon), 'zmin': int(r.Zmin), 'zmed': int(r.Zmed)}

# ASTER dh/dt volume change (Hugonnet et al. 2021 via WGMS FoG change.csv)
import csv as _csv
melt = {}
try:
    import pandas as _pd
    _c = _pd.read_csv('data/glacier/change_at.csv', low_memory=False)
    _c['b'] = _pd.to_datetime(_c.begin_date).dt.year
    _c['e'] = _pd.to_datetime(_c.end_date).dt.year
    for per, w in [((2014, 2019), 'recent'), ((1999, 2019), 'long')]:
        sub = _c[(_c.b == per[0]) & (_c.e == per[1])]
        yrs = per[1]-per[0]
        for _, r in sub.iterrows():
            if _pd.isna(r.volume_change): continue
            melt.setdefault(r.begin_outline_id, {})[w] = -float(r.volume_change)/yrs
except Exception as e:
    print('melt load failed', e)
print(f'{len(melt)} glaciers w/ ASTER volume change', flush=True)

gids = list(GL)
gidx = {g: i for i, g in enumerate(gids)}
# buffered polygons ~ 400 m for outlet detection
gl_m = gl.to_crs(31287)
gl_m['buf'] = gl_m.geometry.buffer(400)
bufs = gpd.GeoSeries(gl_m['buf'], crs=31287).to_crs(4326)
prepped = [(gids[i], prep(bufs.iloc[i]), bufs.iloc[i].bounds) for i in range(len(gids))]

# ---------------------------------------------------------------- graph
print('pass 1: endpoints...', flush=True)
endpoints = set()
for line in open(WATERWAYS):
    line = line.strip().lstrip('\x1e')
    if not line: continue
    try: g = json.loads(line)
    except Exception: continue
    geo = g['geometry']
    if geo['type'] != 'LineString': continue
    p = g.get('properties') or {}
    if 'waterway' not in p: continue
    c = geo['coordinates']
    if len(c) < 2: continue
    endpoints.add(key(*c[0][:2])); endpoints.add(key(*c[-1][:2]))

print('pass 2: directed graph...', flush=True)
adj = defaultdict(list)
segs = []
grid = defaultdict(list)   # snapping index: (lon,lat,downstream_node,dist_to_that_node)
for line in open(WATERWAYS):
    line = line.strip().lstrip('\x1e')
    if not line: continue
    try: g = json.loads(line)
    except Exception: continue
    geo = g['geometry']
    if geo['type'] != 'LineString': continue
    p = g.get('properties') or {}
    if 'waterway' not in p: continue
    c = geo['coordinates']
    if len(c) < 2: continue
    cuts = [i for i in range(1, len(c)-1) if key(*c[i][:2]) in endpoints]
    bounds = [0] + cuts + [len(c)-1]
    for bi in range(len(bounds)-1):
        i0, i1 = bounds[bi], bounds[bi+1]
        n0, n1 = key(*c[i0][:2]), key(*c[i1][:2])
        pts = c[i0:i1+1]; cum = 0.0; lens = [0.0]
        for j in range(1, len(pts)):
            cum += hav_m(pts[j-1][1], pts[j-1][0], pts[j][1], pts[j][0]); lens.append(cum)
        if cum == 0: continue
        adj[n0].append((n1, cum))
        segs.append((n0, n1, [[round(x, 5), round(y, 5)] for x, y in
                              ([q[:2] for q in pts] if len(pts) <= 40 else
                               [q[:2] for q in pts[::max(1, len(pts)//40)]] + [pts[-1][:2]])]))
        for j, pt in enumerate(pts):
            grid[cell(pt[0], pt[1])].append((pt[0], pt[1], n1, cum - lens[j]))
print(f'  {len(adj)} nodes', flush=True)

# ------------------------------------------------- glacier outlet sources
print('snapping glaciers...', flush=True)
node_cells = defaultdict(list)
for c, items in grid.items():
    for (lon, lat, n1, dd) in items:
        node_cells[c].append((lon, lat, n1, dd))

sources = defaultdict(set)   # node -> set of glacier idx
unsnapped = []
for gid, pg, (minx, miny, maxx, maxy) in prepped:
    from shapely.geometry import Point
    hits = set()
    for cx in range(int(minx/CELL), int(maxx/CELL)+1):
        for cy in range(int(miny/CELL), int(maxy/CELL)+1):
            for (lon, lat, n1, dd) in node_cells.get((cx, cy), ()):
                if pg.contains(Point(lon, lat)): hits.add(n1)
    if not hits:
        # fallback: nearest network vertex to centroid
        la, lo = GL[gid]['lat'], GL[gid]['lon']
        cx, cy = cell(lo, la); best = None
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                for (lon, lat, n1, dd) in node_cells.get((cx+dx, cy+dy), ()):
                    d = hav_m(la, lo, lat, lon)
                    if best is None or d < best[0]: best = (d, n1)
        if best and best[0] < 4000: hits = {best[1]}
        else: unsnapped.append(gid); continue
    for n in hits: sources[n].add(gidx[gid])
print(f'  {len(sources)} source nodes, {len(unsnapped)} unsnapped', flush=True)

# ------------------------------------------------- multi-source Dijkstra
print('dijkstra (distance to nearest ice)...', flush=True)
dist = {}
pq = [(0.0, n) for n in sources]
for n in sources: dist[n] = 0.0
heapq.heapify(pq)
while pq:
    d, n = heapq.heappop(pq)
    if d > dist.get(n, 1e18) or d > MAX_NET_KM*1000: continue
    for n2, w in adj.get(n, ()):
        nd = d + w
        if nd < dist.get(n2, 1e18):
            dist[n2] = nd; heapq.heappush(pq, (nd, n2))
print(f'  {len(dist)} reachable nodes', flush=True)

# ------------------------------------------------- mask propagation (SCC DAG)
print('scc + mask propagation...', flush=True)
R = set(dist)
sub = {n: [n2 for n2, w in adj.get(n, ()) if n2 in R] for n in R}
# iterative Tarjan
index = {}; low = {}; onstk = {}; stk = []; comp = {}; counter = [0]; ncomp = [0]
for root in R:
    if root in index: continue
    work = [(root, iter(sub[root]))]
    index[root] = low[root] = counter[0]; counter[0] += 1
    stk.append(root); onstk[root] = True
    while work:
        v, it = work[-1]
        adv = False
        for w in it:
            if w not in index:
                index[w] = low[w] = counter[0]; counter[0] += 1
                stk.append(w); onstk[w] = True
                work.append((w, iter(sub[w]))); adv = True; break
            elif onstk.get(w):
                if index[w] < low[v]: low[v] = index[w]
        if adv: continue
        work.pop()
        if work:
            u = work[-1][0]
            if low[v] < low[u]: low[u] = low[v]
        if low[v] == index[v]:
            cid = ncomp[0]; ncomp[0] += 1
            while True:
                w = stk.pop(); onstk[w] = False; comp[w] = cid
                if w == v: break
print(f'  {ncomp[0]} components', flush=True)

cadj = defaultdict(set)
cin = defaultdict(int)
for n in R:
    cn = comp[n]
    for n2 in sub[n]:
        c2 = comp[n2]
        if c2 != cn and c2 not in cadj[cn]:
            cadj[cn].add(c2); cin[c2] += 1
cmask = defaultdict(int)
for n, gs in sources.items():
    if n in comp:
        m = 0
        for gi in gs: m |= (1 << gi)
        cmask[comp[n]] |= m
# Kahn
from collections import deque
q = deque(c for c in range(ncomp[0]) if cin[c] == 0)
order = []
cin2 = dict(cin)
while q:
    c = q.popleft(); order.append(c)
    for c2 in cadj[c]:
        cin2[c2] = cin2.get(c2, 0) - 1
        if cin2[c2] == 0: q.append(c2)
for c in order:
    m = cmask[c]
    if not m: continue
    for c2 in cadj[c]: cmask[c2] |= m
print(f'  topo {len(order)}/{ncomp[0]}', flush=True)

# ice VOLUME from volume-area scaling (Bahr et al. 1997: V[km3]=c*A^gamma,
# c=0.0347, gamma=1.375 for valley glaciers) -> gives a depletion horizon.
VA_C, VA_G = 0.0347, 1.375
for g in GL:
    a = GL[g]['area_km2']
    GL[g]['vol_mio_m3'] = round(VA_C*(a**VA_G)*1e9/1e6, 1)

for g in GL:
    m = melt.get(g, {})
    GL[g]['melt_m3a_recent'] = m.get('recent')
    GL[g]['melt_m3a_long'] = m.get('long')
# fill glaciers without ASTER coverage with the area-scaled mean specific loss
for w in ('recent', 'long'):
    k = f'melt_m3a_{w}'
    tot_v = sum(GL[g][k] for g in GL if GL[g][k])
    tot_a = sum(GL[g]['area_km2'] for g in GL if GL[g][k])
    rate = tot_v/tot_a if tot_a else 0.0
    n = 0
    for g in GL:
        if GL[g][k] is None:
            GL[g][k] = GL[g]['area_km2']*rate; GL[g][k+'_est'] = True; n += 1
    print(f'{w}: mean {rate/1e6:.2f} mio m3/km2/a, {n} glaciers estimated', flush=True)

for g in GL:
    mr = GL[g]['melt_m3a_recent']
    GL[g]['depletion_years'] = round(GL[g]['vol_mio_m3']*1e6/mr, 1) if mr else None

AREA = [GL[g]['area_km2'] for g in gids]
VOL = [GL[g]['vol_mio_m3'] for g in gids]
MELT_R = [GL[g]['melt_m3a_recent'] for g in gids]
MELT_L = [GL[g]['melt_m3a_long'] for g in gids]
_mcache = {}
def mask_stats(m):
    r = _mcache.get(m)
    if r is not None: return r
    tot = 0.0; n = 0; big = (None, 0.0); mr = 0.0; ml = 0.0; vol = 0.0
    mm = m; i = 0
    while mm:
        if mm & 1:
            tot += AREA[i]; n += 1; mr += MELT_R[i]; ml += MELT_L[i]; vol += VOL[i]
            if AREA[i] > big[1]: big = (gids[i], AREA[i])
        mm >>= 1; i += 1
    r = (tot, n, big[0], mr, ml, vol)
    _mcache[m] = r
    return r

# ------------------------------------------------- glacier-fed reaches
print('exporting glacier-fed reaches...', flush=True)
feats = []
for n0, n1, pts in segs:
    if n1 not in dist: continue           # not downstream of ice
    m = cmask.get(comp[n1], 0)
    if not m: continue
    tot, ngl, big, mr, ml, vol = mask_stats(m)
    feats.append({'type': 'Feature',
        'geometry': {'type': 'LineString', 'coordinates': pts},
        'properties': {'gl_km2': round(tot, 2), 'n_gl': ngl,
                       'km': round(dist[n1]/1000, 1),
                       'melt_mio_m3a': round(mr/1e6, 2)}})
json.dump({'type': 'FeatureCollection', 'features': feats},
          open('data/glacier/glacier_reaches.geojson', 'w'))
print(f'  {len(feats)} reach segments', flush=True)

# ------------------------------------------------- targets
print('assigning targets...', flush=True)
ncell = defaultdict(list)
for n in R: ncell[cell(*n)].append(n)

def query(lat, lon, buf, mode='nearest'):
    """Nearest network node within buf; ice only counted if THAT node is
    downstream of ice (prevents ice-free tributary gauges from inheriting the
    mainstem's glaciers just because the confluence is nearby)."""
    cx, cy = cell(lon, lat); r = int(buf/1000.0)+1
    cands = []
    for dx in range(-r, r+1):
        for dy in range(-r, r+1):
            for (nlon, nlat, n1, dd) in node_cells.get((cx+dx, cy+dy), ()):
                off = hav_m(lat, lon, nlat, nlon)
                if off <= buf: cands.append((off, n1))
    if not cands: return None
    cands.sort()
    near_off = cands[0][0]
    tol = 200 if mode == 'nearest' else 1e9   # 'any': whole buffer (valley aquifer)
    best = None
    for off, n in cands:
        if off > near_off + tol: break
        if n not in dist: continue
        m = cmask.get(comp[n], 0)
        if not m: continue
        tot = mask_stats(m)[0]
        score = (round(tot, 2), -dist[n])
        if best is None or score > best[0]:
            best = (score, dist[n], off, m)
    if best is None: return None
    return best[1], best[2], best[3]

def pack(lat, lon, buf, mode='nearest'):
    r = query(lat, lon, buf, mode)
    if not r: return None
    d, off, m = r
    tot, n, big, mr, ml, vol = mask_stats(m)
    return {'gl_km2': round(tot, 2), 'n_gl': n, 'km': round(d/1000, 1),
            'off_m': round(off), 'top': big,
            'melt_mio_m3a': round(mr/1e6, 2), 'melt_mio_m3a_long': round(ml/1e6, 2),
            'vol_mio_m3': round(vol, 1),
            'depletion_years': round(vol*1e6/mr, 1) if mr else None}

pegel = json.load(open('data/gw_aktuell/pegel_daily.json'))
gwst = json.load(open('data/gw_aktuell/longterm_2026.json'))
kgs = json.load(open('web/data/kg_registry.json'))
gp = json.load(open('web/data/gauge_profiles.json'))['stations']

out_pg = {}
for gid, g in pegel.items():
    lon, lat = g['coords'][:2]
    p = pack(lat, lon, PG_BUF)
    if p: out_pg[gid] = p
out_gp = {}
for gid, g in gp.items():
    if 'lat' not in g or 'lon' not in g: continue
    p = pack(g['lat'], g['lon'], PG_BUF)
    if p:
        if g.get('km2'): p['catch_km2'] = g['km2']; p['ice_pct'] = round(p['gl_km2']/g['km2']*100, 2)
        out_gp[gid] = p
out_gw = {}
for h, s in gwst.items():
    lon, lat = s['coords'][:2]
    p = pack(lat, lon, GW_BUF, 'any')
    if p: out_gw[h] = p
out_kg = {}
for code, k in kgs.items():
    p = pack(k['lat'], k['lon'], KG_BUF, 'any')
    if p: out_kg[code] = p

print(f'pegel {len(out_pg)}/{len(pegel)}, gauge_profiles {len(out_gp)}/{len(gp)}, '
      f'gw {len(out_gw)}/{len(gwst)}, kg {len(out_kg)}/{len(kgs)}', flush=True)
os.makedirs('data/glacier', exist_ok=True)
json.dump({'glaciers': GL, 'unsnapped': unsnapped, 'pegel': out_pg,
           'gauges': out_gp, 'gw': out_gw, 'kg': out_kg,
           'params': {'max_net_km': MAX_NET_KM, 'pg_buf_m': PG_BUF,
                      'gw_buf_m': GW_BUF, 'kg_buf_m': KG_BUF}},
          open(OUT, 'w'))
print('wrote', OUT)

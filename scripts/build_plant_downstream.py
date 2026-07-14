#!/usr/bin/env python3
"""Snap ENTSO-E A73 hydro plants (scripts/entsoe_plants.py) onto the OSM
waterway network (flow = linestring direction) and walk DOWNSTREAM to find
live eHYD GW stations (lateral buffer 4 km: valley aquifer) and river gauges
(buffer 800 m) below each plant, with along-network km.

Multi-candidate snapping: nearest vertices are tried until the downstream
walk reaches > 5 km (dams/side channels often dead-end the nearest segment).

Output: data/plants/plant_downstream.json
  { plant_id: { snap_m, reach_km,
                gw:    {hzbnr: {km, off_m}},
                pegel: {gid:   {km, off_m}} } }
"""
import json, math, sys, heapq, os
from collections import defaultdict
sys.path.insert(0, 'scripts')
from entsoe_plants import PLANTS

WATERWAYS = 'data/osm/waterways.geojsonseq'
OUT = 'data/plants/plant_downstream.json'
MAX_NET_KM, GW_BUF, PG_BUF = 120.0, 4000.0, 800.0

def hav_m(lat1, lon1, lat2, lon2):
    R = 6371000.0; p = math.pi/180
    a = (math.sin((lat2-lat1)*p/2)**2 +
         math.cos(lat1*p)*math.cos(lat2*p)*math.sin((lon2-lon1)*p/2)**2)
    return 2*R*math.asin(math.sqrt(a))

def key(lon, lat): return (round(lon, 6), round(lat, 6))
CELL = 0.01
def cell(lon, lat): return (int(lon/CELL), int(lat/CELL))

print('pass 1: endpoints...', flush=True)
endpoints = set()
for line in open(WATERWAYS):
    line = line.strip().lstrip('\x1e')
    if not line: continue
    try: g = json.loads(line)['geometry']
    except Exception: continue
    c = g['coordinates']
    if g['type'] != 'LineString' or len(c) < 2: continue
    endpoints.add(key(*c[0][:2])); endpoints.add(key(*c[-1][:2]))

print('pass 2: directed graph...', flush=True)
adj = defaultdict(list)
grid = defaultdict(list)
for line in open(WATERWAYS):
    line = line.strip().lstrip('\x1e')
    if not line: continue
    try: g = json.loads(line)['geometry']
    except Exception: continue
    c = g['coordinates']
    if g['type'] != 'LineString' or len(c) < 2: continue
    cuts = [i for i in range(1, len(c)-1) if key(*c[i][:2]) in endpoints]
    bounds = [0] + cuts + [len(c)-1]
    for bi in range(len(bounds)-1):
        i0, i1 = bounds[bi], bounds[bi+1]
        n0, n1 = key(*c[i0][:2]), key(*c[i1][:2])
        pts = c[i0:i1+1]; cum = 0.0; lens = [0.0]
        for j in range(1, len(pts)):
            cum += hav_m(pts[j-1][1], pts[j-1][0], pts[j][1], pts[j][0])
            lens.append(cum)
        if cum == 0: continue
        adj[n0].append((n1, cum))
        for j, p in enumerate(pts):
            grid[cell(p[0], p[1])].append((p[0], p[1], n1, cum - lens[j]))
print(f'  {len(adj)} nodes', flush=True)

def candidates(lat, lon, maxm=3000, k=12):
    cx, cy = cell(lon, lat); cand = []
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            for (vlon, vlat, n1, dd) in grid.get((cx+dx, cy+dy), ()):
                d = hav_m(lat, lon, vlat, vlon)
                if d <= maxm: cand.append((d, n1, dd))
    cand.sort()
    seen, out = set(), []
    for d, n1, dd in cand:
        if n1 in seen: continue
        seen.add(n1); out.append((d, n1, dd))
        if len(out) >= k: break
    return out

def walk(start, extra):
    dist = {start: extra}; pq = [(extra, start)]
    while pq:
        d, n = heapq.heappop(pq)
        if d > dist.get(n, 1e18) or d > MAX_NET_KM*1000: continue
        for n2, w in adj.get(n, ()):
            nd = d + w
            if nd < dist.get(n2, 1e18):
                dist[n2] = nd; heapq.heappush(pq, (nd, n2))
    return dist

gw = json.load(open('data/gw_aktuell/longterm_2026.json'))
pegel = json.load(open('data/gw_aktuell/pegel_daily.json'))

out = {}
for pid, p in PLANTS.items():
    best = None
    for (snap_m, node, dd) in candidates(p['lat'], p['lon']):
        dist = walk(node, dd)
        reach = max(dist.values())/1000.0 if dist else 0
        if best is None or reach > best[2]:
            best = (snap_m, dist, reach)
        if reach > 5.0: break
    if not best:
        print(f'  {pid}: NOT SNAPPED'); continue
    snap_m, dist, reach = best
    ng = defaultdict(list)
    for (lon, lat), d in dist.items(): ng[cell(lon, lat)].append((lon, lat, d))
    def near_path(lat, lon, buf):
        cx, cy = cell(lon, lat); r = int(buf/1000.0) + 1
        bst = None
        for dx in range(-r, r+1):
            for dy in range(-r, r+1):
                for (vlon, vlat, d) in ng.get((cx+dx, cy+dy), ()):
                    s = hav_m(lat, lon, vlat, vlon)
                    if s <= buf and (bst is None or d < bst[0]): bst = (d, s)
        return bst
    hits_gw, hits_pg = {}, {}
    for hzb, s in gw.items():
        lon, lat = s['coords'][:2]
        r = near_path(lat, lon, GW_BUF)
        if r: hits_gw[hzb] = {'km': round(r[0]/1000, 1), 'off_m': round(r[1])}
    for gid, g in pegel.items():
        lon, lat = g['coords'][:2]
        r = near_path(lat, lon, PG_BUF)
        if r: hits_pg[gid] = {'km': round(r[0]/1000, 1), 'off_m': round(r[1])}
    out[pid] = {'snap_m': round(snap_m), 'reach_km': round(reach, 1),
                'gw': hits_gw, 'pegel': hits_pg}
    print(f'  {pid}: snap {snap_m:.0f} m, reach {reach:.0f} km, {len(hits_gw)} GW, {len(hits_pg)} pegel', flush=True)

os.makedirs('data/plants', exist_ok=True)
json.dump(out, open(OUT, 'w'))
print('wrote', OUT)

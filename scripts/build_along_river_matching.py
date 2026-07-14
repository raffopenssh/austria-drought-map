#!/usr/bin/env python3
"""
Along-river gauge matching using OSM/Geofabrik waterways.

Builds an undirected graph from OSM waterway linestrings (river/stream/canal/
drain/ditch, Geofabrik austria-latest extract), snaps each live eHYD GW
station and each live river gauge (Pegel) onto the network, and finds for each
GW station the NEAREST GAUGE BY ALONG-NETWORK DISTANCE (Dijkstra), instead of
straight-line distance.

Output: data/osm/along_river_gauges.json
  { hzbnr: { gauge_id, network_km, gauge_river, snap_station_m, snap_gauge_m,
             straight_km } }
"""
import json, math, heapq, sys
from collections import defaultdict

WATERWAYS = 'data/osm/waterways.geojsonseq'
GW = 'data/gw_aktuell/longterm_2026.json'
PEGEL = 'data/gw_aktuell/pegel_daily.json'
OUT = 'data/osm/along_river_gauges.json'
MAX_SNAP_M = 3000      # station must be within 3km of a waterway vertex
MAX_NET_KM = 150       # dijkstra cutoff

def hav_m(lat1, lon1, lat2, lon2):
    R = 6371000.0; p = math.pi/180
    a = (math.sin((lat2-lat1)*p/2)**2 +
         math.cos(lat1*p)*math.cos(lat2*p)*math.sin((lon2-lon1)*p/2)**2)
    return 2*R*math.asin(math.sqrt(a))

def key(lon, lat):
    return (round(lon, 6), round(lat, 6))

print('pass 1: endpoints...', flush=True)
endpoints = set()
n_ways = 0
with open(WATERWAYS) as f:
    for line in f:
        line = line.strip().lstrip('\x1e')
        if not line: continue
        try: g = json.loads(line)['geometry']
        except Exception: continue
        c = g['coordinates']
        if g['type'] != 'LineString' or len(c) < 2: continue
        endpoints.add(key(*c[0][:2])); endpoints.add(key(*c[-1][:2]))
        n_ways += 1
print(f'  {n_ways} ways, {len(endpoints)} endpoints', flush=True)

# pass 2: build graph. Split ways at interior points that are endpoints of
# other ways (junction handling). Nodes = endpoint keys. Also keep, per edge,
# nothing else (we snap to nearest node via grid of ALL vertices mapped to
# their nearest graph node along the way).
print('pass 2: graph...', flush=True)
adj = defaultdict(list)   # node -> [(node2, weight_m)]
# grid index of vertices -> (graph_node, dist_along_to_node_m)
grid = defaultdict(list)  # cell -> [(lon, lat, node_key, extra_m)]
CELL = 0.01               # ~1km

def cell(lon, lat): return (int(lon/CELL), int(lat/CELL))

with open(WATERWAYS) as f:
    for line in f:
        line = line.strip().lstrip('\x1e')
        if not line: continue
        try: g = json.loads(line)['geometry']
        except Exception: continue
        c = g['coordinates']
        if g['type'] != 'LineString' or len(c) < 2: continue
        # split at interior junction vertices
        seg_start = 0
        cuts = [i for i in range(1, len(c)-1) if key(*c[i][:2]) in endpoints]
        bounds = [0] + cuts + [len(c)-1]
        for bi in range(len(bounds)-1):
            i0, i1 = bounds[bi], bounds[bi+1]
            n0, n1 = key(*c[i0][:2]), key(*c[i1][:2])
            # cumulative length + register vertices in grid
            cum = 0.0
            pts = c[i0:i1+1]
            lens = [0.0]
            for j in range(1, len(pts)):
                cum += hav_m(pts[j-1][1], pts[j-1][0], pts[j][1], pts[j][0])
                lens.append(cum)
            if cum == 0: continue
            adj[n0].append((n1, cum)); adj[n1].append((n0, cum))
            for j, p in enumerate(pts):
                d0, d1 = lens[j], cum - lens[j]
                node, extra = (n0, d0) if d0 <= d1 else (n1, d1)
                grid[cell(p[0], p[1])].append((p[0], p[1], node, extra))
print(f'  {len(adj)} graph nodes', flush=True)

def snap(lat, lon):
    """nearest waterway vertex -> (graph_node, snap_dist_m + along_extra_m)"""
    cx, cy = cell(lon, lat)
    best = None; bd = 1e18
    for r in (1, 3):
        for dx in range(-r, r+1):
            for dy in range(-r, r+1):
                for (vlon, vlat, node, extra) in grid.get((cx+dx, cy+dy), ()):
                    d = hav_m(lat, lon, vlat, vlon)
                    if d < bd:
                        bd = d; best = (node, extra, d)
        if best and bd < MAX_SNAP_M: break
    return best  # (node, extra_m, snap_m) or None

gw = json.load(open(GW))
pegel = json.load(open(PEGEL))

print('snapping gauges...', flush=True)
gauge_at = defaultdict(list)  # graph_node -> [(gauge_id, extra_m, snap_m)]
gauge_meta = {}
for gid, g in pegel.items():
    lon, lat = g['coords'][0], g['coords'][1]
    s = snap(lat, lon)
    gauge_meta[gid] = {'gewasser': g.get('gewasser'), 'lat': lat, 'lon': lon}
    if s and s[2] <= MAX_SNAP_M:
        gauge_at[s[0]].append((gid, s[1], s[2]))
print(f'  {sum(len(v) for v in gauge_at.values())}/{len(pegel)} gauges snapped', flush=True)

def dijkstra_to_gauge(start_node, start_extra):
    dist = {start_node: start_extra}
    pq = [(start_extra, start_node)]
    best = None
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1e18): continue
        if d/1000.0 > MAX_NET_KM: break
        if u in gauge_at:
            for (gid, extra, snap_m) in gauge_at[u]:
                tot = d + extra
                if best is None or tot < best[1]:
                    best = (gid, tot, snap_m)
        if best and d > best[1]:  # cannot improve
            break
        for v, w in adj[u]:
            nd = d + w
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return best

print('matching stations...', flush=True)
out = {}
n_ok = 0
for hzb, s in gw.items():
    lon, lat = s['coords'][:2]
    sn = snap(lat, lon)
    if not sn or sn[2] > MAX_SNAP_M:
        out[hzb] = None; continue
    node, extra, snap_m = sn
    r = dijkstra_to_gauge(node, extra)
    if not r:
        out[hzb] = None; continue
    gid, net_m, gsnap_m = r
    gm = gauge_meta[gid]
    out[hzb] = {
        'gauge_id': gid,
        'network_km': round(net_m/1000.0, 2),
        'gauge_river': gm['gewasser'],
        'snap_station_m': round(snap_m),
        'snap_gauge_m': round(gsnap_m),
        'straight_km': round(hav_m(lat, lon, gm['lat'], gm['lon'])/1000.0, 2),
    }
    n_ok += 1
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
nets = sorted(v['network_km'] for v in out.values() if v)
print(f'matched {n_ok}/{len(gw)} stations; median network dist '
      f'{nets[len(nets)//2] if nets else None} km -> {OUT}')

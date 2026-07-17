#!/usr/bin/env python3
"""Assign each nitrate station to its groundwater body (GWK) by point-in-polygon."""
import json, gzip
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

gwk = json.load(open('web/data/gwk.geojson'))
geoms, ids = [], []
for f in gwk['features']:
    geoms.append(shape(f['geometry']))
    ids.append(f['properties']['id'])
tree = STRtree(geoms)

data = json.load(open('web/data/nitrate_stations.json'))
hit = 0
for s in data['stations']:
    if not (s.get('lat') and s.get('lon')):
        s['body'] = None; continue
    p = Point(s['lon'], s['lat'])
    body = None
    for i in tree.query(p):
        if geoms[i].contains(p):
            body = ids[i]; break
    if body is None:  # nearest within ~2km
        cand = tree.query(p.buffer(0.03))
        best, bd = None, 1e9
        for i in cand:
            d = geoms[i].distance(p)
            if d < bd: bd, best = d, ids[i]
        if best is not None and bd < 0.03: body = best
    s['body'] = body
    if body: hit += 1
print('assigned', hit, '/', len(data['stations']))
out = json.dumps(data, separators=(',', ':'))
open('web/data/nitrate_stations.json', 'w').write(out)
with gzip.open('web/data/nitrate_stations.json.gz', 'wb') as f:
    f.write(out.encode())

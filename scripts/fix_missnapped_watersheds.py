#!/usr/bin/env python3
"""Repair mis-snapped MERIT catchments by searching nearby outlet points.

96 of 640 gauges came back with a catchment >25% off the official eHYD
catchment size. Cause: at confluences MERIT-Hydro's 90 m stream raster snaps a
small-tributary gauge onto the mainstem, so the "watershed" is the whole valley
(Niederau: 9.7 km2 official -> 8,938 km2 delineated).

Fix: probe a small grid of candidate outlets around the gauge (up to ~600 m)
and keep the one whose delineated area best matches the official size. If
nothing gets within 25%, the gauge stays flagged 'missnap' and is excluded from
attribution rather than silently wrong.

Rewrites data/watersheds/<hzb>.json in place (keeps a .orig.json backup).
"""
import json, gzip, os, math, time, urllib.request

UA = 'GW-Power/1.0 (groundwater-at.exe.xyz; austrian groundwater research; contact raffaelhickisch+exedev@gmail.com)'
TOL = 25.0           # % of eHYD area we accept
OFFS_M = [0, 150, 300, 450, 600]

def api(lat, lon):
    url = (f'https://mghydro.com/app/getwshed?task=watershed&lat={lat:.5f}&lng={lon:.5f}'
           '&source=merit&precision=high&simplify=true')
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}),
                                timeout=300).read()
    try: return json.loads(gzip.decompress(raw))
    except Exception: return json.loads(raw)

def area_km2(geom):
    R = 6371.0088
    def ring(cs):
        s = 0.0
        for i in range(len(cs)-1):
            x1, y1 = cs[i]; x2, y2 = cs[i+1]
            s += math.radians(x2-x1)*(2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2)))
        return abs(s*R*R/2)
    polys = [geom['coordinates']] if geom['type'] == 'Polygon' else geom['coordinates']
    return sum(ring(p[0]) - sum(ring(h) for h in p[1:]) for p in polys)

def candidates(lat, lon):
    yield lat, lon
    for m in OFFS_M[1:]:
        dlat = m/111320.0
        dlon = m/(111320.0*math.cos(math.radians(lat)))
        for dy, dx in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            yield lat + dy*dlat, lon + dx*dlon

def main():
    files = sorted(f for f in os.listdir('data/watersheds') if f.endswith('.json')
                   and not f.endswith('.orig.json'))
    todo = []
    for f in files:
        d = json.load(open(f'data/watersheds/{f}'))
        k = d.get('km2_ehyd')
        if not k or not d.get('km2_merit'): continue
        if abs(d['km2_merit']-k)/k*100 > TOL: todo.append(d)
    print(f'{len(todo)} mis-snapped gauges to repair')
    fixed = 0
    for i, d in enumerate(todo):
        k = d['km2_ehyd']
        best = (abs(d['km2_merit']-k)/k*100, None)
        for lat, lon in candidates(d['lat'], d['lon']):
            if best[0] <= 5: break
            try: r = api(lat, lon)
            except Exception: time.sleep(2); continue
            ws = r.get('watershed')
            time.sleep(0.7)
            if not ws: continue
            a = area_km2(ws)
            err = abs(a-k)/k*100
            if err < best[0]:
                best = (err, (lat, lon, r, a))
        if best[1] and best[0] <= TOL:
            lat, lon, r, a = best[1]
            p = f'data/watersheds/{d["hzb"]}.json'
            if not os.path.exists(p.replace('.json', '.orig.json')):
                os.rename(p, p.replace('.json', '.orig.json'))
            sn = [f['properties'] for f in r['outlet']['features']
                  if f['properties'].get('point_type') == 'snapped']
            sn = sn[0] if sn else {}
            d.update({'watershed': r['watershed'], 'rivers': r.get('rivers'),
                      'km2_merit': round(a, 2), 'wid': r.get('wid'),
                      'message': r.get('message'),
                      'probe_lat': round(lat, 5), 'probe_lon': round(lon, 5),
                      'probe_err_pct': round(best[0], 1),
                      'snap_lat': sn.get('latitude'), 'snap_lon': sn.get('longitude'),
                      'repaired': True})
            json.dump(d, open(p, 'w'))
            fixed += 1
            print(f'[{i+1}/{len(todo)}] FIXED {d["hzb"]} {str(d["name"])[:20]:22s} '
                  f'ehyd={k:9.1f} -> {a:9.1f} ({best[0]:.1f}%)', flush=True)
        else:
            print(f'[{i+1}/{len(todo)}] keep flagged {d["hzb"]} {str(d["name"])[:20]:22s} '
                  f'best {best[0]:.0f}% off', flush=True)
    print(f'repaired {fixed}/{len(todo)}')

if __name__ == '__main__':
    main()

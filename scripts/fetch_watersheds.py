#!/usr/bin/env python3
"""Real upstream catchments for every eHYD river gauge, from mghydro.com.

mghydro's Global Watersheds app (Matthew Heberger, github.com/mheberger/delineator)
delineates watersheds on demand from MERIT-Hydro / MERIT-Basins (CC BY-NC-SA).
Endpoint (same one the web UI calls):
  GET https://mghydro.com/app/getwshed?task=watershed&lat=&lng=&source=merit
      &precision=high&simplify=true            -> gzipped JSON
      {message, wid, outlet:FC(requested,snapped), rivers:FC, watershed:Polygon}
  task=flowpath gives the downstream trace instead.

Why: our glacier/snow attribution walked the OSM waterway network and snapped
points, which mis-assigns at confluences (16 gauges had to be dropped for
"more ice upstream than catchment"). A real polygon lets us intersect RGI
glacier outlines and SNOWGRID SWE grids with the actual contributing area.

Resumable: one JSON per gauge in data/watersheds/<hzb>.json. Polite: 1 req/s.
Validation vs the official eHYD catchment size is printed at the end.
"""
import json, gzip, os, sys, time, math, urllib.request, urllib.error

OUT = 'data/watersheds'
UA = 'GW-Power/1.0 (groundwater-at.exe.xyz; austrian groundwater research; contact raffaelhickisch+exedev@gmail.com)'
SLEEP = 1.0

def hav_km(a, b, c, d):
    R = 6371.0; p = math.pi/180
    return 2*R*math.asin(math.sqrt(math.sin((c-a)*p/2)**2 +
           math.cos(a*p)*math.cos(c*p)*math.sin((d-b)*p/2)**2))

def api(lat, lon, task='watershed', precision='high'):
    url = (f'https://mghydro.com/app/getwshed?task={task}&lat={lat:.5f}&lng={lon:.5f}'
           f'&source=merit&precision={precision}&simplify=true')
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    raw = urllib.request.urlopen(req, timeout=300).read()
    try: return json.loads(gzip.decompress(raw))
    except Exception: return json.loads(raw)

def area_km2(geom):
    """Spherical polygon area, km2 (handles Polygon/MultiPolygon)."""
    R = 6371.0088
    def ring(cs):
        s = 0.0
        for i in range(len(cs)-1):
            x1, y1 = cs[i]; x2, y2 = cs[i+1]
            s += math.radians(x2-x1)*(2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2)))
        return abs(s*R*R/2)
    if geom['type'] == 'Polygon': polys = [geom['coordinates']]
    else: polys = geom['coordinates']
    tot = 0.0
    for p in polys:
        tot += ring(p[0]) - sum(ring(h) for h in p[1:])
    return tot

def main():
    os.makedirs(OUT, exist_ok=True)
    st = json.load(open('web/data/gauge_profiles.json'))['stations']
    todo = [(k, v) for k, v in sorted(st.items())
            if v.get('lat') and v.get('lon')]
    print(f'{len(todo)} gauges with coords')
    ok = fail = skip = 0
    for i, (hzb, v) in enumerate(todo):
        p = f'{OUT}/{hzb}.json'
        if os.path.exists(p): skip += 1; continue
        try:
            d = api(v['lat'], v['lon'])
        except Exception as e:
            print(f'  {hzb} {v["name"][:20]:22s} ERR {repr(e)[:70]}'); fail += 1
            time.sleep(3); continue
        ws = d.get('watershed')
        if not ws:
            print(f'  {hzb} {v["name"][:20]:22s} no polygon: {str(d.get("message"))[:60]}')
            json.dump({'hzb': hzb, 'error': d.get('message')}, open(p, 'w')); fail += 1
            time.sleep(SLEEP); continue
        sn = [f['properties'] for f in d['outlet']['features']
              if f['properties'].get('point_type') == 'snapped']
        sn = sn[0] if sn else {}
        rec = {'hzb': hzb, 'name': v.get('name'), 'river': v.get('river'),
               'lat': v['lat'], 'lon': v['lon'],
               'snap_lat': sn.get('latitude'), 'snap_lon': sn.get('longitude'),
               'snap_km': (round(hav_km(v['lat'], v['lon'], sn['latitude'], sn['longitude']), 3)
                           if sn.get('latitude') else None),
               'wid': d.get('wid'), 'message': d.get('message'),
               'km2_merit': round(area_km2(ws), 2), 'km2_ehyd': v.get('km2'),
               'watershed': ws,
               'rivers': d.get('rivers'),
               'source': 'MERIT-Hydro via mghydro.com/watersheds (CC BY-NC-SA)'}
        json.dump(rec, open(p, 'w'))
        ok += 1
        if i % 20 == 0:
            print(f'[{i}/{len(todo)}] {hzb} {str(v["name"])[:18]:20s} '
                  f'ehyd={v.get("km2")} merit={rec["km2_merit"]} snap={rec["snap_km"]}km', flush=True)
        time.sleep(SLEEP)
    print(f'ok {ok} fail {fail} skip {skip}')

if __name__ == '__main__':
    main()

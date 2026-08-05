#!/usr/bin/env python3
"""Downstream flow path from every Austrian glacier, from MERIT-Basins.

Same mghydro backend as fetch_watersheds.py, task=flowpath: given a point it
snaps to the MERIT-Hydro stream network and returns the chain of downstream
river reaches (comid + Strahler order) all the way to the sea. This replaces
our OSM-waterway walk for glacier -> river attribution: MERIT reaches are
topologically connected by construction, while OSM tagging/direction errors
made the walk stop early or leak into neighbouring basins.

One file per glacier: data/flowpaths/<RGIId>.json  {comids:[...], geometry}
Resumable, 1 req/s.
"""
import json, gzip, os, time, urllib.request, sys

OUT = 'data/flowpaths'
UA = 'GW-Power/1.0 (groundwater-at.exe.xyz; austrian groundwater research; contact raffaelhickisch+exedev@gmail.com)'

def api(lat, lon):
    url = (f'https://mghydro.com/app/getwshed?task=flowpath&lat={lat:.5f}&lng={lon:.5f}'
           '&source=merit&precision=high&simplify=true')
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}),
                                timeout=300).read()
    try: return json.loads(gzip.decompress(raw))
    except Exception: return json.loads(raw)

def main():
    os.makedirs(OUT, exist_ok=True)
    gl = json.load(open('data/glacier/glacier_downstream.json'))['glaciers']
    items = sorted(gl.items(), key=lambda kv: -kv[1]['area_km2'])
    print(len(items), 'glaciers')
    for i, (rgi, g) in enumerate(items):
        p = f'{OUT}/{rgi}.json'
        if os.path.exists(p): continue
        try:
            d = api(g['lat'], g['lon'])
        except Exception as e:
            print(rgi, 'ERR', repr(e)[:60]); time.sleep(3); continue
        fc = d.get('rivers') or {'features': []}
        feats = fc.get('features', [])
        rec = {'rgi_id': rgi, 'name': g.get('name'), 'area_km2': g['area_km2'],
               'lat': g['lat'], 'lon': g['lon'],
               'reaches': [{'comid': f['properties'].get('comid'),
                            'sorder': f['properties'].get('sorder'),
                            'coords': f['geometry']['coordinates']}
                           for f in feats if f['geometry']['type'] == 'LineString'],
               'message': d.get('message')}
        json.dump(rec, open(p, 'w'))
        if i % 25 == 0:
            print(f'[{i}/{len(items)}] {rgi} {g["area_km2"]:6.2f} km2 '
                  f'{len(rec["reaches"])} reaches', flush=True)
        time.sleep(1.0)

if __name__ == '__main__':
    main()

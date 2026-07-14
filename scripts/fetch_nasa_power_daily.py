#!/usr/bin/env python3
"""Fetch NASA POWER daily precipitation for the 0.5-deg cells containing
live eHYD GW stations, 2025-01-01..today. Output: data/nasa_power_precip_daily.json
Keyed by "lat,lon" cell center. Used as control in power<->GW analysis."""
import json, urllib.request, time, datetime, os

src = json.load(open('data/gw_aktuell/longterm_2026.json'))
cells = {}
for hzb, s in src.items():
    lon, lat = s['coords'][:2]
    cell = (round((lat // 0.5) * 0.5 + 0.25, 3), round((lon // 0.5) * 0.5 + 0.25, 3))
    cells.setdefault(cell, []).append(hzb)

end = datetime.date.today().strftime('%Y%m%d')
out = {}
for i, (lat, lon) in enumerate(sorted(cells)):
    url = (f'https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR'
           f'&community=AG&longitude={lon}&latitude={lat}&start=20250101&end={end}&format=JSON')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                j = json.load(r)
            out[f'{lat},{lon}'] = j['properties']['parameter']['PRECTOTCORR']
            break
        except Exception as e:
            print(lat, lon, 'retry', attempt, e, flush=True)
            time.sleep(5)
    if i % 10 == 0:
        print(i, '/', len(cells), flush=True)
json.dump(out, open('data/nasa_power_precip_daily.json', 'w'))
print('done', len(out), 'cells')

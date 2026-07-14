#!/usr/bin/env python3
"""Daily eHYD live snapshot + backfill.

eHYD's SPA moved its API from /eHYD/... to /services/... (old ehyd_tools /
hydrogeology-graz URLs 404 now). Working endpoints:
  - /services/GrundwasserAktuell/json      : 227 live GW stations, latest value
  - /services/Diagram/grundwasserLongtermBgis?hzbnr=N : daily values for the
    current year + historical min/mean/max/p5/p95 bands (self-backfilling ~190d)
  - /services/MessstellenExtraData/gw?id=N&file=4 : monthly archive CSV
    (published yearly, currently through ~2022)

This script maintains data/gw_aktuell/daily_levels.json:
  {hzbnr: {"coords":..., "name":..., "bundesland":..., "levels": {date: value}}}
Because the longterm endpoint returns the whole current year, running this
once a day automatically backfills any missed days within the year.
Also refreshes data/gw_aktuell/longterm_<year>.json (with percentile bands).
"""
import json, urllib.request, datetime, os, sys, time

BASE = 'https://ehyd.gv.at/services'
OUTDIR = 'data/gw_aktuell'
os.makedirs(OUTDIR, exist_ok=True)

def get(url, retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if i == retries - 1:
                print(f'FAIL {url}: {e}', file=sys.stderr)
                return None
            time.sleep(5)

aktuell = get(f'{BASE}/GrundwasserAktuell/json')
if not aktuell:
    sys.exit('GrundwasserAktuell unreachable')

daily_path = f'{OUTDIR}/daily_levels.json'
store = json.load(open(daily_path)) if os.path.exists(daily_path) else {}
year = datetime.date.today().year
longterm = {}
keys = ('data_from','data_till','points_in_time_historisch','points_in_time_werte',
        'data','mit_data','p5_data','p95_data','min_data','max_data','last_year_value')
ok = 0
for f in aktuell['features']:
    hzb = str(f['properties']['hzbnr'])
    j = get(f'{BASE}/Diagram/grundwasserLongtermBgis?hzbnr={hzb}')
    if not j or not j.get('points_in_time_werte'):
        continue
    rec = store.setdefault(hzb, {'coords': f['geometry']['coordinates'],
                                 'name': f['properties']['mstnam02'],
                                 'bundesland': f['properties']['bundesland'],
                                 'levels': {}})
    for d, v in zip(j['points_in_time_werte'], j['data']):
        if v is not None:
            rec['levels'][d] = v
    longterm[hzb] = {'coords': f['geometry']['coordinates'],
                     'bundesland': f['properties']['bundesland'],
                     'name': f['properties']['mstnam02'],
                     **{k: j.get(k) for k in keys}}
    ok += 1

json.dump(store, open(daily_path, 'w'))
json.dump(longterm, open(f'{OUTDIR}/longterm_{year}.json', 'w'))
print(f'{datetime.datetime.now().isoformat(timespec="seconds")} '
      f'updated {ok}/{len(aktuell["features"])} stations; '
      f'{sum(len(r["levels"]) for r in store.values())} daily values total')

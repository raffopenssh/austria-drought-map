#!/usr/bin/env python3
"""Build web/data/gauge_profiles.json: per-river-gauge detail for the gauge modal.

Per gauge (keyed by HZB number):
  meta    - name, river, lat/lon (from flow_analysis.json = OWF Stammdaten)
  annual  - annual mean flow series [[year, m3/s], ...] from OWF Q-Tagesmittel
            (years with >=300 daily values)
  live    - 2026 daily flow from eHYD live pegel feed (data/gw_aktuell/pegel_daily.json)
  sed     - suspended-sediment mean t/day + trend (sediment_analysis.json)
Plant-influence links are NOT duplicated here; the frontend joins
plant_influence.json's pegel_links at render time.
"""
import json, os, sys, datetime
from pathlib import Path
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))
from analyze_flow import parse_flow_file  # reuse the OWF CSV parser

flow = {s['hzb']: s for s in json.load(open('web/data/flow_analysis.json'))}
sed = {s['hzb']: s for s in json.load(open('web/data/sediment_analysis.json'))}
live = json.load(open('data/gw_aktuell/pegel_daily.json'))

out = {}
for f in sorted(Path('data/owf/Q-Tagesmittel').glob('*.csv')):
    meta, values = parse_flow_file(f)
    hzb = meta.get('hzb')
    if not hzb or not values:
        continue
    fa = flow.get(hzb)
    # annual means (years with >=300 days)
    peryear = {}
    for d, v in values:
        peryear.setdefault(d.year, []).append(v)
    annual = [[y, round(float(np.mean(vs)), 2)]
              for y, vs in sorted(peryear.items()) if len(vs) >= 300]
    if not annual:
        continue
    rec = {
        'name': meta.get('name', ''),
        'river': (fa or {}).get('river') or meta.get('river', ''),
        'km2': meta.get('catchment_km2'),
        'annual': annual,
    }
    if fa:
        rec.update(lat=fa['lat'], lon=fa['lon'],
                   mean_m3s=fa['mean_flow_m3s'],
                   trend_pct_decade=fa['trend_pct_decade'],
                   trend_years=fa['years_data'])
    s = sed.get(hzb)
    if s:
        rec['sed'] = {'t_day': round(s['mean_daily_t'], 1), 'trend_pct': s['trend_pct'],
                      'days': s['data_points']}
    lv = live.get(hzb)
    if lv and lv.get('levels'):
        days = sorted(lv['levels'])
        d0 = datetime.date.fromisoformat(days[0])
        d1 = datetime.date.fromisoformat(days[-1])
        n = (d1 - d0).days + 1
        vals = []
        lmap = lv['levels']
        for i in range(n):
            d = (d0 + datetime.timedelta(days=i)).isoformat()
            v = lmap.get(d)
            vals.append(round(v, 2) if v is not None else None)
        rec['live'] = {'d0': days[0], 'vals': vals,
                       'unit': lv.get('unit', 'm\u00b3/s'), 'param': lv.get('parameter', '')}
    out[hzb] = rec

# also index live-only gauges (no OWF history) so plant links always resolve
for hzb, lv in live.items():
    if hzb in out or not lv.get('levels'):
        continue
    days = sorted(lv['levels'])
    d0 = datetime.date.fromisoformat(days[0]); d1 = datetime.date.fromisoformat(days[-1])
    n = (d1 - d0).days + 1
    lmap = lv['levels']
    vals = [round(lmap[d], 2) if (d := (d0 + datetime.timedelta(days=i)).isoformat()) in lmap else None
            for i in range(n)]
    out[hzb] = {'name': lv.get('name', hzb), 'river': lv.get('gewasser', ''),
                'lat': lv['coords'][1], 'lon': lv['coords'][0], 'annual': [],
                'live': {'d0': days[0], 'vals': vals, 'unit': lv.get('unit', 'm\u00b3/s'),
                         'param': lv.get('parameter', '')}}

res = {'generated': datetime.datetime.now().isoformat(timespec='seconds'),
       'source': 'OWF Q-Tagesmittel & Schwebstoff (BML hydrographic yearbook data); eHYD live Pegel 2026',
       'stations': out}
with open('web/data/gauge_profiles.json', 'w') as fp:
    json.dump(res, fp, ensure_ascii=False, separators=(',', ':'))
print('gauges:', len(out), 'size:', os.path.getsize('web/data/gauge_profiles.json'))

# slim index for eager loading (KG-modal proximity lists)
slim = []
for hzb, r in out.items():
    if 'lat' not in r:
        continue
    slim.append({'id': hzb, 'n': r['name'], 'riv': r['river'],
                 'lat': round(r['lat'], 5), 'lon': round(r['lon'], 5),
                 'q': r.get('mean_m3s'), 't': r.get('trend_pct_decade'),
                 'live': 1 if r.get('live') else 0,
                 'sed': 1 if r.get('sed') else 0})
with open('web/data/gauges_slim.json', 'w') as fp:
    json.dump(slim, fp, ensure_ascii=False, separators=(',', ':'))
print('slim:', len(slim), 'size:', os.path.getsize('web/data/gauges_slim.json'))

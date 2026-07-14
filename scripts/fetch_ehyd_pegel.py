#!/usr/bin/env python3
"""Fetch daily river stage (current year) for all live eHYD Pegel gauges.
Endpoint: /services/Diagram/pegelLongterm?hzbnr=N -> points_in_time (day-of-year
dates) + current_value (daily stage, cm, nulls after today).
Output: data/gw_aktuell/pegel_daily.json  {hzbnr: {coords, gewasser, name, unit, levels:{date:val}}}
"""
import json, urllib.request, time, sys, os

BASE='https://ehyd.gv.at/services'
def get(url, retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r: return json.load(r)
        except Exception as e:
            if i==retries-1: print('FAIL',url,e,file=sys.stderr); return None
            time.sleep(4)

ak=get(f'{BASE}/PegelAktuell/json')
out={}
for i,f in enumerate(ak['features']):
    p=f['properties']; hzb=str(p['hzbnr'])
    j=get(f'{BASE}/Diagram/pegelLongterm?hzbnr={hzb}')
    if not j or not j.get('current_value'): continue
    levels={d:v for d,v in zip(j['points_in_time'], j['current_value']) if v is not None}
    if len(levels)<60: continue
    out[hzb]={'coords':f['geometry']['coordinates'],'gewasser':p.get('gewasser'),
              'name':p.get('messstelle'),'unit':j.get('einheit'),'parameter':j.get('parameter'),
              'levels':levels}
    if i%50==0: print(i,flush=True)
os.makedirs('data/gw_aktuell',exist_ok=True)
json.dump(out,open('data/gw_aktuell/pegel_daily.json','w'))
print('done',len(out),'gauges')

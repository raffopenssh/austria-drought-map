#!/usr/bin/env python3
"""Day-of-week fingerprint in river flow: turbines follow electricity demand,
nature doesn't. For each gauge: median % deviation of daily Q by weekday
(vs the surrounding 28-day mean), 1990-2022. Weekend dip amplitude =
mean(Mon-Fri) - mean(Sat-Sun) in % of local flow. Grouped by GAUGE_CLASS."""
import os, sys, math, datetime
from collections import defaultdict
import numpy as np
sys.path.insert(0, 'scripts')
from analyze_colmation import parse_ehyd, GAUGE_CLASS, Q_DIR, perm_p

def weekday_signature(h, y0=1990):
    p = f'{Q_DIR}/Q-Tagesmittel-{h}.csv'
    if not os.path.exists(p): return None
    data = [(d, v) for d, v in parse_ehyd(p) if d.year >= y0 and v > 0]
    if len(data) < 3650: return None
    dates = [d for d, _ in data]; vals = np.array([v for _, v in data])
    # 29-day centered rolling mean via cumsum on a contiguous reindex
    idx = {d: i for i, d in enumerate(dates)}
    ratio = np.full(len(vals), np.nan)
    csum = np.concatenate([[0], np.cumsum(vals)])
    # only valid if dates contiguous in window; approximate: use array window
    for i in range(14, len(vals) - 14):
        if (dates[i+14] - dates[i-14]).days == 28:
            m = (csum[i+15] - csum[i-14]) / 29.0
            if m > 0: ratio[i] = vals[i] / m
    by_dow = defaultdict(list)
    for i, d in enumerate(dates):
        if not math.isnan(ratio[i]):
            by_dow[d.weekday()].append(ratio[i])
    if any(len(by_dow[k]) < 300 for k in range(7)): return None
    med = {k: float(np.median(by_dow[k])) for k in range(7)}
    week = np.mean([med[k] for k in range(5)])
    wend = np.mean([med[k] for k in (5, 6)])
    return dict(dow_pct={k: round((med[k]-1)*100, 2) for k in range(7)},
                weekend_dip_pct=round((week - wend) * 100, 2),
                sunday_dip_pct=round((np.mean([med[k] for k in range(5)]) - med[6]) * 100, 2),
                n_days=len(vals))

def main():
    out = {}
    for h, (cls, note) in sorted(GAUGE_CLASS.items()):
        r = weekday_signature(h)
        if r:
            r.update(cls=cls, note=note)
            out[h] = r
            print(f"{cls:8s} {h} weekend_dip={r['weekend_dip_pct']:+6.2f}%  sun={r['sunday_dip_pct']:+6.2f}%  {note}")
    for cls in ('storage', 'ror', 'control'):
        v = [r['weekend_dip_pct'] for r in out.values() if r['cls'] == cls]
        print(cls, 'n=', len(v), 'median weekend dip %', round(float(np.median(v)), 2))
    a = [r['weekend_dip_pct'] for r in out.values() if r['cls'] in ('storage', 'ror')]
    b = [r['weekend_dip_pct'] for r in out.values() if r['cls'] == 'control']
    print('perm p regulated vs control:', perm_p(a, b))
    import json
    json.dump(out, open('data/weekly_pulse.json', 'w'), indent=1)
    print('wrote data/weekly_pulse.json')

if __name__ == '__main__':
    main()

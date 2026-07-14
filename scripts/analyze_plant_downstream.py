#!/usr/bin/env python3
"""Per-plant downstream impact on groundwater & river stage.

For every (hydro plant, downstream station) pair from
data/plants/plant_downstream.json, test whether the plant's daily RELEASE
(turbined water, MWh/day) explains variance in the station's daily
first-differences, after controlling for local precipitation.

Release series:
  - Plants with live ENTSO-E A73 unit data in the GW overlap window (2026):
    sum of unit MWh/day (source=a73).
  - Others (naming changed / stopped publishing): downscaled from the national
    PSR-type aggregate via a per-plant linear fit calibrated on 2023-24 A73
    data (source=downscaled, calib_r reported). NOTE: all downscaled plants of
    one PSR type share the same daily signal shape; attribution to the
    specific plant rests on network topology, not a unique signal.

Model per pair (daily first differences, 2026 overlap ~190 d):
  base: dY ~ precip(t, t-1, t-2, t-3, 7d-sum)
  full: base + dRelease(t, t-1)
  partial R^2 = (R2f - R2b) / (1 - R2b);  F-test on the 2 release terms.
  Placebo: same test with release shifted back 60 days.

Significant := p < 0.01 AND partial >= 0.05 AND partial > placebo_partial.

Output: web/data/plant_influence.json
"""
import csv, json, math, sys, datetime, os
from collections import defaultdict
import numpy as np
sys.path.insert(0, 'scripts')
from entsoe_plants import PLANTS, PSR_ENTSOE, PSR_LABEL

DS = json.load(open('data/plants/plant_downstream.json'))
gw_daily = json.load(open('data/gw_aktuell/daily_levels.json'))
pegel = json.load(open('data/gw_aktuell/pegel_daily.json'))
precip = json.load(open('data/nasa_power_precip_daily.json'))

# ---- release series ----
plant_day = defaultdict(dict)
for r in csv.DictReader(open('data/plant_daily_mwh.csv')):
    plant_day[r['plant']][r['day']] = float(r['mwh'])
nat = defaultdict(dict)
for r in csv.DictReader(open('data/hydro_daily_mwh.csv')):
    nat[r['psr_type']][r['day']] = float(r['mwh'])

def series_for(pid):
    p = PLANTS[pid]
    # live A73 (sum units) if it covers 2026
    live = defaultdict(float); have = defaultdict(int)
    for u in p['units']:
        for d, v in plant_day.get(u, {}).items():
            live[d] += v; have[d] += 1
    days26 = [d for d in live if d >= '2026-01-01']
    if len(days26) > 120:
        return dict(live), 'a73', None
    # downscale from national aggregate, calibrated on this plant's 2023-24 data
    natser = nat[PSR_ENTSOE[p['psr']]]
    days = sorted(set(live) & set(natser))
    if len(days) >= 180:
        y = np.array([live[d] for d in days]); x = np.array([natser[d] for d in days])
        X = np.column_stack([np.ones(len(x)), x])
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        r = float(np.corrcoef(x, y)[0, 1])
        est = {d: max(0.0, b[0] + b[1]*v) for d, v in natser.items()}
        return est, 'downscaled', round(r, 3)
    # last resort: MW share of installed type total (crude)
    share = p['mw'] / sum(q['mw'] for q in PLANTS.values() if q['psr'] == p['psr'])
    return {d: v*share for d, v in natser.items()}, 'mw_share', None

release, rel_src, rel_calib = {}, {}, {}
for pid in DS:
    release[pid], rel_src[pid], rel_calib[pid] = series_for(pid)

def cell_key(lat, lon):
    return f"{round((lat//0.5)*0.5+0.25,3)},{round((lon//0.5)*0.5+0.25,3)}"

def ols_r2(X, y):
    X = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    ssr = float(resid @ resid); sst = float(((y - y.mean())**2).sum())
    return (1 - ssr/sst if sst > 0 else 0.0), beta

def f_pvalue(r2b, r2f, k, n, p_full):
    if r2f <= r2b or n <= p_full + 1: return 1.0
    F = ((r2f - r2b)/k) / ((1 - r2f)/(n - p_full - 1))
    # F(k, n-p_full-1) survival via incomplete beta (regularized)
    d1, d2 = k, n - p_full - 1
    x = d1*F/(d1*F + d2)
    # regularized incomplete beta I_x(d1/2, d2/2) via continued fraction
    return float(1.0 - betainc(d1/2.0, d2/2.0, x))

def betainc(a, b, x):
    # regularized incomplete beta, Lentz continued fraction (NR)
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    lbeta = (math.lgamma(a+b) - math.lgamma(a) - math.lgamma(b)
             + a*math.log(x) + b*math.log(1-x))
    front = math.exp(lbeta)
    if x < (a+1)/(a+b+2):
        return front * cf(a, b, x) / a
    return 1 - front * cf(b, a, 1-x) / b

def cf(a, b, x):
    TINY = 1e-30
    qab, qap, qam = a+b, a+1, a-1
    c, d = 1.0, 1 - qab*x/qap
    if abs(d) < TINY: d = TINY
    d = 1/d; h = d
    for m in range(1, 200):
        m2 = 2*m
        aa = m*(b-m)*x/((qam+m2)*(a+m2))
        d = 1 + aa*d; c = 1 + aa/c
        if abs(d) < TINY: d = TINY
        if abs(c) < TINY: c = TINY
        d = 1/d; h *= d*c
        aa = -(a+m)*(qab+m)*x/((a+m2)*(qap+m2))
        d = 1 + aa*d; c = 1 + aa/c
        if abs(d) < TINY: d = TINY
        if abs(c) < TINY: c = TINY
        d = 1/d
        de = d*c; h *= de
        if abs(de-1) < 3e-12: break
    return h

def day_shift(d, n):
    return (datetime.date.fromisoformat(d) - datetime.timedelta(days=n)).isoformat()

def analyze_pair(levels, lat, lon, rel, placebo_shift=60):
    """levels: {date: value}; rel: {date: mwh}. Returns dict or None."""
    pr = precip.get(cell_key(lat, lon))
    if not pr: return None
    days = sorted(levels)
    rows = []
    for d in days:
        dm1 = day_shift(d, 1)
        if dm1 not in levels: continue
        need = [day_shift(d, i).replace('-', '') for i in range(0, 4)]
        if any(x not in pr for x in need): continue
        if d not in rel or dm1 not in rel: continue
        dp = day_shift(d, placebo_shift); dpm1 = day_shift(dm1, placebo_shift)
        if dp not in rel or dpm1 not in rel: continue
        p7 = sum(pr.get(day_shift(d, i).replace('-', ''), 0) for i in range(7))
        rows.append((levels[d]-levels[dm1],
                     pr[need[0]], pr[need[1]], pr[need[2]], pr[need[3]], p7,
                     rel[d]-rel[dm1], rel[dm1]-rel.get(day_shift(d, 2), rel[dm1]),
                     rel[dp]-rel[dpm1], rel[dpm1]-rel.get(day_shift(dp, 1), rel[dpm1])))
    if len(rows) < 90: return None
    A = np.array(rows, float)
    y = A[:, 0]
    Xb = A[:, 1:6]
    Xf = A[:, 1:8]
    Xp = np.column_stack([A[:, 1:6], A[:, 8:10]])
    r2b, _ = ols_r2(Xb, y)
    r2f, bf = ols_r2(Xf, y)
    r2p, _ = ols_r2(Xp, y)
    n = len(y)
    part = (r2f-r2b)/(1-r2b) if r2b < 1 else 0.0
    partp = (r2p-r2b)/(1-r2b) if r2b < 1 else 0.0
    p = f_pvalue(r2b, r2f, 2, n, Xf.shape[1])
    # direction: response to release increase (sum of the two release betas)
    direction = float(bf[6] + bf[7])
    return dict(n=n, r2_base=round(r2b, 4), r2_full=round(r2f, 4),
                partial=round(part, 4), placebo=round(max(0, partp), 4),
                p=round(p, 5), beta_sum=direction)

links_gw, links_pg = [], []
for pid, ds in DS.items():
    rel = release[pid]
    for hzb, info in ds['gw'].items():
        s = gw_daily.get(hzb)
        if not s or not s.get('levels'): continue
        lon, lat = s['coords'][:2]
        r = analyze_pair(s['levels'], lat, lon, rel)
        if not r: continue
        sig = r['p'] < 0.01 and r['partial'] >= 0.05 and r['partial'] > r['placebo']
        links_gw.append(dict(plant=pid, station=hzb, name=s.get('name'),
                             lat=lat, lon=lon,
                             km=info['km'], off_m=info['off_m'], sig=sig, **r))
    for gid, info in ds['pegel'].items():
        g = pegel.get(gid)
        if not g or not g.get('levels'): continue
        lon, lat = g['coords'][:2]
        r = analyze_pair(g['levels'], lat, lon, rel)
        if not r: continue
        sig = r['p'] < 0.01 and r['partial'] >= 0.05 and r['partial'] > r['placebo']
        links_pg.append(dict(plant=pid, station=gid, name=g.get('name'),
                             river=g.get('gewasser'), km=info['km'],
                             off_m=info['off_m'], sig=sig, **r))

# ---- sparkline series for significant GW links (last ~150 common days) ----
def spark_for(levels, rel, ndays=150):
    days = sorted(set(levels) & set(rel))[-ndays:]
    if len(days) < 60:
        return None
    lv = np.array([levels[d] for d in days], float)
    rl = np.array([rel[d] for d in days], float)
    def norm(a):
        lo, hi = float(a.min()), float(a.max())
        if hi - lo < 1e-9:
            return [50] * len(a)
        return [int(round((v - lo) / (hi - lo) * 100)) for v in a]
    return dict(d0=days[0], d1=days[-1], n=len(days),
                lvl=norm(lv), rel=norm(rl),
                lvl_min=round(float(lv.min()), 2), lvl_max=round(float(lv.max()), 2))

for l in links_gw:
    if not l['sig']:
        continue
    s = gw_daily.get(l['station'])
    sp = spark_for(s['levels'], release[l['plant']]) if s else None
    if sp:
        l['spark'] = sp

plants_out = {}
for pid, ds in DS.items():
    p = PLANTS[pid]
    rel = release[pid]
    d26 = [v for d, v in rel.items() if d >= '2026-01-01']
    plants_out[pid] = dict(
        name=p['name'], lat=p['lat'], lon=p['lon'], mw=p['mw'],
        type=PSR_LABEL[p['psr']], river=p['river'],
        release_source=rel_src[pid], calib_r=rel_calib[pid],
        mean_mwh_day_2026=round(float(np.mean(d26)), 1) if d26 else None,
        snap_m=ds['snap_m'], n_gw_downstream=len(ds['gw']),
        n_pegel_downstream=len(ds['pegel']))

# ---- KG mapping: KGs within 12.5 km of a significant downstream GW station ----
kg_reg = json.load(open('web/data/kg_registry.json'))
def dist_km(a1, o1, a2, o2):
    return math.hypot((a1-a2)*111.32, (o1-o2)*111.32*math.cos(math.radians(a1)))
sig_gw = [l for l in links_gw if l['sig']]
kg_map = {}
for code, reg in kg_reg.items():
    if not reg.get('lat'): continue
    hits = []
    for i, l in enumerate(sig_gw):
        d = dist_km(reg['lat'], reg['lon'], l['lat'], l['lon'])
        if d <= 12.5:
            hits.append((d, i))
    if hits:
        hits.sort()
        kg_map[code] = [i for _, i in hits[:6]]

out = dict(
    generated=datetime.datetime.now().isoformat(timespec='seconds'),
    method=('Daily first-difference OLS per (plant, downstream station) pair, '
            '2026 overlap (~190 d): dLevel ~ precip(t..t-3, 7d) [+ dRelease(t, t-1)]. '
            'Partial R2 over precip baseline; F-test (2 df); placebo = release '
            'shifted back 60 d. Downstream sets from directed OSM waterway walk '
            '(flow direction), GW buffer 4 km, gauge buffer 800 m, max 120 km. '
            'Significant: p<0.01, partial>=0.05, partial>placebo.'),
    caveats=[
        'Correlation, not causation: an upstream release and downstream GW both respond to basin-wide hydrology; precipitation control is coarse (0.5 deg NASA POWER).',
        'Downscaled plants (release_source=downscaled) share the national PSR-type daily signal; attribution to the specific plant is by river topology only. A73-sourced plants have genuinely plant-specific series.',
        'GW overlap window is 2026 daily eHYD data only (~190 days).',
        'OSM linestring direction is assumed = flow direction (true for AT rivers in practice).'],
    plants=plants_out,
    gw_links_sig=sig_gw,
    gw_links=sorted(links_gw, key=lambda x: -x['partial']),
    kg_map=kg_map,
    pegel_links=sorted(links_pg, key=lambda x: -x['partial']))

os.makedirs('web/data', exist_ok=True)
json.dump(out, open('web/data/plant_influence.json', 'w'))
ns = sum(1 for l in links_gw if l['sig']); nsp = sum(1 for l in links_pg if l['sig'])
print(f'gw links {len(links_gw)} ({ns} sig), pegel links {len(links_pg)} ({nsp} sig)')
for l in links_gw:
    if l['sig']: print('GW ', l['plant'], l['station'], l['name'], l['km'], 'km partial', l['partial'], 'p', l['p'], 'placebo', l['placebo'])
for l in links_pg:
    if l['sig']: print('PG ', l['plant'], l['station'], l['name'], l['km'], 'km partial', l['partial'], 'p', l['p'])

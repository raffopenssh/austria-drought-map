#!/usr/bin/env python3
"""Colmation hypothesis test: reservoir operations -> fine-sediment clogging
of riverbeds -> progressive decoupling of river stage from adjacent aquifer.

Three independent tests, all on pre-2023 archives (eHYD), so no dependence on
ENTSO-E release data:

T1 DECOUPLING (core): for every (plant, downstream GW well) pair from
   data/plants/plant_downstream.json, pair the well with the nearest
   downstream river gauge (W-Tagesmittel archive). Deseasonalize both series
   (monthly anomalies vs month-of-year mean), compute Pearson r in decadal
   windows 1973-2022. Colmation predicts r declining over time, more strongly
   below storage (ps/res) plants than below run-of-river (ror) plants.

T2 BED AGGRADATION: at gauges with both W- and Q-Tagesmittel, estimate the
   annual stage at reference discharge (median Q) from a per-year regression
   W ~ a + b*log(Q). A rising W@Qref trend = bed silting up (aggradation).
   Compare storage-affected vs ror-affected vs control gauges.

T3 FLUSHING SIGNATURE: sediment rating residuals log10(S) ~ a + b*log10(Q)
   at the 34 Schwebstoff gauges (2008-2022). (a) trend of annual mean
   residual; (b) frequency of low-flow sediment spikes (residual > +1 dex at
   Q below its 40th pct) -- flushing puts sediment in the river WITHOUT a
   flood; (c) 2015-2022: weekly national reservoir drawdown (A72, MWh
   released) vs weekly mean sediment residual, storage vs control gauges.

Output: data/colmation_analysis.json + console summary.
"""
import csv, json, math, os, sys, datetime
from collections import defaultdict
import numpy as np

sys.path.insert(0, 'scripts')
from entsoe_plants import PLANTS

# ---------------------------------------------------------------- parsing
def parse_ehyd(path):
    """Return list of (date, value) from an eHYD ';'-separated export."""
    out = []
    with open(path, encoding='latin-1') as f:
        started = False
        for line in f:
            if not started:
                if line.startswith('Werte:'):
                    started = True
                continue
            parts = line.split(';')
            if len(parts) < 2:
                continue
            ds, vs = parts[0].strip(), parts[1].strip()
            if not ds or 'cke' in vs:   # Lücke
                continue
            try:
                d = datetime.datetime.strptime(ds, '%d.%m.%Y %H:%M:%S').date()
                v = float(vs.replace(',', '.'))
            except ValueError:
                continue
            out.append((d, v))
    return out

def monthly_means(daily, min_days=20):
    by = defaultdict(list)
    for d, v in daily:
        by[(d.year, d.month)].append(v)
    return {k: float(np.mean(v)) for k, v in by.items() if len(v) >= min_days}

def deseason(mon):
    """month-of-year anomalies, z-scored per calendar month."""
    by_m = defaultdict(list)
    for (y, m), v in mon.items():
        by_m[m].append(v)
    stats = {m: (np.mean(v), np.std(v)) for m, v in by_m.items() if len(v) >= 5}
    out = {}
    for (y, m), v in mon.items():
        if m in stats and stats[m][1] > 1e-9:
            out[(y, m)] = (v - stats[m][0]) / stats[m][1]
    return out

def pearson(x, y):
    x = np.asarray(x); y = np.asarray(y)
    if len(x) < 3 or x.std() < 1e-9 or y.std() < 1e-9:
        return None
    return float(np.corrcoef(x, y)[0, 1])

# ---------------------------------------------------------------- T1
GW_DIR = 'data/gw/Grundwasserstand-Monatsmittel'
W_DIR = 'data/owf/W-Tagesmittel'
Q_DIR = 'data/owf/Q-Tagesmittel'
S_DIR = 'data/owf/Schwebstoff-Tagesfracht'

WINDOWS = [(1973, 1982), (1983, 1992), (1993, 2002), (2003, 2012), (2013, 2022)]

def t1_decoupling():
    ds = json.load(open('data/plants/plant_downstream.json'))
    pegel_mon = {}
    def pegel_anom(h):
        if h not in pegel_mon:
            p = f'{W_DIR}/W-Tagesmittel-{h}.csv'
            pegel_mon[h] = deseason(monthly_means(parse_ehyd(p))) if os.path.exists(p) else None
        return pegel_mon[h]

    pairs = []
    for pid, d in ds.items():
        psr = PLANTS[pid]['psr']
        pegels = [(h, info['km']) for h, info in d.get('pegel', {}).items()
                  if pegel_anom(h)]
        if not pegels:
            continue
        for gh, ginfo in d.get('gw', {}).items():
            gp = f'{GW_DIR}/Grundwasserstand-Monatsmittel-{gh}.csv'
            if not os.path.exists(gp):
                continue
            gmon = deseason({(dt.year, dt.month): v for dt, v in parse_ehyd(gp)})
            if len(gmon) < 240:
                continue
            ph, pkm = min(pegels, key=lambda t: abs(t[1] - ginfo['km']))
            pan = pegel_anom(ph)
            wr = {}
            for (y0, y1) in WINDOWS:
                keys = [k for k in gmon if y0 <= k[0] <= y1 and k in pan]
                if len(keys) < 60:
                    wr[f'{y0}-{y1}'] = None
                    continue
                wr[f'{y0}-{y1}'] = pearson([gmon[k] for k in keys], [pan[k] for k in keys])
            vals = [(i, v) for i, (w, v) in enumerate(sorted(wr.items())) if v is not None]
            if len(vals) < 3:
                continue
            xs, ys = zip(*vals)
            slope = float(np.polyfit(xs, ys, 1)[0])  # r change per decade
            first = vals[0][1]; last = vals[-1][1]
            pairs.append(dict(plant=pid, psr=psr, gw=gh, pegel=ph,
                              km=round(ginfo['km'], 1), windows=wr,
                              slope_per_decade=round(slope, 3),
                              r_first=round(first, 3), r_last=round(last, 3),
                              delta=round(last - first, 3)))
    return pairs

# ---------------------------------------------------------------- gauge classes
# Upstream-regulation class of Schwebstoff/Q gauges (manual, documented):
#  storage = major seasonal-storage / pumped-storage releases upstream
#  ror     = run-of-river chain upstream, no major storage releases
#  control = largely unregulated upstream
GAUGE_CLASS = {
    '200147': ('storage', 'Ill/Gisingen: Illwerke ps cascade'),
    '200196': ('storage', 'Alpenrhein/Lustenau: CH storages + Ill'),
    '200329': ('control', 'Bregenzerach: minor regulation'),
    '201087': ('control', 'Lech/Lechaschau: unregulated in AT'),
    '201350': ('control', 'Rofenache/Vent: glacial, unregulated'),
    '201434': ('control', 'Oetztaler Ache/Tumpen: minor'),
    '201525': ('storage', 'Inn/Innsbruck: Engadin+Sellrain-Silz storages'),
    '201624': ('control', 'Sill: minor'),
    '201780': ('storage', 'Ziller/Hart: Zemm-Ziller ps/res cascade'),
    '201814': ('storage', 'Inn/Rattenberg: Inn storages upstream'),
    '201863': ('control', 'Brixentaler Ache'),
    '202036': ('control', 'Sanna/Landeck'),
    '202382': ('control', 'Grossache'),
    '203323': ('storage', 'Salzach/Golling: Kaprun group + Schwarzach'),
    '205757': ('ror',     'Enns/Jaegerberg: lower Enns ror chain'),
    '205914': ('control', 'Steyr river'),
    '205922': ('ror',     'Enns/Steyr: Enns ror chain'),
    '206201': ('ror',     'Inn/Schaerding: full Inn ror cascade'),
    '206391': ('ror',     'Traun: ror + lakes'),
    '206847': ('ror',     'Salzach/Ach: Salzach ror chain'),
    '207480': ('ror',     'Donau/Hainburg: full Danube ror cascade'),
    '210740': ('control', 'Enns/Trautenfels: upper Enns'),
    '211086': ('control', 'Mur/Gestuethof: upper Mur'),
    '211268': ('control', 'Muerz'),
    '211458': ('control', 'Sulm'),
    '211490': ('ror',     'Mur/Mureck: Mur ror chain'),
    '212167': ('control', 'Isel: unregulated glacial'),
    '212787': ('control', 'Gail'),
    '213090': ('control', 'Lavant'),
    '213173': ('storage', 'Drau/Lavamuend: Malta/Reisseck ps via Moell + Drau ror'),
    '213215': ('control', 'Drau/Amlach: above ror chain'),
    '213660': ('control', 'Drau/Dellach: above ror chain'),
    '230102': ('storage', 'Inn/Oberaudorf: Inn incl. Ziller storages'),
    '231092': ('control', 'Drau/Lienz: upper Drau'),
}

# ---------------------------------------------------------------- T2
import re
def pegelnull_history(h):
    """[(valid_from_date, elevation_m)] from Stammdaten, sorted."""
    p = f'data/owf/Stammdaten/Stammdaten-{h}.csv'
    if not os.path.exists(p):
        return []
    txt = open(p, encoding='latin-1').read()
    m = re.search(r'Pegelnullpunkt:(.*?)\n\s*\n', txt, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        mm = re.match(r'\s*(\d{2}\.\d{2}\.\d{4})\s*;\s*([\d,]+)', line)
        if mm:
            out.append((datetime.datetime.strptime(mm.group(1), '%d.%m.%Y').date(),
                        float(mm.group(2).replace(',', '.'))))
    return sorted(out)

def t2_aggradation():
    res = []
    for h, (cls, note) in GAUGE_CLASS.items():
        wp, qp = f'{W_DIR}/W-Tagesmittel-{h}.csv', f'{Q_DIR}/Q-Tagesmittel-{h}.csv'
        if not (os.path.exists(wp) and os.path.exists(qp)):
            continue
        w = dict(parse_ehyd(wp)); q = dict(parse_ehyd(qp))
        days = sorted(d for d in set(w) & set(q) if q[d] > 0)
        if len(days) < 3650:
            continue
        qref = float(np.median([q[d] for d in days]))
        # Pegelnullpunkt changes usually mean gauge relocation/rebuild -> the
        # stage-discharge relation is not comparable across them. Estimate the
        # trend WITHIN each constant-datum segment (>=10 yr) and combine
        # length-weighted. This measures bed evolution without relocation jumps.
        pn = pegelnull_history(h)
        bounds = [dt for dt, _ in pn[1:]] if pn else []
        segs, cur, bi = [], [], 0
        for d in days:
            while bi < len(bounds) and d >= bounds[bi]:
                if cur: segs.append(cur)
                cur = []; bi += 1
            cur.append(d)
        if cur: segs.append(cur)
        seg_out = []
        for seg in segs:
            byy = defaultdict(list)
            for d in seg:
                byy[d.year].append((math.log(q[d]), w[d]))
            yrs, wref = [], []
            for y in sorted(byy):
                pts = byy[y]
                if len(pts) < 300:
                    continue
                X = np.array([p[0] for p in pts]); Y = np.array([p[1] for p in pts])
                b, a = np.polyfit(X, Y, 1)
                yrs.append(y); wref.append(a + b * math.log(qref))
            if len(yrs) < 10:
                continue
            seg_out.append((yrs, float(np.polyfit(yrs, wref, 1)[0])))
        if not seg_out:
            continue
        tot = sum(len(y) for y, _ in seg_out)
        sl = sum(len(y) * s for y, s in seg_out) / tot
        res.append(dict(hzb=h, cls=cls, note=note,
                        segments=[dict(years=[y[0], y[-1]], n=len(y),
                                       slope_cm_yr=round(s, 3)) for y, s in seg_out],
                        n_years=tot, qref_m3s=round(qref, 1),
                        w_at_qref_trend_cm_yr=round(sl, 3)))
    return res

# ---------------------------------------------------------------- T3
def t3_flushing():
    # weekly national reservoir storage (A72, 2015+)
    resv = {}
    with open('data/reservoir_levels_weekly.csv') as f:
        for r in csv.DictReader(f):
            d = datetime.date.fromisoformat(r['timestamp'][:10])
            resv[d.isocalendar()[:2]] = float(r['stored_energy_mwh'])
    wk = sorted(resv)
    drawdown = {}   # positive = water released that week
    for a, b in zip(wk, wk[1:]):
        drawdown[b] = resv[a] - resv[b]
    # deseasonalize: anomaly vs mean for that ISO week across years
    byw = defaultdict(list)
    for (y, w), v in drawdown.items():
        byw[w].append(v)
    wmean = {w: np.mean(v) for w, v in byw.items()}
    drawdown = {k: v - wmean[k[1]] for k, v in drawdown.items()}

    gauges, spikes_series = [], {}
    for h, (cls, note) in GAUGE_CLASS.items():
        sp = f'{S_DIR}/Schwebstoff-Tagesfracht-{h}.csv'
        qp = f'{Q_DIR}/Q-Tagesmittel-{h}.csv'
        if not (os.path.exists(sp) and os.path.exists(qp)):
            continue
        s = dict(parse_ehyd(sp)); q = dict(parse_ehyd(qp))
        days = [d for d in sorted(set(s) & set(q)) if s[d] > 0 and q[d] > 0]
        if len(days) < 1500:
            continue
        X = np.array([math.log10(q[d]) for d in days])
        Y = np.array([math.log10(s[d]) for d in days])
        b, a = np.polyfit(X, Y, 1)
        resid = {d: Y[i] - (a + b * X[i]) for i, d in enumerate(days)}
        q40 = float(np.percentile([q[d] for d in days], 40))
        # annual mean residual trend
        byy = defaultdict(list)
        for d in days: byy[d.year].append(resid[d])
        yrs = sorted(y for y in byy if len(byy[y]) >= 200)
        tr = None
        if len(yrs) >= 8:
            tr = float(np.polyfit(yrs, [np.mean(byy[y]) for y in yrs], 1)[0])
        # low-flow spikes per year
        spd = defaultdict(int)
        for d in days:
            if q[d] < q40 and resid[d] > 1.0:
                spd[d.year] += 1
        # weekly residual means 2015-2022 for reservoir correlation
        byw = defaultdict(list)
        for d in days:
            if d.year >= 2015:
                byw[d.isocalendar()[:2]].append(resid[d])
        wres = {k: float(np.mean(v)) for k, v in byw.items() if len(v) >= 4}
        # deseasonalize residuals by ISO week too
        byw2 = defaultdict(list)
        for (y, w), v in wres.items():
            byw2[w].append(v)
        wm2 = {w: np.mean(v) for w, v in byw2.items() if len(v) >= 3}
        wres = {k: v - wm2[k[1]] for k, v in wres.items() if k[1] in wm2}
        ck = sorted(set(wres) & set(drawdown))
        r_dd = pearson([drawdown[k] for k in ck], [wres[k] for k in ck]) if len(ck) >= 100 else None
        spikes_series[h] = dict(spd)
        gauges.append(dict(
            hzb=h, cls=cls, note=note, n_days=len(days),
            rating_slope=round(b, 2),
            resid_trend_per_yr=round(tr, 4) if tr is not None else None,
            lowflow_spikes_total=int(sum(spd.values())),
            lowflow_spikes_per_yr=round(sum(spd.values()) / max(len(yrs), 1), 2),
            r_weekly_drawdown=round(r_dd, 3) if r_dd is not None else None,
            n_weeks=len(ck)))
    return gauges, spikes_series

# ---------------------------------------------------------------- T4
def incision_rate(h, y0=1980):
    """cm/yr trend of stage at median Q within constant-datum segments
    (length-weighted), from y0 on; None if no W+Q or too short."""
    wp, qp = f'{W_DIR}/W-Tagesmittel-{h}.csv', f'{Q_DIR}/Q-Tagesmittel-{h}.csv'
    if not (os.path.exists(wp) and os.path.exists(qp)):
        return None
    w = dict(parse_ehyd(wp)); q = dict(parse_ehyd(qp))
    days = sorted(d for d in set(w) & set(q) if q[d] > 0 and d.year >= y0)
    if len(days) < 3650:
        return None
    qref = float(np.median([q[d] for d in days]))
    pn = pegelnull_history(h)
    bounds = [dt for dt, _ in pn[1:]] if pn else []
    segs, cur, bi = [], [], 0
    for d in days:
        while bi < len(bounds) and d >= bounds[bi]:
            if cur: segs.append(cur)
            cur = []; bi += 1
        cur.append(d)
    if cur: segs.append(cur)
    seg_out = []
    for seg in segs:
        byy = defaultdict(list)
        for d in seg:
            byy[d.year].append((math.log(q[d]), w[d]))
        yrs, wref = [], []
        for y in sorted(byy):
            if len(byy[y]) < 300:
                continue
            X = np.array([p[0] for p in byy[y]]); Y = np.array([p[1] for p in byy[y]])
            b, a = np.polyfit(X, Y, 1)
            yrs.append(y); wref.append(a + b * math.log(qref))
        if len(yrs) < 10:
            continue
        seg_out.append((yrs, float(np.polyfit(yrs, wref, 1)[0])))
    if not seg_out:
        return None
    tot = sum(len(y) for y, _ in seg_out)
    return sum(len(y) * s for y, s in seg_out) / tot

def t4_incision_vs_divergence():
    """Across (plant, gw well) pairs: incision rate at nearest downstream
    gauge vs the well's 5-yr precip-GW divergence. Incision-decoupling
    predicts negative relation (more incision -> more negative divergence)."""
    ds = json.load(open('data/plants/plant_downstream.json'))
    div = {s['id']: s['divergence_5yr']
           for s in json.load(open('web/data/precip_gw_correlation.json'))['stations']
           if s.get('divergence_5yr') is not None}
    inc_cache = {}
    rows = []
    for pid, d in ds.items():
        psr = PLANTS[pid]['psr']
        pegels = []
        for h, info in d.get('pegel', {}).items():
            if h not in inc_cache:
                inc_cache[h] = incision_rate(h)
            if inc_cache[h] is not None:
                pegels.append((h, info['km'], inc_cache[h]))
        if not pegels:
            continue
        for gh, ginfo in d.get('gw', {}).items():
            if gh not in div:
                continue
            ph, pkm, inc = min(pegels, key=lambda t: abs(t[1] - ginfo['km']))
            rows.append(dict(plant=pid, psr=psr, gw=gh, pegel=ph,
                             incision_cm_yr=round(inc, 2),
                             divergence_5yr=div[gh]))
    # dedupe wells counted under several plants of the same cascade
    seen = {}
    for r in rows:
        key = r['gw']
        if key not in seen or abs(r['incision_cm_yr']) > abs(seen[key]['incision_cm_yr']):
            seen[key] = r
    rows = list(seen.values())
    x = [r['incision_cm_yr'] for r in rows]
    y = [r['divergence_5yr'] for r in rows]
    r_all = pearson(x, y)
    # split: wells at incising (<-0.3 cm/yr) vs stable/aggrading gauges
    inc_wells = [r['divergence_5yr'] for r in rows if r['incision_cm_yr'] < -0.3]
    oth_wells = [r['divergence_5yr'] for r in rows if r['incision_cm_yr'] >= -0.3]
    return dict(n=len(rows), pearson_r=round(r_all, 3) if r_all else None,
                median_div_incising=med(inc_wells), n_incising=len(inc_wells),
                median_div_stable=med(oth_wells), n_stable=len(oth_wells),
                perm_p=perm_p(inc_wells, oth_wells), pairs=rows)

# ---------------------------------------------------------------- T6
def t6_matched_divergence():
    """Is the ps/res wells' extra-negative divergence just regional?
    Compare each downstream well's divergence_5yr to the median of its
    nearest 15 non-downstream wells (matched local baseline)."""
    ds = json.load(open('data/plants/plant_downstream.json'))
    stations = json.load(open('web/data/precip_gw_correlation.json'))['stations']
    by_id = {s['id']: s for s in stations if s.get('divergence_5yr') is not None}
    downstream = {}
    for pid, d in ds.items():
        grp = 'storage' if PLANTS[pid]['psr'] in ('ps', 'res') else 'ror'
        for gh in d.get('gw', {}):
            if gh in by_id:
                # storage wins if a well sits below both types
                if downstream.get(gh) != 'storage':
                    downstream[gh] = grp
    others = [s for s in stations if s['id'] not in downstream
              and s.get('divergence_5yr') is not None]
    import math as _m
    rows = []
    for gh, grp in downstream.items():
        s = by_id[gh]
        dists = sorted(others, key=lambda o: (o['lat']-s['lat'])**2 +
                       ((o['lon']-s['lon'])*_m.cos(_m.radians(s['lat'])))**2)
        nb = [o['divergence_5yr'] for o in dists[:15]]
        rows.append(dict(gw=gh, grp=grp, divergence=s['divergence_5yr'],
                         neighbor_median=med(nb),
                         excess=round(s['divergence_5yr'] - float(np.median(nb)), 3)))
    out = {}
    for grp in ('storage', 'ror'):
        sub = [r for r in rows if r['grp'] == grp]
        out[grp] = dict(n=len(sub),
                        median_divergence=med([r['divergence'] for r in sub]),
                        median_neighbor=med([r['neighbor_median'] for r in sub]),
                        median_excess=med([r['excess'] for r in sub]))
    out['perm_p_excess_storage_vs_ror'] = perm_p(
        [r['excess'] for r in rows if r['grp'] == 'storage'],
        [r['excess'] for r in rows if r['grp'] == 'ror'])
    out['wells'] = rows
    return out

# ---------------------------------------------------------------- summarize
def med(v): return round(float(np.median(v)), 3) if v else None

def perm_p(a, b, it=20000):
    """two-sided permutation test for difference in medians."""
    if not a or not b: return None
    rng = np.random.default_rng(42)
    both = np.array(a + b); na = len(a)
    obs = abs(np.median(a) - np.median(b))
    cnt = 0
    for _ in range(it):
        rng.shuffle(both)
        if abs(np.median(both[:na]) - np.median(both[na:])) >= obs:
            cnt += 1
    return round(cnt / it, 4)

def main():
    print('=== T1 decoupling ===')
    t1 = t1_decoupling()
    g = defaultdict(list)
    for p in t1:
        grp = 'storage' if p['psr'] in ('ps', 'res') else 'ror'
        g[grp].append(p)
    t1sum = {}
    for grp, ps in g.items():
        deltas = [p['delta'] for p in ps]
        slopes = [p['slope_per_decade'] for p in ps]
        rl = [p['r_last'] for p in ps]; rf = [p['r_first'] for p in ps]
        t1sum[grp] = dict(n=len(ps), median_delta_r=med(deltas),
                          median_slope_per_decade=med(slopes),
                          median_r_first=med(rf), median_r_last=med(rl),
                          share_declining=round(np.mean([d < 0 for d in deltas]), 2))
        print(grp, t1sum[grp])
    t1sum['perm_p_delta_storage_vs_ror'] = perm_p(
        [p['delta'] for p in g['storage']], [p['delta'] for p in g['ror']])
    print('perm p (delta storage vs ror):', t1sum['perm_p_delta_storage_vs_ror'])

    print('=== T2 bed-level evolution ===')
    t2 = t2_aggradation()
    t2sum = {}
    for cls in ('storage', 'ror', 'control'):
        v = [x['w_at_qref_trend_cm_yr'] for x in t2 if x['cls'] == cls]
        t2sum[cls] = dict(n=len(v), median_cm_yr=med(v))
        print(cls, t2sum[cls])
    t2sum['perm_p_storage_vs_control'] = perm_p(
        [x['w_at_qref_trend_cm_yr'] for x in t2 if x['cls'] == 'storage'],
        [x['w_at_qref_trend_cm_yr'] for x in t2 if x['cls'] == 'control'])
    print('perm p (storage vs control):', t2sum['perm_p_storage_vs_control'])

    print('=== T5 sediment load trend by class ===')
    sed = json.load(open('data/sediment_analysis.json'))
    t5sum = {}
    for cls in ('storage', 'ror', 'control'):
        v = [s['trend_pct'] for s in sed
             if s.get('hzb') in GAUGE_CLASS and GAUGE_CLASS[s['hzb']][0] == cls
             and s.get('trend_pct') is not None and s.get('data_points', 0) > 2500]
        t5sum[cls] = dict(n=len(v), median_trend_pct=med(v))
        print(cls, t5sum[cls])

    print('=== T3 flushing ===')
    t3, spikes = t3_flushing()
    t3sum = {}
    for cls in ('storage', 'ror', 'control'):
        sub = [x for x in t3 if x['cls'] == cls]
        t3sum[cls] = dict(
            n=len(sub),
            median_lowflow_spikes_per_yr=med([x['lowflow_spikes_per_yr'] for x in sub]),
            median_resid_trend=med([x['resid_trend_per_yr'] for x in sub
                                    if x['resid_trend_per_yr'] is not None]),
            median_r_drawdown=med([x['r_weekly_drawdown'] for x in sub
                                   if x['r_weekly_drawdown'] is not None]))
        print(cls, t3sum[cls])

    print('=== T4 incision vs GW divergence ===')
    t4 = t4_incision_vs_divergence()
    print({k: v for k, v in t4.items() if k != 'pairs'})

    print('=== T6 matched-neighbor divergence ===')
    t6 = t6_matched_divergence()
    print({k: v for k, v in t6.items() if k != 'wells'})

    out = dict(
        generated=datetime.date.today().isoformat(),
        method=__doc__,
        t1_decoupling=dict(summary=t1sum, pairs=t1),
        t2_aggradation=dict(summary=t2sum, gauges=t2),
        t3_flushing=dict(summary=t3sum, gauges=t3, lowflow_spikes_by_year=spikes),
        t4_incision_vs_divergence=t4,
        t5_sediment_trend=t5sum,
        t6_matched_divergence=t6,
    )
    with open('data/colmation_analysis.json', 'w') as f:
        json.dump(out, f, indent=1)
    print('wrote data/colmation_analysis.json')

if __name__ == '__main__':
    main()

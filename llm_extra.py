#!/usr/bin/env python3
"""Siedler AHEAD-list endpoints (GW-1 .. GW-8) on top of llm_api.

  GET /llm/point?lon=&lat=          water context at a coordinate (GW-1)
  GET /llm/points?west&south&east&north[&categories&limit&history]  (GW-2)
  GET /llm/protection?west&south&east&north   protection-zone polygons (GW-5)
  GET /llm/flowpath?lon=&lat=       downstream reach chain to the border (GW-6)
  GET /llm/gwi.json                 all-KG gwi slim file (GW-7)
  GET /llm/parcel/{parcel_id}       parcel -> points + point context (GW-8)
  drought_block(gem) / now_block(lat,lon) / history_extras(...) for /llm/kg (GW-3/4)

External calls (cadastre point-in-polygon, mghydro flowpath) are cached on disk
under data/cache/ with quantised keys, so the disk footprint stays tiny.
"""
import json, os, gzip, math, hashlib, datetime, urllib.request, urllib.parse, threading
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "web", "data")
CACHE = os.path.join(HERE, "data", "cache")
os.makedirs(CACHE, exist_ok=True)

CADASTRE_POINTS = "https://umfeld-at.exe.xyz/api/v1/spatial/points"
CADASTRE_PARCEL = "https://umfeld-at.exe.xyz/api/v1/search/parcel?id="
MGHYDRO = ("https://mghydro.com/app/getwshed?task=flowpath&lat={lat}&lng={lon}"
           "&source=merit&precision=high&simplify=true")
R_NEAR_KM, R_FALLBACK_KM = 12.5, 30.0
AT_BBOX = (9.4, 46.3, 17.3, 49.1)

_S = {"loaded": False}
_lock = threading.Lock()


def _km(lat1, lon1, lat2, lon2):
    return np.hypot((lat2 - lat1) * 111.32, (lon2 - lon1) * 111.32 * np.cos(np.radians(lat1)))


class Field:
    def __init__(self, recs, key):
        recs = [r for r in recs if r.get("lat") is not None and r.get(key) is not None]
        self.recs = recs
        self.lat = np.array([float(r["lat"]) for r in recs])
        self.lon = np.array([float(r["lon"]) for r in recs])
        self.val = np.array([float(r[key]) for r in recs])

    def query(self, lat, lon):
        if not len(self.val):
            return None
        d = _km(lat, lon, self.lat, self.lon)
        near = d <= R_NEAR_KM
        est = False
        if near.sum() == 0:
            k = np.argsort(d)[:3]
            k = k[d[k] <= R_FALLBACK_KM]
            if not len(k):
                return None
            near = np.zeros_like(d, bool); near[k] = True; est = True
        w = 1.0 / (1.0 + d[near])
        return float(np.sum(self.val[near] * w) / w.sum()), int(near.sum()), est, float(d.min())

    def nearest(self, lat, lon):
        if not len(self.val):
            return None, None
        d = _km(lat, lon, self.lat, self.lon)
        i = int(np.argmin(d))
        return self.recs[i], float(d[i])


def _read(name, default=None):
    p = os.path.join(DATA, name)
    return json.load(open(p)) if os.path.exists(p) else default


def load():
    if _S["loaded"]:
        return
    with _lock:
        if _S["loaded"]:
            return
        gw = _read("gw_stations_trends.json", [])
        _S["gw"] = gw
        _S["f_trend"] = Field(gw, "trend_m_per_decade")
        _S["f_level"] = Field(gw, "current_level")
        div = _read("precip_gw_correlation.json", {}).get("stations", [])
        _S["f_div"] = Field(div, "divergence_5yr")
        no3 = [s for s in _read("nitrate_stations.json", {}).get("stations", [])
               if s.get("latest") is not None and (s.get("last_year") or 0) >= 2015]
        _S["f_no3"] = Field(no3, "latest")
        now = _read("gw_now.json", {"stations": {}})
        _S["now"] = now
        nows = [dict(v, id=k) for k, v in now["stations"].items()]
        _S["f_now_sigma"] = Field(nows, "anomaly_sigma")
        _S["f_now_pct"] = Field(nows, "percentile")
        _S["f_now_tr"] = Field(nows, "trend_30d_cm")
        _S["f_depth"] = Field(nows, "depth_m")
        _S["f_no3_now"] = Field(no3, "latest")
        gp = _read("gauge_profiles.json", {"stations": {}})
        gauges = [dict(v, hzb=k) for k, v in gp["stations"].items() if v.get("lat")]
        _S["gauges"] = gauges
        _S["f_gauge"] = Field(gauges, "mean_m3s")
        _S["drought"] = _read("edo_drought_events.json", {"gemeinden": {}, "meta": {}})
        _S["glacier_comids"] = set(_read("glacier_comids.json", []))
        gwk = _read("gwk_context.json", {"gwks": {}, "kg2gwk": {}})
        _S["gwk"] = gwk
        precip = _read("precip_grid_yearly.json")
        if precip is None:
            precip = _build_precip_yearly()
        _S["precip"] = precip
        _S["outline"] = None
        _S["protection"] = None
        _S["loaded"] = True


def _build_precip_yearly():
    """NASA POWER monthly grid -> per-cell annual precipitation mm (tiny, cached)."""
    src = os.path.join(HERE, "data", "nasa_power_precip.json")
    if not os.path.exists(src):
        return None
    grid = json.load(open(src))["grid"]
    cells = []
    for c in grid:
        yrs = {}
        for ym, v in (c.get("monthly") or {}).items():
            y = ym[:4]
            days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][int(ym[4:6]) - 1]
            yrs.setdefault(y, []).append(v * days)
        yearly = {y: round(sum(v), 0) for y, v in yrs.items() if len(v) == 12}
        cells.append({"lon": c["lon"], "lat": c["lat"], "yearly": yearly})
    out = {"source": "NASA POWER PRECTOTCORR monthly, 0.5 deg", "cells": cells}
    json.dump(out, open(os.path.join(DATA, "precip_grid_yearly.json"), "w"), separators=(",", ":"))
    return out


# ------------------------------------------------------------------ helpers
def _cache_get(kind, key):
    p = os.path.join(CACHE, kind, key + ".json.gz")
    if os.path.exists(p):
        try:
            return json.load(gzip.open(p, "rt"))
        except Exception:
            return None
    return None


def _cache_put(kind, key, obj):
    d = os.path.join(CACHE, kind)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, key + ".tmp")
    with gzip.open(tmp, "wt") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(d, key + ".json.gz"))


def _http_json(url, data=None, timeout=20):
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "groundwater-at/1.0", "Content-Type": "application/json",
        "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw)


def _q4(x):
    return round(float(x), 4)


def kg_at_point(lon, lat, api):
    """(kg_code, parcel_id) via cadastre PiP; cached; falls back to nearest KG centroid."""
    key = f"{_q4(lon):.4f}_{_q4(lat):.4f}"
    hit = _cache_get("pip", key)
    if hit is None:
        hit = {}
        try:
            body = json.dumps({"points": [{"id": "p", "lon": _q4(lon), "lat": _q4(lat)}]}).encode()
            res = _http_json(CADASTRE_POINTS, body, timeout=8)
            r = (res.get("results") or [{}])[0]
            if r.get("kg_code"):
                hit = {"kg_code": str(r["kg_code"]).zfill(5),
                       "parcel_id": (r.get("parcel") or {}).get("parcel_id"),
                       "method": res.get("meta", {}).get("method")}
                _cache_put("pip", key, hit)
        except Exception as exc:
            hit = {"error": str(exc)[:120]}
    if not hit.get("kg_code"):
        # nearest KG centroid from the registry
        reg = api._state.get("kg_registry") or {}
        if reg:
            codes = list(reg)
            lat_a = np.array([reg[c]["lat"] for c in codes]); lon_a = np.array([reg[c]["lon"] for c in codes])
            d = _km(lat, lon, lat_a, lon_a)
            i = int(np.argmin(d))
            if d[i] < 15:
                hit = dict(hit, kg_code=codes[i], method="nearest_kg_centroid")
    return hit


def _cat(g):
    return "good" if g < 0.30 else "watch" if g < 0.50 else "stressed"


# ------------------------------------------------------------------ blocks
def point_metrics(lat, lon, kg_code, api):
    load()
    W = {"trend": 0.30, "div": 0.10, "use": 0.15, "nitrate": 0.20, "wfd": 0.10, "edo": 0.15}
    comps, m = {}, {}
    q = _S["f_trend"].query(lat, lon)
    if q:
        comps["trend"] = max(0, min(1, -q[0] / 0.5)); m["gwi_gw_trend"] = round(q[0], 3); m["gwi_n_gw_stations"] = q[1]
    q = _S["f_div"].query(lat, lon)
    if q:
        comps["div"] = max(0, min(1, -q[0] / 1.5)); m["gwi_gw_div"] = round(q[0], 2)
    q = _S["f_no3"].query(lat, lon)
    if q:
        comps["nitrate"] = max(0, min(1, q[0] / 50)); m["gwi_no3"] = round(q[0], 1); m["gwi_n_no3_stations"] = q[1]
    gwk_id = _S["gwk"]["kg2gwk"].get(kg_code) if kg_code else None
    gwk = _S["gwk"]["gwks"].get(gwk_id) if gwk_id else None
    if gwk:
        comps["use"] = max(0, min(1, gwk["intensity_pct"] / 40)); m["gwi_use_pct"] = gwk["intensity_pct"]; m["gwi_gwk"] = gwk_id
        m["aquifer_type"] = gwk.get("aquifer")
    gem = api._state["kg2gem"].get(kg_code) if kg_code else None
    mun = api._state["gem_by_code"].get(gem) if gem else None
    if mun and mun.get("wq_gw_stations"):
        comps["wfd"] = max(0, min(1, mun.get("wq_risk") or 0))
    if mun and mun.get("edo_cdi_mean") is not None:
        comps["edo"] = max(0, min(1, mun["edo_cdi_mean"] / 2))
    if comps:
        ws = sum(W[c] for c in comps)
        g = sum(W[c] * comps[c] for c in comps) / ws
        m["gwi"] = round(g, 4); m["gwi_category"] = _cat(g)
        for c, v in comps.items():
            m[f"gwi_q_{c}"] = round(v, 3)
    # depth to groundwater: IDW of (ground elevation - level) at live stations
    q = _S["f_depth"].query(lat, lon)
    if q and q[3] <= 5:
        m["depth_to_gw_m_est"] = round(q[0], 1); m["depth_confidence"] = "high" if q[3] <= 2 else "med"
    elif q:
        m["depth_to_gw_m_est"] = round(q[0], 1) if q[3] <= 30 else None; m["depth_confidence"] = "low"
    else:
        m["depth_to_gw_m_est"] = None; m["depth_confidence"] = "low"
    return m


def nearest_blocks(lat, lon, api):
    load()
    out = {}
    s, d = _S["f_level"].nearest(lat, lon)
    if s:
        pid = "gw:" + str(s["id"])
        hit = api._state["point_by_id"].get(pid)
        out["nearest_gw_station"] = {"id": pid, "name": s.get("name"), "distance_m": int(d * 1000),
                                     "gw_level_m": s.get("current_level"),
                                     "gw_trend_m_per_decade": s.get("trend_m_per_decade"),
                                     "parcel_id": (hit[1].get("parcel_id") if hit else None),
                                     "history_url": f"/llm/point/{pid}"}
    s, d = _S["f_no3"].nearest(lat, lon)
    if s:
        out["nearest_no3_station"] = {"id": "no3:" + str(s["id"]), "distance_m": int(d * 1000),
                                      "no3_mg_l": s.get("latest"), "year": s.get("latest_year"),
                                      "history_url": f"/llm/point/no3:{s['id']}"}
    s, d = _S["f_gauge"].nearest(lat, lon)
    if s:
        out["nearest_river"] = {"name": s.get("river"), "distance_m": int(d * 1000),
                                "gauge_hzb": s["hzb"], "gauge_name": s.get("name"),
                                "flow_mean_m3s": s.get("mean_m3s"),
                                "reach_id": None, "glacier_fed": None,
                                "note": "nearest eHYD river gauge (river network distance not computed)",
                                "url": f"/llm/gauge/{s['hzb']}"}
    return out


def drought_block(gem_code):
    load()
    rec = _S["drought"]["gemeinden"].get(str(gem_code)) if gem_code else None
    if not rec:
        return None
    meta = _S["drought"]["meta"]
    return {"source": meta.get("source"), "indicator": meta.get("indicator"),
            "as_of": f"{rec['years'][1]}-12-31", "years": rec["years"],
            "scale": meta.get("scale"), "p_drought_year_rule": meta.get("p_drought_year_rule"),
            "p_drought_year": rec["p_drought_year"], "worst_year": rec["worst_year"],
            "season_profile": rec["season_profile"], "events": rec["events"]}


def now_block(lat, lon):
    load()
    q = _S["f_now_sigma"].query(lat, lon)
    if not q:
        return {"as_of": _S["now"].get("as_of"), "n_stations": 0, "status": None,
                "gw_level_anomaly_sigma": None, "note": "no live eHYD station within 30 km"}
    sig, n, est, dmin = q
    p = _S["f_now_pct"].query(lat, lon)
    t = _S["f_now_tr"].query(lat, lon)
    status = "very_low" if sig < -1.5 else "low" if sig < -0.5 else "high" if sig > 0.5 else "normal"
    out = {"as_of": _S["now"].get("as_of"), "gw_level_anomaly_sigma": round(sig, 2),
           "gw_percentile_of_month": round(p[0], 1) if p else None, "n_stations": n,
           "nearest_station_km": round(dmin, 1), "estimated": est,
           "trend_30d_cm": round(t[0], 1) if t else None, "status": status,
           "source": _S["now"].get("source"),
           "note": "anomaly vs. the station's own day-of-year climatology (eHYD longterm bands), "
                   "IDW over live stations within 12.5 km (nearest-3 <=30 km fallback)"}
    q = _S["f_no3_now"].query(lat, lon)
    if q:
        out["no3_latest_mg_l"] = round(q[0], 1)
    return out


def history_extras(history, lat, lon):
    """Add precip_mm (NASA POWER cell) + gw_level_anomaly_m (stations <=12.5 km) per year."""
    load()
    if not history:
        return history
    pr = _S.get("precip")
    cell = None
    if pr:
        lat_a = np.array([c["lat"] for c in pr["cells"]]); lon_a = np.array([c["lon"] for c in pr["cells"]])
        cell = pr["cells"][int(np.argmin(_km(lat, lon, lat_a, lon_a)))]
    f = _S["f_level"]
    d = _km(lat, lon, f.lat, f.lon) if len(f.val) else None
    near = [f.recs[i] for i in np.where(d <= R_NEAR_KM)[0]] if d is not None else []
    for h in history:
        y = h["as_of"][:4]
        if cell:
            h["precip_mm"] = cell["yearly"].get(y)
        anoms = []
        for s in near:
            ad = s.get("annual_data") or {}
            if y in ad and s.get("mean_level") is not None:
                anoms.append(ad[y] - s["mean_level"])
        h["gw_level_anomaly_m"] = round(sum(anoms) / len(anoms), 3) if anoms else None
    return history


# ------------------------------------------------------------------ endpoints
def ep_point(query, api):
    try:
        lon = float(query["lon"][0]); lat = float(query["lat"][0])
    except (KeyError, ValueError):
        return 400, {"error": "lon and lat required"}
    if not (AT_BBOX[0] <= lon <= AT_BBOX[2] and AT_BBOX[1] <= lat <= AT_BBOX[3]):
        return 404, {"lon": lon, "lat": lat, "error": "no_data", "detail": "outside Austria"}
    api._load(); load()
    lon, lat = _q4(lon), _q4(lat)
    hit = kg_at_point(lon, lat, api)
    kg = hit.get("kg_code")
    m = point_metrics(lat, lon, kg, api)
    if "gwi" not in m:
        return 404, {"lon": lon, "lat": lat, "kg_code": kg, "error": "no_data"}
    out = {"service": api.SERVICE, "lon": lon, "lat": lat, "kg_code": kg,
           "gemeinde_code": api._state["kg2gem"].get(kg) if kg else None,
           "parcel_id": hit.get("parcel_id"), "kg_method": hit.get("method"),
           "granularity": "point", "as_of": api.AS_OF, "updated_at": api._state["updated_at"],
           "source": api.SOURCE, "license": api.LICENSE, "metrics": m}
    out.update(nearest_blocks(lat, lon, api))
    gwk_id = m.get("gwi_gwk")
    if gwk_id:
        g = _S["gwk"]["gwks"][gwk_id]
        out["groundwater_body"] = {"gwk_id": gwk_id, "name": g.get("name"), "aquifer": g.get("aquifer"),
                                   "abstraction_intensity_pct": g.get("intensity_pct")}
    out["now"] = now_block(lat, lon)
    out["kg_url"] = f"/llm/kg/{kg}" if kg else None
    return 200, out


def _bbox(query):
    try:
        w, s, e, n = (float(query[k][0]) for k in ("west", "south", "east", "north"))
    except (KeyError, ValueError):
        return None
    if not (w < e and s < n):
        return None
    return w, s, e, n


def ep_points(query, api):
    bb = _bbox(query)
    if not bb:
        return 400, {"error": "west,south,east,north required (west<east, south<north)"}
    api._load()
    cats = set((query.get("categories", [""])[0] or "").split(",")) - {""}
    limit = max(1, min(500, int(query.get("limit", ["500"])[0] or 500)))
    hist = query.get("history", ["0"])[0] == "1"
    w, s, e, n = bb
    pts = []
    for pid, (kg, p) in api._state["point_by_id"].items():
        if p.get("lon") is None or not (w <= p["lon"] <= e and s <= p["lat"] <= n):
            continue
        if cats and p["category"] not in cats:
            continue
        o = {k: v for k, v in p.items() if k != "history" or hist}
        o["kg_code"] = kg
        o["history_url"] = f"/llm/point/{pid}"
        pts.append(o)
    pts.sort(key=lambda o: o["id"])
    return 200, {"service": api.SERVICE, "bbox": [w, s, e, n], "points": pts[:limit],
                 "count": min(len(pts), limit), "total": len(pts), "truncated": len(pts) > limit,
                 "categories": sorted(cats) or api.manifest()["point_categories"],
                 "as_of": api.AS_OF, "license": api.LICENSE}


def _load_protection():
    if _S.get("protection") is not None:
        return _S["protection"]
    with _lock:
        if _S.get("protection") is not None:
            return _S["protection"]
        from shapely.geometry import shape, box
        from shapely.strtree import STRtree
        p = os.path.join(DATA, "water_protection_at.geojson")
        feats = json.load(open(p))["features"] if os.path.exists(p) else []
        geoms, props = [], []
        for i, f in enumerate(feats):
            try:
                g = shape(f["geometry"])
            except Exception:
                continue
            geoms.append(g)
            pr = f.get("properties") or {}
            zt = pr.get("zone_type") or ""
            zone = None
            for z in ("III", "II", "I"):
                if f"Zone {z})" in zt or zt.endswith(z):
                    zone = z; break
            props.append({"id": f"wp:{i}", "name": pr.get("name"),
                          "type": "schongebiet" if "schon" in zt.lower() else "schutzgebiet",
                          "zone": zone, "state": pr.get("province"),
                          "source": f"{pr.get('province')} WIS / INSPIRE AM (fetch_water_protection.py)"})
        _S["protection"] = {"tree": STRtree(geoms) if geoms else None, "geoms": geoms, "props": props,
                            "as_of": datetime.datetime.utcfromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d") if feats else None}
        return _S["protection"]


def ep_protection(query, api):
    bb = _bbox(query)
    if not bb:
        return 400, {"error": "west,south,east,north required"}
    from shapely.geometry import box, mapping
    P = _load_protection()
    limit = max(1, min(500, int(query.get("limit", ["500"])[0] or 500)))
    zones = []
    if P["tree"] is not None:
        b = box(*bb)
        idx = P["tree"].query(b)
        idx = sorted(int(i) for i in idx if P["geoms"][int(i)].intersects(b))
        for i in idx[:limit]:
            z = dict(P["props"][i]); z["geometry"] = mapping(P["geoms"][i]); zones.append(z)
    else:
        idx = []
    return 200, {"service": api.SERVICE, "bbox": list(bb), "zones": zones, "count": len(zones),
                 "total": len(idx), "truncated": len(idx) > limit, "ready": True,
                 "as_of": P["as_of"], "license": "per-state open data (Länder WIS / INSPIRE); CC-BY-4.0 compilation",
                 "coverage": "OÖ, Stmk, T, Bgld, W, NÖ, Vbg (K, Sbg missing)"}


def _outline():
    if _S.get("outline") is None:
        from shapely.geometry import shape
        p = os.path.join(DATA, "austria_outline.json")
        _S["outline"] = shape(json.load(open(p))).buffer(0.002) if os.path.exists(p) else False
    return _S["outline"]


def _order_reaches(features, lon, lat):
    """mghydro flowpath features are unordered/mixed direction; chain them by
    shared endpoints starting from the reach nearest to the query point."""
    def key(c):
        return (round(c[0], 4), round(c[1], 4))
    segs = []
    for f in features:
        cs = f["geometry"]["coordinates"]
        if f["geometry"]["type"] == "MultiLineString":
            cs = [c for part in cs for c in part]
        if len(cs) >= 2:
            segs.append({"comid": f["properties"].get("comid"), "sorder": f["properties"].get("sorder"), "c": cs})
    if not segs:
        return []
    # index endpoints
    ends = {}
    for i, s in enumerate(segs):
        ends.setdefault(key(s["c"][0]), []).append(i)
        ends.setdefault(key(s["c"][-1]), []).append(i)
    # start: segment with the closest vertex to the point
    best, bi = 1e9, 0
    for i, s in enumerate(segs):
        for c in s["c"]:
            d = (c[0] - lon) ** 2 + ((c[1] - lat) * 1.4) ** 2
            if d < best:
                best, bi = d, i
    def walk(start_seg, from_end):
        out, seen, cur = [], set(), start_seg
        node = key(cur["c"][-1] if from_end else cur["c"][0])
        cur_pts = cur["c"] if from_end else cur["c"][::-1]
        out.append(dict(cur, c=cur_pts)); seen.add(id(cur))
        while True:
            nxt = [segs[j] for j in ends.get(node, []) if id(segs[j]) not in seen]
            if not nxt:
                break
            # prefer higher stream order (main stem) when branching
            nxt.sort(key=lambda s: -(s["sorder"] or 0))
            s = nxt[0]
            pts = s["c"] if key(s["c"][0]) == node else s["c"][::-1]
            node = key(pts[-1]); seen.add(id(s)); out.append(dict(s, c=pts))
        return out
    a = walk(segs[bi], True); b = walk(segs[bi], False)
    best_walk = a if sum(len(x["c"]) for x in a) >= sum(len(x["c"]) for x in b) else b
    if len(best_walk) < len(segs) // 2 and len(segs) > 1:
        # the nearest reach is a disconnected stub (mghydro splits the reach at
        # the requested point). Walk from every dangling endpoint instead and
        # keep the longest chain; prepend the stub so the start is at the point.
        for node, idxs in ends.items():
            if len(idxs) != 1:
                continue
            s0 = segs[idxs[0]]
            w = walk(s0, key(s0["c"][0]) == node)
            if len(w) > len(best_walk):
                best_walk = w
        if segs[bi] not in best_walk and all(x["comid"] != segs[bi]["comid"] for x in best_walk):
            stub = segs[bi]
            head = best_walk[0]["c"][0]
            d0 = (stub["c"][0][0] - head[0]) ** 2 + (stub["c"][0][1] - head[1]) ** 2
            d1 = (stub["c"][-1][0] - head[0]) ** 2 + (stub["c"][-1][1] - head[1]) ** 2
            best_walk.insert(0, dict(stub, c=stub["c"] if d1 <= d0 else stub["c"][::-1]))
    return best_walk


def ep_flowpath(query, api):
    try:
        lon = float(query["lon"][0]); lat = float(query["lat"][0])
    except (KeyError, ValueError):
        return 400, {"error": "lon and lat required"}
    if not (AT_BBOX[0] <= lon <= AT_BBOX[2] and AT_BBOX[1] <= lat <= AT_BBOX[3]):
        return 404, {"lon": lon, "lat": lat, "error": "no_data", "detail": "outside Austria"}
    api._load(); load()
    lon, lat = round(lon, 3), round(lat, 3)  # 3 decimals: ~100 m, matches MERIT 90 m
    key = f"{lon:.3f}_{lat:.3f}"
    res = _cache_get("flowpath", key)
    if res is None:
        try:
            raw = _http_json(MGHYDRO.format(lat=lat, lon=lon), timeout=25)
            feats = (raw.get("rivers") or {}).get("features") or []
            chain = _order_reaches(feats, lon, lat)
            res = {"reaches": [{"comid": s["comid"], "sorder": s["sorder"], "c": s["c"]} for s in chain]}
            if chain:
                _cache_put("flowpath", key, res)
        except Exception as exc:
            return 503, {"error": "upstream_unavailable", "detail": str(exc)[:200], "retry_after_s": 30}
    chain = res["reaches"]
    if not chain:
        return 404, {"lon": lon, "lat": lat, "error": "no_data"}
    from shapely.geometry import LineString, Point
    outline = _outline()
    gaug = _S["gauges"]
    g_lat = np.array([float(g["lat"]) for g in gaug]); g_lon = np.array([float(g["lon"]) for g in gaug])
    reaches, total, coords, exit_pt, border_hit = [], 0.0, [], None, False
    used_g = set()
    for s in chain:
        pts = s["c"]
        # length km
        L = 0.0
        for a, b in zip(pts, pts[1:]):
            L += float(_km(a[1], a[0], b[1], b[0]))
        # clip at the border
        if outline:
            for i, c in enumerate(pts):
                if not outline.contains(Point(c)):
                    border_hit = True
                    pts = pts[:max(1, i + 1)]
                    exit_pt = [round(c[0], 5), round(c[1], 5)]
                    L = sum(float(_km(a[1], a[0], b[1], b[0])) for a, b in zip(pts, pts[1:]))
                    break
        r = {"reach_id": s["comid"], "stream_order": s["sorder"], "length_km": round(L, 1),
             "glacier_fed": s["comid"] in _S["glacier_comids"]}
        # gauges within 400 m of this reach's vertices
        if len(gaug):
            line = LineString(pts) if len(pts) > 1 else Point(pts[0])
            cand = np.where(_km(pts[0][1], pts[0][0], g_lat, g_lon) < L + 3)[0]
            best = None
            for j in cand:
                if j in used_g:
                    continue
                d = line.distance(Point(g_lon[j], g_lat[j])) * 111.32 * 1000 * math.cos(math.radians(g_lat[j]))
                if d < 400 and (best is None or d < best[0]):
                    best = (d, j)
            if best:
                j = best[1]; used_g.add(j); g = gaug[j]
                r["river"] = g.get("river")
                r["gauge"] = {"hzb": g["hzb"], "name": g.get("name"), "flow_mean_m3s": g.get("mean_m3s"),
                              "flow_trend_pct_per_decade": g.get("trend_pct_decade"),
                              "distance_m": int(best[0]), "url": f"/llm/gauge/{g['hzb']}"}
        total += L
        coords.extend(pts if not coords else pts[1:])
        reaches.append(r)
        if border_hit:
            break
    # carry river names forward/backward from gauges along the chain
    name = None
    for r in reaches:
        if r.get("river"):
            name = r["river"]
        r.setdefault("river", name)
    name = None
    for r in reversed(reaches):
        if r.get("river"):
            name = r["river"]
        elif name:
            r["river"] = name
    if exit_pt is None:
        exit_pt = [round(coords[-1][0], 5), round(coords[-1][1], 5)]
    sea = "north_sea" if (exit_pt[0] < 10.3 or (exit_pt[1] > 48.6 and exit_pt[0] < 15.3)) else "black_sea"
    line = LineString(coords) if len(coords) > 1 else None
    geom = None
    if line is not None:
        tol = 0.0005
        while True:
            simp = line.simplify(tol, preserve_topology=False)
            geom = {"type": "LineString", "coordinates": [[round(x, 4), round(y, 4)] for x, y in simp.coords]}
            if len(json.dumps(geom, separators=(",", ":"))) <= 3000 or tol > 0.5:
                break
            tol *= 2
    first = reaches[0]
    d0 = float(_km(lat, lon, chain[0]["c"][0][1], chain[0]["c"][0][0]))
    return 200, {
        "service": api.SERVICE, "lon": lon, "lat": lat,
        "start": {"reach_id": first["reach_id"], "river": first.get("river"), "distance_m": int(d0 * 1000)},
        "reaches": reaches, "n_reaches": len(reaches), "total_km": round(total, 1),
        "exit": {"river": reaches[-1].get("river"), "border_point": exit_pt, "sea": sea,
                 "clipped_at_border": border_hit},
        "geometry": geom,
        "catchment_geometry_url": "/data/catchments.geojson",
        "source": "MERIT-Basins flow paths via mghydro.com (CC BY-NC-SA); gauges eHYD/OWF",
        "license": "CC BY-NC-SA 4.0 (MERIT-Basins/mghydro) for geometry; CC-BY-4.0 for gauge attributes",
        "note": "reach chain follows the main stem (highest stream order) at confluences; "
                "river names come from eHYD gauges snapped within 400 m; "
                "glacier_fed = reach lies on a downstream path of an RGI glacier",
    }


def ep_gwi(api):
    api._load()
    kgs = {k: [r["i"], {"good": 0, "watch": 1, "stressed": 2}[r["c"]]]
           for k, r in api._state["gwi_kgs"].items() if r.get("i") is not None}
    return 200, {"service": api.SERVICE, "as_of": api.AS_OF,
                 "generated": api._state.get("gwi_meta", {}).get("generated"),
                 "categories": {"0": "good", "1": "watch", "2": "stressed"},
                 "thresholds": {"good": "<0.30", "watch": "<0.50", "stressed": ">=0.50"},
                 "fields": ["gwi", "category_index"], "kg_count": len(kgs), "kgs": kgs}


def ep_parcel(pid, api):
    api._load(); load()
    pid = pid.strip("/")
    if not pid or "-" not in pid:
        return 400, {"error": "parcel_id like 63307-133/5 required"}
    kg = pid.split("-")[0].zfill(5)
    pts = [dict(p, history_url=f"/llm/point/{p['id']}") for p in api._state["kg_points"].get(kg, [])
           if p.get("parcel_id") == pid]
    for p in pts:
        p.pop("history", None)
    key = hashlib.md5(pid.encode()).hexdigest()[:16]
    meta = _cache_get("parcel", key)
    if meta is None:
        try:
            res = _http_json(CADASTRE_PARCEL + urllib.parse.quote(pid, safe=""), timeout=8)
            rows = res.get("data") or []
            if rows:
                r = rows[0]
                meta = {"lon": r.get("lon"), "lat": r.get("lat"), "area_sqm": r.get("area_sqm"),
                        "ez": r.get("ez"), "gnr": r.get("gnr"), "kg_name": r.get("kg_name"),
                        "landuse_summary": r.get("landuse_summary")}
                _cache_put("parcel", key, meta)
            else:
                meta = {}
        except Exception as exc:
            meta = {"error": str(exc)[:120]}
    if not meta.get("lat") and not pts:
        return 404, {"parcel_id": pid, "error": "no_data"}
    lat = meta.get("lat") or pts[0]["lat"]; lon = meta.get("lon") or pts[0]["lon"]
    m = point_metrics(lat, lon, kg, api)
    out = {"service": api.SERVICE, "parcel_id": pid, "kg_code": kg,
           "gemeinde_code": api._state["kg2gem"].get(kg), "granularity": "parcel",
           "centroid": {"lon": lon, "lat": lat}, "parcel": {k: v for k, v in meta.items() if k not in ("lon", "lat")} or None,
           "points": pts, "n_points": len(pts), "metrics": m,
           "as_of": api.AS_OF, "updated_at": api._state["updated_at"],
           "source": api.SOURCE, "license": api.LICENSE}
    out.update(nearest_blocks(lat, lon, api))
    gwk_id = m.get("gwi_gwk")
    if gwk_id:
        g = _S["gwk"]["gwks"][gwk_id]
        out["water_body"] = {"gwk_id": gwk_id, "name": g.get("name"), "aquifer": g.get("aquifer"),
                             "abstraction_intensity_pct": g.get("intensity_pct")}
    out["now"] = now_block(lat, lon)
    out["kg_url"] = f"/llm/kg/{kg}"
    return 200, out


def handle(path, query, api):
    if path == "/llm/point":
        return ep_point(query, api)
    if path == "/llm/points":
        return ep_points(query, api)
    if path == "/llm/protection":
        return ep_protection(query, api)
    if path == "/llm/flowpath":
        return ep_flowpath(query, api)
    if path == "/llm/gwi.json":
        return ep_gwi(api)
    if path.startswith("/llm/parcel/"):
        return ep_parcel(urllib.parse.unquote(path[len("/llm/parcel/"):]), api)
    return None

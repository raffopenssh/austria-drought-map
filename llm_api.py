#!/usr/bin/env python3
"""Sibling-service integration endpoints for the Kohlschwarz cadastre ecosystem.

Implements the "Integration Spec for Sibling Data Services" published at
https://umfeld-at.exe.xyz/api/v1/docs/llm.txt?section=integration

Granularity is MIXED:
  - The Groundwater Status Index (GWI) and its components are computed at
    every KG centroid (web/data/gw_index_kg.json) -> granularity "kg".
  - The legacy drought-risk metrics are per-municipality (Gemeinde); for a
    requested kg_code we map UP to its gemeinde_code and return the
    Gemeinde-level block alongside.
  - Station observations (groundwater levels, nitrate, hydropower, WFD
    sites) are per-point, snapped once to their KG via the cadastre
    POST /api/v1/spatial/points (scripts/snap_points.py).

Endpoints:
  GET /llm/kg/{kg_code}            per-KG payload (alias: .json)
  GET /llm/kgs?codes=a,b,c         batch (<=500) of per-KG payloads
  GET /llm/gemeinde/{code_or_name} per-Gemeinde payload (alias: /llm/muni/)
  GET /llm/gemeinden?codes=a,b,c   batch (<=500) of per-Gemeinde payloads
  GET /llm/point/{id}              single point, e.g. gw:336446, no3:AT...
  GET /llm/manifest.json           coverage + schema descriptor
  GET /llm/covered_kgs.json        array of every kg_code we can answer
  GET /llm/covered_gemeinden.json  array of every gemeinde_code we can answer
"""
import json
import os
import datetime
import urllib.request
import urllib.parse
import sys

import llm_extra

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "web", "data")

SERVICE = "groundwater-at"
DATASET = "Austrian drought & water-stress risk"
SOURCE = ("Copernicus EDO CDI, eHYD groundwater & surface-flow stations, "
          "GeoSphere precipitation, WISE water quality, INSPIRE soil, e-control hydro")
LICENSE = "CC-BY-4.0"
# Validity date of the headline figures: latest EDO drought year we ingest.
AS_OF = "2023-12-31"

GWI_GLOSSARY = {
    "gwi": "Groundwater Status Index 0-1 (higher = more stressed); KG-granular",
    "gwi_category": "good|watch|stressed bucket of gwi (<0.30 / <0.50 / >=0.50)",
    "gwi_q_trend": "GWI quantity component: 10-yr level-trend sub-risk 0-1 (w 30%)",
    "gwi_q_div": "GWI quantity component: precip-divergence sub-risk 0-1 (w 10%)",
    "gwi_q_use": ("GWI use component: groundwater-body abstraction intensity sub-risk 0-1 "
                  "= clamp(Nutzungsintensitaet/40%), Wasserschatz 2021 (w 15%)"),
    "gwi_q_nitrate": "GWI quality component: nitrate sub-risk 0-1 vs 50 mg/L EU limit (w 20%)",
    "gwi_q_wfd": "GWI quality component: WFD 2022 status sub-risk 0-1 (w 10%)",
    "gwi_q_edo": "GWI drought component: EDO CDI sub-risk 0-1 (w 15%)",
    "gwi_gw_trend": "IDW groundwater level trend at the KG centroid, m/decade (neg = declining)",
    "gwi_gw_div": "IDW 5-yr precip-vs-level divergence, sigma (neg = below precip-explained)",
    "gwi_no3": "IDW latest annual-mean nitrate at the KG centroid, mg/L",
    "gwi_use_pct": "groundwater body Nutzungsintensitaet: abstraction / available resource, %",
    "gwi_gwk": "groundwater body (GWK) id of the KG, e.g. GK100026",
    "gwi_n_gw_stations": "# groundwater level stations used for the interpolation",
    "gwi_n_no3_stations": "# nitrate stations used for the interpolation",
    "gwi_estimated": "1 = >=1 component used the nearest-3 <=30 km fallback (sparse area)",
}

# gw_index_kg.json compact key -> API metric name
_GWI_KEYMAP = [
    ("i", "gwi"), ("c", "gwi_category"),
    ("q_trend", "gwi_q_trend"), ("q_div", "gwi_q_div"),
    ("q_use", "gwi_q_use"),
    ("q_nitrate", "gwi_q_nitrate"), ("q_wfd", "gwi_q_wfd"),
    ("q_edo", "gwi_q_edo"),
    ("gw_trend", "gwi_gw_trend"), ("gw_div", "gwi_gw_div"),
    ("no3", "gwi_no3"),
    ("use_pct", "gwi_use_pct"), ("gwk", "gwi_gwk"),
    ("n_gw", "gwi_n_gw_stations"), ("n_no3", "gwi_n_no3_stations"),
    ("est", "gwi_estimated"),
]

UNIT_GLOSSARY = {
    "risk_score": "composite drought-risk index 0-1 (higher = drier/more stressed)",
    "risk_category": "low|medium|high bucket of risk_score",
    "edo_cdi_mean": "Copernicus EDO Combined Drought Indicator, mean class 0-5",
    "edo_cdi_max": "Copernicus EDO Combined Drought Indicator, max class 0-5",
    "edo_risk": "drought-indicator sub-risk 0-1",
    "gw_risk": "groundwater-level sub-risk 0-1",
    "gw_trend": "groundwater level trend (m/decade, negative = declining)",
    "precip_risk": "precipitation sub-risk 0-1",
    "precip_trend_mm": "annual precipitation trend (mm/decade)",
    "precip_mean_mm": "mean annual precipitation (mm)",
    "flow_risk": "river-flow sub-risk 0-1",
    "flow_trend_pct": "river-flow trend (percent/decade)",
    "flow_mean_m3s": "mean river flow (m3/s)",
    "hydro_risk": "hydropower-exposure sub-risk 0-1",
    "soil_permeability": "INSPIRE soil permeability class (higher = more permeable)",
    "soil_risk": "soil-permeability sub-risk 0-1",
    "wq_risk": "water-quality sub-risk 0-1",
}

# Keys copied verbatim from the municipality record into metrics (when present).
METRIC_KEYS = [
    "risk_score", "risk_category", "edo_cdi_mean", "edo_cdi_max", "edo_risk",
    "gw_risk", "gw_trend", "precip_risk", "precip_trend_mm", "precip_mean_mm",
    "flow_risk", "flow_trend_pct", "flow_mean_m3s", "hydro_risk",
    "soil_permeability", "soil_risk", "wq_risk",
]

METRICS_SCHEMA = {
    "risk_score": "number", "risk_category": "string",
    "edo_cdi_mean": "number", "edo_cdi_max": "number", "edo_risk": "number",
    "gw_risk": "number", "gw_trend": "number",
    "precip_risk": "number", "precip_trend_mm": "number", "precip_mean_mm": "number",
    "flow_risk": "number", "flow_trend_pct": "number", "flow_mean_m3s": "number",
    "hydro_risk": "number", "soil_permeability": "number", "soil_risk": "number",
    "wq_risk": "number",
}

# ---- point datasets (granularity=point), snapped to KGs once via the cadastre
# POST /api/v1/spatial/points (see scripts/snap_points.py) -------------------
POINT_GLOSSARY = {
    "no3_mg_l": "nitrate concentration, mg/L (annual mean; <LOQ counted as LOQ/2)",
    "no3_latest_year": "year of the latest nitrate annual mean",
    "no3_trend_mg_l_per_yr": "Theil-Sen nitrate trend, mg/L per year",
    "nitrate_station_count": "# WISE-6 nitrate stations in this KG",
    "gw_level_m": "groundwater level, m above adriatic (latest annual mean)",
    "gw_trend_m_per_decade": "groundwater level trend, m/decade (neg = declining)",
    "gw_p_value": "p-value of the groundwater trend",
    "capacity_mw": "hydropower plant capacity, MW",
    "chem_status": "WISE/WFD chemical status (Good|Poor|...)",
    "eco_status": "WISE/WFD ecological status",
    "at_risk": "WISE/WFD at-risk flag (Yes|No)",
    "gw_station_count": "# groundwater stations in this KG",
    "power_plant_count": "# hydropower plants in this KG",
    "water_quality_site_count": "# WISE water-quality sites in this KG",
}

_state = {"loaded": False}
_load_lock = __import__("threading").Lock()


def _gw_point(s, snap):
    """Groundwater station -> point object with full annual history."""
    metrics = {
        "gw_level_m": s.get("current_level"),
        "gw_trend_m_per_decade": s.get("trend_m_per_decade"),
        "gw_p_value": s.get("p_value"),
    }
    history = []
    for yr in sorted((s.get("annual_data") or {}).keys()):
        history.append({"as_of": str(yr), "gw_level_m": s["annual_data"][yr]})
    p = {
        "id": "gw:" + str(s["id"]),
        "category": "groundwater_station",
        "name": s.get("name"),
        "lon": s.get("lon"), "lat": s.get("lat"),
        "metrics": {k: v for k, v in metrics.items() if v is not None},
    }
    if snap.get("parcel_id"):
        p["parcel_id"] = snap["parcel_id"]
    if history:
        p["history"] = history
    return p


def _pp_point(idx, p, snap):
    obj = {
        "id": "pp:" + str(idx),
        "category": "power_plant",
        "name": p.get("type"),
        "lon": p.get("lon"), "lat": p.get("lat"),
        "metrics": {"capacity_mw": p.get("mw")},
        "plant_type": p.get("type"),
        "river": p.get("river"),
    }
    if snap.get("parcel_id"):
        obj["parcel_id"] = snap["parcel_id"]
    return obj


def _wq_point(f, snap):
    pr = f.get("properties") or {}
    c = (f.get("geometry") or {}).get("coordinates") or [None, None]
    obj = {
        "id": "wq:" + str(pr.get("id")),
        "category": "water_quality_site",
        "name": pr.get("name"),
        "lon": c[0], "lat": c[1],
        "water_body_type": pr.get("type"),
        "metrics": {
            "chem_status": pr.get("chemStatus"),
            "eco_status": pr.get("ecoStatus"),
            "at_risk": pr.get("atRisk"),
        },
    }
    if snap.get("parcel_id"):
        obj["parcel_id"] = snap["parcel_id"]
    return obj


def _no3_point(s, snap):
    """WISE-6 nitrate station -> point object with full annual history."""
    metrics = {
        "no3_mg_l": s.get("latest"),
        "no3_latest_year": s.get("latest_year"),
        "no3_trend_mg_l_per_yr": s.get("trend_per_yr"),
    }
    p = {
        "id": "no3:" + str(s["id"]),
        "category": "nitrate_station",
        "name": s.get("id"),
        "lon": s.get("lon"), "lat": s.get("lat"),
        "metrics": {k: v for k, v in metrics.items() if v is not None},
    }
    if snap.get("parcel_id"):
        p["parcel_id"] = snap["parcel_id"]
    history = [{"as_of": str(yr), "no3_mg_l": v}
               for yr, v in sorted((s.get("annual") or {}).items())]
    if history:
        p["history"] = history
    return p


def _load():
    if _state["loaded"]:
        return
    with _load_lock:
        if _state["loaded"]:
            return
        _load_impl()


def _load_impl():
    munis = json.load(open(os.path.join(DATA, "municipalities.json")))
    _state["gem_by_code"] = {str(m["iso"]).zfill(5): m for m in munis}
    # kg_code / gemeinde_code are canonically 5-char zero-padded strings.
    # kg_registry.json (all 7,850 KGs, from the cadastre EDM register) is the
    # primary source; kg_to_gemeinde.json fills any historical stragglers.
    kg2gem = {}
    reg_path = os.path.join(DATA, "kg_registry.json")
    if os.path.exists(reg_path):
        _state["kg_registry"] = json.load(open(reg_path))
        for k, r in _state["kg_registry"].items():
            kg2gem[str(k).zfill(5)] = str(r["g"]).zfill(5)
    else:
        _state["kg_registry"] = {}
    raw = json.load(open(os.path.join(DATA, "kg_to_gemeinde.json")))
    for k, v in raw.items():
        kg2gem.setdefault(str(k).zfill(5), str(v).zfill(5))
    _state["kg2gem"] = kg2gem
    # Per-KG Groundwater Status Index (the model behind the GW Power app).
    gwi_path = os.path.join(DATA, "gw_index_kg.json")
    if os.path.exists(gwi_path):
        gwi = json.load(open(gwi_path))
        _state["gwi_kgs"] = gwi.get("kgs", {})
        _state["gwi_meta"] = {"generated": gwi.get("generated"),
                              "weights": gwi.get("weights")}
    else:
        _state["gwi_kgs"], _state["gwi_meta"] = {}, {}
    # Hydropower downstream influence (informational; not part of the GWI).
    pi_path = os.path.join(DATA, "plant_influence.json")
    if os.path.exists(pi_path):
        pi = json.load(open(pi_path))
        _state["plant_infl"] = pi
        _state["plant_kg_map"] = pi.get("kg_map", {})
    else:
        _state["plant_infl"], _state["plant_kg_map"] = None, {}
    # Per-plant profiles (generation history, downstream gauges, reservoir).
    ppf_path = os.path.join(DATA, "plant_profiles.json")
    _state["plant_profiles"] = (json.load(open(ppf_path))
                                if os.path.exists(ppf_path) else None)
    # Per-gauge profiles (annual + live flow, sediment).
    gpf_path = os.path.join(DATA, "gauge_profiles.json")
    _state["gauge_profiles"] = (json.load(open(gpf_path))
                                if os.path.exists(gpf_path) else None)
    # Groundwater-body context (Wasserschatz 2021) + population (Statistik AT).
    gc_path = os.path.join(DATA, "gwk_context.json")
    if os.path.exists(gc_path):
        gc = json.load(open(gc_path))
        _state["gwk_ctx"] = gc
    else:
        _state["gwk_ctx"] = None
    # Glacier / snow context (WGMS FoG + ASTER dh/dt, RGI 6.0, SNOWGRID-CL).
    gl_path = os.path.join(DATA, "glacier_context.json")
    _state["glacier"] = json.load(open(gl_path)) if os.path.exists(gl_path) else None
    # Real upstream catchments (MERIT-Hydro via mghydro.com) + the glacier-fed
    # MERIT reach beside each KG. Validated against official eHYD catchment size.
    ws_path = os.path.join(DATA, "watershed_context.json")
    _state["ws"] = json.load(open(ws_path)) if os.path.exists(ws_path) else None
    mr_path = os.path.join(DATA, "merit_reach_kg.json")
    _state["merit_kg"] = json.load(open(mr_path)) if os.path.exists(mr_path) else None
    pop_path = os.path.join(DATA, "population.json")
    if os.path.exists(pop_path):
        _state["pop"] = json.load(open(pop_path))
    else:
        _state["pop"] = None
    # Reverse map gemeinde_code -> [kg_code, ...] for the per-Gemeinde endpoint.
    gem2kgs = {}
    for kg, gem in _state["kg2gem"].items():
        gem2kgs.setdefault(str(gem), []).append(str(kg))
    _state["gem2kgs"] = {g: sorted(k) for g, k in gem2kgs.items()}
    # Exact (casefolded) name -> gemeinde_code index. Names come from the
    # canonical municipality registry; only unambiguous names are indexed.
    by_name = {}
    for code, m in _state["gem_by_code"].items():
        key = str(m.get("name", "")).casefold()
        by_name.setdefault(key, set()).add(code)
    _state["gem_by_name"] = {k: next(iter(v)) for k, v in by_name.items() if len(v) == 1}
    _state["gem_ambiguous"] = {k: sorted(v) for k, v in by_name.items() if len(v) > 1}
    covered = {str(k).zfill(5) for k in json.load(open(os.path.join(DATA, "covered_kgs.json")))}

    # Build kg_code -> [point objects] from the snapped point datasets.
    kg_points = {}
    snap_path = os.path.join(DATA, "point_snap.json")
    snap = json.load(open(snap_path)) if os.path.exists(snap_path) else {}

    point_by_id = {}

    def add(pid, obj):
        point_by_id[pid] = (None, obj)
        s = snap.get(pid)
        if not s or not s.get("kg_code"):
            return
        kg = str(s["kg_code"])
        point_by_id[pid] = (kg, obj)
        kg_points.setdefault(kg, []).append(obj)
        covered.add(kg)

    gw_path = os.path.join(DATA, "gw_stations_trends.json")
    if os.path.exists(gw_path):
        for s in json.load(open(gw_path)):
            pid = "gw:" + str(s["id"])
            add(pid, _gw_point(s, snap.get(pid) or {}))
    pp_path = os.path.join(DATA, "powerplants.json")
    if os.path.exists(pp_path):
        for i, p in enumerate(json.load(open(pp_path))):
            pid = "pp:" + str(i)
            add(pid, _pp_point(i, p, snap.get(pid) or {}))
    wq_path = os.path.join(DATA, "wise_monitoring_sites.json")
    if os.path.exists(wq_path):
        for f in json.load(open(wq_path))["features"]:
            pr = f.get("properties") or {}
            pid = "wq:" + str(pr.get("id"))
            add(pid, _wq_point(f, snap.get(pid) or {}))
    no3_path = os.path.join(DATA, "nitrate_stations.json")
    if os.path.exists(no3_path):
        for s in json.load(open(no3_path)).get("stations", []):
            pid = "no3:" + str(s["id"])
            add(pid, _no3_point(s, snap.get(pid) or {}))

    # Flat point index for /llm/point/{id} (includes unsnapped points).
    _state["point_by_id"] = point_by_id
    # Every KG with a GWI value is covered.
    covered.update(str(k).zfill(5) for k in _state["gwi_kgs"])

    _state["kg_points"] = kg_points
    _state["covered"] = sorted(covered)
    # updated_at: when the underlying data files were last recomputed.
    mtime = os.path.getmtime(os.path.join(DATA, "municipalities.json"))
    _state["updated_at"] = (datetime.datetime.utcfromtimestamp(mtime)
                            .strftime("%Y-%m-%dT%H:%M:%SZ"))
    _state["loaded"] = True


def _point_rollup(points):
    """KG-level roll-up metrics derived from the snapped points."""
    gw = [p for p in points if p["category"] == "groundwater_station"]
    pp = [p for p in points if p["category"] == "power_plant"]
    wq = [p for p in points if p["category"] == "water_quality_site"]
    out = {}
    if gw:
        out["gw_station_count"] = len(gw)
        trends = [p["metrics"].get("gw_trend_m_per_decade") for p in gw
                  if p["metrics"].get("gw_trend_m_per_decade") is not None]
        if trends:
            out["gw_trend_m_per_decade_mean"] = round(sum(trends) / len(trends), 4)
    if pp:
        out["power_plant_count"] = len(pp)
        caps = [p["metrics"].get("capacity_mw") for p in pp
                if p["metrics"].get("capacity_mw") is not None]
        if caps:
            out["power_capacity_mw_total"] = round(sum(caps), 1)
    if wq:
        out["water_quality_site_count"] = len(wq)
        at_risk = sum(1 for p in wq if p["metrics"].get("at_risk") == "Yes")
        out["water_quality_sites_at_risk"] = at_risk
    no3 = [p for p in points if p["category"] == "nitrate_station"]
    if no3:
        out["nitrate_station_count"] = len(no3)
    return out


def _gwi_metrics(kg_code):
    """Per-KG GWI metrics (granularity: kg) from gw_index_kg.json."""
    rec = _state["gwi_kgs"].get(kg_code) or _state["gwi_kgs"].get(kg_code.lstrip("0"))
    if not rec:
        return {}
    return {name: rec[k] for k, name in _GWI_KEYMAP if rec.get(k) is not None}


def _history(m):
    """Per-year EDO drought time-series as a 'history' array (ascending)."""
    yearly = m.get("edo_yearly") or {}
    out = []
    for year in sorted(yearly.keys()):
        e = yearly[year] or {}
        if e.get("mean") is None:
            continue
        entry = {"as_of": str(year), "edo_cdi_mean": round(e["mean"], 3)}
        if e.get("max") is not None:
            entry["edo_cdi_max"] = round(e["max"], 3)
        out.append(entry)
    return out


def _payload_for_kg(kg_code):
    """Return (dict, http_status). 404 dict when we hold nothing."""
    _load()
    kg_code = str(kg_code).strip().zfill(5)
    gem_code = _state["kg2gem"].get(kg_code)
    m = _state["gem_by_code"].get(gem_code) if gem_code else None
    points = _state["kg_points"].get(kg_code, [])
    has_gwi = bool(_state["gwi_kgs"].get(kg_code))
    # Nothing at all for this KG.
    if not m and not points and not has_gwi:
        return {"kg_code": kg_code, "error": "no_data"}, 404

    metrics = {}
    if m:
        for k in METRIC_KEYS:
            if k in m and m[k] is not None:
                metrics[k] = m[k]
    # The GWI and its components are evaluated at THIS KG's centroid.
    gwi = _gwi_metrics(kg_code)
    metrics.update(gwi)
    # Fold the point roll-up (station counts etc.) into the KG-level metrics.
    metrics.update(_point_rollup(points))

    glossary = dict(UNIT_GLOSSARY)
    if gwi:
        glossary.update(GWI_GLOSSARY)
    if points:
        glossary.update(POINT_GLOSSARY)

    payload = {
        "service": SERVICE,
        "dataset": DATASET,
        "kg_code": kg_code,
        "gemeinde_code": gem_code,
        "gemeinde_name": m.get("name") if m else None,
        # gwi_* metrics are KG-granular (computed at this KG's centroid);
        # the legacy drought metrics are municipal; snapped point
        # observations (stations/plants/sites) for this KG are in 'points'.
        "granularity": "kg" if gwi else "gemeinde",
        "granularity_note": ("gwi_* metrics: kg; legacy risk metrics: "
                             "gemeinde; points: point"),
        "as_of": AS_OF,
        "updated_at": _state["updated_at"],
        "source": SOURCE,
        "license": LICENSE,
        "unit_glossary": glossary,
        "metrics": metrics,
        "history": _history(m) if m else [],
        "points": points,
    }
    hydro = _hydro_influence_for_kg(kg_code)
    if hydro:
        payload["hydropower_influence"] = hydro
    gwk = _gwk_block(kg_code)
    if gwk:
        payload["groundwater_body"] = gwk
    cryo = _cryosphere_block(kg_code)
    if cryo:
        payload["cryosphere"] = cryo
    basin = _basin_block(kg_code)
    if basin:
        payload["catchment"] = basin
    popb = _population_block(gem_code)
    if popb:
        popb["per_year"] = None  # keep per-KG payloads small
        payload["population"] = {k: v for k, v in popb.items() if v is not None}
    # GW-3 drought calendar (Gemeinde, EDO CDI dekads) + GW-4 live state (IDW
    # over eHYD live stations at the KG centroid) + per-year precip/GW anomaly.
    reg = _state["kg_registry"].get(kg_code) or _state["kg_registry"].get(kg_code.lstrip("0"))
    lat = reg["lat"] if reg else (float(m["lat"]) if m and m.get("lat") else None)
    lon = reg["lon"] if reg else (float(m["lon"]) if m and m.get("lon") else None)
    try:
        dr = llm_extra.drought_block(gem_code)
        if dr:
            payload["drought"] = dr
        if lat is not None:
            payload["now"] = llm_extra.now_block(lat, lon)
            payload["history"] = llm_extra.history_extras(payload["history"], lat, lon)
            payload["point_url"] = f"/llm/point?lon={lon:.4f}&lat={lat:.4f}"
    except Exception as exc:  # never lose the base payload over an add-on
        payload["extras_error"] = str(exc)[:200]
    return payload, 200


def _slim(obj, query):
    """?fields=a,b (top-level keys; id/contract keys always kept) and ?history=0."""
    if not isinstance(obj, dict):
        return obj
    if (query.get("history", ["1"])[0]) == "0" and "history" in obj:
        obj = dict(obj); obj["history"] = []
        obj["history_omitted"] = True
    fields = (query.get("fields", [""])[0] or "").strip()
    if fields:
        keep = {"service", "kg_code", "gemeinde_code", "granularity", "as_of", "error"}
        keep.update(f.strip() for f in fields.split(",") if f.strip())
        obj = {k: v for k, v in obj.items() if k in keep}
    return obj


def _basin_block(kg_code, series=False):
    """The real upstream catchment of this KG's river, or None.

    Delineated from the MERIT-Hydro DEM (MERIT-Basins) by mghydro.com and
    validated against the officially published eHYD catchment size, so this is
    the hydrologically correct contributing area rather than a snap onto the
    nearest waterway line. Glacier outlines (RGI 6.0) and the SNOWGRID-CL snow
    grid are intersected with the polygon.

    Informational, NOT a GWI component -- like the cryosphere block it describes
    upstream supply, not the state of the aquifer.
    """
    ws = _state.get("ws")
    if not ws:
        return None
    k = (ws.get("kg") or {}).get(kg_code)
    if not k:
        return None
    g = (ws.get("gauges") or {}).get(k["hzb"])
    if not g:
        return None
    sn = g.get("snow") or {}
    out = {
        "in_gwi": False,
        "source": ws.get("source"),
        "method": ("MERIT-Hydro catchment delineation via mghydro.com "
                   "(CC BY-NC-SA), cross-checked against the official eHYD "
                   "catchment size; catchments off by >25% are excluded"),
        "outlet_gauge": {
            "hzb": k["hzb"], "name": g.get("name"), "river": g.get("river"),
            "lat": g.get("lat"), "lon": g.get("lon"),
        },
        "area_km2": g.get("km2"),
        "area_km2_official_ehyd": g.get("km2_ehyd"),
        "area_agreement_pct": g.get("km2_err_pct"),
        "quality": g.get("quality"),
        "nested_gauged_basins_containing_this_kg": k.get("n_nested"),
        "mean_annual_river_flow_mio_m3": g.get("flow_mio_m3a"),
        "river_flow_trend_pct_per_decade": g.get("trend_pct_decade"),
        "glacier": {
            "ice_area_km2_in_catchment": g.get("ice_km2"),
            "ice_share_of_catchment_pct": g.get("ice_pct"),
            "n_glaciers": g.get("n_gl"),
            "net_ice_loss_mio_m3_per_year": g.get("melt_mio_m3a"),
            "net_ice_loss_share_of_annual_flow_pct": g.get("melt_pct_flow"),
            "depletion_years_at_current_rate": g.get("depletion_years"),
        },
        "snow": {
            "store_1apr_mio_m3_last10": g.get("snow_store_mio_m3"),
            "store_1apr_mio_m3_1961_1990": g.get("snow_store_6190_mio_m3"),
            "store_1apr_as_share_of_annual_flow_pct": g.get("snow_pct_flow"),
            "swe_1apr_mm_last10": sn.get("apr_mean_last10"),
            "swe_1apr_mm_1961_1990": sn.get("apr_mean_6190"),
            "swe_1apr_trend_pct_per_decade": sn.get("apr_pct_dec"),
            "swe_1jul_mm_last10": sn.get("jul_mean_last10"),
            "swe_1jul_trend_pct_per_decade": sn.get("jul_pct_dec"),
            "grid_coverage_of_catchment": g.get("snow_coverage"),
            "grid_cells_km2": g.get("snow_px_km2"),
            "note": ("SNOWGRID-CL v2 covers Austria only: volumes use the "
                     "in-country cell count and the share-of-flow ratio is "
                     "reported only when >=90% of the catchment is inside the "
                     "grid. It is a store/flux ratio (how snow-dependent the "
                     "basin is), not a runoff share."),
        },
    }
    if k.get("ice_basin"):
        out["wider_glacier_fed_basin"] = k["ice_basin"]
    mk = (_state.get("merit_kg") or {}).get("kg", {}).get(kg_code)
    if mk:
        out["nearest_glacier_fed_river_reach"] = {
            "comid": mk.get("comid"),
            "distance_to_kg_centroid_m": mk.get("dist_to_river_m"),
            "river_km_downstream_of_nearest_ice": mk.get("river_km_from_ice"),
            "upstream_ice_area_km2": mk.get("ice_km2"),
            "upstream_net_ice_loss_mio_m3_per_year": mk.get("melt_mio_m3a"),
            "n_glaciers_upstream": mk.get("n_gl"),
            "strahler_order": mk.get("sorder"),
            "method": "MERIT-Basins downstream flow paths from every RGI 6.0 glacier",
        }
    if series:
        out["snow"]["swe_1apr_per_year"] = sn.get("apr")
        out["snow"]["swe_1jul_per_year"] = sn.get("jul")
    return out


def _gwk_block(kg_code):
    """Wasserschatz groundwater-body context for the KG's body, or None."""
    gc = _state.get("gwk_ctx")
    if not gc:
        return None
    gid = gc["kg2gwk"].get(kg_code)
    g = gc["gwks"].get(gid) if gid else None
    if not g:
        return None
    out = {
        "gwk_id": gid, "name": g["name"], "aquifer_type": g["aquifer"],
        "area_km2": g["area_km2"],
        "available_resource_m3_per_year": g["resource_m3a"],
        "total_abstraction_m3_per_year": g["demand_m3a"],
        "abstraction_intensity_pct": g["intensity_pct"],
        "abstraction_by_sector_m3_per_year": g["demand"],
        "population_on_body": g["population"],
        "source": "Wasserschatz Oesterreichs (BMLRT/Umweltbundesamt 2021)",
    }
    if g.get("supply_lcd") is not None:
        out["public_supply_abstraction_l_per_cap_day"] = g["supply_lcd"]
    if g.get("note"):
        out["note"] = g["note"]
    return out


def _cryosphere_block(kg_code, series=False):
    """Glacier melt upstream + seasonal snow store for a KG, or None.

    Informational: an upstream, non-renewable input to the same aquifers, on a
    different clock than abstraction or nitrate -- deliberately NOT a GWI
    component. See the Methods section of the app.
    """
    gl = _state.get("glacier")
    if not gl:
        return None
    r = (gl.get("kg") or {}).get(kg_code)
    if not r:
        return None
    out = {
        "source": gl.get("source"),
        "in_gwi": False,
        "note": ("Net glacier ice loss is a one-off storage release that is "
                 "currently added to river flow and valley recharge; it ends "
                 "with the ice. Snow is the larger, faster-shrinking store."),
    }
    if r.get("melt_mio_m3a"):
        out["glacier"] = {
            "ice_area_km2_upstream": r.get("ice_km2"),
            "n_glaciers_upstream": r.get("n_gl"),
            "net_ice_loss_mio_m3_per_year": r.get("melt_mio_m3a"),
            "ice_volume_mio_m3_upstream": r.get("vol_mio_m3"),
            "depletion_years_at_current_rate": r.get("depletion_years"),
            "river_km_from_nearest_ice": r.get("dist_km"),
            "share_of_kg_in_glacier_fed_corridor": r.get("corridor_share"),
            "corridor_buffer_m": 2000,
            "method": ("directed OSM waterway walk downstream from RGI 6.0 "
                       "outlines; loss rates from ASTER dh/dt (Hugonnet et al. "
                       "2021) via WGMS FoG 2026-02; volume from volume-area "
                       "scaling (Bahr et al. 1997)"),
        }
        traj = (gl.get("ice_traj") or {}).get(r.get("ice_traj"))
        if traj:
            out["glacier"]["projection"] = {
                "year_half_of_todays_melt": traj.get("year_half_melt"),
                "year_ice_effectively_gone": traj.get("year_gone"),
                "model": "melt scales with remaining area (peak water, then collapse)",
            }
            if series:
                out["glacier"]["projection"]["melt_mio_m3_per_year"] = traj.get("melt")
                out["glacier"]["observed_melt_mio_m3_per_year"] = traj.get("hist")
    if r.get("snow_apr_mm") is not None:
        snow = {
            "swe_1apr_mm_mean_last10": r.get("snow_apr_mm"),
            "swe_1apr_mm_mean_1961_1990": r.get("snow_apr_mm_6190"),
            "swe_1apr_trend_pct_per_decade": r.get("snow_apr_pct_decade"),
            "swe_1jul_mm_mean_last10": r.get("snow_jul_mm"),
            "swe_1jul_trend_pct_per_decade": r.get("snow_jul_pct_decade"),
            "source": "GeoSphere Austria SNOWGRID-CL v2, 1 km, 1961-2026",
        }
        sser = (gl.get("snow") or {}).get(kg_code)
        if sser and sser.get("apr_proj"):
            snow["projection_1apr"] = {
                "mm_2050": sser["apr_proj"].get("proj_2050"),
                "year_half_of_1961_1990_store": sser["apr_proj"].get("year_half"),
                "model": "linear fit on the last 40 years, floored at zero",
            }
        if series and sser:
            snow["swe_1apr_per_year"] = sser.get("apr")
            snow["swe_1jul_per_year"] = sser.get("jul")
        out["snow"] = snow
    return out if ("glacier" in out or "snow" in out) else None


def _population_block(gem_code):
    """Population time-series summary for a Gemeinde, or None."""
    pop = _state.get("pop")
    if not pop or not gem_code:
        return None
    code = pop.get("alias", {}).get(gem_code, gem_code)
    r = pop["gemeinden"].get(code)
    if not r:
        return None
    yrs = pop["years"]
    n = len(yrs) - 1
    return {
        "latest_year": yrs[n], "population": r["t"][n],
        "population_2002": r["t"][0],
        "growth_since_2002_pct": round((r["t"][n] - r["t"][0]) / r["t"][0] * 100, 1),
        "share_65plus_pct": round(r["y65"][n] / r["t"][n] * 100, 1),
        "per_year": {"years": yrs, "total": r["t"], "age_65plus": r["y65"]},
        "source": "Statistik Austria OGD (CC-BY-4.0), Jan 1, 2026 boundaries",
    }


def _hydro_influence_for_kg(kg_code):
    """Significant upstream hydro plant -> downstream GW well couplings
    relevant to this KG (well within 12.5 km). Informational; not in GWI."""
    pi = _state.get("plant_infl")
    idxs = _state.get("plant_kg_map", {}).get(kg_code)
    if not pi or not idxs:
        return None
    links = []
    for i in idxs:
        try:
            l = pi["gw_links_sig"][i]
        except (IndexError, KeyError):
            continue
        p = pi["plants"].get(l["plant"], {})
        links.append({
            "plant": p.get("name", l["plant"]),
            "plant_type": p.get("type"),
            "plant_mw": p.get("mw"),
            "river": p.get("river"),
            "release_source": p.get("release_source"),
            "gw_station": l["station"],
            "gw_station_name": l.get("name"),
            "km_downstream": l["km"],
            "partial_r2": l["partial"],
            "p_value": l["p"],
            "placebo_partial_r2": l["placebo"],
            "direction": "level_rises_with_release" if l.get("beta_sum", 0) > 0
                         else "level_falls_with_release",
        })
    if not links:
        return None
    return {
        "note": ("Daily turbined releases of the listed upstream hydro plants "
                 "(ENTSO-E) explain partial_r2 of the day-to-day level variation "
                 "at the listed downstream monitoring well (river-network "
                 "topology, precipitation-controlled, p<0.01, above placebo). "
                 "Correlation with controls, not proven causation; NOT part of "
                 "the GWI."),
        "links": links,
    }


_lookup_cache = {}


def _canonical_lookup(name):
    """Resolve a Gemeinde name via the canonical cadastre EDM lookup.

    Used only when the local exact-name index misses; result is cached.
    Returns gemeinde_code or None.
    """
    key = name.casefold()
    if key in _lookup_cache:
        return _lookup_cache[key]
    code = None
    try:
        url = ("https://umfeld-at.exe.xyz/api/v1/lookup?type=gemeinde&limit=2&q="
               + urllib.parse.quote(name))
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.load(resp).get("data") or []
        if len(data) == 1 and data[0].get("gemeinde_code"):
            code = str(data[0]["gemeinde_code"])
    except Exception:
        code = None
    _lookup_cache[key] = code
    return code


def _payload_for_gemeinde(ident):
    """Per-Gemeinde payload. ident = 5-digit gemeinde_code or exact name.

    Returns (dict, http_status).
    """
    _load()
    ident = str(ident).strip()
    gem_code = None
    if ident.isdigit() and len(ident) == 5:
        gem_code = ident
    else:
        key = ident.casefold()
        gem_code = _state["gem_by_name"].get(key)
        if not gem_code and key in _state["gem_ambiguous"]:
            return {"gemeinde": ident, "error": "ambiguous_name",
                    "candidates": _state["gem_ambiguous"][key]}, 300
        if not gem_code:
            gem_code = _canonical_lookup(ident)
    m = _state["gem_by_code"].get(gem_code) if gem_code else None
    if not m:
        return {"gemeinde": ident, "error": "no_data"}, 404

    kgs = _state["gem2kgs"].get(gem_code, [])
    # Union of the snapped points across all KGs of this Gemeinde.
    points = []
    for kg in kgs:
        for p in _state["kg_points"].get(kg, []):
            q = dict(p)
            q["kg_code"] = kg
            points.append(q)

    metrics = {k: m[k] for k in METRIC_KEYS if m.get(k) is not None}
    # Gemeinde-mean GWI (aggregated over its KGs by build_gw_index.py).
    gwi_keys = [n for _, n in _GWI_KEYMAP]
    gwi = {k: m[k] for k in gwi_keys if m.get(k) is not None}
    metrics.update(gwi)
    metrics.update(_point_rollup(points))

    glossary = dict(UNIT_GLOSSARY)
    if gwi:
        glossary.update(GWI_GLOSSARY)
        glossary["gwi"] += " (Gemeinde value = mean over its KGs)"
    if points:
        glossary.update(POINT_GLOSSARY)

    payload = {
        "service": SERVICE,
        "dataset": DATASET,
        "gemeinde_code": gem_code,
        "gemeinde_name": m.get("name"),
        "kg_codes": kgs,
        "granularity": "gemeinde",
        "as_of": AS_OF,
        "updated_at": _state["updated_at"],
        "source": SOURCE,
        "license": LICENSE,
        "unit_glossary": glossary,
        "metrics": metrics,
        "history": _history(m),
        "points": points,
    }
    popb = _population_block(gem_code)
    if popb:
        payload["population"] = popb
    if kgs and _state.get("gwk_ctx"):
        # a Gemeinde can span several groundwater bodies: use the dominant one
        k2g = _state["gwk_ctx"]["kg2gwk"]
        counts = {}
        for kg in kgs:
            gid = k2g.get(kg)
            if gid:
                counts[gid] = counts.get(gid, 0) + 1
        if counts:
            dominant_kg = next(kg for kg in kgs
                               if k2g.get(kg) == max(counts, key=counts.get))
            gwk = _gwk_block(dominant_kg)
            if gwk:
                if len(counts) > 1:
                    gwk["note_span"] = (f"Gemeinde spans {len(counts)} "
                                        "groundwater bodies; dominant shown")
                payload["groundwater_body"] = gwk
    if kgs:
        # Cryosphere: report the KG of this Gemeinde with the most upstream ice
        # (a Gemeinde is glacier-fed if any of its KGs is), full series here.
        gl = _state.get("glacier")
        if gl:
            best, bm = None, -1.0
            for kg in kgs:
                r = (gl.get("kg") or {}).get(kg) or {}
                m = r.get("melt_mio_m3a") or 0
                if m > bm:
                    bm, best = m, kg
            if best is None:
                best = kgs[0]
            cryo = _cryosphere_block(best, series=True)
            if cryo:
                cryo["representative_kg_code"] = best
                payload["cryosphere"] = cryo
        # Catchment: the largest verified basin any of the Gemeinde's KGs sits
        # in (a Gemeinde usually drains to one river), with the full snow series.
        ws = _state.get("ws")
        if ws:
            cand = [(((ws.get("kg") or {}).get(kg) or {}).get("km2") or 0, kg)
                    for kg in kgs]
            cand = [c for c in cand if c[0] > 0]
            if cand:
                basin = _basin_block(max(cand)[1], series=True)
                if basin:
                    basin["representative_kg_code"] = max(cand)[1]
                    payload["catchment"] = basin
    return payload, 200


def manifest():
    _load()
    schema = dict(METRICS_SCHEMA)
    for _, name in _GWI_KEYMAP:
        schema[name] = "string" if name == "gwi_category" else "number"
    return {
        "service": SERVICE,
        "dataset": DATASET,
        "finest_granularity": "kg",
        "granularity_note": ("gwi_* metrics are KG-granular (7,850 KGs); "
                             "legacy drought metrics are Gemeinde-level; "
                             "station observations are point-level with "
                             "annual history"),
        "model": {"name": "Groundwater Status Index (GWI)",
                  **_state.get("gwi_meta", {}),
                  "docs": "scripts/build_gw_index.py; Methods modal at /"},
        "join_keys": ["kg_code", "gemeinde_code"],
        "kg_endpoint": "/llm/kg/{kg_code}",
        "batch_endpoint": "/llm/kgs?codes={kg_code,...}",
        "gemeinde_endpoint": "/llm/gemeinde/{gemeinde_code_or_name}",
        "gemeinde_batch_endpoint": "/llm/gemeinden?codes={gemeinde_code,...}",
        "point_endpoint": "/llm/point/{point_id}",
        "point_context_endpoint": "/llm/point?lon={lon}&lat={lat}",
        "points_bbox_endpoint": "/llm/points?west&south&east&north[&categories&limit&history=0|1]",
        "protection_endpoint": "/llm/protection?west&south&east&north",
        "flowpath_endpoint": "/llm/flowpath?lon={lon}&lat={lat}",
        "gwi_all_kgs_url": "/llm/gwi.json",
        "parcel_endpoint": "/llm/parcel/{parcel_id}",
        "kg_query_params": "?fields=metrics,points,drought,now (top-level keys) &history=0",
        "kg_blocks": ["metrics", "history", "points", "drought", "now", "groundwater_body",
                      "catchment", "cryosphere", "hydropower_influence", "population"],
        "covered_gemeinden_url": "/llm/covered_gemeinden.json",
        "metrics_schema": schema,
        "point_categories": [
            "groundwater_station", "nitrate_station", "power_plant",
            "water_quality_site"],
        "point_kg_count": len(_state["kg_points"]),
        "kg_count": len(_state["covered"]),
        "gemeinde_count": len(set(_state["kg2gem"].values())),
        "covered_kgs_url": "/llm/covered_kgs.json",
        "as_of": AS_OF,
        "source": SOURCE,
        "license": LICENSE,
        "updated_at": _state["updated_at"],
    }


def covered_kgs():
    _load()
    return _state["covered"]


def handle(path, query):
    """Route an /llm/ request.

    Returns (status_int, obj) or None if path is not an /llm/ route.
    """
    if path == "/llm/manifest.json":
        return 200, manifest()
    if path == "/llm/covered_kgs.json":
        return 200, covered_kgs()
    if path == "/llm/covered_gemeinden.json":
        _load()
        return 200, sorted(_state["gem_by_code"].keys())
    if path == "/llm/gemeinden":
        codes = (query.get("codes", [""])[0]).strip()
        if not codes:
            return 400, {"error": "missing 'codes' query parameter"}
        code_list = [c.strip() for c in codes.split(",") if c.strip()][:500]
        results = []
        for c in code_list:
            obj, _ = _payload_for_gemeinde(c)
            results.append(obj)
        return 200, {"results": results, "meta": {"requested": len(code_list)}}
    for prefix in ("/llm/gemeinde/", "/llm/muni/"):
        if path.startswith(prefix):
            ident = urllib.parse.unquote(path[len(prefix):])
            if ident.endswith(".json"):
                ident = ident[:-5]
            ident = ident.strip("/")
            if not ident:
                return 400, {"error": "missing gemeinde code or name"}
            obj, status = _payload_for_gemeinde(ident)
            return status, obj
    if path == "/llm/kgs":
        codes = (query.get("codes", [""])[0]).strip()
        if not codes:
            return 400, {"error": "missing 'codes' query parameter"}
        code_list = [c.strip() for c in codes.split(",") if c.strip()][:500]
        results = []
        for c in code_list:
            obj, _ = _payload_for_kg(c)
            results.append(_slim(obj, query))
        return 200, {"results": results,
                     "meta": {"requested": len(code_list)}}
    if path.startswith("/llm/plant/"):
        pid = urllib.parse.unquote(path[len("/llm/plant/"):]).strip("/")
        if pid.endswith(".json"):
            pid = pid[:-5]
        _load()
        pp = _state.get("plant_profiles")
        if not pp:
            return 404, {"error": "no_plant_profiles"}
        if not pid:
            return 200, {"plants": sorted(pp["plants"].keys()),
                         "generated": pp.get("generated"),
                         "endpoint": "/llm/plant/{plant_id}"}
        p = pp["plants"].get(pid)
        if not p:
            return 404, {"plant_id": pid, "error": "no_data",
                         "known_plants": sorted(pp["plants"].keys())}
        obj = dict(p)
        obj.update({
            "service": SERVICE, "dataset": DATASET, "plant_id": pid,
            "granularity": "plant",
            "reservoir_at": pp.get("reservoir", {}).get("latest"),
            "as_of": AS_OF, "updated_at": _state["updated_at"],
            "source": "ENTSO-E Transparency (generation, reservoir storage); "
                      "eHYD/OWF (downstream gauges, flow & sediment trends)",
            "license": LICENSE,
            "notes": "gen = daily turbined MWh (last 365 d); gw/pegel = downstream "
                     "monitoring points along the river network with share of daily "
                     "variation explained by this plant's releases. Correlation, "
                     "not proven causation.",
        })
        return 200, obj
    if path.startswith("/llm/gauge/"):
        hzb = urllib.parse.unquote(path[len("/llm/gauge/"):]).strip("/")
        if hzb.endswith(".json"):
            hzb = hzb[:-5]
        _load()
        gp = _state.get("gauge_profiles")
        if not gp:
            return 404, {"error": "no_gauge_profiles"}
        if not hzb:
            return 200, {"gauges": sorted(gp["stations"].keys()),
                         "generated": gp.get("generated"),
                         "endpoint": "/llm/gauge/{hzb_number}"}
        g = gp["stations"].get(hzb)
        if not g:
            return 404, {"hzb": hzb, "error": "no_data"}
        obj = dict(g)
        obj.update({
            "service": SERVICE, "dataset": DATASET, "hzb": hzb,
            "granularity": "river_gauge",
            "as_of": AS_OF, "updated_at": _state["updated_at"],
            "source": gp.get("source"), "license": LICENSE,
            "notes": "annual = annual mean flow m3/s (OWF yearbook); live = daily "
                     "flow this year (eHYD, refreshed daily); sed = suspended "
                     "sediment t/day and long-term trend percent.",
        })
        return 200, obj
    if path.startswith("/llm/point/"):
        pid = urllib.parse.unquote(path[len("/llm/point/"):]).strip("/")
        if pid.endswith(".json"):
            pid = pid[:-5]
        if not pid:
            return 400, {"error": "missing point id"}
        _load()
        hit = _state["point_by_id"].get(pid)
        if not hit:
            return 404, {"point_id": pid, "error": "no_data"}
        kg, p = hit
        obj = dict(p)
        obj.update({
            "service": SERVICE, "dataset": DATASET,
            "kg_code": kg,
            "gemeinde_code": _state["kg2gem"].get(kg),
            "granularity": "point",
            "as_of": AS_OF, "updated_at": _state["updated_at"],
            "source": SOURCE, "license": LICENSE,
            "unit_glossary": {k: v for k, v in POINT_GLOSSARY.items()
                              if k in p.get("metrics", {})},
        })
        return 200, obj
    if path.startswith("/llm/kg/"):
        kg = path[len("/llm/kg/"):]
        if kg.endswith(".json"):
            kg = kg[:-5]
        kg = kg.strip("/")
        if not kg:
            return 400, {"error": "missing kg_code"}
        obj, status = _payload_for_kg(kg)
        return status, _slim(obj, query)
    extra = llm_extra.handle(path, query, sys.modules[__name__])
    if extra is not None:
        return extra
    return None

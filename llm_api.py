#!/usr/bin/env python3
"""Sibling-service integration endpoints for the Kohlschwarz cadastre ecosystem.

Implements the "Integration Spec for Sibling Data Services" published at
https://cadastre-process-api.exe.xyz/api/v1/docs/llm.txt?section=integration

This dataset (Austrian drought / water-stress risk) is per-municipality
(Gemeinde), so every endpoint reports granularity="gemeinde": for a requested
kg_code we map UP to its gemeinde_code (via the canonical /api/v1/lookup,
pre-resolved into data/kg_to_gemeinde.json) and return the Gemeinde-level block.
Every KG inside a Gemeinde returns the same metrics.

Endpoints:
  GET /llm/kg/{kg_code}            per-KG payload (alias: .json)
  GET /llm/kgs?codes=a,b,c         batch (<=500) of per-KG payloads
  GET /llm/manifest.json           coverage + schema descriptor
  GET /llm/covered_kgs.json        array of every kg_code we can answer
"""
import json
import os
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "web", "data")

SERVICE = "groundwater-at"
DATASET = "Austrian drought & water-stress risk"
SOURCE = ("Copernicus EDO CDI, eHYD groundwater & surface-flow stations, "
          "GeoSphere precipitation, WISE water quality, INSPIRE soil, e-control hydro")
LICENSE = "CC-BY-4.0"
# Validity date of the headline figures: latest EDO drought year we ingest.
AS_OF = "2023-12-31"

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

_state = {"loaded": False}


def _load():
    if _state["loaded"]:
        return
    munis = json.load(open(os.path.join(DATA, "municipalities.json")))
    _state["gem_by_code"] = {str(m["iso"]): m for m in munis}
    _state["kg2gem"] = json.load(open(os.path.join(DATA, "kg_to_gemeinde.json")))
    covered = json.load(open(os.path.join(DATA, "covered_kgs.json")))
    _state["covered"] = covered
    # updated_at: when the underlying data files were last recomputed.
    mtime = os.path.getmtime(os.path.join(DATA, "municipalities.json"))
    _state["updated_at"] = (datetime.datetime.utcfromtimestamp(mtime)
                            .strftime("%Y-%m-%dT%H:%M:%SZ"))
    _state["loaded"] = True


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
    kg_code = str(kg_code)
    gem_code = _state["kg2gem"].get(kg_code)
    if not gem_code:
        return {"kg_code": kg_code, "error": "no_data"}, 404
    m = _state["gem_by_code"].get(gem_code)
    if not m:
        return {"kg_code": kg_code, "error": "no_data"}, 404
    metrics = {}
    for k in METRIC_KEYS:
        if k in m and m[k] is not None:
            metrics[k] = m[k]
    return {
        "service": SERVICE,
        "dataset": DATASET,
        "kg_code": kg_code,
        "gemeinde_code": gem_code,
        "gemeinde_name": m.get("name"),
        "granularity": "gemeinde",
        "as_of": AS_OF,
        "updated_at": _state["updated_at"],
        "source": SOURCE,
        "license": LICENSE,
        "unit_glossary": UNIT_GLOSSARY,
        "metrics": metrics,
        "history": _history(m),
    }, 200


def manifest():
    _load()
    return {
        "service": SERVICE,
        "dataset": DATASET,
        "finest_granularity": "gemeinde",
        "join_keys": ["kg_code", "gemeinde_code"],
        "kg_endpoint": "/llm/kg/{kg_code}",
        "batch_endpoint": "/llm/kgs?codes={kg_code,...}",
        "metrics_schema": METRICS_SCHEMA,
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
    if path == "/llm/kgs":
        codes = (query.get("codes", [""])[0]).strip()
        if not codes:
            return 400, {"error": "missing 'codes' query parameter"}
        code_list = [c.strip() for c in codes.split(",") if c.strip()][:500]
        results = []
        for c in code_list:
            obj, _ = _payload_for_kg(c)
            results.append(obj)
        return 200, {"results": results,
                     "meta": {"requested": len(code_list)}}
    if path.startswith("/llm/kg/"):
        kg = path[len("/llm/kg/"):]
        if kg.endswith(".json"):
            kg = kg[:-5]
        kg = kg.strip("/")
        if not kg:
            return 400, {"error": "missing kg_code"}
        obj, status = _payload_for_kg(kg)
        return status, obj
    return None

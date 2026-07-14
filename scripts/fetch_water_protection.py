#!/usr/bin/env python3
"""Fetch drinking-water protection zones (Wasserschutz-/Wasserschongebiete)
for Austrian provinces from provincial WFS/INSPIRE services, merge, simplify
and write web/data/water_protection_at.geojson (+ .gz) plus a summary JSON.

Sources (best effort; provinces that fail are skipped):
  - Oberösterreich : DORIS ArcGIS WFS (GEOJSON output, EPSG:4326)
  - Steiermark     : haleconnect WFS (Schutzgebiete + Schongebiete, GeoJSON, CRS84)
  - Tirol          : haleconnect WFS (Wasserschutzgebiete)
  - Burgenland     : haleconnect WFS (Wasserschongebiete)
  - Wien           : haleconnect WFS (INSPIRE Area Management; drinking water zones)
  - Niederösterreich: predefined INSPIRE GML download (EPSG:4258, lat/lon order)
  - Vorarlberg     : VOGIS GeoServer WFS (schutzundschongebiete, srsName=EPSG:4326)
  - Kärnten        : OGC API Features at gis.ktn.gv.at (often unreachable -> skipped)
  - Salzburg       : INSPIRE download exists but contains WFD water bodies, not
                     protection zones -> skipped
"""
import gzip
import json
import re
import sys
import urllib.request
import urllib.parse
from pathlib import Path

from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely.ops import transform as shp_transform
from shapely.validation import make_valid
import pyproj

ROOT = Path(__file__).resolve().parent.parent
OUT_GEOJSON = ROOT / "web/data/water_protection_at.geojson"
OUT_SUMMARY = ROOT / "data/water_protection_summary.json"

SIMPLIFY_TOL = 0.0005  # degrees (~50 m)
PRECISION = 5

UA = {"User-Agent": "austria-drought-map/1.0 (data pipeline)"}

TO_LAEA = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform


def http_get(url, timeout=180):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def zone_type_from_text(text, default_kind):
    """Derive zone_type like 'Schutzgebiet (Zone II)' from a name string."""
    kind = default_kind
    t = text or ""
    tl = t.lower()
    if "schongebiet" in tl:
        kind = "Schongebiet"
    elif "schutzgebiet" in tl or "schutzzone" in tl:
        kind = "Schutzgebiet"
    m = re.search(r"(?:schutz)?zone\s*(III|II|I)\b", t, re.I)
    if not m:
        m = re.search(r"zone\s*(3|2|1)\b", tl)
    if m:
        z = m.group(1).upper().replace("1", "I").replace("2", "II").replace("3", "III")
        return f"{kind} (Zone {z})"
    return kind


def polygonal(geom):
    """Return polygonal part of a shapely geometry or None."""
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    if geom.geom_type == "GeometryCollection":
        polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if polys:
            return MultiPolygon(
                [p for g in polys for p in (g.geoms if g.geom_type == "MultiPolygon" else [g])]
            )
    return None


def add_feature(out, province, name, zone_type, geom):
    geom = polygonal(geom)
    if geom is None:
        return
    geom = make_valid(geom)
    geom = polygonal(geom)
    if geom is None or geom.is_empty:
        return
    out.append({"province": province, "name": name, "zone_type": zone_type, "geom": geom})


# ---------------------------------------------------------------- haleconnect
def fetch_haleconnect(base, province, default_kind, out, page=1000):
    """Page through a haleconnect INSPIRE WFS (am:ManagementRestrictionOrRegulationZone)."""
    start = 0
    n_before = len(out)
    while True:
        url = (
            f"{base}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
            f"&TYPENAMES=am:ManagementRestrictionOrRegulationZone"
            f"&OUTPUTFORMAT=application/json&COUNT={page}&STARTINDEX={start}"
        )
        data = json.loads(http_get(url))
        feats = data.get("features", [])
        for f in feats:
            g = f.get("geometry")
            if not g or g.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            p = f.get("properties", {})
            text = p.get("text") or ""
            # Some services (e.g. Steiermark) expose the competent-authority
            # postal address in 'text' – ignore those.
            if text.endswith(", Austria"):
                text = ""
            name = (
                text
                or p.get("name")
                or p.get("thematicId|ThematicIdentifier|identifier")
                or p.get("localId")
                or p.get("gml_id")
                or ""
            )
            zt = zone_type_from_text(name, default_kind)
            add_feature(out, province, name, zt, shape(g))
        if len(feats) < page:
            break
        start += page
    print(f"  {province}: +{len(out)-n_before} polygon features", flush=True)


# ---------------------------------------------------------------- DORIS (OÖ)
def fetch_ooe(out, page=1000):
    base = "https://ags.doris.at/arcgis/services/HVD/MapServer/WFSServer"
    start = 0
    n_before = len(out)
    while True:
        url = (
            f"{base}?service=WFS&version=2.0.0&request=GetFeature"
            f"&typeNames=HVD:Wasserschutzgebiete&outputFormat=GEOJSON"
            f"&count={page}&startIndex={start}"
        )
        data = json.loads(http_get(url))
        crs = (data.get("crs") or {}).get("properties", {}).get("name", "EPSG:4326")
        tf = None
        if "4326" not in crs and "CRS84" not in crs:
            epsg = crs.split(":")[-1]
            tf = pyproj.Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True).transform
        feats = data.get("features", [])
        for f in feats:
            g = f.get("geometry")
            if not g or g.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            p = f.get("properties", {})
            name = p.get("Bezeichnung") or p.get("Name") or p.get("WIS_ID") or ""
            kind = "Schongebiet" if (p.get("Typ") or "").lower().startswith("schon") else "Schutzgebiet"
            zt = zone_type_from_text(p.get("Zonenart") or p.get("Name") or "", kind)
            geom = shape(g)
            if tf:
                geom = shp_transform(tf, geom)
            add_feature(out, "Oberösterreich", name, zt, geom)
        if len(feats) < page:
            break
        start += page
    print(f"  Oberösterreich: +{len(out)-n_before} polygon features", flush=True)


# ---------------------------------------------------------------- VOGIS (Vlbg)
def fetch_vorarlberg(out, page=1000):
    base = "https://vogis.cnv.at/geoserver/vogis/ows"
    start = 0
    n_before = len(out)
    while True:
        url = (
            f"{base}?service=WFS&version=2.0.0&request=GetFeature"
            f"&typeNames=vogis:schutzundschongebiete&outputFormat=application/json"
            f"&srsName=EPSG:4326&count={page}&startIndex={start}"
        )
        data = json.loads(http_get(url))
        feats = data.get("features", [])
        for f in feats:
            g = f.get("geometry")
            if not g or g.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            p = f.get("properties", {})
            sub = p.get("anlagensub") or ""
            gem = p.get("gemeinde") or ""
            name = " - ".join(x for x in (gem, sub) if x) or p.get("wis_id") or ""
            kind = "Schongebiet" if "schon" in sub.lower() else "Schutzgebiet"
            zt = zone_type_from_text(sub, kind)
            add_feature(out, "Vorarlberg", name, zt, shape(g))
        if len(feats) < page:
            break
        start += page
    print(f"  Vorarlberg: +{len(out)-n_before} polygon features", flush=True)


# ---------------------------------------------------------------- NÖ GML
NOE_GML_URL = (
    "https://geo.noe.gv.at/inspire-download/c901c0c6-4247-459a-b547-02fd134c5d22/"
    "c901c0c6-4247-459a-b547-02fd134c5d22_GML_4258.gml"
)


def _rings_from_patch(patch_xml):
    """Extract (exterior, [interiors]) coordinate rings from a PolygonPatch/Polygon XML
    chunk with lat/lon posLists (EPSG:4258 urn axis order)."""
    def parse_poslist(txt):
        vals = [float(v) for v in txt.split()]
        return [(vals[i + 1], vals[i]) for i in range(0, len(vals) - 1, 2)]  # lon,lat

    ext = None
    ints = []
    for m in re.finditer(
        r"<gml:(exterior|interior)>.*?<gml:posList[^>]*>([^<]+)</gml:posList>.*?</gml:\1>",
        patch_xml,
        re.S,
    ):
        ring = parse_poslist(m.group(2))
        if m.group(1) == "exterior":
            ext = ring
        else:
            ints.append(ring)
    return ext, ints


def fetch_noe(out):
    n_before = len(out)
    xml = http_get(NOE_GML_URL, timeout=300).decode("utf-8", "replace")
    for m in re.finditer(
        r"<am:ManagementRestrictionOrRegulationZone\b.*?</am:ManagementRestrictionOrRegulationZone>",
        xml,
        re.S,
    ):
        blk = m.group(0)
        zt_m = re.search(r'<am:zoneType xlink:href="([^"]+)"', blk)
        if not zt_m or "drinkingWaterProtectionArea" not in zt_m.group(1):
            continue
        name_m = re.search(r"<gn:text>([^<]*)</gn:text>", blk)
        name = name_m.group(1) if name_m else ""
        if not name:
            lid = re.search(r"<base:localId>([^<]*)</base:localId>", blk)
            name = lid.group(1) if lid else ""
        kind = "Schongebiet" if "schongebiet" in name.lower() else "Schutzgebiet"
        zt = zone_type_from_text(name, kind)
        polys = []
        for pm in re.finditer(r"<gml:PolygonPatch>.*?</gml:PolygonPatch>", blk, re.S):
            ext, ints = _rings_from_patch(pm.group(0))
            if ext and len(ext) >= 4:
                try:
                    polys.append(Polygon(ext, ints))
                except Exception:
                    pass
        if not polys:
            continue
        geom = polys[0] if len(polys) == 1 else MultiPolygon(polys)
        add_feature(out, "Niederösterreich", name, zt, geom)
    print(f"  Niederösterreich: +{len(out)-n_before} polygon features", flush=True)


# ---------------------------------------------------------------- Kärnten OGC API
def fetch_kaernten(out, page=1000):
    base = (
        "https://gis.ktn.gv.at/api/features/inspire/v1/collections/"
        "AT.0019.ba27e261-f505-49b7-94ed-6b2845744bcf/items"
    )
    n_before = len(out)
    start = 0
    while True:
        url = f"{base}?limit={page}&offset={start}&f=json"
        data = json.loads(http_get(url, timeout=60))
        feats = data.get("features", [])
        for f in feats:
            g = f.get("geometry")
            if not g or g.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            p = f.get("properties", {})
            name = p.get("text") or p.get("name") or p.get("localId") or ""
            zt = zone_type_from_text(str(name), "Schutzgebiet")
            add_feature(out, "Kärnten", name, zt, shape(g))
        if len(feats) < page:
            break
        start += page
    print(f"  Kärnten: +{len(out)-n_before} polygon features", flush=True)


# ---------------------------------------------------------------- Wien filter
def fetch_wien(out):
    """Wien Area Management contains multiple zone kinds; keep drinking water ones."""
    tmp = []
    fetch_haleconnect(
        "https://haleconnect.com/ows/services/org.670.e1904c37-792a-494f-8099-8a1a3511b20e_wfs",
        "Wien",
        "Schutzgebiet",
        tmp,
    )
    kept = 0
    for f in tmp:
        nm = (f["name"] or "").lower()
        if "schutzgebiet" in nm or "schutzzone" in nm or "schongebiet" in nm or "brunnen" in nm or "wasser" in nm:
            out.append(f)
            kept += 1
    print(f"  Wien: kept {kept}/{len(tmp)} drinking-water features", flush=True)


# ---------------------------------------------------------------- main
def round_coords(obj, nd=PRECISION):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], float):
            return [round(v, nd) for v in obj]
        return [round_coords(v, nd) for v in obj]
    return obj


def main():
    feats = []
    sources = [
        ("Oberösterreich (DORIS WFS)", lambda: fetch_ooe(feats)),
        (
            "Steiermark Schutzgebiete",
            lambda: fetch_haleconnect(
                "https://haleconnect.com/ows/services/org.926.42e8a025-5671-46fd-ad40-1c05d9c64fc5_wfs",
                "Steiermark",
                "Schutzgebiet",
                feats,
            ),
        ),
        (
            "Steiermark Schongebiete",
            lambda: fetch_haleconnect(
                "https://haleconnect.com/ows/services/org.926.22a7159e-4350-4b1f-b38f-fefa46b0a8b7_wfs",
                "Steiermark",
                "Schongebiet",
                feats,
            ),
        ),
        (
            "Tirol Wasserschutzgebiete",
            lambda: fetch_haleconnect(
                "https://haleconnect.com/ows/services/org.892.0b200b21-c24f-4e29-aa7f-9f5bde2ca228_wfs",
                "Tirol",
                "Schutzgebiet",
                feats,
            ),
        ),
        (
            "Burgenland Schongebiete",
            lambda: fetch_haleconnect(
                "https://haleconnect.com/ows/services/org.868.bad5516a-311f-4bc8-aaae-f41772089eeb_wfs",
                "Burgenland",
                "Schongebiet",
                feats,
            ),
        ),
        ("Wien Area Management", lambda: fetch_wien(feats)),
        ("Niederösterreich INSPIRE GML", lambda: fetch_noe(feats)),
        ("Vorarlberg VOGIS", lambda: fetch_vorarlberg(feats)),
        ("Kärnten OGC API", lambda: fetch_kaernten(feats)),
    ]
    ok, failed = [], []
    for label, fn in sources:
        print(f"Fetching {label} ...", flush=True)
        try:
            fn()
            ok.append(label)
        except Exception as e:
            print(f"  FAILED {label}: {type(e).__name__}: {e}", flush=True)
            failed.append(label)

    # simplify + serialize
    out_features = []
    summary = {}
    for f in feats:
        geom = f["geom"].simplify(SIMPLIFY_TOL, preserve_topology=True)
        geom = polygonal(make_valid(geom))
        if geom is None or geom.is_empty:
            continue
        area_km2 = shp_transform(TO_LAEA, f["geom"]).area / 1e6
        s = summary.setdefault(f["province"], {"features": 0, "area_km2": 0.0})
        s["features"] += 1
        s["area_km2"] += area_km2
        gj = mapping(geom)
        gj = {"type": gj["type"], "coordinates": round_coords(gj["coordinates"])}
        out_features.append(
            {
                "type": "Feature",
                "properties": {
                    "province": f["province"],
                    "name": f["name"],
                    "zone_type": f["zone_type"],
                },
                "geometry": gj,
            }
        )

    fc = {"type": "FeatureCollection", "features": out_features}
    OUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(fc, ensure_ascii=False, separators=(",", ":"))
    OUT_GEOJSON.write_text(txt, encoding="utf-8")
    with gzip.open(str(OUT_GEOJSON) + ".gz", "wt", encoding="utf-8") as fh:
        fh.write(txt)

    for s in summary.values():
        s["area_km2"] = round(s["area_km2"], 1)
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text(
        json.dumps(
            {
                "total_features": len(out_features),
                "provinces": summary,
                "sources_ok": ok,
                "sources_failed": failed,
                "simplify_tolerance_deg": SIMPLIFY_TOL,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Wrote {OUT_GEOJSON} ({len(txt)/1e6:.1f} MB), features={len(out_features)}")


if __name__ == "__main__":
    main()

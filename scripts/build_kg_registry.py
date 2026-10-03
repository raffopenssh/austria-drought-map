#!/usr/bin/env python3
"""Build web/data/kg_registry.json: every Austrian KG with name, gemeinde_code,
centroid (bbox center) and bbox, from the canonical cadastre API.

Used by the frontend for KG search/click resolution (bbox prefilter, exact
containment via cadastre POST /spatial/points) and by build_gw_index.py for
per-KG model evaluation points.
"""
import gzip, json, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = ("https://umfeld-at.exe.xyz/api/v1/spatial/kgs"
       "?west=9.4&south=46.3&east=17.2&north=49.1&limit=20000"
       "&fields=kg_code,kg_name,gemeinde_code,bbox")

def main():
    with urllib.request.urlopen(URL, timeout=120) as r:
        kgs = json.load(r)["data"]["kgs"]
    out = {}
    for k in kgs:
        b = k["bbox"]
        out[k["kg_code"]] = {
            "n": k["kg_name"], "g": k["gemeinde_code"],
            "lat": round((b["min_lat"] + b["max_lat"]) / 2, 5),
            "lon": round((b["min_lon"] + b["max_lon"]) / 2, 5),
            "bb": [round(b["min_lon"], 4), round(b["min_lat"], 4),
                   round(b["max_lon"], 4), round(b["max_lat"], 4)],
        }
    blob = json.dumps(out, separators=(",", ":"))
    (ROOT / "web/data/kg_registry.json").write_text(blob)
    with gzip.open(ROOT / "web/data/kg_registry.json.gz", "wt") as f:
        f.write(blob)
    print(f"{len(out)} KGs")

if __name__ == "__main__":
    main()

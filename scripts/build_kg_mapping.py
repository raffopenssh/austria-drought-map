#!/usr/bin/env python3
# NOTE (2026-10): cadastre-process-api.exe.xyz was replaced by umfeld-at.exe.xyz,
# which serves NO cadastre; /lookup still works but this crawl is kept only for
# provenance of the committed web/data outputs; re-running it will fail.
# Point->KG is now resolved via /api/v1/search/municipalities + local kg_registry.
"""Build canonical kg_code -> gemeinde_code mapping by crawling the cadastre
EDM lookup (the shared source of truth) once for every Gemeinde we cover.
Output: web/data/kg_to_gemeinde.json  and  web/data/covered_kgs.json
"""
import json, os, sys, time, urllib.request, urllib.error

BASE = "https://umfeld-at.exe.xyz/api/v1/lookup"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "web", "data")

def lookup_kgs(gem_code):
    url = f"{BASE}?q={gem_code}&type=kg&limit=500"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                d = json.load(r)
            return d.get("data", [])
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                time.sleep(1.5 * (attempt + 1)); continue
            raise
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return []

def main():
    munis = json.load(open(os.path.join(DATA, "municipalities.json")))
    gem_codes = sorted({str(m["iso"]) for m in munis})
    kg2gem = {}
    covered_gem = set()
    for i, g in enumerate(gem_codes):
        kgs = lookup_kgs(g)
        for k in kgs:
            kc = str(k.get("kg_code") or k.get("code"))
            gc = str(k.get("gemeinde_code") or g)
            # Only map KGs whose gemeinde we actually have data for
            kg2gem[kc] = gc
            covered_gem.add(gc)
        if (i + 1) % 100 == 0 or i + 1 == len(gem_codes):
            print(f"  {i+1}/{len(gem_codes)} gemeinden, {len(kg2gem)} KGs", flush=True)
        time.sleep(0.03)
    # Keep only KGs whose gemeinde_code is one we have data for
    have = {str(m["iso"]) for m in munis}
    kg2gem = {k: v for k, v in kg2gem.items() if v in have}
    covered = sorted(kg2gem.keys())
    json.dump(kg2gem, open(os.path.join(DATA, "kg_to_gemeinde.json"), "w"))
    json.dump(covered, open(os.path.join(DATA, "covered_kgs.json"), "w"))
    print(f"Wrote {len(kg2gem)} KG mappings across {len(set(kg2gem.values()))} gemeinden")

if __name__ == "__main__":
    main()

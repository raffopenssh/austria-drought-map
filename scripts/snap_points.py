#!/usr/bin/env python3
"""Snap ALL of this app's point datasets to the official cadastre in ONE crawl.

Per the cadastre 'Integration Spec for Sibling Data Services' (granularity=point),
point datasets must be snapped once via POST /api/v1/spatial/points (exact
point-in-polygon) and stored with their kg_code (+ parcel_id when confident).

We snap three datasets together so each KG's geometry is only loaded once on the
cadastre side (and we sort points spatially so same-KG points cluster into the
same/adjacent requests, maximising their 30-min server cache):

  gw : groundwater stations          (web/data/gw_stations_trends.json)
  pp : hydro power plants            (web/data/powerplants.json)
  wq : WISE water-quality sites      (web/data/wise_monitoring_sites.json)

IDs are namespaced "<src>:<localid>". Output (resumable):
  web/data/point_snap.json  { "gw:374793": {matched,kg_code,parcel_id}, ... }

Drought risk & the municipal water-quality roll-up are already per-Gemeinde and
need NO cadastre calls — they are served straight from municipalities.json.
"""
import json, os, time, urllib.request, urllib.error

URL = "https://cadastre-process-api.exe.xyz/api/v1/spatial/points"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "web", "data")
SNAP = os.path.join(DATA, "point_snap.json")
LEGACY_GW = os.path.join(DATA, "gw_station_snap.json")

CHUNK = 20            # points per request
SLEEP_BETWEEN = 3.0   # pause between successful chunks (be a good neighbour)


def collect_points():
    pts = []
    # groundwater stations
    for s in json.load(open(os.path.join(DATA, "gw_stations_trends.json"))):
        pts.append(("gw:" + str(s["id"]), s["lon"], s["lat"]))
    # power plants (no native id -> synthesise a stable index id)
    for i, p in enumerate(json.load(open(os.path.join(DATA, "powerplants.json")))):
        pts.append(("pp:" + str(i), p["lon"], p["lat"]))
    # WISE water-quality monitoring sites (GeoJSON FeatureCollection)
    wq = json.load(open(os.path.join(DATA, "wise_monitoring_sites.json")))
    for f in wq["features"]:
        c = (f.get("geometry") or {}).get("coordinates")
        pid = (f.get("properties") or {}).get("id")
        if not c or pid is None:
            continue
        pts.append(("wq:" + str(pid), c[0], c[1]))
    return pts


def post(points):
    body = json.dumps({"points": points}).encode()
    for attempt in range(6):
        try:
            req = urllib.request.Request(URL, data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            wait = min(60, 5 * (2 ** attempt))
            print(f"   retry {attempt+1} after error: {e} (sleep {wait}s)", flush=True)
            time.sleep(wait)
    return None


def main():
    snap = json.load(open(SNAP)) if os.path.exists(SNAP) else {}
    # Migrate prior gw-only work (keyed by bare station id) into namespaced keys.
    if os.path.exists(LEGACY_GW):
        for sid, v in json.load(open(LEGACY_GW)).items():
            snap.setdefault("gw:" + str(sid), v)

    allpts = collect_points()
    # Sort spatially (rounded grid) so same-KG points fall in nearby requests.
    allpts.sort(key=lambda t: (round(t[2], 2), round(t[1], 2)))
    todo = [t for t in allpts if t[0] not in snap]
    by_src = {}
    for pid, _, _ in todo:
        by_src[pid.split(":")[0]] = by_src.get(pid.split(":")[0], 0) + 1
    print(f"{len(allpts)} total points, {len(snap)} already snapped, "
          f"{len(todo)} to do {by_src}", flush=True)

    for i in range(0, len(todo), CHUNK):
        chunk = todo[i:i+CHUNK]
        pts = [{"lon": lon, "lat": lat, "id": pid} for pid, lon, lat in chunk]
        r = post(pts)
        if r is None:
            print("   giving up on this chunk, will resume next run", flush=True)
            continue
        for res in r["results"]:
            parcel = res.get("parcel") or {}
            snap[str(res["id"])] = {
                "matched": bool(res.get("matched")),
                "kg_code": res.get("kg_code"),
                "parcel_id": parcel.get("parcel_id"),
            }
        json.dump(snap, open(SNAP, "w"))
        done = min(i+CHUNK, len(todo))
        m = sum(1 for v in snap.values() if v.get("kg_code"))
        print(f"  {done}/{len(todo)} this run, {m} total with kg_code "
              f"({r['meta'].get('matched')}/{r['meta'].get('point_count')} "
              f"in {r['meta'].get('duration_ms')}ms)", flush=True)
        time.sleep(SLEEP_BETWEEN)

    m = sum(1 for v in snap.values() if v.get("kg_code"))
    pc = sum(1 for v in snap.values() if v.get("parcel_id"))
    print(f"DONE: {len(snap)} points, {m} with kg_code, {pc} with parcel_id")


if __name__ == "__main__":
    main()

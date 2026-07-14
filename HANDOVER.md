# GW Power — rebuild COMPLETE (2026-07-14)

Live: https://groundwater-at.exe.xyz:8000 (systemd `drought-map`).
The rebuild described in earlier revisions of this file is finished:

- web/index.html + web/app.js: the GW Power app (GWI choropleth, zoom-adaptive
  station dots, KG tap -> cadastre-resolved detail modal w/ component bars,
  EDO bars, nearby-station lists; GW & nitrate station timelines; local +
  cadastre search incl. address_osm; ?v/kg/st/no3/gem share links; Methods
  modal). Old app: web/explore.html.
- Model: scripts/build_gw_index.py (per-KG GWI; Vienna/merged-Gemeinde KGs
  reassigned to nearest municipality -> full 2117/2117 choropleth coverage).
- API (llm_api.py): KG-granular gwi_* metrics, nitrate_station points with
  annual history, GET /llm/point/{id}, manifest finest_granularity=kg.
  Docs: web/llm.txt, README.md.
- Nitrate point snapping DONE (point_snap.json committed, no3: namespace).
- Hydropower downstream influence (2026-07-14): scripts/entsoe_plants.py
  (22 ENTSO-E A73 plants w/ tailrace coords), build_plant_downstream.py
  (directed OSM waterway walk, needs data/osm/waterways.geojsonseq from the
  pbf via osmium export), analyze_plant_downstream.py (per plant-station pair:
  partial R2 of daily releases over precip baseline, F-test, 60d placebo;
  A73 per-unit series where live in 2026, else downscaled from national
  aggregate via per-plant 2023-24 calibration). Output
  web/data/plant_influence.json -> "Hydropower influence" section in KG &
  GW-station modals (app.js), hydropower_influence in /llm/kg payloads,
  Methods modal section. Informational only, NOT a GWI component (shared
  basin hydrology; downscaled plants share the national signal shape).
  44 sig GW links, 48 sig gauge links; strongest: Ziller cascade (partial
  R2 up to 0.33 GW / 0.79 river stage), Salzach/Kaprun, Danube cascade.

Re-run order after data updates: fetch_* scripts -> build_gw_index.py ->
snap_points.py (resumable) -> systemctl restart drought-map (API caches
in-process). Cache-bust web/index.html's app.js?v=N when editing app.js.

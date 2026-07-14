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

Re-run order after data updates: fetch_* scripts -> build_gw_index.py ->
snap_points.py (resumable) -> systemctl restart drought-map (API caches
in-process). Cache-bust web/index.html's app.js?v=N when editing app.js.

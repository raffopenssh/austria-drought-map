# Handover — 2026-07-14 (GW Power rebuild, mid-flight)

Live app: https://groundwater-at.exe.xyz:8000 (systemd `drought-map`, python3 server.py 8000, serves web/).
Repo: /home/exedev/austria-drought-map. Commit 8f72c6d = this WIP state.

## User's brief (verbatim intent)
Make this the REAL "GW Power" app: how the nation manages groundwater
quantity & quality. ONE choropleth layer + subtle station dots. Sound model.
Users tap a KG and see GW stations, EDO drought history, pollution (nitrate),
etc. — with the nice timelines the old app already has for groundwater.
Search by address/municipality must be nice and sound. API exposes ALL data
incl. model values per KG and Gemeinde, following the sibling spec at
https://cadastre-process-api.exe.xyz/api/v1/docs/llm.txt?section=integration
(name lookup like cadastre). Link sharing must work; Methods must be
comprehensive & transparent. Good on desktop AND mobile.

## Done this session (committed)
1. **Nitrate finished**: `scripts/fetch_wise_nitrate.py` builds
   `web/data/nitrate_stations.json(.gz)` — 2,250 AT GW stations, 1992–2024,
   per-station `annual` {year: mean}, latest, Theil–Sen trend. Source CSVs
   committed under data/water_quality/ (regenerate: see --refetch header).
2. **KG registry**: `scripts/build_kg_registry.py` →
   `web/data/kg_registry.json(.gz)` — all 7,850 KGs {code: {n(ame),
   g(emeinde_code), lat, lon, bb(ox)}} from cadastre API.
3. **THE MODEL — Groundwater Status Index (GWI)**: `scripts/build_gw_index.py`
   → `web/data/gw_index_kg.json(.gz)` (per KG: i=gwi 0-1, c=category
   good/watch/stressed, q_* sub-risks, raw gw_trend/gw_div/no3, n_* counts,
   est flag) and merges gwi_* into municipalities.json +
   municipalities_risk.geojson(.gz) (Gemeinde mean) for the choropleth.
   Weights: trend .35 (clamp(-t/0.5 m/dec)), divergence .15 (clamp(-d/1.5σ)),
   nitrate .25 (latest/50 mg/L, stations reporting ≥2015), WFD wq_risk .10
   (only where GW bodies monitored), EDO CDI .15 (mean/2). Weights
   renormalized over available components. Categories <0.30/<0.50/≥.
   Calibrated: ~28% good / 40% watch / 31% stressed. Re-run after data changes.
4. **Old app preserved** as web/explore.html (all layers still work there;
   linked from new footer as "Advanced explorer").
5. **web/index.html REWRITTEN from scratch — ONLY ~278 lines done: head,
   CSS, body scaffolding (map-first, floating topbar w/ search, legend w/
   2 station toggles, footbar). NO JavaScript yet. THIS IS THE MAIN TODO.**
6. `scripts/snap_points.py` extended with `no3:` namespace; snapping run
   was in tmux `snap` — CHECK `tail logs/snap_no3.log`; if not "DONE",
   rerun `python3 scripts/snap_points.py` (resumable), then commit
   web/data/point_snap.json.

## TODO (in order)
1. **Finish web/index.html JS** (~500-700 lines, keep it lean; Leaflet +
   Chart.js already in head; dark carto tiles like explore.html):
   - Load municipalities_risk.geojson → ONE choropleth colored by
     `gwi` (gradient #1a9850→#d73027, grey where missing), tooltip
     name + gwi + category.
   - Subtle station dots (small, muted, canvas renderer): GW stations
     (gw_stations_slim.json, on by default) + nitrate stations (toggle).
     Click → station modal with the SAME nice Chart.js timeline the old app
     has (see explore.html showGWStationDetailModal/loadGwChartData;
     gw_stations_trends.json has annual_data; nitrate has `annual`).
   - **Map click → KG detail modal**: resolve click → KG via kg_registry
     bbox prefilter + POST cadastre /api/v1/spatial/points (exact, 1 point)
     fallback nearest-centroid. Modal shows: KG name, Gemeinde, GWI badge +
     component bars (data from gw_index_kg.json), nearby GW station list
     (clickable → timeline), nitrate stations, EDO yearly bar chart
     (edo_yearly in municipalities.json of the Gemeinde — reuse explore.html
     rendering), link "API: /llm/kg/{code}".
   - **Search**: local index over Gemeinden (municipalities.json) + KGs
     (kg_registry) + debounced remote cadastre /api/v1/lookup (plz,
     ortschaft) and /search/address_osm for addresses. Selecting → flyTo +
     open KG/Gemeinde modal.
   - **Share links**: ?v=lat,lng,z&kg=CODE&gem=CODE&st=STATIONID&no3=ID —
     restore on load (open modal). Share buttons: header + inside modals.
   - **Methods modal** (#methods-link): comprehensive & honest — document
     GWI formula/weights/scales/calibration, all sources (eHYD, EEA WISE-6
     Waterbase ICM 2026, WISE WFD 2022, Copernicus EDO, NASA POWER, BEV
     cadastre), IDW radii 12.5/30km, `est` flag meaning, limitations
     (interpolation, coarse precip grid, WFD status is water-body not
     station, nitrate LOQ/2 convention). Much of this text exists in
     explore.html sources modal + build_gw_index.py docstring.
   - Mobile: already CSS'd (test at 390px); modals full-width, legend compact.
2. **API (llm_api.py)**: add GWI to per-KG payloads — now KG-granular!
   Load gw_index_kg.json; per-KG metrics = gwi + components (granularity
   "kg" for these, keep gemeinde block too); add `no3:` points w/ annual
   history from nitrate_stations.json + point_snap.json; update manifest
   (finest_granularity mixed/kg), unit glossary, README §API. Server passes
   /llm/* through (server.py). Also worth adding: /llm/gemeinde/{name}
   already does name lookup — verify it, and mention gwi there too.
3. **Verify + polish**: browser-test desktop 1400px & mobile 390px,
   screenshot, check share URL round-trip, modal deep links, search for
   an address ("Stephansplatz 1 Wien"), KG tap in rural area.
4. Update README (rebrand GW Power, model section), commit in sensible
   chunks, restart `sudo systemctl restart drought-map` (server caches
   llm_api data in-process).

## Gotchas
- git hooks forbid `git add -A` — add files explicitly.
- municipalities.json keyed by name in geojson matching; iso = gemeinde_code.
- kg_to_gemeinde.json exists (7,545 KGs) but kg_registry.json (7,850) is
  fresher/complete — prefer it, keep both consistent in llm_api.
- Big JSONs served pre-gzipped (.gz twin) by server.py automatically.
- Don't loop cadastre API per-KG (N+1); it's fine for single click lookups.
- edo_municipality_timeseries.json is 46MB, NOT in git, don't load in frontend.

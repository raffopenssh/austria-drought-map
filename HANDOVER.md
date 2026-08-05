# GW Power — rebuild COMPLETE (2026-07-14)

Real catchments (2026-08-05, DONE): the glacier/snow attribution now has a
second, independent routing built on MERIT-Hydro basins instead of the OSM
waterway snap. See the commit message of 3861810 for the full story; short form:
- data/watersheds/*.json (640 gauges) + data/flowpaths/*.json (735 glaciers)
  fetched from mghydro.com/watersheds at ~1 req/s (gitignored, a couple of
  hours to regenerate). Endpoint: GET mghydro.com/app/getwshed?task=watershed|
  flowpath&lat=&lng=&source=merit&precision=high&simplify=true -> gzipped JSON.
- Catchments validated against the official eHYD catchment size (median 0.1%,
  85% within 10%); 96 mis-snaps re-probed by fix_missnapped_watersheds.py, 22
  repaired, 60 stay flagged 'missnap' and are excluded everywhere.
- Re-run order for this branch of the pipeline: fetch_watersheds.py ->
  fix_missnapped_watersheds.py -> build_watershed_context.py; separately
  fetch_glacier_flowpaths.py -> build_merit_glacier_reaches.py; then
  analyze_watershed_cryosphere.py and restart drought-map.
- Key numbers now in Methods/README/llm.txt: 1 Apr snow store = median 7% of a
  basin's annual flow (max 84%), median basin lost 61% of its 1961-90 store;
  flow trends -2.2%/dec ice-free vs +2.1%/dec at ice>=5% (perm p<0.001); wells
  in snow-rich basins -0.13 vs -0.23 m/dec rain-fed (perm p<0.001); 4.0 km3 of
  1 Apr store already lost = ~9x annual net ice loss.
- Gotchas found the hard way: (a) mghydro's flowpath response is UNORDERED and
  linestring direction is mixed, so distance-from-ice must be Dijkstra over the
  reach graph; (b) SNOWGRID's rectangular grid is no-data outside Austria, so
  zonal means must mask on a reference grid and volumes must use the valid cell
  count -- otherwise foreign-headwater basins (Danube, Rhine, upper Inn) get
  absurd snow-vs-flow ratios; (c) json.dump writes NaN, which browsers reject:
  build_watershed_context.py cleans with allow_nan=False.
- Possible next: karst check for the 60 excluded gauges (the Altaussee/Traun
  ones are genuine karst, not a snap error); MERIT-Basins comid join to give
  every gauge its own upstream reach set; INSPIRE-Austria BEV ALS 1 m DTM for
  valley-floor aquifer widths instead of the fixed 2 km corridor.

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

Colmation hypothesis test (2026-07-14): scripts/analyze_colmation.py ->
data/colmation_analysis.json. Question: does reservoir flushing
(Stauraumspülung) silt riverbeds below storage plants and decouple river
from aquifer, explaining downstream wells' divergence (ps/res -0.9 vs
ror -0.4)? Six tests on eHYD archives (GW monthly to 2022, W/Q daily,
Schwebstoff 2008-22) + ENTSO-E A72 weekly reservoir levels 2015+
(data/reservoir_levels_weekly.csv, via austria-power.exe.xyz).
RESULT: NOT SUPPORTED.
  T1 river-GW correlation by decade (86 pairs): no decline below storage
     plants (median delta r -0.002 vs ror +0.054, perm p 0.11; levels
     actually higher below storage, r~0.52).
  T2 stage-at-median-Q trend within constant-Pegelnullpunkt segments:
     storage gauges INCISE (-1.0 cm/yr median) — bed degradation, the
     OPPOSITE of silting; ror -0.2, control -0.28 (p 0.30).
  T3 sediment-rating residuals: storage gauges show NO excess low-flow
     sediment spikes (1.2/yr vs control 2.3/yr), no rising residual trend,
     no positive correlation of weekly residuals w/ reservoir drawdown.
  T4 gauge incision rate vs nearby wells' divergence: r=0.07, p 0.93.
  T5 suspended-load 2008-22 trends: storage -0.1%, control +2.5%,
     ror -57% (retention in ror chains, consistent w/ incision literature).
  T6 matched-neighbor control: downstream wells' divergence excess over 15
     nearest non-downstream wells is only -0.06 sigma (storage) vs +0.07
     (ror), perm p 0.30 -> the ps/res -0.9 divergence is mostly REGIONAL
     (inner-alpine valleys drier vs precip history), not plant-caused.
Interpretation: sediment starvation + incision below storage plants (T2/T5)
is the documented mechanism (channel bed LOWERS, which can lower adjacent GW
base level) — colmation/silting is not. GAUGE_CLASS in the script maps the 34
Schwebstoff gauges to storage/ror/control; reuse for follow-ups.

Water-use / GWK integration (2026-07-17, DONE):
- scripts/build_gwk_context.py: Wasserschatz Oesterreichs 2021 xlsx
  (data/pop/wasserschatz_ergebnistabelle.xlsx) + INSPIRE NGP2015 GWK
  boundaries (data/gwk/gwk.zip, 138 feats, 129 match xlsx) ->
  web/data/gwk_context.json (per body: resource m3/a, sector demand
  wells+springs, Nutzungsintensitaet %, population via KG-share allocation,
  supply_lcd L/cap/d) + kg2gwk (PiP of KG centroids, 6 lakeside via
  nearest) + web/data/gwk.geojson overlay (simplified, ~360KB).
- GWI now has 6 components: q_use = clamp(intensity/40%) at w 15%
  (WEI+ convention: 20% stress, 40% severe). New weights: trend .30,
  div .10, use .15, nitrate .20, wfd .10, edo .15 -> 23/42/35
  good/watch/stressed. corr(intensity, old gwi)=0.21 so it adds signal
  (it's the only demand-pressure component; others are observed state).
- app.js v8: KG modal 'The water body underneath' (use%, resource,
  people-on-body, supply L/cap/d w/ 'likely exports' hint >300, sector
  bars); legend toggle 'Water bodies & use' (outline colour by intensity,
  taps pass through to KG); Methods + sources updated.
- llm_api.py: gwi_q_use/gwi_use_pct/gwi_gwk metrics; 'groundwater_body'
  block on KG+Gemeinde payloads (dominant body when spanning several);
  'population' block (per-year series only on Gemeinde endpoint).
- Re-run order now: fetch_* -> build_gwk_context.py (only if xlsx/GML
  change) -> build_gw_index.py -> snap_points.py -> restart drought-map.
- Possible next: 2050 scenarios (xlsx sheet '3 - Szenarienergebnisse',
  89 Szenarienregionen, guenstig/unguenstig demand+resource; region names
  are aggregations of GWK names -- 15 ambiguous matches, needs manual map
  or the report's region shapefile).

Population integration (2026-07-17, DONE except per-capita consumption):
- DONE: scripts/build_population.py -> web/data/population.json(.gz).
  Source: Statistik Austria OGD OGD_bevstandjbab2002_BevStand_{2002..2026}
  (~18MB/yr CSVs in data/pop/, gitignored; re-download loop in script docstring
  comments / see git log). Per Gemeinde: t[] total & y65[] 65+ per year,
  2026 Gebietsstand, Vienna districts + 90001 aggregate, alias map for
  merged Gemeinden (Fuerstenfeld 62280, Matrei a.B. 70370).
  Verified vs ODS upload: AT 2026 = 9,215,956. Deliberately NO gender/pyramid
  (male share 49.8+-1.5pp everywhere; 65+ share corr -0.62 with growth).
- DONE: app.js "People on this water" in KG modal (pop, growth since 2002,
  65+ share, est. household demand at 130 L/cap/d, sparkline total+65+),
  choropleth tooltip pop+growth. app.js?v=7. Tested in browser, works.
- NOT DONE: measured per-capita consumption (research findings below):
  * No measured per-Gemeinde consumption exists publicly. Best available:
  * Wasserschatz Oesterreichs (BMLUK 2021) Ergebnistabelle.xlsx COMMITTED at
    data/pop/wasserschatz_ergebnistabelle.xlsx: per GWK (129 groundwater
    bodies) water demand m3/a by sector (Wasserversorgung/Landwirtschaft
    Bewaesserung+Vieh/Industrie/Dienstleistungen, Brunnen+Quellen) +
    verfuegbare Ressource + Nutzungsintensitaet %. Sheet '5 - GWK_Wasserbedarf'
    rows 7+, sheet '4 - GWK_Ressourcen'. GWK geometry: INSPIRE GML
    https://inspire.lfrz.gv.at/000801/ds/WFDGroundWaterBody_NGP2015.zip
    (138 features incl 9 TGWK deep bodies; localId GK1xxxxx matches xlsx
    'GWK Nummer'; converted OK w/ ogr2ogr to EPSG:4326, in /tmp/pop/gwk.geojson).
    All 129 xlsx GWKs present in GML. => Plan: point-in-polygon Gemeinde/KG
    centroid -> GWK, show sector demand + Nutzungsintensitaet in modal
    ("water body context"), maybe demand/capita using summed GWK population.
  * WAVE update 2024 (unsertrinkwasser.at, in /tmp/pop/wave.txt): household
    use 130-141 L/cap/d AT average; per-dwelling-type model (EFH 231,
    Reihenhaus 179, Mehrparteien 120 L/cap/d base) driven by
    Gebaeude/Wohnungszaehlung -- OGD_rzgwz_gwz_zr_geb_GWZ_GEB_1 exists but
    only Bezirk-level (117 regions), NOT Gemeinde. So a dwelling-mix-weighted
    per-capita estimate is possible only per Bezirk.
  * Eurostat env_wat_abs: national only. WISA H2O DB: quality only, no volumes.
- Next steps if continued: build_gwk_context.py (xlsx+GML -> web/data/
  gwk_context.json keyed by GWK, plus kg/gem->GWK mapping), modal section,
  Methods update, llm_api exposure. Restart drought-map after data changes.

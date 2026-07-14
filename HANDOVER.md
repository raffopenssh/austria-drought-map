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

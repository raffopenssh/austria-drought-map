# Handover — 2026-07-14 (later session, GW-Power rebrand)

## Done

1. **Along-river gauge matching (OSM/Geofabrik)** —
   `scripts/build_along_river_matching.py`: downloads Geofabrik
   austria-latest.osm.pbf, `osmium tags-filter waterway=river,stream,canal,
   drain,ditch` → geojsonseq (338k ways), builds an undirected graph split at
   junctions, snaps 292 live Pegel + 227 live GW stations, Dijkstra to nearest
   gauge ALONG the network → `data/osm/along_river_gauges.json` (committed;
   raw pbf/geojsonseq deleted + gitignored, regenerate as per script header).
   Result: 193/227 stations matched along-river, median 9.9 km.
   `scripts/analyze_power_gw.py` now prefers along-river gauge (fallback
   straight-line); summary: 191/225 along-river, median excess partial R²
   ~6.1% vs placebo 0.2% — conclusion unchanged.

2. **App renamed to GW-Power**, UI simplified:
   - Layer chaos → 3 groups: Background choropleth (radio: Drought Risk / Water
     Quality / None), Stations (radio: Power↔GW coupling [default] / GW trends /
     Divergence / Flow / Precip / None), Overlays (checkboxes: plants, zones).
     Only one choropleth + one station legend visible at a time.
   - Header share button; **view state in URL** (?base=&st=&ov=&v=lat,lng,zoom)
     restored on load; modal deep links (?muni/?wq/?gw) still work and now
     coexist with view params.
   - Mobile: map-first layout, collapsible bottom sheet sidebar
     (#sidebar-toggle), compact legends. Detail modals (GW trends chart, EDO
     history etc.) untouched.

## Still open (both external services down, retested this session)

- **WISE nitrate**: EEA SDI datashare bulk download now returns HTTP 502
  (subagent conv c7Y7X3P tried ranged requests too); discodata SQL API
  limitations as documented below. Retry the datashare URL later.
- **LFRZ WFS** still "General error"; **Kärnten GIS** still unreachable.

---

# Handover — 2026-07-14 session

Live: https://groundwater-at.exe.xyz:8000 (systemd service `drought-map`, python3 server.py 8000)

## Done this session

1. **NASA POWER precipitation** — `scripts/fetch_nasa_power.py` fetches monthly
   PRECTOTCORR 0.5° grid for Austria 1990–2024 (single regional API call,
   ~470KB) → `data/nasa_power_precip.json`. Works reliably; re-run anytime.

2. **Precip↔GW correlation** — `scripts/analyze_precip_gw_correlation.py`
   parses eHYD monthly GW CSVs (`data/gw/Grundwasserstand-Monatsmittel/`,
   ISO-8859-1, data after "Werte:" line, comma decimals), z-scores 12-month
   rolling precip sums from nearest POWER cell vs monthly GW level, finds best
   lag 0–24 months. Output `web/data/precip_gw_correlation.json(.gz)`.
   **Result: 3,727 stations, median r=0.34, median lag 0 months,
   median 5-yr divergence −0.55σ, 70% of stations below what precip explains**
   (suggests abstraction/structural loss — good story for the map).

3. **UI stubs** — `web/index.html` has two NEW layer checkboxes without
   renderers yet: `#layer-divergence` (data ready: precip_gw_correlation.json;
   color by `divergence_5yr`, tooltip: r, lag_months, divergence) and
   `#layer-nitrate` (data NOT ready, see below). **TODO: write
   renderDivergenceLayer()/renderNitrateLayer() + change handlers + legends**,
   mirroring renderFlowLayer/renderPrecipLayer pattern (~line 1265ff).

## Blocked / open

- **WISE nitrate values** (`scripts/fetch_wise_nitrate.py`, WIP):
  EEA discodata SQL API (https://discodata.eea.europa.eu/sql) has AT GW
  nitrate 1990s–2012-ish in `[WISE_SOE].[latest].[Waterbase_T_WISE6_DisaggregatedData]`
  (code CAS_14797-55-8, GW category). Problem: **only plain `SELECT TOP n ... p=1`
  queries return; any offset pagination (p>1), GROUP BY on that table, year
  filters, LIKE filters all time out after ~30s, consistently.**
  TOP 5000 works (~2s), TOP 30000 untested-success; TOP with ORDER BY is
  rejected ("query not allowed execution").
  → Best route: download the full Waterbase ICM CSV dump instead:
  https://sdi.eea.europa.eu/datashare/s/sptXqwkQr5g7Bp5/download
  (EU-wide, large; stream-filter countryCode=AT + determinand). Then reuse the
  aggregation half of fetch_wise_nitrate.py (per-station annual means, trend,
  latest, writes web/data/nitrate_stations.json). Site coords fetch
  (Waterbase_S_WISE_SpatialObject_DerivedData, 2,918 AT sites) WORKS via SQL.
  Aggregated table `Waterbase_T_WISE6_AggregatedData` (GW, y≤2023) works for
  pesticides/metals but has NO nitrate rows; `AggregatedDataByWaterBody` GROUP BY
  times out too.

- **Kärnten protection zones**: entire *.ktn.gv.at (gis/kagis/www) is
  unreachable (connect timeout, also 522 via public proxies) — server-side
  outage, not our network. Retry later:
  `python3 scripts/fetch_water_protection.py` (Kärnten fetcher already coded,
  OGC API collection AT.0019.ba27e261-f505-49b7-94ed-6b2845744bcf).
  Feedback filed with inspire-austria (ids 2,3).

- **LFRZ real-time Pegel/GW WFS**: https://gis.lfrz.gv.at/wmsgw/?key=... returns
  "General error" ServiceExceptionReport for ALL requests (WFS+WMS, all
  versions/keys from INSPIRE metadata 6a67faa7…/e993a684…). Gateway appears
  broken. Alternatives to try: provincial hydro portals (hydro.ooe.gv.at etc.),
  ehyd.gv.at (reachable, needs scraping).

## Notes
- discodata quirk: retries don't help for the timing-out query shapes; it's
  deterministic by query shape, not load.
- `.gitignore` now excludes bulk raw downloads (data/gw, data/edo, data/nlv,
  data/owf, data/qu, *.zip, soil_permeability.gpkg, logs/,
  web/data/edo_municipality_timeseries.json 46MB — served from disk, not git).
- No tmux sessions left running.

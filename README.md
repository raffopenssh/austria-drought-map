# GW Power — the groundwater status of Austria

One map, one model: the **Groundwater Status Index (GWI)** for every one of
Austria's 7,850 Katastralgemeinden — groundwater quantity, quality (nitrate)
and drought pressure in a single transparent 0–1 index. Tap anywhere for the
KG's component breakdown, nearby station timelines (levels since 1966,
nitrate since 1992) and its EDO drought history.

## Live

**https://groundwater-at.exe.xyz:8000/** — the GW Power app
(the previous multi-layer explorer survives at `/explore.html`).

## The model (GWI)

Computed at every KG centroid by `scripts/build_gw_index.py`
(→ `web/data/gw_index_kg.json`), Gemeinde mean for the choropleth.
Weighted mean of six sub-risks, weights renormalized over available data:

| Component | Weight | Definition |
|---|---|---|
| Level trend | 30% | IDW of 10-yr eHYD level trends (≤12.5 km); risk = clamp(−trend / 0.5 m/dec) |
| Precip divergence | 10% | 5-yr level residual vs precipitation regression; risk = clamp(−div / 1.5σ) |
| Abstraction vs resource | 15% | Nutzungsintensität of the KG's groundwater body (Wasserschatz 2021, 129 GWKs); risk = clamp(intensity / 40%), WEI+ convention |
| Nitrate | 20% | IDW of latest WISE-6 annual means (stations ≥2015); risk = clamp(NO₃ / 50 mg/L) |
| WFD status | 10% | WISE WFD 2022 water-body status risk |
| Drought pressure | 15% | Copernicus EDO CDI mean 2012–23; risk = clamp(CDI / 2) |

Categories: good < 0.30 ≤ watch < 0.50 ≤ stressed (≈ 23/42/35% nationally). `est` flags KGs where the nearest-3 (≤30 km) fallback was used.
Full honesty section: the Methods modal in the app.

## Key findings

- Nation-wide: ~2,730 KGs (35%) score *stressed*, concentrated in the
  Weinviertel/Marchfeld, the Vienna basin and SE Styria
- Nitrate is the dominant quality signal: dozens of stations still exceed
  the 50 mg/L EU limit in 2024
- Mean groundwater decline ≈4.7 cm/decade, with strong east–west gradient

## Glaciers & snow — the watering cans

Informational, deliberately not a GWI component (an upstream, non-renewable
input on a different clock than abstraction or nitrate):

- **735 glaciers, 348 km²** (RGI 6.0, centroid in Austria) are losing
  **363 Mm³/yr** of ice (ASTER dh/dt, Hugonnet et al. 2021, via WGMS FoG
  2026-02) — ≈32% of Austria's entire annual groundwater abstraction, arriving
  as river water. In-situ mass balance: −0.52 m w.e./yr in the 1980s →
  **−1.78 m w.e./yr for 2021–25**.
- Ice is routed to the valleys by walking the directed OSM waterway network
  downstream from every outline; the reaches are buffered 2 km →
  **633 Gemeinden and 1,482 KGs in the glacier-fed corridor**.
- Those corridor wells trend **+0.068 m/decade above** their nearest
  non-corridor neighbours (perm p < 0.001) and glacier-fed gauges still *gain*
  flow (**+2.3%/dec** where ice ≥10% of the catchment) while ice-free gauges
  lose **2.0%/dec** — a melt subsidy that masks drought, with an expiry date.
- The bigger store is snow: SNOWGRID-CL v2 1 Apr SWE, median KG
  **−18%/decade**; national KG-centroid mean 27 mm (1961–90) → 9 mm (2011–26).
- Sparklines in the KG modal show observed history plus simple projections
  (linear snow trend to 2050; ice melt depleted with melt ∝ remaining area →
  peak water, then collapse). Scripts: `build_glacier_downstream.py`,
  `build_glacier_corridor.py`, `build_snow_reservoir.py`,
  `analyze_glacier_contribution.py`, `analyze_glacier_gw.py`.

## Real catchments — the basin above you

The attribution above routes water along the OSM waterway graph, which
mis-assigns at confluences. A second, independent pass uses the *actual*
contributing area:

- All **640 eHYD river gauges** delineated from the **MERIT-Hydro** DEM
  (MERIT-Basins) via [mghydro.com/watersheds](https://mghydro.com/watersheds/)
  (M. Heberger, [delineator](https://github.com/mheberger/delineator),
  CC BY-NC-SA), then **validated against the officially published eHYD catchment
  size**: median agreement **0.1%**, 85% within 10%. Catchments off by >25%
  (tributary outlets snapping onto the mainstem) are re-probed on a grid of
  nearby outlets and otherwise **excluded** rather than used wrong.
  **7,627 of 7,850 KGs** land inside a verified basin.
- Glacier outlines (RGI 6.0) and SNOWGRID cells are intersected with the
  *polygon*, so ice shares and snow volumes are hydrologically meaningful:
  the **1 April snowpack holds a median 7% of a basin's annual river flow**
  (p90 26%, up to **84%** in the Zemmbach headwater), and the median basin has
  lost **61%** of its 1961–90 store.
- Flow trends grade cleanly with ice: **−2.2%/dec at ice-free gauges vs
  +2.1%/dec where ice ≥ 5% of the catchment** (+3.0 pp, permutation p < 0.001);
  r = +0.27 between catchment snow trend and flow trend (458 gauges).
- Groundwater wells in **snow-rich basins** (1 Apr store ≥ 20% of annual flow)
  fall at **−0.13 m/decade vs −0.23 in rain-fed basins** (+0.102 m/dec,
  perm p < 0.001) at similar precipitation divergence — the melt/snow subsidy,
  reproduced with correct basins.
- Scale check: over 23 non-overlapping basins the 1 Apr store is **4.9 km³**
  today vs **8.9 km³** in 1961–90 — the **4.0 km³ already lost is ~9× the
  annual net glacier ice loss**. Glaciers are the symbol; snow is the reservoir.
- Downstream **MERIT-Basins flow paths** from all 735 glaciers give the
  glacier-fed reach layer (485 reaches in/near Austria, river distance from ice
  by Dijkstra over the reach graph; 1,842 KGs within 5 km of one).
- Scripts: `fetch_watersheds.py`, `fix_missnapped_watersheds.py`,
  `fetch_glacier_flowpaths.py`, `build_watershed_context.py`,
  `build_merit_glacier_reaches.py`, `analyze_watershed_cryosphere.py`.
  Caveat: MERIT is a 90 m DEM product — it knows nothing of karst, canals or
  inter-basin hydropower transfers, which is why every catchment is size-checked.

## Context

In recent years, Austrian municipalities have had to implement water rationing measures (e.g., restrictions on car washing, pool filling). While Vienna has its historic high-mountain water supply, most of Austria depends on groundwater. Climate change impacts are compounded by:

1. **Land use changes** causing increased runoff
2. **Hydropower operations** - reservoir flushing deposits silt that seals riverbeds, reducing groundwater recharge
3. **Groundwater heat pump proliferation** - receding water tables causing system failures

## Data Sources

- [eHYD Portal](https://ehyd.gv.at/) — 3,732 groundwater level stations (annual means, most 1966–2022)
- EEA Waterbase ICM 2026 (WISE-6 SoE) — 2,250 nitrate stations, 1992–2024 (`scripts/fetch_wise_nitrate.py`)
- WISE WFD 2022 — water-body chemical/ecological status
- [Copernicus EDO](https://edo.jrc.ec.europa.eu/) — Combined Drought Indicator 2012–2023
- NASA POWER — daily precipitation behind the divergence component
- Wasserschatz Österreichs (BMLRT/Umweltbundesamt 2021) — per-groundwater-body available resource & sector water demand (`data/pop/wasserschatz_ergebnistabelle.xlsx`, `scripts/build_gwk_context.py`); GWK boundaries INSPIRE WFD NGP-2015 (`data/gwk/gwk.zip`)
- Statistik Austria OGD — population 2002–2026 per Gemeinde (CC-BY-4.0, `scripts/build_population.py`)
- [umfeld-at API](https://umfeld-at.exe.xyz/) (successor of cadastre-process-api) — Gemeinde/KG register lookup, point→Gemeinde, address search. It no longer serves cadastre/PiP; KG resolution uses the committed `kg_registry.json` (built from the retired API) + nearest centroid within the Gemeinde
- [WGMS Fluctuations of Glaciers 2026-02](https://wgms.ch/) (doi:10.5904/wgms-fog-2026-02) — Austrian mass balance 1946–2025, front variations since 1803, ASTER dh/dt volume change
- [Randolph Glacier Inventory 6.0](https://www.glims.org/RGI/) region 11 — glacier outlines
- [GeoSphere Austria data.hub](https://data.hub.geosphere.at/) — SNOWGRID-CL v2 snow water equivalent, 1 km, 1961–2026
- [MERIT-Hydro / MERIT-Basins](https://www.reachhydro.org/home/params/merit-basins) via [mghydro.com/watersheds](https://mghydro.com/watersheds/) — on-demand catchment delineation & downstream flow paths (CC BY-NC-SA, non-commercial; research use)
- [INSPIRE Austria](https://inspire-austria.exe.xyz/) — dataset discovery (BEV ALS 1 m DTM/DSM tiles for future corridor work)
- [Oesterreichs Energie](https://oesterreichsenergie.at/) — power plant registry
- Austrian municipality boundaries from GeoJSON-Austria

## API

Sibling-service endpoints per the [umfeld-at docs](https://umfeld-at.exe.xyz/api/v1/docs/llm.txt), keyed on official BEV/Statistik Austria codes (5-char zero-padded strings):

- `GET /llm/kg/{kg_code}` — per Katastralgemeinde: **KG-granular GWI + components**, legacy Gemeinde metrics, snapped point observations
- `GET /llm/gemeinde/{code_or_name}` — per municipality (alias `/llm/muni/`), name lookup included
- `GET /llm/kgs?codes=...` / `GET /llm/gemeinden?codes=...` — batch (≤500)
- `GET /llm/point/{id}` — single station (`gw:336446`, `no3:ATPG90100012`, `pp:12`, `wq:AT…`) with full annual history
- `GET /llm/manifest.json`, `/llm/covered_kgs.json`, `/llm/covered_gemeinden.json`

Point categories: groundwater_station, nitrate_station, power_plant, water_quality_site — all snapped once to their KG/parcel via the cadastre. See [`web/llm.txt`](web/llm.txt).

## Share links

`?v=lat,lng,zoom` (view) plus deep links `&kg=66123` (KG modal), `&st=336446` (GW station), `&no3=ATPG90100012` (nitrate station), `&gem=61045` (Gemeinde).

## Technical Stack

- **Frontend**: Leaflet.js, vanilla JavaScript
- **Data Processing**: Python (pandas, numpy, scipy, geopandas)
- **Data Format**: GeoJSON, JSON

## Project Structure

```
austria-drought-map/
├── data/                 # Raw downloaded data
│   ├── gw/               # Groundwater data
│   ├── nlv/              # Precipitation data
│   ├── owf/              # Surface water data
│   └── qu/               # Springs data
├── scripts/
│   ├── quick_process.py  # Initial data processing
│   └── analyze_trends.py # Groundwater trend analysis
└── web/
    ├── index.html        # Interactive map
    └── data/             # Processed JSON data
```

## Limitations

- IDW interpolation between stations is an estimate, not a measurement (`est` flag marks sparse areas)
- Aquifers ignore administrative borders; sharp steps between neighbouring KGs deserve skepticism
- WFD status is per water body (Gemeinde attribution approximate); nitrate <LOQ counted as LOQ/2
- NASA POWER precipitation grid is coarse (~50 km); trend windows differ per source (eHYD →2022, nitrate →2024)

## Future Enhancements

- Incorporate actual river discharge correlations with hydropower operations
- Add time slider for historical trend visualization
- Include heat pump density data when available
- Connect to ENTSO-E for real-time power production data

## Related Resources

- [Tagesschau: Groundwater heat pump issues](https://www.tagesschau.de/wirtschaft/energie/grundwasser-waermepumpen-100.html)
- [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/)
- [EDM River Network Data](https://edm.gv.at/)

## License

Code: [MIT](LICENSE). Derived data (GWI, `web/data/*`, `/llm/` API): CC BY 4.0 —
except the MERIT-Hydro catchment products, which inherit CC BY-NC-SA. Upstream
sources keep their own terms; the full table is in [LICENSE](LICENSE) and is
served at `/LICENSE`.

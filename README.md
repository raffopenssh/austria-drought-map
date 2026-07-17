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
- [BEV cadastre API](https://cadastre-process-api.exe.xyz/) — canonical KG/Gemeinde registry, point-in-polygon snapping, address search
- [Oesterreichs Energie](https://oesterreichsenergie.at/) — power plant registry
- Austrian municipality boundaries from GeoJSON-Austria

## API

Sibling-service endpoints per the [cadastre integration spec](https://cadastre-process-api.exe.xyz/api/v1/docs/llm.txt?section=integration), keyed on official BEV/Statistik Austria codes (5-char zero-padded strings):

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

Data sources have their own licenses. Code is provided as-is for educational purposes.

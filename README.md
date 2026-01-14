# Austria Drought Risk Map

Interactive municipality-level drought risk visualization for Austria, combining 100-year groundwater monitoring data with hydropower infrastructure analysis.

## Live Demo

**https://groundwater-at.exe.xyz:8000/**

## Overview

This project visualizes drought risk across Austrian municipalities based on:

- **Groundwater trends** from 100-year eHYD monitoring data (2,074 stations)
- **Hydropower impact** from pump storage, run-of-river, and storage plants (156 plants)
- **Surface water discharge** patterns
- **Precipitation data** (495 stations)

## Key Findings

- **54 declining vs 40 rising** groundwater stations (based on statistically valid long-term data)
- **Mean groundwater decline: -4.7cm/decade**
- **186 at-risk municipalities** identified
- Highest risk areas: Marchfeld/Vienna Basin, SE Styria

## Context

In recent years, Austrian municipalities have had to implement water rationing measures (e.g., restrictions on car washing, pool filling). While Vienna has its historic high-mountain water supply, most of Austria depends on groundwater. Climate change impacts are compounded by:

1. **Land use changes** causing increased runoff
2. **Hydropower operations** - reservoir flushing deposits silt that seals riverbeds, reducing groundwater recharge
3. **Groundwater heat pump proliferation** - receding water tables causing system failures

## Data Sources

- [eHYD Portal](https://ehyd.gv.at/) - Austrian hydrographic data
  - Groundwater levels (cat=gw)
  - Surface water discharge (cat=owf)
  - Precipitation (cat=nlv)
  - Springs (cat=qu)
- [Oesterreichs Energie](https://oesterreichsenergie.at/) - Power plant registry
- Austrian municipality boundaries from GeoJSON-Austria

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

## Risk Calculation

The risk score combines:
- **Groundwater trend risk** (50%): Negative trend = higher risk
- **Hydropower impact risk** (50%): Higher capacity nearby = higher risk

## Limitations

- Coordinate transformation from BMN to WGS84 is approximate
- Time series analysis limited to stations with 10+ years of data
- Trend analysis excludes stations with unrealistic variance
- Heat pump risk is currently proxied by groundwater trend (actual depth data would improve accuracy)

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

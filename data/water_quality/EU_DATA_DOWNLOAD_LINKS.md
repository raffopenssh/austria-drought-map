# EU Water Quality Data - Download Links

## 1. EEA WISE Waterbase (Recommended - has measurement data)

### Direct Downloads
- **Main portal**: https://www.eea.europa.eu/en/datahub/datahubitem-view/fbf3717c-cd7b-4785-933a-d0cf510542e1
- **Data files** (requires clicking through):
  - Waterbase_v2024_1_T_WISE6_AggregatedDataByWaterBody.csv
  - Waterbase_v2024_1_T_WISE6_DisaggregatedData.csv
  
### SDI Catalogue
- https://sdi.eea.europa.eu/catalogue/srv/eng/catalog.search#/metadata/f39fd6e2-71b5-4b59-a82e-7a9e6fdfe404

## 2. WISE REST Services (Query Austrian data)

### Monitoring Sites
```
https://water.discomap.eea.europa.eu/arcgis/rest/services/WISE_SoE/EIONET_MonitoringSite_WM/MapServer/0/query?where=countryCode='AT'&outFields=*&f=json
```

### Water Quality Status (WFD 2022)
```
https://water.discomap.eea.europa.eu/arcgis/rest/services/WISE_WFD/WFD2022_QualityElements_WM/MapServer/2/query?where=countryCode='AT'&outFields=*&f=json
```

### Groundwater Bodies
```
https://water.discomap.eea.europa.eu/arcgis/rest/services/WISE_SoE/EIONET_GroundWaterBody_WM/MapServer
```

## 3. Nitrates Directive Data

### EU Nitrates Directive Reports (has station-level nitrate data!)
- **Download portal**: https://water.europa.eu/freshwater/data-and-maps/nitrate-groundwater
- **API**: Check https://water.discomap.eea.europa.eu/arcgis/rest/services/Nitrates

## 4. WISE Freshwater Portal
- **Austria country page**: https://water.europa.eu/freshwater/countries/austria
- Browse: Rivers, Lakes, Groundwater quality status

## 5. Copernicus Data

### European Drought Observatory (EDO)
- **Download**: https://drought.emergency.copernicus.eu/tumbo/edo/download/
- Indicators: SPI, SPEI, Soil Moisture Anomaly, Combined Drought Index

### Copernicus Climate Data Store
- https://cds.climate.copernicus.eu/datasets

## 6. Austrian National Sources

### Umweltbundesamt H2O Database
- https://wasser.umweltbundesamt.at/h2odb/
- Requires registration for full data access

### eHYD Hydrological Data
- https://ehyd.gv.at/
- Groundwater levels (already in our app)
- Surface water flows

## Priority Downloads for Nitrogen Data

1. **EEA Waterbase Disaggregated Data** - Contains actual measurements
2. **Nitrates Directive data** - Station-level nitrate measurements
3. **WISE WFD Quality data** - Status assessments by water body


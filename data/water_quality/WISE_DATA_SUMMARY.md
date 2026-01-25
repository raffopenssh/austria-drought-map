# WISE Water Quality Data for Austria

## Data Sources
All data from EEA WISE (Water Information System for Europe) WFD 2022 reporting.

## Downloaded Files

### 1. Monitoring Sites
- **File**: `wise_wfd2022_monitoring_sites_austria.json`
- **Records**: 9,617 monitoring sites
- **Types**:
  - Groundwater: 6,408 sites
  - Rivers: 3,176 sites
  - Lakes: 33 sites

### 2. River Water Quality
- **File**: `wise_wfd2022_river_quality_austria.json`
- **Records**: 8,116 river water bodies
- **Ecological Status Distribution**:
  - High: 1,537 (18.9%)
  - Good: 2,447 (30.2%)
  - Moderate: 3,050 (37.6%)
  - Poor: 754 (9.3%)
  - Bad: 227 (2.8%)
  - Unknown: 101 (1.2%)

### 3. Groundwater Chemical Status
- **File**: `wise_wfd2022_groundwater_chemical_austria.json`
- **Records**: 142 groundwater bodies
- **Chemical Status**:
  - Failing to achieve good: 137 (96.5%)
  - Unknown: 5 (3.5%)

### 4. Processed Combined Data
- **File**: `wise_monitoring_sites_processed.geojson`
- **Records**: 9,617 monitoring sites with water body quality status
- **Format**: GeoJSON with Point features

## Key Findings

### Groundwater Quality
- **96.5% of Austrian groundwater bodies are failing to achieve good chemical status**
- This is primarily due to nitrate pollution from agriculture
- 6,408 monitoring sites track groundwater quality

### Surface Water Quality
- Only **49% of river water bodies** achieve High or Good ecological status
- **37.6%** are in Moderate status
- **12.1%** are Poor or Bad (needing urgent remediation)

## Data Structure

### Monitoring Site Properties
```json
{
  "id": "AT300012",
  "name": "ACHAU, BR",
  "siteType": "groundWaterBody|riverWaterBody|lakeWaterBody",
  "lat": 48.08114,
  "lon": 16.38584,
  "waterBodyCode": "ATGK100024",
  "chemicalStatus": "1|2|3",  // 1=Good, 2=Failing, 3=Unknown
  "ecologicalStatus": "1-5",   // 1=High to 5=Bad (rivers only)
  "quantitativeStatus": "1|2", // Groundwater only
  "purpose": "WFD|SOE",
  "activityStart": "1940-05-03"
}
```

## API Endpoints Used

### WISE REST Services (EEA)
```
Base URL: https://water.discomap.eea.europa.eu/arcgis/rest/services/

Services:
- WISE_WFD/WFD2022_MonitoringSite_WM/MapServer/0
- WISE_WFD/WFD2022_QualityElements_WM/MapServer/2 (rivers)
- WISE_WFD/WFD2022_GroundWaterBody_WM/MapServer/1 (gw chemical)

Query example:
?where=countryCode='AT'&outFields=*&f=json
```

## Integration with Webapp

The processed GeoJSON file can be served directly for:
1. Map visualization of all monitoring stations
2. Color-coding by water quality status
3. Popup information with station details
4. Filtering by site type (groundwater, river, lake)

## Update Frequency
- WFD data is updated every 6 years (next update: 2028)
- Source data version: WFD 2022

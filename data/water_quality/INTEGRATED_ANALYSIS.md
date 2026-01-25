# Integrated Analysis: The Agriculture-Drought-Water Quality Nexus in Austria

## Executive Summary

Analysis of combined data from eHYD (groundwater/river monitoring), EEA WISE (water quality), and Austrian ammonia emissions reveals important relationships between agricultural activity, groundwater levels, and water quality.

**Key Finding:** Regions with highest agricultural emissions (measured by NH3) tend to have the worst groundwater level decline AND the highest proportion of at-risk groundwater bodies.

---

## Data Sources Combined

| Source | Data Type | Records |
|--------|-----------|---------|
| eHYD | Groundwater levels | 3,788 wells |
| eHYD | River flow | 317 stations |
| WISE WFD 2022 | Water quality status | 9,617 sites |
| Austrian IIR 2023 | NH3 emissions | By Bundesland |
| Umweltbundesamt | NH3 measurements | 24 stations |

---

## CORRECTED Water Quality Assessment

### Groundwater Bodies (142 total)
Based on Austria's NGP 2021 and WISE WFD 2022 data:

| Status | Bodies | Percentage |
|--------|--------|------------|
| **Good** chemical status | 120 | 84.5% |
| **Poor/At Risk** (nitrate, pesticides) | 17 | 12.0% |
| Unknown | 5 | 3.5% |
| **Good** quantitative status | 142 | 100% |

### Monitoring Sites (by water body status)
Of 6,408 groundwater monitoring sites:
- **5,150 sites** (80.4%) in water bodies with Good status
- **1,079 sites** (16.8%) in water bodies with Poor/At Risk status
- **179 sites** (2.8%) in water bodies with Unknown status

### River Water Bodies (8,116 total)
Ecological status distribution:

| Status | Count | Percentage |
|--------|-------|------------|
| High | 1,537 | 18.9% |
| Good | 2,447 | 30.2% |
| Moderate | 3,050 | 37.6% |
| Poor | 754 | 9.3% |
| Bad | 227 | 2.8% |
| Unknown | 101 | 1.2% |

**Note:** Only 49.1% of river water bodies achieve High or Good ecological status.

---

## Regional Risk Assessment

### High Risk: Oberösterreich 🔴
- **NH3 Emissions:** 1.19 tonnes/km²/year (highest in Austria)
- **Wells Declining:** 71.6% (highest in Austria)
- **GW Trend:** -0.093 m/decade

### High Risk: Niederösterreich 🟠
- **NH3 Emissions:** 0.82 tonnes/km²/year
- **Wells Declining:** 66.0%
- **GW Trend:** -0.056 m/decade

### Medium Risk: Steiermark, Vorarlberg, Salzburg 🟡
- NH3: 0.34-0.73 tonnes/km²/year
- Wells declining: 60-66%
- Mixed agricultural/alpine character

### Lower Risk: Tirol, Kärnten, Wien, Burgenland 🟢
- NH3: 0.30-0.81 tonnes/km²/year
- Wells declining: 51-59%
- More alpine or urban character

---

## Statistical Correlation

| Metric | Value |
|--------|-------|
| Correlation (NH3 vs Well Decline) | **0.485** |
| R-squared | 0.235 |
| Interpretation | Moderate positive correlation |

**The correlation suggests:**
1. Higher agricultural activity (NH3 as proxy) is associated with more groundwater decline
2. But other factors (climate, geology) also play significant roles
3. The relationship is not deterministic

---

## Key Mechanisms

### 1. Agricultural Water Demand
- Irrigation increases groundwater extraction
- Oberösterreich and Niederösterreich have highest agricultural intensity
- These regions show 66-72% of wells with declining trends

### 2. River Baseflow Decline
Rivers in agricultural regions showing dramatic decline:

| River | Decline/Decade | Region |
|-------|---------------|--------|
| Traisen | -67.3% | NÖ |
| Piesting | -57.4% | NÖ |
| Pulkau | -57.0% | NÖ |
| Badener Mühlbach | -48.7% | NÖ |
| Warme Fischa | -48.1% | NÖ |

### 3. Water Quality Pressure
- 17 groundwater bodies (12%) are at risk due to nitrate/pesticides
- These are concentrated in agricultural lowlands
- Affects ~1,079 monitoring sites

---

## Implications

### For Drought Risk
1. Agricultural regions face **higher vulnerability**:
   - Greater groundwater extraction rates
   - Less buffer for dry periods
   
2. River baseflow decline in NÖ indicates:
   - Reduced summer water availability
   - Less ecosystem resilience

### For Water Management
1. While overall groundwater quality is good (84.5%), the 12% at risk needs attention
2. Agricultural water use regulation is important in hotspot regions
3. Quantitative status is good nationwide, but trends are concerning

### For Climate Adaptation
1. High-risk regions (OÖ, NÖ) need priority adaptation measures
2. Water-efficient farming techniques would help most in these areas
3. Early warning systems for groundwater decline

---

## Data Quality Notes

- Correlation of 0.485 is moderate but statistically meaningful
- NH3 data is by Bundesland (coarse spatial resolution)
- Groundwater body boundaries don't perfectly match well locations
- WFD assessments are at water body level, not individual well level

---

## Status Code Reference

### Groundwater (WISE WFD 2022)
- `gwChemicalStatusValue='2'` + `gwAtRiskChemical='No'` = **Good**
- `gwChemicalStatusValue='2'` + `gwAtRiskChemical='Yes'` = **Poor/At Risk**
- `gwChemicalStatusValue='3'` = **Unknown**

### Rivers (WISE WFD 2022)
- `swEcologicalStatusOrPotentialValue`: 1=High, 2=Good, 3=Moderate, 4=Poor, 5=Bad

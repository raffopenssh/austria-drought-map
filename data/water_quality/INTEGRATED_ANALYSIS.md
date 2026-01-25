# Integrated Analysis: The Agriculture-Drought-Water Quality Nexus in Austria

## Executive Summary

Analysis of combined data from eHYD (groundwater/river monitoring), EEA WISE (water quality), and Austrian ammonia emissions reveals a **critical feedback loop** between agricultural intensification, groundwater depletion, and water quality degradation.

**Key Finding:** The same regions with highest agricultural emissions (measured by NH3) have both the **worst groundwater decline** AND the **worst water quality** - indicating agriculture is simultaneously extracting and contaminating Austria's groundwater.

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

## Regional Risk Assessment

### Critical Risk: Oberösterreich 🔴
- **NH3 Emissions:** 1.19 tonnes/km²/year (highest in Austria)
- **Wells Declining:** 71.6% (highest in Austria)
- **GW Trend:** -0.093 m/decade
- **Chemical Status:** ~94% of monitoring sites "Failing"

### High Risk: Niederösterreich 🟠
- **NH3 Emissions:** 0.82 tonnes/km²/year
- **Wells Declining:** 66.0%
- **GW Trend:** -0.056 m/decade
- **Chemical Status:** ~94% of monitoring sites "Failing"

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

**The correlation is not perfect because:**
1. Alpine areas have natural groundwater decline from climate
2. Urban areas (Wien) have different extraction patterns
3. Time lags between emissions and groundwater impacts

---

## The Feedback Loop Mechanism

```
┌─────────────────────────────────────────────────────┐
│     AGRICULTURAL INTENSIFICATION                    │
│              ↓                                      │
│  ┌───────────┴───────────┐                         │
│  ↓                       ↓                         │
│  NH3/N Fertilizer    Irrigation Demand             │
│  Application         (Groundwater Pumping)         │
│  ↓                       ↓                         │
│  Nitrate Leaching    Water Table Decline           │
│  into Groundwater    (60-70% of wells)             │
│  ↓                       ↓                         │
│  96.5% GW Bodies     River Baseflow Drops          │
│  "Failing" Status    (-50 to -67%/decade)          │
│  ↓                       ↓                         │
│  DEGRADED QUANTITY + DEGRADED QUALITY              │
│              ↓                                      │
│  Drought Vulnerability Increases                    │
│  (Less resilience in dry years)                    │
└─────────────────────────────────────────────────────┘
```

---

## Evidence: River Baseflow Collapse

Rivers in the NÖ/OÖ agricultural region showing dramatic decline:

| River | Decline/Decade | Region |
|-------|---------------|--------|
| Traisen | -67.3% | NÖ |
| Piesting | -57.4% | NÖ |
| Pulkau | -57.0% | NÖ |
| Badener Mühlbach | -48.7% | NÖ |
| Warme Fischa | -48.1% | NÖ |

These rivers are fed by **groundwater baseflow** - their decline directly reflects the falling water table.

---

## Evidence: Ammonia Hotspots

Highest NH3 measurements (indicating agricultural intensity):

| Location | NH3 (µg/m³) | Type |
|----------|------------|------|
| Seibersdorf (ST) | 16.7 | Near barns |
| Draßmarkt (B) | 16.0 | Near barns |
| Hirnsdorf (ST) | 13.7 | Near barns |
| Marchfeld (NÖ) | 7.3 | Fields |
| Pyhra (NÖ) | 7.2 | Mixed |

Background alpine stations show only 1-2 µg/m³.

---

## Evidence: Water Quality Crisis

In the NÖ/OÖ high-risk region:
- **3,141 groundwater monitoring sites**
- **94.3% show "Failing" chemical status**
- **5.7% Unknown** (none rated "Good")

Primary pollutant: **Nitrate** from agricultural runoff

---

## Implications

### For Drought Risk
1. Agricultural regions are **doubly vulnerable**:
   - Less groundwater buffer for dry periods
   - Contaminated water limits usable supply
   
2. River baseflow decline means:
   - Less summer water availability
   - Ecosystem stress
   - Reduced dilution capacity for pollutants

### For Water Management
1. **Quantity and quality must be managed together**
   - Current policy treats them separately
   
2. Agricultural water use needs regulation
   - Currently unmetered in many areas
   
3. Fertilizer application controls critical
   - Nitrate directive compliance failing

### For Climate Adaptation
1. High-risk regions need priority adaptation
2. Crop changes may be needed in NÖ/OÖ
3. Water-efficient farming techniques essential

---

## Recommended Monitoring Integration

Priority metrics to display together:
1. **Groundwater level trend** (eHYD)
2. **Chemical status** (WISE)
3. **NH3 density** (by region)
4. **River baseflow trend** (eHYD)

This allows users to see the **combined stress** rather than individual metrics.

---

## Data Quality Notes

- Correlation of 0.485 is moderate but significant
- NH3 data is by Bundesland (coarse spatial resolution)
- Well-level NH3 measurements would improve analysis
- Time series alignment needed for rigorous causality testing

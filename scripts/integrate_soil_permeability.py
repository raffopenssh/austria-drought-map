#!/usr/bin/env python3
"""
Integrate soil permeability into the drought risk model.

Risk model now includes:
- Groundwater trend risk (35%)
- Hydropower impact risk (25%)
- EDO Combined Drought Index (25%)
- Soil permeability risk (15%)

Soil permeability: 1-9 scale (1=very low, 9=very high)
- Low permeability (1-3) = Higher drought risk (slower recharge)
- Medium permeability (4-6) = Medium risk
- High permeability (7-9) = Lower drought risk (faster recharge)
"""
import json
from pathlib import Path
import statistics

DATA_DIR = Path('/home/exedev/austria-drought-map/web/data')

def load_json(filename):
    return json.loads((DATA_DIR / filename).read_text())

def save_json(filename, data):
    (DATA_DIR / filename).write_text(json.dumps(data, ensure_ascii=False))

def permeability_to_risk(perm):
    """Convert soil permeability (1-9) to risk (0-1).
    Low permeability = high risk, high permeability = low risk.
    """
    if perm is None:
        return 0.5  # Default to medium risk if no data
    
    # Invert: 9 -> 0 risk, 1 -> 1 risk
    # Using scale where 1-3 is high risk, 4-6 medium, 7-9 low
    risk = 1.0 - ((perm - 1) / 8.0)  # Maps 1->1, 9->0
    return max(0.0, min(1.0, risk))

def main():
    print("Integrating Soil Permeability into Risk Model")
    print("=" * 50)
    
    # Load data
    municipalities = load_json('municipalities.json')
    geojson = load_json('municipalities_risk.geojson')
    
    # Check soil permeability coverage
    with_soil = [m for m in municipalities if m.get('soil_permeability') is not None]
    print(f"Municipalities with soil data: {len(with_soil)}/{len(municipalities)}")
    
    # Get permeability distribution
    perms = [m['soil_permeability'] for m in with_soil]
    print(f"Soil permeability range: {min(perms):.2f} - {max(perms):.2f}")
    print(f"Mean permeability: {statistics.mean(perms):.2f}")
    
    # Update risk scores
    updated = 0
    for muni in municipalities:
        perm = muni.get('soil_permeability')
        soil_risk = permeability_to_risk(perm)
        muni['soil_risk'] = round(soil_risk, 3)
        
        # Recalculate composite risk score
        # New weights: GW 35%, Hydro 25%, EDO 25%, Soil 15%
        gw_risk = muni.get('gw_risk', 0.5)
        hydro_factor = muni.get('hydro_factor', 0)
        edo_risk = muni.get('edo_risk', 0.5)
        
        # Normalize hydro factor (0-1000 range typical)
        hydro_risk = min(1.0, hydro_factor / 500) if hydro_factor else 0
        
        old_risk = muni.get('risk_score', 0)
        new_risk = (0.35 * gw_risk) + (0.25 * hydro_risk) + (0.25 * edo_risk) + (0.15 * soil_risk)
        
        muni['risk_score'] = round(new_risk, 4)
        
        # Update risk category
        if new_risk >= 0.45:
            muni['risk_category'] = 'high'
        elif new_risk >= 0.25:
            muni['risk_category'] = 'medium'
        else:
            muni['risk_category'] = 'low'
        
        if abs(new_risk - old_risk) > 0.001:
            updated += 1
    
    print(f"Risk scores updated: {updated}")
    
    # Save updated municipalities
    save_json('municipalities.json', municipalities)
    print(f"Saved: municipalities.json")
    
    # Update GeoJSON features
    muni_lookup = {m['name']: m for m in municipalities}
    muni_by_iso = {str(m.get('iso', '')): m for m in municipalities if m.get('iso')}
    
    for feature in geojson['features']:
        props = feature['properties']
        name = props.get('name')
        iso = str(props.get('iso', ''))
        
        m = muni_lookup.get(name) or muni_by_iso.get(iso)
        if m:
            props['risk_score'] = m.get('risk_score', 0)
            props['risk_category'] = m.get('risk_category', 'low')
            props['soil_permeability'] = m.get('soil_permeability')
            props['soil_risk'] = m.get('soil_risk')
    
    save_json('municipalities_risk.geojson', geojson)
    print(f"Saved: municipalities_risk.geojson")
    
    # Print risk distribution
    high_risk = [m for m in municipalities if m.get('risk_category') == 'high']
    med_risk = [m for m in municipalities if m.get('risk_category') == 'medium']
    low_risk = [m for m in municipalities if m.get('risk_category') == 'low']
    
    print(f"\nRisk Distribution:")
    print(f"  High risk:   {len(high_risk)} municipalities")
    print(f"  Medium risk: {len(med_risk)} municipalities")
    print(f"  Low risk:    {len(low_risk)} municipalities")
    
    # Top 10 highest risk
    sorted_munis = sorted(municipalities, key=lambda x: x.get('risk_score', 0), reverse=True)
    print(f"\nTop 10 Highest Risk Municipalities:")
    for m in sorted_munis[:10]:
        perm = m.get('soil_permeability')
        perm_str = f"{perm:.1f}" if perm else "N/A"
        print(f"  {m['name']}: {m['risk_score']:.3f}")
        print(f"    GW:{m.get('gw_risk','N/A'):.2f} Hydro:{m.get('hydro_factor',0):.0f} EDO:{m.get('edo_risk','N/A'):.2f} Soil:{perm_str}")

if __name__ == '__main__':
    main()

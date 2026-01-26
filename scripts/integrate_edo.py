#!/usr/bin/env python3
"""
Integrate EDO CDI data into the drought risk model.
Updates municipalities.json and municipalities_risk.geojson with EDO values.

Risk model now includes:
- Groundwater trend risk (40%)
- Hydropower impact risk (30%)
- EDO Combined Drought Index (30%)
"""
import json
from pathlib import Path
import statistics

DATA_DIR = Path('/home/exedev/austria-drought-map/web/data')

def load_json(filename):
    return json.loads((DATA_DIR / filename).read_text())

def save_json(filename, data):
    (DATA_DIR / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2))

def normalize_cdi(cdi, min_cdi=0, max_cdi=2):
    """Normalize CDI to 0-1 risk score (higher CDI = higher risk)"""
    return min(1.0, max(0.0, (cdi - min_cdi) / (max_cdi - min_cdi)))

def main():
    print("Integrating EDO CDI into Risk Model")
    print("=" * 50)
    
    # Load data
    municipalities = load_json('municipalities.json')
    edo_summary = load_json('edo_municipality_summary.json')
    geojson = load_json('municipalities_risk.geojson')
    
    # Create EDO lookup by municipality ID (ISO code)
    edo_lookup = edo_summary['municipalities']
    
    # Get CDI distribution for normalization
    all_cdi_means = [v['overall']['mean'] for v in edo_lookup.values()]
    cdi_min = min(all_cdi_means)
    cdi_max = max(all_cdi_means)
    cdi_avg = statistics.mean(all_cdi_means)
    
    print(f"EDO CDI range: {cdi_min:.3f} - {cdi_max:.3f} (avg: {cdi_avg:.3f})")
    print(f"  Municipalities with EDO data: {len(edo_lookup)}")
    
    # Update municipalities.json
    matched = 0
    updated_risk = 0
    
    for muni in municipalities:
        # Match by ISO code if available, otherwise by name
        muni_id = str(muni.get('iso', muni.get('id', '')))
        
        if muni_id in edo_lookup:
            edo_data = edo_lookup[muni_id]
            muni['edo_cdi_mean'] = edo_data['overall']['mean']
            muni['edo_cdi_max'] = edo_data['overall']['max']
            muni['edo_cdi_median'] = edo_data['overall']['median']
            muni['edo_yearly'] = edo_data['yearly']
            
            # Calculate EDO risk component (normalize to 0-1)
            # Use mean CDI, scaled where 0=no risk, 2+=max risk
            edo_risk = normalize_cdi(edo_data['overall']['mean'], 0, 2)
            muni['edo_risk'] = round(edo_risk, 3)
            
            matched += 1
        else:
            # No EDO data - use Austria average
            muni['edo_cdi_mean'] = round(cdi_avg, 3)
            muni['edo_risk'] = normalize_cdi(cdi_avg, 0, 2)
        
        # Recalculate composite risk score
        # New weights: GW 40%, Hydro 30%, EDO 30%
        gw_risk = muni.get('gw_risk', 0.5)  # Default to medium if missing
        hydro_factor = muni.get('hydro_factor', 0)
        edo_risk = muni.get('edo_risk', 0.5)
        
        # Normalize hydro factor (0-1000 range typical)
        hydro_risk = min(1.0, hydro_factor / 500) if hydro_factor else 0
        
        old_risk = muni.get('risk_score', 0)
        new_risk = (0.40 * gw_risk) + (0.30 * hydro_risk) + (0.30 * edo_risk)
        
        muni['risk_score'] = round(new_risk, 4)
        
        # Update risk category
        if new_risk >= 0.45:
            muni['risk_category'] = 'high'
        elif new_risk >= 0.25:
            muni['risk_category'] = 'medium'
        else:
            muni['risk_category'] = 'low'
        
        if abs(new_risk - old_risk) > 0.01:
            updated_risk += 1
    
    print(f"  Matched {matched}/{len(municipalities)} municipalities")
    print(f"  Risk scores updated: {updated_risk}")
    
    # Save updated municipalities
    save_json('municipalities.json', municipalities)
    print(f"  Saved: municipalities.json")
    
    # Update GeoJSON features
    muni_lookup = {m['name']: m for m in municipalities}
    muni_by_iso = {str(m.get('iso', '')): m for m in municipalities if m.get('iso')}
    
    geo_updated = 0
    for feature in geojson['features']:
        props = feature['properties']
        name = props.get('name')
        iso = str(props.get('iso', ''))
        
        m = muni_lookup.get(name) or muni_by_iso.get(iso)
        if m:
            props['risk_score'] = m.get('risk_score', 0)
            props['risk_category'] = m.get('risk_category', 'low')
            props['gw_trend'] = m.get('gw_trend')
            props['gw_risk'] = m.get('gw_risk')
            props['hydro_factor'] = m.get('hydro_factor')
            props['edo_cdi_mean'] = m.get('edo_cdi_mean')
            props['edo_cdi_max'] = m.get('edo_cdi_max')
            props['edo_risk'] = m.get('edo_risk')
            geo_updated += 1
    
    save_json('municipalities_risk.geojson', geojson)
    print(f"  Updated GeoJSON: {geo_updated} features")
    
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
        print(f"  {m['name']}: {m['risk_score']:.3f} (GW: {m.get('gw_risk', 'N/A')}, Hydro: {m.get('hydro_factor', 0):.0f}, EDO: {m.get('edo_cdi_mean', 'N/A')})")

if __name__ == '__main__':
    main()

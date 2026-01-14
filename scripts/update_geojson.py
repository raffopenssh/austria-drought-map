#!/usr/bin/env python3
"""Update GeoJSON with latest risk scores from municipalities.json"""

import json
from pathlib import Path

def main():
    # Load current data
    muni = json.loads(Path('web/data/municipalities.json').read_text())
    geo = json.loads(Path('web/data/municipalities_risk.geojson').read_text())
    
    # Create lookup by name
    muni_lookup = {m['name']: m for m in muni}
    
    updated = 0
    for feature in geo['features']:
        name = feature['properties'].get('name')
        if name and name in muni_lookup:
            m = muni_lookup[name]
            # Update all relevant properties
            feature['properties']['risk_score'] = m.get('risk_score', 0)
            feature['properties']['risk_category'] = m.get('risk_category', 'low')
            feature['properties']['gw_trend'] = m.get('gw_trend')
            feature['properties']['gw_risk'] = m.get('gw_risk')
            feature['properties']['hydro_factor'] = m.get('hydro_factor')
            feature['properties']['precip_risk'] = m.get('precip_risk')
            feature['properties']['precip_trend_mm'] = m.get('precip_trend_mm')
            feature['properties']['flow_risk'] = m.get('flow_risk')
            feature['properties']['flow_trend_pct'] = m.get('flow_trend_pct')
            updated += 1
    
    # Save updated GeoJSON
    Path('web/data/municipalities_risk.geojson').write_text(
        json.dumps(geo, ensure_ascii=False)
    )
    
    print(f"Updated {updated}/{len(geo['features'])} features")
    
    # Verify
    for name in ['Kaprun', 'Wien', 'Fusch an der Großglocknerstraße']:
        m = muni_lookup.get(name)
        g = next((f for f in geo['features'] if f['properties']['name'] == name), None)
        if m and g:
            print(f"{name}: {m['risk_score']:.3f} == {g['properties']['risk_score']:.3f}")

if __name__ == '__main__':
    main()

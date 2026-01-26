#!/usr/bin/env python3
"""
Calculate water quality risk per municipality.
Combines chemical and ecological status from WISE WFD 2022 data.

WFD Status codes:
- Ecological: 1=High, 2=Good, 3=Moderate, 4=Poor, 5=Bad
- Chemical: 2=Good, 3=Failing to achieve good (Poor)

Risk calculation:
- Chemical status: 60% weight (prioritized per user request)
- Ecological status: 40% weight
"""
import json
from pathlib import Path
from collections import defaultdict
import statistics

DATA_DIR = Path('/home/exedev/austria-drought-map/data/water_quality')
WEB_DATA = Path('/home/exedev/austria-drought-map/web/data')

# WFD status to risk score mapping
# Higher score = worse quality = higher risk
ECO_STATUS_RISK = {
    '1': 0.0,   # High - excellent
    '2': 0.25,  # Good
    '3': 0.5,   # Moderate
    '4': 0.75,  # Poor
    '5': 1.0,   # Bad
    'Unknown': 0.5,
}

CHEM_STATUS_RISK = {
    '2': 0.0,     # Good
    'Good': 0.0,
    '3': 1.0,     # Failing to achieve good
    'Poor': 1.0,
    'Unknown': 0.5,
}

def load_json(path):
    with open(path) as f:
        return json.load(f)

def get_status_risk(status, mapping):
    """Convert status to risk score (0-1)"""
    if not status or status == 'Inapplicable':
        return None
    return mapping.get(str(status), 0.5)

def main():
    print("Water Quality Risk by Municipality")
    print("=" * 50)
    
    # Load monitoring sites with coordinates
    sites = load_json(DATA_DIR / 'wise_wfd2022_monitoring_sites_austria.json')
    print(f"Monitoring sites: {len(sites['features'])}")
    
    # Load river/surface water quality
    river_quality = load_json(DATA_DIR / 'wise_wfd2022_river_quality_austria.json')
    print(f"River water bodies: {len(river_quality['features'])}")
    
    # Load groundwater quality
    gw_quality = load_json(DATA_DIR / 'wise_wfd2022_groundwater_chemical_austria.json')
    print(f"Groundwater bodies: {len(gw_quality['features'])}")
    
    # Create water body code -> quality mapping
    wb_quality = {}
    
    # Process river/surface water bodies
    for f in river_quality['features']:
        attr = f['attributes']
        wb_code = attr.get('euSurfaceWaterBodyCode')
        if wb_code:
            eco_status = attr.get('swEcologicalStatusOrPotentialValue')
            chem_status = attr.get('swChemicalStatusValue')
            wb_quality[wb_code] = {
                'type': 'surface',
                'eco_status': eco_status,
                'chem_status': chem_status,
                'eco_risk': get_status_risk(eco_status, ECO_STATUS_RISK),
                'chem_risk': get_status_risk(chem_status, CHEM_STATUS_RISK),
            }
    
    # Process groundwater bodies
    for f in gw_quality['features']:
        attr = f['attributes']
        wb_code = attr.get('euGroundWaterBodyCode')
        if wb_code:
            chem_status = attr.get('gwChemicalStatusValue')
            quant_status = attr.get('gwQuantitativeStatusValue')
            wb_quality[wb_code] = {
                'type': 'groundwater',
                'eco_status': None,
                'chem_status': chem_status,
                'quant_status': quant_status,
                'eco_risk': None,
                'chem_risk': get_status_risk(chem_status, CHEM_STATUS_RISK),
            }
    
    print(f"Water bodies with quality data: {len(wb_quality)}")
    
    # Create site -> quality mapping by joining on water body code
    site_quality = []
    matched = 0
    
    for f in sites['features']:
        attr = f['attributes']
        geom = f.get('geometry', {})
        
        # Get coordinates
        lat = attr.get('lat')
        lon = attr.get('lon')
        if not lat or not lon:
            continue
            
        site_type = attr.get('specialisedZoneType')
        
        # Get water body code
        if site_type == 'groundWaterBody':
            wb_code = attr.get('featureOfInterestIdentifier')
        else:
            wb_code = attr.get('featureOfInterestIdentifier')
        
        # Look up quality
        quality = wb_quality.get(wb_code, {})
        
        if quality:
            matched += 1
            
        site_quality.append({
            'id': attr.get('thematicIdIdentifier'),
            'name': attr.get('nameText'),
            'lat': lat,
            'lon': lon,
            'type': site_type,
            'wb_code': wb_code,
            'eco_risk': quality.get('eco_risk'),
            'chem_risk': quality.get('chem_risk'),
        })
    
    print(f"Sites with coordinates: {len(site_quality)}")
    print(f"Sites matched to water body quality: {matched}")
    
    # Load municipalities
    municipalities = load_json(WEB_DATA / 'municipalities.json')
    print(f"Municipalities: {len(municipalities)}")
    
    # Assign sites to municipalities by proximity
    # Simple approach: use pre-computed municipality centroids
    muni_sites = defaultdict(list)
    
    for site in site_quality:
        if site['chem_risk'] is None and site['eco_risk'] is None:
            continue
            
        # Find nearest municipality
        min_dist = float('inf')
        nearest_muni = None
        
        for muni in municipalities:
            if 'lat' not in muni or 'lon' not in muni:
                continue
            dist = ((site['lat'] - muni['lat'])**2 + (site['lon'] - muni['lon'])**2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                nearest_muni = muni['name']
        
        if nearest_muni and min_dist < 0.3:  # ~30km threshold
            muni_sites[nearest_muni].append(site)
    
    print(f"Municipalities with water quality sites: {len(muni_sites)}")
    
    # Calculate risk per municipality
    muni_wq_risk = {}
    
    for muni_name, sites in muni_sites.items():
        chem_risks = [s['chem_risk'] for s in sites if s['chem_risk'] is not None]
        eco_risks = [s['eco_risk'] for s in sites if s['eco_risk'] is not None]
        
        # Calculate weighted risk: chemical 60%, ecological 40%
        if chem_risks and eco_risks:
            avg_chem = statistics.mean(chem_risks)
            avg_eco = statistics.mean(eco_risks)
            combined_risk = 0.6 * avg_chem + 0.4 * avg_eco
        elif chem_risks:
            combined_risk = statistics.mean(chem_risks)
            avg_chem = combined_risk
            avg_eco = None
        elif eco_risks:
            combined_risk = statistics.mean(eco_risks)
            avg_eco = combined_risk
            avg_chem = None
        else:
            continue
        
        # Count by type
        gw_count = sum(1 for s in sites if s['type'] == 'groundWaterBody')
        sw_count = sum(1 for s in sites if s['type'] != 'groundWaterBody')
        
        muni_wq_risk[muni_name] = {
            'wq_risk': round(combined_risk, 3),
            'wq_chem_risk': round(avg_chem, 3) if avg_chem is not None else None,
            'wq_eco_risk': round(avg_eco, 3) if avg_eco is not None else None,
            'wq_stations': len(sites),
            'wq_gw_stations': gw_count,
            'wq_sw_stations': sw_count,
        }
    
    print(f"Municipalities with calculated risk: {len(muni_wq_risk)}")
    
    # Update municipalities.json
    for muni in municipalities:
        name = muni['name']
        if name in muni_wq_risk:
            muni.update(muni_wq_risk[name])
        else:
            muni['wq_risk'] = None
            muni['wq_stations'] = 0
    
    # Save updated municipalities
    with open(WEB_DATA / 'municipalities.json', 'w') as f:
        json.dump(municipalities, f)
    print(f"Updated: municipalities.json")
    
    # Update GeoJSON
    geojson = load_json(WEB_DATA / 'municipalities_risk.geojson')
    muni_lookup = {m['name']: m for m in municipalities}
    
    for feature in geojson['features']:
        name = feature['properties'].get('name')
        if name and name in muni_lookup:
            m = muni_lookup[name]
            feature['properties']['wq_risk'] = m.get('wq_risk')
            feature['properties']['wq_chem_risk'] = m.get('wq_chem_risk')
            feature['properties']['wq_eco_risk'] = m.get('wq_eco_risk')
            feature['properties']['wq_stations'] = m.get('wq_stations', 0)
    
    with open(WEB_DATA / 'municipalities_risk.geojson', 'w') as f:
        json.dump(geojson, f)
    print(f"Updated: municipalities_risk.geojson")
    
    # Print statistics
    risks = [v['wq_risk'] for v in muni_wq_risk.values()]
    print(f"\nWater Quality Risk Distribution:")
    print(f"  Min: {min(risks):.3f}")
    print(f"  Max: {max(risks):.3f}")
    print(f"  Mean: {statistics.mean(risks):.3f}")
    print(f"  Median: {statistics.median(risks):.3f}")
    
    # Top 10 worst
    sorted_munis = sorted(muni_wq_risk.items(), key=lambda x: x[1]['wq_risk'], reverse=True)
    print(f"\nTop 10 Worst Water Quality:")
    for name, data in sorted_munis[:10]:
        print(f"  {name}: {data['wq_risk']:.3f} (chem: {data['wq_chem_risk']}, eco: {data['wq_eco_risk']})")

if __name__ == '__main__':
    main()

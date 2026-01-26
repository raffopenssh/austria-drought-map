#!/usr/bin/env python3
"""
Build detailed water quality station info per municipality.
Includes station names, types, status values, and assessment dates.
"""
import json
from pathlib import Path
from collections import defaultdict
import statistics

DATA_DIR = Path('/home/exedev/austria-drought-map/data/water_quality')
WEB_DATA = Path('/home/exedev/austria-drought-map/web/data')

# WFD status labels
ECO_STATUS_LABELS = {
    '1': 'High',
    '2': 'Good', 
    '3': 'Moderate',
    '4': 'Poor',
    '5': 'Bad',
    'Unknown': 'Unknown',
}

CHEM_STATUS_LABELS = {
    '2': 'Good',
    '3': 'Failing to achieve good',
    'Good': 'Good',
    'Poor': 'Failing to achieve good',
    'Unknown': 'Unknown',
}

# Risk scores
ECO_STATUS_RISK = {'1': 0.0, '2': 0.25, '3': 0.5, '4': 0.75, '5': 1.0, 'Unknown': 0.5}
CHEM_STATUS_RISK = {'2': 0.0, 'Good': 0.0, '3': 1.0, 'Poor': 1.0, 'Unknown': 0.5}

def load_json(path):
    with open(path) as f:
        return json.load(f)

def main():
    print("Building Water Quality Station Details")
    print("=" * 50)
    
    # Load monitoring sites
    sites = load_json(DATA_DIR / 'wise_wfd2022_monitoring_sites_austria.json')
    print(f"Monitoring sites: {len(sites['features'])}")
    
    # Load water body quality data
    river_quality = load_json(DATA_DIR / 'wise_wfd2022_river_quality_austria.json')
    gw_quality = load_json(DATA_DIR / 'wise_wfd2022_groundwater_chemical_austria.json')
    
    # Build water body lookup with detailed info
    wb_info = {}
    
    for f in river_quality['features']:
        attr = f['attributes']
        wb_code = attr.get('euSurfaceWaterBodyCode')
        if wb_code:
            eco_status = attr.get('swEcologicalStatusOrPotentialValue')
            chem_status = attr.get('swChemicalStatusValue')
            wb_info[wb_code] = {
                'wb_name': attr.get('surfaceWaterBodyName', 'Unknown'),
                'wb_type': 'River/Surface',
                'eco_status': eco_status,
                'eco_label': ECO_STATUS_LABELS.get(str(eco_status), 'N/A'),
                'chem_status': chem_status,
                'chem_label': CHEM_STATUS_LABELS.get(str(chem_status), 'N/A'),
                'year': attr.get('cYear', 2022),
            }
    
    for f in gw_quality['features']:
        attr = f['attributes']
        wb_code = attr.get('euGroundWaterBodyCode')
        if wb_code:
            chem_status = attr.get('gwChemicalStatusValue')
            wb_info[wb_code] = {
                'wb_name': attr.get('groundWaterBodyName', 'Unknown'),
                'wb_type': 'Groundwater',
                'eco_status': None,
                'eco_label': 'N/A',
                'chem_status': chem_status,
                'chem_label': CHEM_STATUS_LABELS.get(str(chem_status), 'N/A'),
                'chem_assessment_year': attr.get('gwChemicalAssessmentYear'),
                'year': attr.get('cYear', 2022),
            }
    
    print(f"Water bodies with quality info: {len(wb_info)}")
    
    # Build station details
    station_details = []
    
    for f in sites['features']:
        attr = f['attributes']
        lat = attr.get('lat')
        lon = attr.get('lon')
        if not lat or not lon:
            continue
        
        site_type = attr.get('specialisedZoneType')
        wb_code = attr.get('featureOfInterestIdentifier')
        wb = wb_info.get(wb_code, {})
        
        # Get risk scores
        eco_risk = ECO_STATUS_RISK.get(str(wb.get('eco_status'))) if wb.get('eco_status') else None
        chem_risk = CHEM_STATUS_RISK.get(str(wb.get('chem_status'))) if wb.get('chem_status') else None
        
        station = {
            'id': attr.get('thematicIdIdentifier'),
            'name': attr.get('nameText', 'Unknown'),
            'lat': lat,
            'lon': lon,
            'type': 'Groundwater' if site_type == 'groundWaterBody' else 'Surface Water',
            'wb_code': wb_code,
            'wb_name': wb.get('wb_name', 'Unknown'),
            'eco_status': wb.get('eco_label'),
            'chem_status': wb.get('chem_label'),
            'eco_risk': eco_risk,
            'chem_risk': chem_risk,
            'assessment_year': wb.get('chem_assessment_year') or wb.get('year'),
            'start_date': attr.get('operationalActivityPeriodBegin'),
        }
        station_details.append(station)
    
    print(f"Stations with details: {len(station_details)}")
    
    # Load municipalities
    municipalities = load_json(WEB_DATA / 'municipalities.json')
    
    # Assign stations to municipalities
    muni_stations = defaultdict(list)
    
    for station in station_details:
        if station['chem_risk'] is None and station['eco_risk'] is None:
            continue
        
        # Find nearest municipality
        min_dist = float('inf')
        nearest_muni = None
        
        for muni in municipalities:
            if 'lat' not in muni or 'lon' not in muni:
                continue
            dist = ((station['lat'] - muni['lat'])**2 + (station['lon'] - muni['lon'])**2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                nearest_muni = muni['name']
        
        if nearest_muni and min_dist < 0.3:
            muni_stations[nearest_muni].append(station)
    
    print(f"Municipalities with stations: {len(muni_stations)}")
    
    # Calculate risk per municipality and save station list
    muni_wq = {}
    
    for muni_name, stations in muni_stations.items():
        chem_risks = [s['chem_risk'] for s in stations if s['chem_risk'] is not None]
        eco_risks = [s['eco_risk'] for s in stations if s['eco_risk'] is not None]
        
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
        
        # Sort stations by name
        sorted_stations = sorted(stations, key=lambda x: x['name'])
        
        muni_wq[muni_name] = {
            'wq_risk': round(combined_risk, 3),
            'wq_chem_risk': round(avg_chem, 3) if avg_chem is not None else None,
            'wq_eco_risk': round(avg_eco, 3) if avg_eco is not None else None,
            'wq_stations': len(stations),
            'wq_gw_stations': sum(1 for s in stations if s['type'] == 'Groundwater'),
            'wq_sw_stations': sum(1 for s in stations if s['type'] == 'Surface Water'),
            'wq_station_list': [{
                'name': s['name'],
                'type': s['type'],
                'chem_status': s['chem_status'],
                'eco_status': s['eco_status'],
                'year': s['assessment_year'],
                'start': s['start_date'],
            } for s in sorted_stations[:20]]  # Limit to 20 stations
        }
    
    # Update municipalities.json
    for muni in municipalities:
        name = muni['name']
        if name in muni_wq:
            muni.update(muni_wq[name])
        else:
            muni['wq_risk'] = None
            muni['wq_stations'] = 0
            muni['wq_station_list'] = []
    
    with open(WEB_DATA / 'municipalities.json', 'w') as f:
        json.dump(municipalities, f)
    print(f"Updated: municipalities.json")
    
    # Update GeoJSON
    geojson = load_json(WEB_DATA / 'municipalities_risk.geojson')
    muni_lookup = {m['name']: m for m in municipalities}
    
    for feat in geojson['features']:
        name = feat['properties'].get('name')
        if name in muni_lookup:
            m = muni_lookup[name]
            feat['properties']['wq_risk'] = m.get('wq_risk')
            feat['properties']['wq_chem_risk'] = m.get('wq_chem_risk')
            feat['properties']['wq_eco_risk'] = m.get('wq_eco_risk')
            feat['properties']['wq_stations'] = m.get('wq_stations', 0)
    
    with open(WEB_DATA / 'municipalities_risk.geojson', 'w') as f:
        json.dump(geojson, f)
    print(f"Updated: municipalities_risk.geojson")
    
    # Stats
    risks = [v['wq_risk'] for v in muni_wq.values()]
    print(f"\nWater Quality Risk Distribution:")
    print(f"  Municipalities with data: {len(risks)}")
    print(f"  Min: {min(risks):.3f}, Max: {max(risks):.3f}")
    print(f"  Mean: {statistics.mean(risks):.3f}")

if __name__ == '__main__':
    main()

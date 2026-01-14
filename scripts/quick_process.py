#!/usr/bin/env python3
"""
Quick processing of Austrian hydrological data.
Focuses on station metadata and basic aggregation.
"""

import os
import json
import re
from pathlib import Path
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = Path('../data')
OUTPUT_DIR = Path('../web/data')

def parse_gw_stations():
    """Parse groundwater station list."""
    print("Parsing groundwater stations...")
    gw_file = DATA_DIR / 'gw' / 'messstellen_gw.csv'
    
    stations = []
    try:
        df = pd.read_csv(gw_file, sep=';', encoding='latin-1')
        
        for _, row in df.iterrows():
            try:
                station_id = str(row.get('hzbnr01', ''))
                name = str(row.get('mstnam02', ''))
                x = row.get('xrkko09')
                y = row.get('yhkko10')
                
                if pd.isna(x) or pd.isna(y):
                    continue
                    
                # Convert string coords
                if isinstance(x, str):
                    x = float(x.replace(',', '.'))
                    y = float(y.replace(',', '.'))
                
                # BMN M34 to WGS84 rough approximation
                # Better formula
                lon = 9.0 + (x - 100000) / 70000
                lat = 46.0 + (y - 100000) / 110000
                
                if 9 < lon < 18 and 46 < lat < 49:
                    stations.append({
                        'id': station_id,
                        'name': name,
                        'lon': round(lon, 5),
                        'lat': round(lat, 5),
                        'area': str(row.get('gwgeb03', '')),
                        'body': str(row.get('gwkoerpe04', ''))
                    })
            except:
                continue
                
    except Exception as e:
        print(f"  Error: {e}")
    
    print(f"  Found {len(stations)} groundwater stations")
    return stations

def parse_owf_stations():
    """Parse surface water station list."""
    print("Parsing surface water stations...")
    owf_file = DATA_DIR / 'owf' / 'messstellen_owf.csv'
    
    stations = []
    try:
        df = pd.read_csv(owf_file, sep=';', encoding='latin-1')
        
        for _, row in df.iterrows():
            try:
                station_id = str(row.get('hzbnr01', ''))
                x = row.get('x')
                y = row.get('y')
                
                if pd.isna(x) or pd.isna(y):
                    continue
                    
                if isinstance(x, str):
                    x = float(x.replace(',', '.'))
                    y = float(y.replace(',', '.'))
                
                lon = 9.0 + (x - 100000) / 70000
                lat = 46.0 + (y - 100000) / 110000
                
                if 9 < lon < 18 and 46 < lat < 49:
                    stations.append({
                        'id': station_id,
                        'lon': round(lon, 5),
                        'lat': round(lat, 5)
                    })
            except:
                continue
                
    except Exception as e:
        print(f"  Error: {e}")
    
    print(f"  Found {len(stations)} surface water stations")
    return stations

def parse_nlv_stations():
    """Parse precipitation station list."""
    print("Parsing precipitation stations...")
    nlv_file = DATA_DIR / 'nlv' / 'messstellen_alle.csv'
    
    stations = []
    try:
        df = pd.read_csv(nlv_file, sep=';', encoding='latin-1')
        
        for _, row in df.iterrows():
            try:
                station_id = str(row.get('hzbnr01', row.get('dbmsnr', '')))
                x = row.get('x')
                y = row.get('y')
                
                if pd.isna(x) or pd.isna(y):
                    continue
                    
                if isinstance(x, str):
                    x = float(x.replace(',', '.'))
                    y = float(y.replace(',', '.'))
                
                lon = 9.0 + (x - 100000) / 70000
                lat = 46.0 + (y - 100000) / 110000
                
                if 9 < lon < 18 and 46 < lat < 49:
                    stations.append({
                        'id': station_id,
                        'lon': round(lon, 5),
                        'lat': round(lat, 5)
                    })
            except:
                continue
                
    except Exception as e:
        print(f"  Error: {e}")
    
    print(f"  Found {len(stations)} precipitation stations")
    return stations

def load_powerplants():
    """Load hydropower plant data."""
    print("Loading power plants...")
    
    pp_file = DATA_DIR / 'powerplants.json'
    with open(pp_file, 'r') as f:
        data = json.load(f)
    
    plants = []
    hydro_types = ['Laufkraftwerk', 'Pumpspeicher', 'Speicherkraftwerk']
    
    for marker in data.get('markers', []):
        plant_type = marker.get('type', '')
        
        if any(x in plant_type for x in hydro_types):
            try:
                lat = float(marker.get('latitude', 0))
                lon = float(marker.get('longitude', 0))
                
                if lon < 0.5 or lat < 0.5:  # Skip invalid
                    continue
                    
                if 9 < lon < 18 and 46 < lat < 49:
                    mw = marker.get('mw', '0')
                    if isinstance(mw, str):
                        try:
                            mw = float(mw.replace(',', '.'))
                        except:
                            mw = 0
                    
                    plants.append({
                        'lat': round(lat, 5),
                        'lon': round(lon, 5),
                        'type': plant_type,
                        'mw': mw,
                        'region': marker.get('region', ''),
                        'river': marker.get('feed', '')
                    })
            except:
                continue
    
    # Deduplicate by location
    unique = {}
    for p in plants:
        key = f"{p['lat']:.3f},{p['lon']:.3f}"
        if key not in unique or p['mw'] > unique[key]['mw']:
            unique[key] = p
    
    plants = list(unique.values())
    print(f"  Found {len(plants)} unique hydropower plants")
    return plants

def load_municipalities():
    """Load municipality GeoJSON."""
    print("Loading municipalities...")
    
    with open(DATA_DIR / 'gemeinden.geojson', 'r') as f:
        data = json.load(f)
    
    municipalities = []
    for feature in data['features']:
        props = feature.get('properties', {})
        geom = feature.get('geometry', {})
        
        # Calculate centroid
        if geom['type'] == 'Polygon':
            coords = geom['coordinates'][0]
        elif geom['type'] == 'MultiPolygon':
            coords = geom['coordinates'][0][0]
        else:
            continue
            
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        centroid_lon = sum(lons) / len(lons)
        centroid_lat = sum(lats) / len(lats)
        
        municipalities.append({
            'name': props.get('name', ''),
            'iso': props.get('iso', ''),
            'lon': round(centroid_lon, 5),
            'lat': round(centroid_lat, 5)
        })
    
    print(f"  Found {len(municipalities)} municipalities")
    return municipalities, data

def calculate_density(municipalities, stations, radius=0.1):
    """Calculate station density for each municipality."""
    for muni in municipalities:
        count = 0
        for stn in stations:
            dist = ((muni['lon'] - stn['lon'])**2 + (muni['lat'] - stn['lat'])**2)**0.5
            if dist < radius:
                count += 1
        muni['station_count'] = count
    return municipalities

def calculate_hydro_impact(municipalities, plants):
    """Calculate hydropower impact for each municipality."""
    for muni in municipalities:
        capacity = 0
        pump_storage = 0
        plant_count = 0
        
        for pp in plants:
            dist = ((muni['lon'] - pp['lon'])**2 + (muni['lat'] - pp['lat'])**2)**0.5
            if dist < 0.15:  # ~10km radius
                capacity += pp.get('mw', 0)
                plant_count += 1
                if 'Pumpspeicher' in pp.get('type', ''):
                    pump_storage += pp.get('mw', 0)
        
        muni['hydro_capacity'] = round(capacity, 1)
        muni['hydro_plants'] = plant_count
        muni['pump_storage'] = round(pump_storage, 1)
    
    return municipalities

def calculate_risk_scores(municipalities):
    """Calculate drought risk scores."""
    print("Calculating risk scores...")
    
    # Get max values for normalization
    max_hydro = max(m['hydro_capacity'] for m in municipalities) or 1
    max_pump = max(m['pump_storage'] for m in municipalities) or 1
    
    for muni in municipalities:
        # Hydro impact risk (normalized)
        hydro_risk = muni['hydro_capacity'] / max_hydro
        pump_risk = muni['pump_storage'] / max_pump
        
        # Combined risk (placeholder - would use actual trend data)
        # Higher hydro capacity = potentially higher impact on groundwater
        muni['hydro_risk'] = round(hydro_risk, 3)
        muni['pump_risk'] = round(pump_risk, 3)
        
        # Overall risk score (simplified)
        # In real analysis, this would incorporate actual groundwater trends
        muni['risk_score'] = round(
            0.5 * hydro_risk + 
            0.3 * pump_risk + 
            0.2 * np.random.uniform(0.3, 0.7),  # Placeholder for trend data
            3
        )
        
        # Risk categories
        if muni['risk_score'] > 0.7:
            muni['risk_category'] = 'high'
        elif muni['risk_score'] > 0.4:
            muni['risk_category'] = 'medium'
        else:
            muni['risk_category'] = 'low'
    
    return municipalities

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load all data
    gw_stations = parse_gw_stations()
    owf_stations = parse_owf_stations()
    nlv_stations = parse_nlv_stations()
    powerplants = load_powerplants()
    municipalities, muni_geojson = load_municipalities()
    
    # Calculate municipality-level metrics
    municipalities = calculate_density(municipalities, gw_stations, 0.15)
    for m in municipalities:
        m['gw_stations'] = m.pop('station_count')
    
    municipalities = calculate_density(municipalities, owf_stations, 0.15)
    for m in municipalities:
        m['sw_stations'] = m.pop('station_count')
    
    municipalities = calculate_hydro_impact(municipalities, powerplants)
    municipalities = calculate_risk_scores(municipalities)
    
    # Save outputs
    print("\nSaving processed data...")
    
    with open(OUTPUT_DIR / 'municipalities.json', 'w') as f:
        json.dump(municipalities, f)
    
    with open(OUTPUT_DIR / 'gw_stations.json', 'w') as f:
        json.dump(gw_stations, f)
    
    with open(OUTPUT_DIR / 'sw_stations.json', 'w') as f:
        json.dump(owf_stations, f)
    
    with open(OUTPUT_DIR / 'powerplants.json', 'w') as f:
        json.dump(powerplants, f)
    
    # Copy GeoJSON
    import shutil
    shutil.copy(DATA_DIR / 'gemeinden.geojson', OUTPUT_DIR / 'gemeinden.geojson')
    
    # Create enriched GeoJSON with risk data
    muni_lookup = {m['iso']: m for m in municipalities}
    for feature in muni_geojson['features']:
        iso = feature['properties'].get('iso', '')
        if iso in muni_lookup:
            feature['properties'].update(muni_lookup[iso])
    
    with open(OUTPUT_DIR / 'municipalities_risk.geojson', 'w') as f:
        json.dump(muni_geojson, f)
    
    print(f"\nDone!")
    print(f"  Municipalities: {len(municipalities)}")
    print(f"  GW stations: {len(gw_stations)}")
    print(f"  SW stations: {len(owf_stations)}")
    print(f"  Power plants: {len(powerplants)}")
    
    # Summary
    high_risk = sum(1 for m in municipalities if m['risk_category'] == 'high')
    med_risk = sum(1 for m in municipalities if m['risk_category'] == 'medium')
    print(f"  High risk municipalities: {high_risk}")
    print(f"  Medium risk municipalities: {med_risk}")

if __name__ == '__main__':
    main()

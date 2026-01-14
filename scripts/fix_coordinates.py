#!/usr/bin/env python3
"""
Fix groundwater station coordinates.
Converts from MGI Austria Lambert (EPSG:31287) to WGS84 (EPSG:4326).
"""

import json
import pandas as pd
from pathlib import Path
from pyproj import Transformer

DATA_DIR = Path('../data')
OUTPUT_DIR = Path('../web/data')

def parse_gw_stations_correct():
    """Parse groundwater stations with correct coordinate transformation."""
    print("Parsing groundwater stations with corrected coordinates...")
    gw_file = DATA_DIR / 'gw' / 'messstellen_gw.csv'
    
    # Create transformer from MGI Austria Lambert to WGS84
    transformer = Transformer.from_crs('EPSG:31287', 'EPSG:4326', always_xy=True)
    
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
                if isinstance(y, str):
                    y = float(y.replace(',', '.'))
                
                # Transform from MGI Austria Lambert to WGS84
                lon, lat = transformer.transform(x, y)
                
                # Validate Austria bounds
                if 9.5 < lon < 17.2 and 46.4 < lat < 49.0:
                    stations.append({
                        'id': station_id,
                        'name': name,
                        'lon': round(lon, 5),
                        'lat': round(lat, 5),
                        'area': str(row.get('gwgeb03', '')),
                        'body': str(row.get('gwkoerpe04', ''))
                    })
            except Exception as e:
                continue
                
    except Exception as e:
        print(f"  Error: {e}")
    
    print(f"  Found {len(stations)} groundwater stations")
    return stations

def main():
    # Get corrected stations
    corrected_stations = parse_gw_stations_correct()
    
    # Save corrected gw_stations.json
    with open(OUTPUT_DIR / 'gw_stations.json', 'w') as f:
        json.dump(corrected_stations, f)
    print(f"Saved corrected gw_stations.json")
    
    # Also update gw_stations_trends.json - preserve trend data but fix coords
    try:
        with open(OUTPUT_DIR / 'gw_stations_trends.json', 'r') as f:
            old_trends = json.load(f)
        
        # Build lookup by station ID from old trends (to preserve trend data)
        trend_data = {}
        for s in old_trends:
            if 'trend_m_per_decade' in s:
                trend_data[s['id']] = {
                    'station_id': s.get('station_id', s['id']),
                    'trend_m_per_decade': s['trend_m_per_decade'],
                    'p_value': s.get('p_value'),
                    'change_pct': s.get('change_pct', 0),
                    'data_years': s.get('data_years'),
                    'mean_level': s.get('mean_level'),
                    'current_level': s.get('current_level')
                }
        
        # Merge trend data with corrected coordinates
        for s in corrected_stations:
            if s['id'] in trend_data:
                s.update(trend_data[s['id']])
        
        # Save updated trends file
        with open(OUTPUT_DIR / 'gw_stations_trends.json', 'w') as f:
            json.dump(corrected_stations, f)
        print(f"Saved corrected gw_stations_trends.json")
        
    except Exception as e:
        print(f"Error updating trends file: {e}")
    
    # Print some samples to verify
    print("\nSample corrected coordinates:")
    for s in corrected_stations[:5]:
        print(f"  {s['name']}: lat={s['lat']}, lon={s['lon']}")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Build river network from OWF station data."""

import csv
import json
from pathlib import Path
from collections import defaultdict

def load_owf_stations():
    """Load surface water station metadata."""
    stations = []
    with open('data/owf/messstellen_owf.csv', 'r', encoding='latin-1') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            try:
                stations.append({
                    'id': row['hzbnr01'],
                    'name': row['mstnam02'],
                    'river': row['gew03'],
                    'km': float(row['mpua04'].replace(',', '.')) if row['mpua04'] else None,
                    'catchment_km2': float(row['egarea05'].replace(',', '.')) if row['egarea05'] else None,
                    'x': float(row['xrkko08'].replace(',', '.')) if row['xrkko08'] else None,
                    'y': float(row['yhkko09'].replace(',', '.')) if row['yhkko09'] else None,
                })
            except (ValueError, KeyError) as e:
                continue
    return stations

def build_river_dict(stations):
    """Group stations by river."""
    rivers = defaultdict(list)
    for s in stations:
        if s['river'] and s['km'] is not None:
            rivers[s['river']].append(s)
    # Sort by km (river position)
    for river in rivers:
        rivers[river].sort(key=lambda x: x['km'])
    return dict(rivers)

def identify_major_rivers(rivers):
    """Identify major Austrian rivers."""
    major = ['Donau', 'Inn', 'Mur', 'Drau', 'Salzach', 'Enns', 'Traun', 'Raab']
    found = {}
    for river, stations in rivers.items():
        for m in major:
            if m.lower() in river.lower():
                if m not in found or len(stations) > len(found[m]):
                    found[m] = {'name': river, 'stations': len(stations)}
    return found

if __name__ == '__main__':
    print("Loading OWF stations...")
    stations = load_owf_stations()
    print(f"Loaded {len(stations)} stations")
    
    rivers = build_river_dict(stations)
    print(f"Found {len(rivers)} rivers")
    
    # Top rivers by station count
    top = sorted(rivers.items(), key=lambda x: len(x[1]), reverse=True)[:20]
    print("\nTop rivers by station count:")
    for r, s in top:
        print(f"  {r}: {len(s)} stations")
    
    # Save river network
    output = {
        'rivers': {r: [{'id': s['id'], 'name': s['name'], 'km': s['km']} 
                       for s in stations] 
                   for r, stations in rivers.items()},
        'station_count': len(stations),
        'river_count': len(rivers)
    }
    
    Path('data/river_network.json').write_text(json.dumps(output, indent=2))
    print("\nSaved to data/river_network.json")

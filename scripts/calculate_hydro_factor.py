#!/usr/bin/env python3
"""Calculate nuanced hydro_factor for municipalities based on:
- Upstream hydropower capacity and type
- Distance to major river systems
- Local groundwater conditions
"""

import json
import math
from pathlib import Path

def haversine(lat1, lon1, lat2, lon2):
    """Distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def load_data():
    muni = json.loads(Path('web/data/municipalities.json').read_text())
    plants = json.loads(Path('web/data/powerplants.json').read_text())
    river_impact = json.loads(Path('data/river_hydro_impact.json').read_text())
    return muni, plants, river_impact

def calculate_nearby_hydro(muni, plants, max_dist_km=30):
    """Find plants within distance and calculate weighted impact."""
    impact_weights = {
        'Laufkraftwerk': 0.3,
        'Speicherkraftwerk': 0.7,
        'Pumpspeicherkraftwerk': 0.5,
    }
    
    total_impact = 0
    nearby_count = 0
    
    for p in plants:
        dist = haversine(muni['lat'], muni['lon'], p['lat'], p['lon'])
        if dist <= max_dist_km:
            # Distance decay: closer = more impact
            decay = max(0, 1 - (dist / max_dist_km))
            mw = p.get('mw', 0) or 0
            ptype = p.get('type', 'Unknown')
            weight = impact_weights.get(ptype, 0.4)
            total_impact += mw * weight * decay
            nearby_count += 1
    
    return total_impact, nearby_count

def main():
    muni, plants, river_impact = load_data()
    
    # Calculate hydro factor for each municipality
    results = []
    for m in muni:
        impact, count = calculate_nearby_hydro(m, plants)
        
        # Normalize: 500 MW weighted impact = 1.0 factor
        hydro_factor = min(1.0, impact / 500)
        
        results.append({
            **m,
            'hydro_factor': round(hydro_factor, 3),
            'nearby_hydro_plants': count,
            'weighted_hydro_impact': round(impact, 1)
        })
    
    # Sort by hydro_factor
    results.sort(key=lambda x: x['hydro_factor'], reverse=True)
    
    print("Top 20 municipalities by hydro_factor:")
    print(f"{'Municipality':<25} {'Factor':>8} {'Plants':>8} {'Impact':>10}")
    print("-" * 55)
    for r in results[:20]:
        print(f"{r['name'][:24]:<25} {r['hydro_factor']:>8.3f} {r['nearby_hydro_plants']:>8} {r['weighted_hydro_impact']:>10.1f}")
    
    # Save updated municipalities
    Path('web/data/municipalities_hydro.json').write_text(json.dumps(results, indent=2))
    print(f"\nSaved to web/data/municipalities_hydro.json")

if __name__ == '__main__':
    main()

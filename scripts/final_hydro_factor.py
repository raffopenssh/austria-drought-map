#!/usr/bin/env python3
"""Calculate final hydro_factor combining all data sources."""

import json
import math
from pathlib import Path

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def load_all_data():
    muni = json.loads(Path('web/data/municipalities.json').read_text())
    plants = json.loads(Path('web/data/powerplants.json').read_text())
    sediment = json.loads(Path('data/sediment_analysis.json').read_text())
    owf_meta = []
    with open('data/owf/messstellen_owf.csv', 'r', encoding='latin-1') as f:
        import csv
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            try:
                owf_meta.append({
                    'id': row['hzbnr01'],
                    'name': row['mstnam02'],
                    'river': row['gew03'],
                    'x': float(row['xrkko08'].replace(',', '.')) if row['xrkko08'] else None,
                    'y': float(row['yhkko09'].replace(',', '.')) if row['yhkko09'] else None,
                })
            except:
                continue
    return muni, plants, sediment, owf_meta

def calculate_factor(m, plants, sediment, owf_meta):
    impact_weights = {'Laufkraftwerk': 0.3, 'Speicherkraftwerk': 0.7, 'Pumpspeicherkraftwerk': 0.5}
    
    # 1. Nearby hydropower impact (30km radius)
    hydro_impact = 0
    for p in plants:
        dist = haversine(m['lat'], m['lon'], p['lat'], p['lon'])
        if dist <= 30:
            decay = max(0, 1 - (dist / 30))
            mw = p.get('mw', 0) or 0
            weight = impact_weights.get(p.get('type', ''), 0.4)
            hydro_impact += mw * weight * decay
    
    # 2. Sediment trends (negative trend = less sediment = bad for groundwater)
    # Find nearby sediment stations
    sed_factor = 0
    for s in sediment:
        # Match to OWF stations for coordinates
        for owf in owf_meta:
            if owf['id'] == s['hzb'] and owf['x'] and owf['y']:
                # Convert BMN to approx lat/lon
                lat_approx = 46 + (owf['y'] - 150000) / 111000
                lon_approx = 9 + (owf['x'] - 100000) / 75000
                dist = haversine(m['lat'], m['lon'], lat_approx, lon_approx)
                if dist <= 50:
                    # Negative trend = more impact
                    sed_factor += max(0, -s['trend_pct'] / 100) * (1 - dist/50)
                break
    
    # Combine: hydro_impact normalized to 500 MW, sediment factor as modifier
    base_factor = min(1.0, hydro_impact / 500)
    final_factor = min(1.0, base_factor * (1 + sed_factor * 0.2))
    
    return round(final_factor, 3), round(hydro_impact, 1), round(sed_factor, 3)

def main():
    muni, plants, sediment, owf_meta = load_all_data()
    
    results = []
    for m in muni:
        factor, impact, sed = calculate_factor(m, plants, sediment, owf_meta)
        results.append({
            **m,
            'hydro_factor': factor,
            'hydro_impact_score': impact,
            'sediment_modifier': sed
        })
    
    results.sort(key=lambda x: x['hydro_factor'], reverse=True)
    
    print("Top 15 by final hydro_factor:")
    print(f"{'Municipality':<22} {'Factor':>8} {'Impact':>10} {'Sed.Mod':>8}")
    print("-" * 52)
    for r in results[:15]:
        print(f"{r['name'][:21]:<22} {r['hydro_factor']:>8.3f} {r['hydro_impact_score']:>10.1f} {r['sediment_modifier']:>+8.3f}")
    
    # Save back to municipalities.json
    Path('web/data/municipalities.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nUpdated web/data/municipalities.json")

if __name__ == '__main__':
    main()

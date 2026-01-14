#!/usr/bin/env python3
"""Map hydropower plants to rivers and calculate cumulative impact."""

import json
from pathlib import Path
from collections import defaultdict

def load_powerplants():
    return json.loads(Path('web/data/powerplants.json').read_text())

def aggregate_by_river():
    """Group power plants by river and calculate stats."""
    plants = load_powerplants()
    rivers = defaultdict(lambda: {'total_mw': 0, 'plants': [], 'types': defaultdict(float)})
    
    for p in plants:
        river = p.get('river', '-')
        if river == '-' or not river:
            river = 'Unknown'
        mw = p.get('mw', 0) or 0
        ptype = p.get('type', 'Unknown')
        
        rivers[river]['total_mw'] += mw
        rivers[river]['plants'].append(p)
        rivers[river]['types'][ptype] += mw
    
    return dict(rivers)

def calculate_impact_factors():
    """Calculate impact factors for each plant type."""
    # Impact on groundwater/sediment (higher = worse)
    return {
        'Laufkraftwerk': 0.3,       # Run-of-river: moderate sediment trap
        'Speicherkraftwerk': 0.7,   # Storage: major sediment trap
        'Pumpspeicherkraftwerk': 0.5,  # Pumped storage: moderate impact
    }

def main():
    rivers = aggregate_by_river()
    impacts = calculate_impact_factors()
    
    # Calculate weighted impact per river
    river_impacts = []
    for river, data in rivers.items():
        weighted_impact = 0
        for ptype, mw in data['types'].items():
            impact = impacts.get(ptype, 0.4)  # default moderate
            weighted_impact += mw * impact
        
        river_impacts.append({
            'river': river,
            'total_mw': data['total_mw'],
            'weighted_impact': weighted_impact,
            'plant_count': len(data['plants']),
            'types': dict(data['types'])
        })
    
    # Sort by total MW
    river_impacts.sort(key=lambda x: x['total_mw'], reverse=True)
    
    print("Rivers by hydropower capacity:")
    print(f"{'River':<20} {'MW':>10} {'Plants':>8} {'Impact':>10}")
    print("-" * 50)
    for r in river_impacts[:25]:
        print(f"{r['river'][:19]:<20} {r['total_mw']:>10.1f} {r['plant_count']:>8} {r['weighted_impact']:>10.1f}")
    
    # Save
    output = {
        'river_impacts': river_impacts,
        'impact_factors': impacts
    }
    Path('data/river_hydro_impact.json').write_text(json.dumps(output, indent=2))
    print(f"\nSaved to data/river_hydro_impact.json")

if __name__ == '__main__':
    main()

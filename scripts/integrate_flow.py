#!/usr/bin/env python3
"""Integrate surface water flow into municipality risk model.

Links flow data to:
- Hydropower (dam releases affect downstream flow)
- Sediment (flow affects sediment transport capacity)
"""

import json
import math
from pathlib import Path

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def load_data():
    muni = json.loads(Path('web/data/municipalities.json').read_text())
    flow = json.loads(Path('data/flow_analysis.json').read_text())
    plants = json.loads(Path('web/data/powerplants.json').read_text())
    sediment = json.loads(Path('data/sediment_analysis.json').read_text())
    
    # Filter flow stations with coordinates
    flow = [f for f in flow if f.get('lat') and f.get('lon')]
    return muni, flow, plants, sediment

def find_nearby_flow(muni, flow_stations, max_dist_km=30):
    """Find flow stations near municipality.
    
    If no stations within max_dist_km, expand search to find nearest 3 stations.
    """
    # First try within standard radius
    nearby = []
    for f in flow_stations:
        dist = haversine(muni['lat'], muni['lon'], f['lat'], f['lon'])
        if dist <= max_dist_km:
            nearby.append({**f, 'dist': dist})
    
    # If no nearby stations, find nearest 3 regardless of distance
    estimated = False
    if not nearby:
        all_with_dist = []
        for f in flow_stations:
            dist = haversine(muni['lat'], muni['lon'], f['lat'], f['lon'])
            all_with_dist.append({**f, 'dist': dist})
        all_with_dist.sort(key=lambda x: x['dist'])
        nearby = all_with_dist[:3]  # Take nearest 3
        estimated = True
    
    if not nearby:
        return None, None, 0, [], False
    
    # Distance-weighted average trend
    total_weight = 0
    weighted_trend = 0
    weighted_flow = 0
    
    for f in nearby:
        weight = 1 / (1 + f['dist'])
        weighted_trend += f['trend_pct_decade'] * weight
        weighted_flow += f['mean_flow_m3s'] * weight
        total_weight += weight
    
    if total_weight > 0:
        avg_trend = weighted_trend / total_weight
        avg_flow = weighted_flow / total_weight
        # Get rivers
        rivers = list(set(f['river'] for f in nearby if f.get('river')))
        return avg_trend, avg_flow, len(nearby), rivers[:4], estimated
    
    return None, None, 0, [], False

def check_hydro_influence(muni, plants, flow_rivers, max_dist_km=50):
    """Check if nearby hydropower affects flow on these rivers."""
    influenced_mw = 0
    for p in plants:
        dist = haversine(muni['lat'], muni['lon'], p['lat'], p['lon'])
        if dist <= max_dist_km and p.get('river') in flow_rivers:
            influenced_mw += p.get('mw', 0) or 0
    return influenced_mw

def check_sediment_correlation(flow_rivers, sediment_data):
    """Check sediment trends on same rivers."""
    matching = [s for s in sediment_data if s.get('river') in flow_rivers]
    if matching:
        avg_sed_trend = sum(s['trend_pct'] for s in matching) / len(matching)
        return avg_sed_trend, len(matching)
    return None, 0

def calculate_flow_risk(trend_pct):
    """Convert flow trend to risk factor.
    
    Declining flow = higher drought risk
    Scale: -20% per decade = 100% risk, +20% = 0% risk
    """
    if trend_pct is None:
        return None
    clamped = max(-20, min(20, trend_pct))
    risk = (20 - clamped) / 40  # Maps -20..+20 to 1..0
    return round(risk, 3)

def recalculate_risk_score(muni):
    """Recalculate composite risk with flow.
    
    New weights:
    - Groundwater: 35%
    - Hydropower: 25%
    - Precipitation: 25%
    - Surface water flow: 15%
    """
    gw_risk = muni.get('gw_risk', 0) or 0
    hydro_factor = muni.get('hydro_factor', 0) or 0
    precip_risk = muni.get('precip_risk', 0.5) or 0.5
    flow_risk = muni.get('flow_risk', 0.5) or 0.5
    
    risk_score = (gw_risk * 0.35) + (hydro_factor * 0.25) + (precip_risk * 0.25) + (flow_risk * 0.15)
    
    if risk_score >= 0.6:
        category = 'high'
    elif risk_score >= 0.4:
        category = 'medium'
    else:
        category = 'low'
    
    return round(risk_score, 3), category

def main():
    muni, flow, plants, sediment = load_data()
    print(f"Loaded {len(muni)} municipalities, {len(flow)} flow stations")
    
    results = []
    with_flow = 0
    hydro_influenced = 0
    
    for m in muni:
        trend, mean_flow, station_count, rivers, estimated = find_nearby_flow(m, flow)
        flow_risk = calculate_flow_risk(trend)
        
        # Check hydropower influence on these rivers
        hydro_mw = check_hydro_influence(m, plants, rivers) if rivers else 0
        
        # Check sediment correlation
        sed_trend, sed_count = check_sediment_correlation(rivers, sediment) if rivers else (None, 0)
        
        # Update municipality data
        m['flow_trend_pct'] = round(trend, 1) if trend else None
        m['flow_mean_m3s'] = round(mean_flow, 1) if mean_flow else None
        m['flow_stations'] = station_count
        m['flow_rivers'] = rivers if rivers else []
        m['flow_estimated'] = estimated
        m['flow_risk'] = flow_risk
        m['flow_hydro_mw'] = hydro_mw  # MW of hydro on same rivers
        m['flow_sediment_trend'] = round(sed_trend, 1) if sed_trend else None
        
        if flow_risk is not None:
            with_flow += 1
        if hydro_mw > 0:
            hydro_influenced += 1
        
        # Recalculate composite risk
        m['risk_score'], m['risk_category'] = recalculate_risk_score(m)
        results.append(m)
    
    results.sort(key=lambda x: x['risk_score'], reverse=True)
    
    print(f"\nFlow data added to {with_flow}/{len(muni)} municipalities")
    print(f"Hydropower-influenced flow: {hydro_influenced} municipalities")
    
    print(f"\nTop 15 by new risk score:")
    print(f"{'Municipality':<20} {'Risk':>6} {'GW':>5} {'Hyd':>5} {'Prc':>5} {'Flow':>5} {'FlwTr':>8}")
    print("-" * 62)
    for m in results[:15]:
        ft = f"{m['flow_trend_pct']:+.0f}%" if m['flow_trend_pct'] else 'N/A'
        print(f"{m['name'][:19]:<20} {m['risk_score']*100:>5.1f}% {m.get('gw_risk',0)*100:>4.0f}% {m.get('hydro_factor',0)*100:>4.0f}% {(m.get('precip_risk',0) or 0)*100:>4.0f}% {(m.get('flow_risk',0) or 0)*100:>4.0f}% {ft:>8}")
    
    # Risk categories
    high = len([m for m in results if m['risk_category'] == 'high'])
    med = len([m for m in results if m['risk_category'] == 'medium'])
    print(f"\nRisk categories: {high} high, {med} medium, {len(results)-high-med} low")
    
    # Save
    Path('web/data/municipalities.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nUpdated web/data/municipalities.json")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Integrate precipitation data into municipality risk scores."""

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
    precip = json.loads(Path('data/precipitation_analysis.json').read_text())
    # Filter stations with coordinates
    precip = [p for p in precip if p.get('lat') and p.get('lon')]
    return muni, precip

def find_nearby_precip(muni, precip_stations, max_dist_km=30):
    """Find precipitation stations near municipality and calculate weighted average.
    
    If no stations within max_dist_km, expand search to find nearest 3 stations.
    """
    # First try within standard radius
    nearby = []
    for p in precip_stations:
        dist = haversine(muni['lat'], muni['lon'], p['lat'], p['lon'])
        if dist <= max_dist_km:
            nearby.append({**p, 'dist': dist})
    
    # If no nearby stations, find nearest 3 regardless of distance
    estimated = False
    if not nearby:
        all_with_dist = []
        for p in precip_stations:
            dist = haversine(muni['lat'], muni['lon'], p['lat'], p['lon'])
            all_with_dist.append({**p, 'dist': dist})
        all_with_dist.sort(key=lambda x: x['dist'])
        nearby = all_with_dist[:3]  # Take nearest 3
        estimated = True
    
    if not nearby:
        return None, None, 0, False
    
    # Distance-weighted average trend
    total_weight = 0
    weighted_trend = 0
    weighted_mean = 0
    
    for p in nearby:
        weight = 1 / (1 + p['dist'])  # Inverse distance weighting
        weighted_trend += p['trend_mm_decade'] * weight
        weighted_mean += p['mean_annual_mm'] * weight
        total_weight += weight
    
    if total_weight > 0:
        avg_trend = weighted_trend / total_weight
        avg_mean = weighted_mean / total_weight
        return avg_trend, avg_mean, len(nearby), estimated
    
    return None, None, 0, False

def calculate_precip_risk(trend_mm, mean_mm):
    """Convert precipitation trend to risk factor (0-1).
    
    Declining precipitation = higher risk
    Scale: -100 mm/decade = 1.0 risk, +100 mm/decade = 0.0 risk
    """
    if trend_mm is None:
        return None
    
    # Normalize: -100mm/dec -> 1.0, +100mm/dec -> 0.0
    # Clamp to reasonable range
    clamped = max(-100, min(100, trend_mm))
    risk = (100 - clamped) / 200  # Maps -100..+100 to 1..0
    return round(risk, 3)

def recalculate_risk_score(muni):
    """Recalculate composite risk score with precipitation.
    
    New weights:
    - Groundwater trend: 40%
    - Hydropower impact: 30%
    - Precipitation trend: 30%
    """
    gw_risk = muni.get('gw_risk', 0) or 0
    hydro_factor = muni.get('hydro_factor', 0) or 0
    precip_risk = muni.get('precip_risk', 0.5) or 0.5  # Default to neutral
    
    # Weighted combination
    risk_score = (gw_risk * 0.4) + (hydro_factor * 0.3) + (precip_risk * 0.3)
    
    # Categorize
    if risk_score >= 0.6:
        category = 'high'
    elif risk_score >= 0.4:
        category = 'medium'
    else:
        category = 'low'
    
    return round(risk_score, 3), category

def main():
    muni, precip = load_data()
    print(f"Loaded {len(muni)} municipalities, {len(precip)} precip stations with coords")
    
    results = []
    with_precip = 0
    
    for m in muni:
        trend, mean_precip, station_count, estimated = find_nearby_precip(m, precip)
        precip_risk = calculate_precip_risk(trend, mean_precip)
        
        # Update municipality data
        m['precip_trend_mm'] = round(trend, 1) if trend else None
        m['precip_mean_mm'] = round(mean_precip, 0) if mean_precip else None
        m['precip_stations'] = station_count
        m['precip_estimated'] = estimated
        m['precip_risk'] = precip_risk
        
        if precip_risk is not None:
            with_precip += 1
        
        # Recalculate composite risk
        m['risk_score'], m['risk_category'] = recalculate_risk_score(m)
        
        results.append(m)
    
    # Sort by new risk score
    results.sort(key=lambda x: x['risk_score'], reverse=True)
    
    print(f"\nPrecipitation data added to {with_precip}/{len(muni)} municipalities")
    
    print(f"\nTop 15 by new risk score:")
    print(f"{'Municipality':<22} {'Risk':>6} {'GW':>6} {'Hydro':>6} {'Precip':>6} {'P.Trend':>10}")
    print("-" * 65)
    for m in results[:15]:
        pt = f"{m['precip_trend_mm']:+.0f}mm" if m['precip_trend_mm'] else 'N/A'
        print(f"{m['name'][:21]:<22} {m['risk_score']*100:>5.1f}% {m.get('gw_risk',0)*100:>5.1f}% {m.get('hydro_factor',0)*100:>5.1f}% {(m.get('precip_risk',0) or 0)*100:>5.1f}% {pt:>10}")
    
    # Count risk categories
    high = len([m for m in results if m['risk_category'] == 'high'])
    med = len([m for m in results if m['risk_category'] == 'medium'])
    low = len([m for m in results if m['risk_category'] == 'low'])
    print(f"\nRisk categories: {high} high, {med} medium, {low} low")
    
    # Save
    Path('web/data/municipalities.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nUpdated web/data/municipalities.json")

if __name__ == '__main__':
    main()

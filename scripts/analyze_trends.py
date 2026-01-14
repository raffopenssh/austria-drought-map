#!/usr/bin/env python3
"""
Analyze groundwater and hydrological trends from eHYD data.
This processes a sample of stations to compute actual trends.
"""

import os
import json
import re
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = Path('../data')
OUTPUT_DIR = Path('../web/data')

def parse_ehyd_monthly(filepath):
    """Parse eHYD monthly CSV files."""
    try:
        with open(filepath, 'r', encoding='latin-1') as f:
            lines = f.readlines()
        
        # Find data start
        data_start = 0
        for i, line in enumerate(lines):
            if line.strip().startswith('01.'):
                data_start = i
                break
        
        dates = []
        values = []
        
        for line in lines[data_start:]:
            line = line.strip()
            if not line or 'L\xfccke' in line or 'Lücke' in line:
                continue
            
            parts = line.split(';')
            if len(parts) >= 2:
                try:
                    date_str = parts[0].strip()
                    date_match = re.match(r'(\d{2}\.\d{2}\.\d{4})', date_str)
                    if date_match:
                        date = pd.to_datetime(date_match.group(1), format='%d.%m.%Y')
                        
                        val_str = parts[1].strip().replace(',', '.')
                        val_str = re.sub(r'[^0-9.\-]', '', val_str)
                        if val_str:
                            val = float(val_str)
                            dates.append(date)
                            values.append(val)
                except:
                    continue
        
        if len(dates) > 100:
            return pd.Series(values, index=pd.DatetimeIndex(dates))
        return None
    except Exception as e:
        return None

def calculate_trend(series):
    """Calculate trend per decade using linear regression."""
    if series is None or len(series) < 120:  # At least 10 years
        return None, None, None
    
    try:
        # Resample to annual means
        annual = series.resample('Y').mean().dropna()
        if len(annual) < 10:
            return None, None, None
        
        # Check for realistic groundwater values (50-800m above sea level typical for Austria)
        mean_val = annual.mean()
        if mean_val < 50 or mean_val > 2000:
            return None, None, None
        
        # Check for reasonable variance (not flat or wild)
        std_val = annual.std()
        if std_val > 50 or std_val < 0.01:
            return None, None, None
        
        x = np.arange(len(annual))
        y = annual.values
        
        # Linear fit
        from scipy import stats
        slope, intercept, r, p, se = stats.linregress(x, y)
        
        # Trend per decade (realistic range: -2 to +2 m/decade)
        trend_per_decade = slope * 10
        if abs(trend_per_decade) > 5:  # Filter unrealistic trends
            return None, None, None
        
        # Recent vs historic comparison
        n = len(annual)
        if n >= 20:
            recent = annual[-10:].mean()
            historic = annual[:10].mean()
            change_pct = (recent - historic) / abs(historic) * 100 if historic != 0 else 0
        else:
            change_pct = 0
        
        return trend_per_decade, p, change_pct
    except:
        return None, None, None

def process_groundwater_trends():
    """Process groundwater trends from monthly data."""
    print("Analyzing groundwater trends...")
    
    gw_dir = DATA_DIR / 'gw' / 'Grundwasserstand-Monatsmittel'
    if not gw_dir.exists():
        print(f"  Directory not found: {gw_dir}")
        return []
    
    files = list(gw_dir.glob('*.csv'))[:500]  # Limit for speed
    print(f"  Processing {len(files)} files...")
    
    results = []
    declining = 0
    rising = 0
    
    for i, f in enumerate(files):
        if i % 100 == 0:
            print(f"    {i}/{len(files)}...")
        
        station_id = f.stem.split('-')[-1]
        series = parse_ehyd_monthly(f)
        
        if series is not None:
            trend, p_val, change = calculate_trend(series)
            
            if trend is not None:
                results.append({
                    'station_id': station_id,
                    'trend_m_per_decade': round(trend, 4),
                    'p_value': round(p_val, 4) if p_val else None,
                    'change_pct': round(change, 2) if change else 0,
                    'data_years': len(series) / 12,
                    'mean_level': round(series.mean(), 2),
                    'current_level': round(series[-12:].mean(), 2) if len(series) >= 12 else None
                })
                
                if trend < 0:
                    declining += 1
                else:
                    rising += 1
    
    print(f"  Analyzed {len(results)} stations")
    print(f"    Declining: {declining}")
    print(f"    Rising: {rising}")
    
    return results

def merge_trends_with_stations():
    """Merge trend data with station locations."""
    print("Merging trends with station data...")
    
    # Load existing station data
    with open(OUTPUT_DIR / 'gw_stations.json', 'r') as f:
        stations = json.load(f)
    
    station_lookup = {s['id']: s for s in stations}
    
    # Load trends
    trends = process_groundwater_trends()
    
    # Merge
    for t in trends:
        sid = t['station_id']
        if sid in station_lookup:
            station_lookup[sid].update(t)
    
    # Save merged data
    merged = list(station_lookup.values())
    with open(OUTPUT_DIR / 'gw_stations_trends.json', 'w') as f:
        json.dump(merged, f)
    
    print(f"  Saved {len(merged)} stations with trend data")
    return merged

def update_municipality_risk(gw_data):
    """Update municipality risk scores based on actual GW trends."""
    print("Updating municipality risk scores...")
    
    # Load municipalities
    with open(OUTPUT_DIR / 'municipalities.json', 'r') as f:
        municipalities = json.load(f)
    
    # Create station lookup by location
    gw_by_loc = {}
    for s in gw_data:
        if 'trend_m_per_decade' in s:
            key = f"{s['lat']:.2f},{s['lon']:.2f}"
            if key not in gw_by_loc:
                gw_by_loc[key] = []
            gw_by_loc[key].append(s)
    
    # Update each municipality
    for muni in municipalities:
        # Find nearby stations
        nearby_trends = []
        for key, stations in gw_by_loc.items():
            parts = key.split(',')
            slat, slon = float(parts[0]), float(parts[1])
            dist = ((muni['lat'] - slat)**2 + (muni['lon'] - slon)**2)**0.5
            if dist < 0.2:  # ~15km
                for s in stations:
                    if 'trend_m_per_decade' in s:
                        nearby_trends.append(s['trend_m_per_decade'])
        
        if nearby_trends:
            avg_trend = np.mean(nearby_trends)
            muni['gw_trend'] = round(avg_trend, 4)
            
            # Update risk score
            # Negative trend = declining groundwater = higher risk
            gw_risk = max(0, min(1, -avg_trend / 0.5))  # Normalize: -0.5m/decade = risk 1
            
            # Combine with hydro risk
            hydro_risk = muni.get('hydro_risk', 0)
            muni['gw_risk'] = round(gw_risk, 3)
            muni['risk_score'] = round(0.5 * gw_risk + 0.5 * hydro_risk, 3)
            muni['risk_category'] = 'high' if muni['risk_score'] > 0.6 else ('medium' if muni['risk_score'] > 0.3 else 'low')
    
    # Save updated municipalities
    with open(OUTPUT_DIR / 'municipalities.json', 'w') as f:
        json.dump(municipalities, f)
    
    # Update GeoJSON
    with open(OUTPUT_DIR / 'municipalities_risk.geojson', 'r') as f:
        geojson = json.load(f)
    
    muni_lookup = {m['iso']: m for m in municipalities}
    for feature in geojson['features']:
        iso = feature['properties'].get('iso', '')
        if iso in muni_lookup:
            feature['properties'].update(muni_lookup[iso])
    
    with open(OUTPUT_DIR / 'municipalities_risk.geojson', 'w') as f:
        json.dump(geojson, f)
    
    # Stats
    high_risk = sum(1 for m in municipalities if m.get('risk_category') == 'high')
    med_risk = sum(1 for m in municipalities if m.get('risk_category') == 'medium')
    print(f"  High risk municipalities: {high_risk}")
    print(f"  Medium risk municipalities: {med_risk}")

def main():
    gw_data = merge_trends_with_stations()
    update_municipality_risk(gw_data)
    print("\nTrend analysis complete!")

if __name__ == '__main__':
    main()

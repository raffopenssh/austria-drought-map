#!/usr/bin/env python3
"""
Analyze groundwater trends from ALL eHYD data.
Processes all stations with less restrictive filtering.
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
        
        # Find data start - look for lines starting with date pattern
        data_start = 0
        for i, line in enumerate(lines):
            if re.match(r'^\s*\d{2}\.\d{2}\.\d{4}', line.strip()):
                data_start = i
                break
        
        dates = []
        values = []
        
        for line in lines[data_start:]:
            line = line.strip()
            if not line:
                continue
            # Skip lines with "Lücke" (gap) markers
            if 'cke' in line.lower():  # Matches Lücke, lücke, etc.
                continue
            
            parts = line.split(';')
            if len(parts) >= 2:
                try:
                    date_str = parts[0].strip()
                    date_match = re.match(r'(\d{2}\.\d{2}\.\d{4})', date_str)
                    if date_match:
                        date = pd.to_datetime(date_match.group(1), format='%d.%m.%Y')
                        
                        val_str = parts[1].strip().replace(',', '.')
                        # Remove any non-numeric characters except . and -
                        val_str = re.sub(r'[^0-9.\-]', '', val_str)
                        if val_str and val_str != '-':
                            val = float(val_str)
                            if val > 0:  # Basic sanity check
                                dates.append(date)
                                values.append(val)
                except:
                    continue
        
        # Require at least 60 data points (5 years of monthly data)
        if len(dates) >= 60:
            return pd.Series(values, index=pd.DatetimeIndex(dates)).sort_index()
        return None
    except Exception as e:
        return None

def calculate_trend(series):
    """Calculate trend per decade using linear regression."""
    if series is None or len(series) < 60:  # At least 5 years
        return None, None, None, None, None
    
    try:
        # Remove duplicates and sort
        series = series[~series.index.duplicated(keep='first')].sort_index()
        
        # Remove outliers using IQR method (3x IQR)
        Q1 = series.quantile(0.25)
        Q3 = series.quantile(0.75)
        IQR = Q3 - Q1
        if IQR > 0:
            lower = Q1 - 3 * IQR
            upper = Q3 + 3 * IQR
            series = series[(series >= lower) & (series <= upper)]
        
        if len(series) < 60:
            return None, None, None, None, None
        
        # Resample to annual means
        annual = series.resample('YE').mean().dropna()
        if len(annual) < 5:
            return None, None, None, None, None
        
        x = np.arange(len(annual))
        y = annual.values
        
        # Basic sanity check - values should be reasonable (0-3000m for Austrian groundwater)
        mean_val = np.mean(y)
        if mean_val < 0 or mean_val > 3000:
            return None, None, None, None, None
        
        # Linear fit
        from scipy import stats
        slope, intercept, r, p, se = stats.linregress(x, y)
        
        # Trend per decade
        trend_per_decade = slope * 10
        
        # Filter extreme trends (> 2m per decade is unrealistic for groundwater)
        if abs(trend_per_decade) > 2:
            return None, None, None, None, None
        
        mean_level = float(np.mean(y))
        current_level = float(annual.iloc[-1]) if len(annual) > 0 else None
        
        return trend_per_decade, p, len(series) / 12, mean_level, current_level
    except Exception as e:
        return None, None, None, None, None

def process_all_groundwater_trends():
    """Process groundwater trends from ALL monthly data files."""
    print("Analyzing ALL groundwater trends...")
    
    gw_dir = DATA_DIR / 'gw' / 'Grundwasserstand-Monatsmittel'
    if not gw_dir.exists():
        print(f"  Directory not found: {gw_dir}")
        return []
    
    files = list(gw_dir.glob('*.csv'))
    print(f"  Processing {len(files)} files...")
    
    results = {}
    processed = 0
    with_trend = 0
    declining = 0
    rising = 0
    
    for i, f in enumerate(files):
        if i % 500 == 0:
            print(f"    {i}/{len(files)}...")
        
        # Extract station ID from filename
        station_id = f.stem.split('-')[-1]
        
        series = parse_ehyd_monthly(f)
        
        if series is not None:
            processed += 1
            trend, p_val, data_years, mean_level, current_level = calculate_trend(series)
            
            if trend is not None:
                with_trend += 1
                results[station_id] = {
                    'station_id': station_id,
                    'trend_m_per_decade': round(trend, 4),
                    'p_value': round(p_val, 4) if p_val is not None else None,
                    'data_years': round(data_years, 1),
                    'mean_level': round(mean_level, 2),
                    'current_level': round(current_level, 2) if current_level else None
                }
                
                if trend < 0:
                    declining += 1
                else:
                    rising += 1
    
    print(f"  Processed {processed} files with sufficient data")
    print(f"  Computed trends for {with_trend} stations")
    print(f"    Declining: {declining}")
    print(f"    Rising/Stable: {rising}")
    
    return results

def merge_trends_with_stations(trend_results):
    """Merge trend data with station locations."""
    print("Merging trends with station data...")
    
    # Load existing station data (with correct coordinates)
    with open(OUTPUT_DIR / 'gw_stations.json', 'r') as f:
        stations = json.load(f)
    
    # Merge trends into stations
    merged_count = 0
    for station in stations:
        sid = station['id']
        if sid in trend_results:
            station.update(trend_results[sid])
            merged_count += 1
    
    # Save merged data
    with open(OUTPUT_DIR / 'gw_stations_trends.json', 'w') as f:
        json.dump(stations, f)
    
    print(f"  Merged {merged_count} stations with trend data")
    print(f"  Total stations: {len(stations)}")
    
    return stations

def update_municipality_risk(gw_data):
    """Update municipality risk scores based on actual GW trends."""
    print("Updating municipality risk scores...")
    
    # Load municipalities
    with open(OUTPUT_DIR / 'municipalities.json', 'r') as f:
        municipalities = json.load(f)
    
    # Get stations with trends
    stations_with_trends = [s for s in gw_data if 'trend_m_per_decade' in s]
    print(f"  Using {len(stations_with_trends)} stations with trend data")
    
    # Update each municipality based on nearby stations
    updated = 0
    for muni in municipalities:
        nearby_trends = []
        for s in stations_with_trends:
            if s.get('lat') and s.get('lon'):
                dist = ((muni['lat'] - s['lat'])**2 + (muni['lon'] - s['lon'])**2)**0.5
                if dist < 0.3:  # ~25km radius
                    nearby_trends.append(s['trend_m_per_decade'])
        
        if nearby_trends:
            avg_trend = np.mean(nearby_trends)
            muni['gw_trend'] = round(avg_trend, 4)
            
            # Negative trend = declining groundwater = higher risk
            gw_risk = max(0, min(1, -avg_trend / 0.3))  # -0.3m/decade = max risk
            
            hydro_risk = muni.get('hydro_risk', 0) + muni.get('pump_risk', 0)
            muni['gw_risk'] = round(gw_risk, 3)
            muni['risk_score'] = round(0.4 * gw_risk + 0.6 * hydro_risk, 3)
            muni['risk_category'] = 'high' if muni['risk_score'] > 0.7 else ('medium' if muni['risk_score'] > 0.4 else 'low')
            updated += 1
    
    print(f"  Updated {updated} municipalities with GW data")
    
    # Save updated municipalities
    with open(OUTPUT_DIR / 'municipalities.json', 'w') as f:
        json.dump(municipalities, f)
    
    # Update GeoJSON
    with open(OUTPUT_DIR / 'municipalities_risk.geojson', 'r') as f:
        geojson = json.load(f)
    
    muni_lookup = {m['name']: m for m in municipalities}
    for feature in geojson['features']:
        name = feature['properties'].get('name', '')
        if name in muni_lookup:
            m = muni_lookup[name]
            for key in ['gw_trend', 'gw_risk', 'risk_score', 'risk_category']:
                if key in m:
                    feature['properties'][key] = m[key]
    
    with open(OUTPUT_DIR / 'municipalities_risk.geojson', 'w') as f:
        json.dump(geojson, f)
    
    # Stats
    high_risk = sum(1 for m in municipalities if m.get('risk_category') == 'high')
    med_risk = sum(1 for m in municipalities if m.get('risk_category') == 'medium')
    print(f"  High risk municipalities: {high_risk}")
    print(f"  Medium risk municipalities: {med_risk}")

def main():
    # Process all GW trends
    trend_results = process_all_groundwater_trends()
    
    # Merge with station coordinates
    gw_data = merge_trends_with_stations(trend_results)
    
    # Update municipality risk
    update_municipality_risk(gw_data)
    
    print("\nFull trend analysis complete!")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Recalculate groundwater trends with proper 10-year windows.
Stores both full history and recent trends for analysis.
"""

import os
import json
import re
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = Path('../data')
OUTPUT_DIR = Path('../web/data')

def parse_ehyd_monthly(filepath):
    """Parse eHYD monthly CSV files, returning full time series."""
    try:
        with open(filepath, 'r', encoding='latin-1') as f:
            lines = f.readlines()
        
        # Find data start
        data_start = 0
        for i, line in enumerate(lines):
            if re.match(r'^\s*\d{2}\.\d{2}\.\d{4}', line.strip()):
                data_start = i
                break
        
        dates = []
        values = []
        
        for line in lines[data_start:]:
            line = line.strip()
            if not line or 'cke' in line.lower():  # Skip gaps
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
                        if val_str and val_str != '-':
                            val = float(val_str)
                            if 0 < val < 3000:  # Reasonable for Austrian GW
                                dates.append(date)
                                values.append(val)
                except:
                    continue
        
        if len(dates) >= 60:  # At least 5 years
            series = pd.Series(values, index=pd.DatetimeIndex(dates)).sort_index()
            series = series[~series.index.duplicated(keep='first')]
            return series
        return None
    except:
        return None

def calculate_trends(series):
    """Calculate both full-period and recent 10-year trends."""
    if series is None or len(series) < 60:
        return None
    
    try:
        # Remove outliers (3x IQR)
        Q1, Q3 = series.quantile([0.25, 0.75])
        IQR = Q3 - Q1
        if IQR > 0:
            series = series[(series >= Q1 - 3*IQR) & (series <= Q3 + 3*IQR)]
        
        if len(series) < 60:
            return None
        
        # Annual means
        annual = series.resample('YE').mean().dropna()
        if len(annual) < 5:
            return None
        
        # Full period trend
        x_full = np.arange(len(annual))
        y_full = annual.values
        slope_full, _, _, p_full, _ = stats.linregress(x_full, y_full)
        trend_full = slope_full * 10  # per decade
        
        # Filter unrealistic
        if abs(trend_full) > 2:
            return None
        
        # Recent 10-year trend (last 10 years of data)
        cutoff = annual.index.max() - pd.DateOffset(years=10)
        recent = annual[annual.index >= cutoff]
        
        trend_10yr = None
        p_10yr = None
        if len(recent) >= 8:  # At least 8 years of recent data
            x_recent = np.arange(len(recent))
            y_recent = recent.values
            slope_recent, _, _, p_recent, _ = stats.linregress(x_recent, y_recent)
            trend_10yr = slope_recent * 10
            p_10yr = p_recent
            if abs(trend_10yr) > 2:
                trend_10yr = None
        
        # Get data range
        start_year = annual.index.min().year
        end_year = annual.index.max().year
        
        # Annual data for charting (year: value pairs)
        annual_data = {str(idx.year): round(float(val), 2) 
                       for idx, val in annual.items()}
        
        return {
            'trend_full_period': round(trend_full, 4),
            'p_value_full': round(p_full, 4),
            'trend_10yr': round(trend_10yr, 4) if trend_10yr else None,
            'p_value_10yr': round(p_10yr, 4) if p_10yr else None,
            'data_years': round(len(series) / 12, 1),
            'start_year': start_year,
            'end_year': end_year,
            'mean_level': round(float(series.mean()), 2),
            'current_level': round(float(annual.iloc[-1]), 2),
            'annual_data': annual_data
        }
    except:
        return None

def main():
    print("Recalculating groundwater trends with 10-year windows...")
    
    gw_dir = DATA_DIR / 'gw' / 'Grundwasserstand-Monatsmittel'
    files = list(gw_dir.glob('*.csv'))
    print(f"Processing {len(files)} stations...")
    
    # Load existing station data
    with open(OUTPUT_DIR / 'gw_stations.json') as f:
        stations = json.load(f)
    station_lookup = {s['id']: s for s in stations}
    
    results = []
    with_10yr_trend = 0
    declining_10yr = 0
    
    for i, f in enumerate(files):
        if i % 500 == 0:
            print(f"  {i}/{len(files)}...")
        
        station_id = f.stem.split('-')[-1]
        series = parse_ehyd_monthly(f)
        trends = calculate_trends(series)
        
        if trends and station_id in station_lookup:
            station = station_lookup[station_id].copy()
            station.update(trends)
            
            # Use 10-year trend if available, else full period
            if trends['trend_10yr'] is not None:
                station['trend_m_per_decade'] = trends['trend_10yr']
                station['p_value'] = trends['p_value_10yr']
                with_10yr_trend += 1
                if trends['trend_10yr'] < 0:
                    declining_10yr += 1
            else:
                station['trend_m_per_decade'] = trends['trend_full_period']
                station['p_value'] = trends['p_value_full']
            
            results.append(station)
    
    print(f"\nResults:")
    print(f"  Total stations with trends: {len(results)}")
    print(f"  Stations with 10-year trends: {with_10yr_trend}")
    print(f"  Declining (10yr): {declining_10yr}")
    
    # Save
    with open(OUTPUT_DIR / 'gw_stations_trends.json', 'w') as f:
        json.dump(results, f)
    
    print(f"Saved to gw_stations_trends.json")
    return results

if __name__ == '__main__':
    main()

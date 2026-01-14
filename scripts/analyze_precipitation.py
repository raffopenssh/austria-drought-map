#!/usr/bin/env python3
"""Analyze precipitation trends from NLV stations."""

import json
from pathlib import Path
from datetime import datetime
import numpy as np

def parse_precip_file(filepath):
    """Parse a precipitation CSV file."""
    with open(filepath, 'r', encoding='latin-1') as f:
        content = f.read().replace('\r\n', '\n').replace('\r', '\n')
    lines = content.split('\n')
    
    meta = {}
    data_start = 0
    for i, line in enumerate(lines):
        if line.startswith('Messstelle:'):
            meta['name'] = line.split(';')[1].strip()
        elif line.startswith('HZB-Nummer:'):
            meta['hzb'] = line.split(';')[1].strip()
        elif 'he [m' in line and ';' in line:
            # Height line
            pass
        elif 'nge (Grad' in line:  # Länge
            pass
        elif line.strip().startswith('01.') and 'g' not in line:
            # Found coordinates line with date format - next section has coords
            pass
        elif line.startswith('Werte:'):
            data_start = i + 1
            break
    
    # Try to get coordinates from metadata file
    values = []
    for line in lines[data_start:]:
        parts = line.strip().split(';')
        if len(parts) >= 2 and parts[0].strip():
            try:
                date = datetime.strptime(parts[0].strip(), '%d.%m.%Y %H:%M:%S')
                val = float(parts[1].strip().replace(',', '.'))
                values.append((date, val))
            except:
                continue
    return meta, values

def calculate_annual_totals(values):
    """Calculate annual precipitation totals."""
    by_year = {}
    for dt, val in values:
        year = dt.year
        by_year.setdefault(year, []).append(val)
    
    # Sum daily values for each year (only complete years with >300 days)
    annual = {}
    for year, vals in by_year.items():
        if len(vals) >= 300:  # At least 300 days of data
            annual[year] = sum(vals)
    return annual

def calculate_trend(annual):
    """Calculate linear trend in mm/decade."""
    if len(annual) < 10:
        return None, None
    
    years = sorted(annual.keys())
    values = [annual[y] for y in years]
    
    # Sanity check: reasonable annual precipitation (100-5000 mm)
    values_clean = [(y, v) for y, v in zip(years, values) if 100 < v < 5000]
    if len(values_clean) < 10:
        return None, None
    
    x = np.array([v[0] for v in values_clean])
    y = np.array([v[1] for v in values_clean])
    
    # Remove outliers (>2 std from mean)
    mean_y = np.mean(y)
    std_y = np.std(y)
    if std_y > 0:
        mask = np.abs(y - mean_y) < 2 * std_y
        x, y = x[mask], y[mask]
    
    if len(x) < 10:
        return None, None
    
    slope, intercept = np.polyfit(x, y, 1)
    trend_per_decade = slope * 10  # mm per decade
    
    # Mean annual precip
    mean_precip = np.mean(y)
    
    # Final sanity check on trend
    if abs(trend_per_decade) > 500:  # More than 500mm/decade is unrealistic
        return None, None
    
    return trend_per_decade, mean_precip

def load_station_coords():
    """Load station coordinates from metadata."""
    coords = {}
    meta_file = Path('data/nlv/messstellen_nlv.csv')
    if meta_file.exists():
        with open(meta_file, 'r', encoding='latin-1') as f:
            lines = f.readlines()
        # Parse header
        if lines:
            header = lines[0].strip().split(';')
            for line in lines[1:]:
                parts = line.strip().split(';')
                if len(parts) >= 10:
                    try:
                        hzb = parts[1].strip()
                        x = float(parts[8].replace(',', '.')) if parts[8] else None
                        y = float(parts[9].replace(',', '.')) if parts[9] else None
                        if x and y:
                            # Convert BMN to approx WGS84
                            lat = 46 + (y - 150000) / 111000
                            lon = 9 + (x - 100000) / 75000
                            coords[hzb] = {'lat': lat, 'lon': lon}
                    except:
                        continue
    return coords

def main():
    precip_dir = Path('data/nlv/N-Tagessummen')
    coords = load_station_coords()
    
    results = []
    processed = 0
    
    for f in sorted(precip_dir.glob('*.csv')):
        meta, values = parse_precip_file(f)
        if not values:
            continue
        
        annual = calculate_annual_totals(values)
        trend, mean_precip = calculate_trend(annual)
        
        if trend is not None and meta.get('hzb'):
            hzb = meta['hzb']
            coord = coords.get(hzb, {})
            
            results.append({
                'station': meta.get('name', 'Unknown'),
                'hzb': hzb,
                'lat': coord.get('lat'),
                'lon': coord.get('lon'),
                'mean_annual_mm': round(mean_precip, 0),
                'trend_mm_decade': round(trend, 1),
                'trend_pct_decade': round(trend / mean_precip * 100, 1) if mean_precip > 0 else 0,
                'years_data': len(annual)
            })
            processed += 1
    
    # Sort by trend
    results.sort(key=lambda x: x['trend_mm_decade'])
    
    print(f"Analyzed {processed} precipitation stations:")
    print(f"{'Station':<25} {'Mean mm':>10} {'Trend mm/dec':>12} {'Trend %':>10}")
    print("-" * 60)
    
    # Show driest trends (most declining)
    print("\nMost declining:")
    for r in results[:10]:
        print(f"{r['station'][:24]:<25} {r['mean_annual_mm']:>10.0f} {r['trend_mm_decade']:>+12.1f} {r['trend_pct_decade']:>+10.1f}%")
    
    print("\nMost increasing:")
    for r in results[-10:]:
        print(f"{r['station'][:24]:<25} {r['mean_annual_mm']:>10.0f} {r['trend_mm_decade']:>+12.1f} {r['trend_pct_decade']:>+10.1f}%")
    
    # Summary stats
    trends = [r['trend_mm_decade'] for r in results]
    declining = len([t for t in trends if t < 0])
    print(f"\nSummary: {declining}/{len(results)} stations show declining precipitation")
    print(f"Mean trend: {np.mean(trends):+.1f} mm/decade")
    
    # Save
    Path('data/precipitation_analysis.json').write_text(json.dumps(results, indent=2))
    print(f"\nSaved to data/precipitation_analysis.json")

if __name__ == '__main__':
    main()

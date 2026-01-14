#!/usr/bin/env python3
"""Analyze surface water flow trends from OWF Q-Tagesmittel stations."""

import json
import re
from pathlib import Path
from datetime import datetime
import numpy as np

def parse_flow_file(filepath):
    """Parse a flow (Q) CSV file."""
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
        elif 'sser:' in line and ';' in line:  # Gewässer
            parts = line.split(';')
            if len(parts) > 1:
                meta['river'] = parts[1].strip()
        elif 'Einzugsgebiet' in line and ';' in line:
            try:
                val = line.split(';')[1].strip().replace(',', '.')
                meta['catchment_km2'] = float(val)
            except:
                pass
        elif 'Rechtswert' in line and ';' in line:
            # BMN coordinates
            try:
                coords = line.split(';')[1].strip()
                match = re.search(r'([\d,]+)\s*-\s*([\d,]+)', coords)
                if match:
                    meta['x'] = float(match.group(1).replace(',', '.'))
                    meta['y'] = float(match.group(2).replace(',', '.'))
            except:
                pass
        elif line.startswith('Werte:'):
            data_start = i + 1
            break
    
    # Parse flow values
    values = []
    for line in lines[data_start:]:
        parts = line.strip().split(';')
        if len(parts) >= 2 and parts[0].strip():
            try:
                date = datetime.strptime(parts[0].strip(), '%d.%m.%Y %H:%M:%S')
                val = float(parts[1].strip().replace(',', '.'))
                if val >= 0:  # Flow can't be negative
                    values.append((date, val))
            except:
                continue
    
    return meta, values

def calculate_annual_stats(values):
    """Calculate annual mean flow."""
    by_year = {}
    for dt, val in values:
        year = dt.year
        by_year.setdefault(year, []).append(val)
    
    # Mean for years with enough data (>300 days)
    annual = {}
    for year, vals in by_year.items():
        if len(vals) >= 300:
            annual[year] = np.mean(vals)
    return annual

def calculate_trend(annual):
    """Calculate linear trend in m³/s per decade."""
    if len(annual) < 10:
        return None, None, None
    
    years = sorted(annual.keys())
    values = [annual[y] for y in years]
    
    x = np.array(years)
    y = np.array(values)
    
    # Remove outliers
    mean_y = np.mean(y)
    std_y = np.std(y)
    if std_y > 0:
        mask = np.abs(y - mean_y) < 2 * std_y
        x, y = x[mask], y[mask]
    
    if len(x) < 10:
        return None, None, None
    
    slope, intercept = np.polyfit(x, y, 1)
    trend_per_decade = slope * 10  # m³/s per decade
    mean_flow = np.mean(y)
    trend_pct = (trend_per_decade / mean_flow * 100) if mean_flow > 0 else 0
    
    return trend_per_decade, mean_flow, trend_pct

def load_owf_coords():
    """Load station coordinates from OWF metadata."""
    coords = {}
    meta_file = Path('data/owf/messstellen_owf.csv')
    if meta_file.exists():
        import csv
        with open(meta_file, 'r', encoding='latin-1') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                try:
                    hzb = row['hzbnr01'].strip()
                    x = float(row['xrkko08'].replace(',', '.')) if row['xrkko08'] else None
                    y = float(row['yhkko09'].replace(',', '.')) if row['yhkko09'] else None
                    if x and y:
                        # Convert BMN to WGS84 (approximate)
                        lat = 46 + (y - 150000) / 111000
                        lon = 9 + (x - 100000) / 75000
                        coords[hzb] = {'lat': lat, 'lon': lon, 'river': row.get('gew03', '')}
                except:
                    continue
    return coords

def main():
    flow_dir = Path('data/owf/Q-Tagesmittel')
    owf_coords = load_owf_coords()
    print(f"Loaded coordinates for {len(owf_coords)} OWF stations")
    
    results = []
    
    for f in sorted(flow_dir.glob('*.csv')):
        meta, values = parse_flow_file(f)
        if not values or not meta.get('hzb'):
            continue
        
        annual = calculate_annual_stats(values)
        trend, mean_flow, trend_pct = calculate_trend(annual)
        
        if trend is not None:
            hzb = meta['hzb']
            coord = owf_coords.get(hzb, {})
            lat = coord.get('lat')
            lon = coord.get('lon')
            river = meta.get('river') or coord.get('river', 'Unknown')
            
            results.append({
                'station': meta.get('name', 'Unknown'),
                'hzb': hzb,
                'river': river,
                'lat': round(lat, 5) if lat else None,
                'lon': round(lon, 5) if lon else None,
                'catchment_km2': meta.get('catchment_km2'),
                'mean_flow_m3s': round(mean_flow, 2),
                'trend_m3s_decade': round(trend, 3),
                'trend_pct_decade': round(trend_pct, 1),
                'years_data': len(annual)
            })
    
    # Sort by trend percentage
    results.sort(key=lambda x: x['trend_pct_decade'])
    
    print(f"Analyzed {len(results)} flow stations:")
    print(f"{'Station':<25} {'River':<12} {'Mean m³/s':>10} {'Trend %/dec':>12}")
    print("-" * 65)
    
    print("\nMost declining flow:")
    for r in results[:10]:
        print(f"{r['station'][:24]:<25} {r['river'][:11]:<12} {r['mean_flow_m3s']:>10.1f} {r['trend_pct_decade']:>+12.1f}%")
    
    print("\nMost increasing flow:")
    for r in results[-10:]:
        print(f"{r['station'][:24]:<25} {r['river'][:11]:<12} {r['mean_flow_m3s']:>10.1f} {r['trend_pct_decade']:>+12.1f}%")
    
    # Summary
    trends = [r['trend_pct_decade'] for r in results]
    declining = len([t for t in trends if t < 0])
    print(f"\nSummary: {declining}/{len(results)} stations show declining flow")
    print(f"Mean trend: {np.mean(trends):+.1f}% per decade")
    
    # Save
    Path('data/flow_analysis.json').write_text(json.dumps(results, indent=2))
    print(f"\nSaved to data/flow_analysis.json")

if __name__ == '__main__':
    main()

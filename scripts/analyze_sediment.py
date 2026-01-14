#!/usr/bin/env python3
"""Analyze sediment transport data from OWF stations."""

import json
from pathlib import Path
from datetime import datetime

def parse_sediment_file(filepath):
    """Parse a sediment CSV file."""
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
        elif 'sser:' in line and ';' in line:
            parts = line.split(';')
            if len(parts) > 1:
                meta['river'] = parts[1].strip()
        elif line.startswith('Werte:'):
            data_start = i + 1
            break
    
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

def analyze_trends(values):
    if not values:
        return None
    vals = [v[1] for v in values]
    by_year = {}
    for dt, v in values:
        by_year.setdefault(dt.year, []).append(v)
    yearly_avg = {y: sum(v)/len(v) for y, v in by_year.items()}
    sorted_years = sorted(yearly_avg.keys())
    if len(sorted_years) >= 6:
        recent = sum(yearly_avg[y] for y in sorted_years[-3:]) / 3
        older = sum(yearly_avg[y] for y in sorted_years[:3]) / 3
        trend = (recent - older) / older if older > 0 else 0
    else:
        trend = 0
    return {'mean': sum(vals)/len(vals), 'trend': trend, 'count': len(vals)}

def main():
    sed_dir = Path('data/owf/Schwebstoff-Tagesfracht')
    results = []
    for f in sorted(sed_dir.glob('*.csv')):
        meta, values = parse_sediment_file(f)
        stats = analyze_trends(values)
        if stats and meta.get('river'):
            results.append({
                'station': meta.get('name', 'Unknown'),
                'hzb': meta.get('hzb', ''),
                'river': meta['river'],
                'mean_daily_t': round(stats['mean'], 1),
                'trend_pct': round(stats['trend'] * 100, 1),
                'data_points': stats['count']
            })
    print(f"Analyzed {len(results)} sediment stations:")
    for r in sorted(results, key=lambda x: x['mean_daily_t'], reverse=True)[:15]:
        print(f"{r['station'][:19]:<20} {r['river'][:14]:<15} {r['mean_daily_t']:>10.1f}t {r['trend_pct']:>+8.1f}%")
    Path('data/sediment_analysis.json').write_text(json.dumps(results, indent=2))
    print(f"\nSaved to data/sediment_analysis.json")

if __name__ == '__main__':
    main()

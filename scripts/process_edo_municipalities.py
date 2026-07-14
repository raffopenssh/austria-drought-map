#!/usr/bin/env python3
"""
Extract EDO CDI values per Austrian municipality.
Calculate mean CDI for each municipality across all time periods.
"""
import os
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from collections import defaultdict

TIFF_DIR = Path('/home/exedev/austria-drought-map/data/edo/tiffs')
MUNI_GEOJSON = Path('/home/exedev/austria-drought-map/web/data/gemeinden.geojson')
OUTPUT_DIR = Path('/home/exedev/austria-drought-map/web/data')

def parse_date_from_filename(filename):
    parts = filename.split('_')
    date_str = parts[3]
    return datetime.strptime(date_str, '%Y%m%d')

def get_sample_tiffs():
    """Get a representative sample of tiffs (summer months, recent years)"""
    all_tiffs = sorted(TIFF_DIR.glob('cdinx_m_edo_*.tif'))
    
    # Focus on summer months (Jun-Sep) when drought matters most
    # Use recent 5 years for trend
    summer_tiffs = []
    for t in all_tiffs:
        date = parse_date_from_filename(t.name)
        if date.year >= 2019 and date.month in [6, 7, 8, 9]:
            summer_tiffs.append(t)
    
    print(f"Selected {len(summer_tiffs)} summer tiffs (2019-2023, Jun-Sep)")
    return summer_tiffs

def create_municipality_centroids():
    """Extract centroids from municipality GeoJSON"""
    with open(MUNI_GEOJSON) as f:
        geojson = json.load(f)
    
    centroids = []
    for feat in geojson['features']:
        props = feat['properties']
        geom = feat['geometry']
        
        # Calculate centroid from geometry
        if geom['type'] == 'Polygon':
            coords = geom['coordinates'][0]
        elif geom['type'] == 'MultiPolygon':
            # Use largest polygon
            largest = max(geom['coordinates'], key=lambda p: len(p[0]))
            coords = largest[0]
        else:
            continue
        
        # Simple centroid calculation
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        centroid = (sum(lons)/len(lons), sum(lats)/len(lats))
        
        centroids.append({
            'id': props.get('iso', props.get('id', '')),
            'name': props.get('name', ''),
            'lon': centroid[0],
            'lat': centroid[1]
        })
    
    return centroids

def sample_raster_at_points(tiff_path, centroids):
    """Sample raster values at centroid points using gdallocationinfo"""
    values = {}
    
    for c in centroids:
        try:
            result = subprocess.run(
                ['gdallocationinfo', '-valonly', '-geoloc', 
                 str(tiff_path), str(c['lon']), str(c['lat'])],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                val = float(result.stdout.strip())
                if val > -9000:  # Exclude nodata
                    values[c['id']] = val
        except:
            pass
    
    return values

def main():
    print("Processing EDO CDI per Municipality")
    print("=" * 50)
    
    # Get municipality centroids
    print("Loading municipalities...")
    centroids = create_municipality_centroids()
    print(f"  {len(centroids)} municipalities")
    
    # Get sample tiffs
    tiffs = get_sample_tiffs()
    
    # Accumulate values per municipality
    muni_values = defaultdict(list)
    
    for i, tiff in enumerate(tiffs):
        values = sample_raster_at_points(tiff, centroids)
        for muni_id, val in values.items():
            muni_values[muni_id].append(val)
        
        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(tiffs)} tiffs...")
    
    # Calculate mean CDI per municipality
    muni_cdi = {}
    for muni_id, vals in muni_values.items():
        if vals:
            muni_cdi[muni_id] = {
                'mean_cdi': round(sum(vals) / len(vals), 3),
                'max_cdi': round(max(vals), 3),
                'observations': len(vals)
            }
    
    print(f"\nCalculated CDI for {len(muni_cdi)} municipalities")
    
    # Save results
    output = {
        'metadata': {
            'source': 'Copernicus EDO',
            'period': '2019-2023 summer months (Jun-Sep)',
            'processed': datetime.now().isoformat()
        },
        'municipalities': muni_cdi
    }
    
    output_file = OUTPUT_DIR / 'edo_cdi_municipalities.json'
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"Saved to {output_file}")
    
    # Show distribution
    means = [v['mean_cdi'] for v in muni_cdi.values()]
    print(f"\nCDI Distribution:")
    print(f"  Min: {min(means):.2f}")
    print(f"  Max: {max(means):.2f}")
    print(f"  Mean: {sum(means)/len(means):.2f}")

if __name__ == '__main__':
    main()

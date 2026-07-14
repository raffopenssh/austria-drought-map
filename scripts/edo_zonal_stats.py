#!/usr/bin/env python3
"""
Calculate zonal statistics for EDO CDI data per Austrian municipality.
Uses municipality polygons to properly clip and aggregate raster values.

Outputs:
- edo_municipality_timeseries.json: Full time series per municipality
- edo_municipality_summary.json: Aggregated statistics per municipality
"""
import os
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import statistics

# Paths
TIFF_DIR = Path('/home/exedev/austria-drought-map/data/edo/tiffs')
MUNI_GEOJSON = Path('/home/exedev/austria-drought-map/web/data/gemeinden.geojson')
OUTPUT_DIR = Path('/home/exedev/austria-drought-map/web/data')
CACHE_DIR = Path('/home/exedev/austria-drought-map/data/edo/cache')

CACHE_DIR.mkdir(parents=True, exist_ok=True)

def parse_date_from_filename(filename):
    """Extract date from filename like cdinx_m_edo_20230101_t_400_z03.tif"""
    parts = filename.split('_')
    date_str = parts[3]
    return datetime.strptime(date_str, '%Y%m%d')

def load_municipalities():
    """Load municipality GeoJSON and return features with IDs"""
    with open(MUNI_GEOJSON) as f:
        data = json.load(f)
    
    municipalities = []
    for feat in data['features']:
        props = feat['properties']
        muni_id = props.get('iso', props.get('id', str(len(municipalities))))
        name = props.get('name', 'Unknown')
        municipalities.append({
            'id': muni_id,
            'name': name,
            'feature': feat
        })
    
    return municipalities

def calculate_zonal_stats_for_tiff(tiff_path, municipalities):
    """
    Calculate zonal statistics for each municipality using a single GeoTIFF.
    Uses exactextract if available, otherwise falls back to sampling approach.
    """
    cache_file = CACHE_DIR / f"{tiff_path.stem}_stats.json"
    
    # Check cache first
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)
    
    stats = {}
    
    # Create temp GeoJSON for each municipality and use gdalwarp + gdalinfo
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        for muni in municipalities:
            muni_id = muni['id']
            
            # Write single feature GeoJSON
            single_geojson = tmpdir / f"{muni_id}.geojson"
            with open(single_geojson, 'w') as f:
                json.dump({
                    'type': 'FeatureCollection',
                    'features': [muni['feature']]
                }, f)
            
            # Clip raster to municipality
            clipped = tmpdir / f"{muni_id}_clip.tif"
            
            try:
                result = subprocess.run(
                    ['gdalwarp', '-q', '-cutline', str(single_geojson),
                     '-crop_to_cutline', '-dstnodata', '-9999',
                     str(tiff_path), str(clipped)],
                    capture_output=True, text=True, timeout=30
                )
                
                if result.returncode != 0 or not clipped.exists():
                    continue
                
                # Get statistics from clipped raster
                stat_result = subprocess.run(
                    ['gdalinfo', '-json', '-stats', str(clipped)],
                    capture_output=True, text=True, timeout=30
                )
                
                if stat_result.returncode == 0:
                    info = json.loads(stat_result.stdout)
                    if 'bands' in info and len(info['bands']) > 0:
                        band = info['bands'][0]
                        if 'mean' in band and band['mean'] is not None:
                            stats[muni_id] = {
                                'mean': round(band['mean'], 3),
                                'min': round(band.get('minimum', band['mean']), 3),
                                'max': round(band.get('maximum', band['mean']), 3),
                                'stddev': round(band.get('stdDev', 0), 3)
                            }
                
                # Clean up
                if clipped.exists():
                    clipped.unlink()
                    
            except Exception as e:
                pass
    
    # Cache results
    with open(cache_file, 'w') as f:
        json.dump(stats, f)
    
    return stats

def main():
    print("EDO Zonal Statistics per Municipality")
    print("=" * 60)
    
    # Load municipalities
    print("Loading municipalities...")
    municipalities = load_municipalities()
    print(f"  Loaded {len(municipalities)} municipalities")
    
    # Get all tiffs
    tiff_files = sorted(TIFF_DIR.glob('cdinx_m_edo_*.tif'))
    print(f"  Found {len(tiff_files)} GeoTIFF files")
    
    # Process each tiff and build time series
    # Structure: {muni_id: {year: [values]}}
    timeseries = defaultdict(lambda: defaultdict(list))
    all_observations = defaultdict(list)  # For overall stats
    
    for i, tiff_path in enumerate(tiff_files):
        date = parse_date_from_filename(tiff_path.name)
        year = date.year
        
        stats = calculate_zonal_stats_for_tiff(tiff_path, municipalities)
        
        for muni_id, muni_stats in stats.items():
            if muni_stats['mean'] > -1000:  # Valid data
                timeseries[muni_id][year].append({
                    'date': date.strftime('%Y-%m-%d'),
                    'mean': muni_stats['mean'],
                    'min': muni_stats['min'],
                    'max': muni_stats['max']
                })
                all_observations[muni_id].append(muni_stats['mean'])
        
        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(tiff_files)} tiffs...")
    
    print(f"\nProcessed all tiffs, calculating summaries...")
    
    # Calculate yearly and overall summaries per municipality
    muni_summary = {}
    
    for muni_id in timeseries:
        yearly_stats = {}
        all_means = []
        
        for year, observations in timeseries[muni_id].items():
            means = [o['mean'] for o in observations]
            all_means.extend(means)
            
            yearly_stats[str(year)] = {
                'mean': round(statistics.mean(means), 3),
                'median': round(statistics.median(means), 3),
                'min': round(min(means), 3),
                'max': round(max(means), 3),
                'count': len(means)
            }
        
        # Overall summary
        if all_means:
            muni_summary[muni_id] = {
                'overall': {
                    'mean': round(statistics.mean(all_means), 3),
                    'median': round(statistics.median(all_means), 3),
                    'min': round(min(all_means), 3),
                    'max': round(max(all_means), 3),
                    'count': len(all_means)
                },
                'yearly': yearly_stats
            }
    
    print(f"  Calculated summaries for {len(muni_summary)} municipalities")
    
    # Save time series (full data)
    ts_file = OUTPUT_DIR / 'edo_municipality_timeseries.json'
    ts_data = {
        'metadata': {
            'source': 'Copernicus European Drought Observatory (EDO)',
            'indicator': 'Combined Drought Index (CDI)',
            'description': 'CDI integrates SPI, soil moisture anomaly, and fAPAR anomaly',
            'scale': '0=none, 1=watch, 2=warning, 3=alert',
            'period': '2012-2023',
            'processed': datetime.now().isoformat()
        },
        'municipalities': {k: dict(v) for k, v in timeseries.items()}
    }
    with open(ts_file, 'w') as f:
        json.dump(ts_data, f)
    print(f"  Saved time series to {ts_file}")
    
    # Save summary (for risk model integration)
    summary_file = OUTPUT_DIR / 'edo_municipality_summary.json'
    summary_data = {
        'metadata': ts_data['metadata'],
        'municipalities': muni_summary
    }
    with open(summary_file, 'w') as f:
        json.dump(summary_data, f)
    print(f"  Saved summary to {summary_file}")
    
    # Print distribution stats
    overall_means = [v['overall']['mean'] for v in muni_summary.values()]
    print(f"\nOverall CDI Distribution across municipalities:")
    print(f"  Min:    {min(overall_means):.3f}")
    print(f"  Max:    {max(overall_means):.3f}")
    print(f"  Mean:   {statistics.mean(overall_means):.3f}")
    print(f"  Median: {statistics.median(overall_means):.3f}")
    
    # Identify highest risk municipalities
    sorted_munis = sorted(muni_summary.items(), key=lambda x: x[1]['overall']['mean'], reverse=True)
    print(f"\nTop 10 highest CDI municipalities:")
    for muni_id, data in sorted_munis[:10]:
        muni_name = next((m['name'] for m in municipalities if m['id'] == muni_id), muni_id)
        print(f"  {muni_name}: {data['overall']['mean']:.3f} (max: {data['overall']['max']:.3f})")

if __name__ == '__main__':
    main()

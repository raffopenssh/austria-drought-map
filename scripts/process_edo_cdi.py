#!/usr/bin/env python3
"""
Process EDO Combined Drought Index (CDI) GeoTIFF data for Austria.
Extracts mean CDI values using GDAL command-line tools.
"""
import os
import json
import subprocess
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import re

# Paths
TIFF_DIR = Path('/home/exedev/austria-drought-map/data/edo/tiffs')
OUTPUT_DIR = Path('/home/exedev/austria-drought-map/web/data')

# Austria bounding box (WGS84)
AUSTRIA_BBOX = {
    'west': 9.5,
    'south': 46.3,
    'east': 17.2,
    'north': 49.0
}

def parse_date_from_filename(filename):
    """Extract date from filename like cdinx_m_edo_20230101_t_400_z03.tif"""
    parts = filename.split('_')
    date_str = parts[3]  # e.g., '20230101'
    return datetime.strptime(date_str, '%Y%m%d')

def extract_cdi_stats(tiff_path):
    """
    Extract statistics for Austria region using gdalinfo.
    """
    # First clip to Austria bounds, then get stats
    # Use gdal_translate to clip, then gdalinfo for stats
    
    try:
        # Use gdalinfo with -stats to get statistics
        # We'll read the full raster and filter by bounds
        result = subprocess.run(
            ['gdalinfo', '-json', '-stats', str(tiff_path)],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode != 0:
            return None
            
        info = json.loads(result.stdout)
        
        # Get the band statistics
        if 'bands' in info and len(info['bands']) > 0:
            band = info['bands'][0]
            if 'mean' in band:
                return float(band['mean'])
            elif 'computedMin' in band:
                # Compute from min/max if mean not available
                return (float(band['computedMin']) + float(band['computedMax'])) / 2
                
    except Exception as e:
        print(f"  Error processing {tiff_path.name}: {e}")
        
    return None

def extract_cdi_via_translate(tiff_path):
    """
    Extract Austria-clipped statistics using gdal_translate with projwin.
    """
    import tempfile
    
    try:
        # Create temp file for clipped raster
        with tempfile.NamedTemporaryFile(suffix='.tif', delete=True) as tmp:
            tmp_path = tmp.name
            
            # Clip to Austria bounds
            clip_result = subprocess.run(
                ['gdal_translate', '-q',
                 '-projwin', str(AUSTRIA_BBOX['west']), str(AUSTRIA_BBOX['north']),
                 str(AUSTRIA_BBOX['east']), str(AUSTRIA_BBOX['south']),
                 str(tiff_path), tmp_path],
                capture_output=True, text=True, timeout=30
            )
            
            if clip_result.returncode != 0:
                return None
                
            # Get stats from clipped raster
            stats_result = subprocess.run(
                ['gdalinfo', '-json', '-stats', tmp_path],
                capture_output=True, text=True, timeout=30
            )
            
            if stats_result.returncode != 0:
                return None
                
            info = json.loads(stats_result.stdout)
            
            if 'bands' in info and len(info['bands']) > 0:
                band = info['bands'][0]
                if 'mean' in band:
                    return float(band['mean'])
                    
    except Exception as e:
        print(f"  Error: {e}")
        
    return None

def main():
    print("EDO CDI Processing for Austria")
    print("=" * 50)
    
    # Get all tiff files sorted by date
    tiff_files = sorted(TIFF_DIR.glob('cdinx_m_edo_*.tif'))
    print(f"Found {len(tiff_files)} CDI tiff files")
    
    # Process each file and build time series
    time_series = []
    yearly_data = defaultdict(list)
    
    for i, tiff_path in enumerate(tiff_files):
        date = parse_date_from_filename(tiff_path.name)
        cdi_value = extract_cdi_via_translate(tiff_path)
        
        if cdi_value is not None:
            entry = {
                'date': date.strftime('%Y-%m-%d'),
                'year': date.year,
                'month': date.month,
                'cdi': round(cdi_value, 2)
            }
            time_series.append(entry)
            yearly_data[date.year].append(cdi_value)
        
        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(tiff_files)} files...")
    
    print(f"\nExtracted {len(time_series)} data points")
    
    # Calculate yearly summaries
    yearly_summary = []
    for year in sorted(yearly_data.keys()):
        values = yearly_data[year]
        yearly_summary.append({
            'year': year,
            'mean_cdi': round(sum(values)/len(values), 2),
            'min_cdi': round(min(values), 2),
            'max_cdi': round(max(values), 2),
            'observations': len(values)
        })
    
    # Save results
    output = {
        'metadata': {
            'source': 'Copernicus European Drought Observatory (EDO)',
            'indicator': 'Combined Drought Index (CDI)',
            'description': 'CDI integrates SPI, soil moisture, and fAPAR anomalies',
            'scale': {
                '0': 'No drought',
                '1': 'Watch',
                '2': 'Warning', 
                '3': 'Alert'
            },
            'period': f"{time_series[0]['date']} to {time_series[-1]['date']}" if time_series else 'N/A',
            'processed': datetime.now().isoformat()
        },
        'time_series': time_series,
        'yearly_summary': yearly_summary
    }
    
    output_file = OUTPUT_DIR / 'edo_cdi_austria.json'
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {output_file}")
    
    # Print summary statistics
    print("\nYearly Summary:")
    print("-" * 50)
    for ys in yearly_summary:
        print(f"  {ys['year']}: Mean CDI = {ys['mean_cdi']:.2f} (min: {ys['min_cdi']:.2f}, max: {ys['max_cdi']:.2f})")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Fast zonal statistics for EDO CDI using rasterized municipality IDs.
Creates a lookup raster once, then processes all tiffs quickly.
"""
import os
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import statistics
import struct

TIFF_DIR = Path('/home/exedev/austria-drought-map/data/edo/tiffs')
MUNI_GEOJSON = Path('/home/exedev/austria-drought-map/web/data/gemeinden.geojson')
OUTPUT_DIR = Path('/home/exedev/austria-drought-map/web/data')
CACHE_DIR = Path('/home/exedev/austria-drought-map/data/edo')

def parse_date_from_filename(filename):
    parts = filename.split('_')
    date_str = parts[3]
    return datetime.strptime(date_str, '%Y%m%d')

def get_raster_info(tiff_path):
    """Get raster dimensions and transform"""
    result = subprocess.run(
        ['gdalinfo', '-json', str(tiff_path)],
        capture_output=True, text=True
    )
    info = json.loads(result.stdout)
    return {
        'size': info['size'],
        'geoTransform': info['geoTransform']
    }

def create_zone_raster(template_tiff, geojson_path, output_path):
    """Create a rasterized version of municipalities matching the template"""
    print(f"Creating zone raster from {geojson_path}...")
    
    # Get template info
    info = get_raster_info(template_tiff)
    width, height = info['size']
    gt = info['geoTransform']
    
    # Rasterize using gdal_rasterize with numeric IDs
    subprocess.run([
        'gdal_rasterize',
        '-a', 'iso',  # Use ISO code as zone ID
        '-of', 'GTiff',
        '-ot', 'Int32',
        '-te', str(gt[0]), str(gt[3] + height * gt[5]), str(gt[0] + width * gt[1]), str(gt[3]),
        '-ts', str(width), str(height),
        '-init', '0',
        str(geojson_path),
        str(output_path)
    ], check=True)
    
    print(f"  Created {output_path}")

def read_raw_raster(tiff_path):
    """Read raster data using GDAL translate to raw format"""
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        # Get dimensions
        info = get_raster_info(tiff_path)
        width, height = info['size']
        
        # Convert to raw float32
        subprocess.run([
            'gdal_translate', '-q',
            '-of', 'ENVI',
            '-ot', 'Float32',
            str(tiff_path), tmp_path
        ], check=True)
        
        # Read binary data
        with open(tmp_path, 'rb') as f:
            data = f.read()
        
        # Convert to list of floats
        count = width * height
        values = struct.unpack(f'{count}f', data[:count*4])
        
        return values, width, height
    finally:
        for ext in ['', '.hdr', '.aux.xml']:
            p = Path(tmp_path + ext)
            if p.exists():
                p.unlink()

def read_int_raster(tiff_path):
    """Read integer raster (zone IDs)"""
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        info = get_raster_info(tiff_path)
        width, height = info['size']
        
        subprocess.run([
            'gdal_translate', '-q',
            '-of', 'ENVI',
            '-ot', 'Int32',
            str(tiff_path), tmp_path
        ], check=True)
        
        with open(tmp_path, 'rb') as f:
            data = f.read()
        
        count = width * height
        values = struct.unpack(f'{count}i', data[:count*4])
        
        return values, width, height
    finally:
        for ext in ['', '.hdr', '.aux.xml']:
            p = Path(tmp_path + ext)
            if p.exists():
                p.unlink()

def calculate_zonal_stats(zone_data, value_data, nodata=-9999):
    """Calculate zonal statistics from parallel arrays"""
    zone_values = defaultdict(list)
    
    for zone_id, value in zip(zone_data, value_data):
        if zone_id > 0 and value > nodata + 1000:  # Valid zone and value
            zone_values[zone_id].append(value)
    
    stats = {}
    for zone_id, values in zone_values.items():
        if len(values) > 0:
            stats[str(zone_id)] = {
                'mean': round(sum(values) / len(values), 3),
                'min': round(min(values), 3),
                'max': round(max(values), 3),
                'count': len(values)
            }
    
    return stats

def main():
    print("EDO Zonal Statistics (Fast Method)")
    print("=" * 60)
    
    # Use first tiff as template
    tiff_files = sorted(TIFF_DIR.glob('cdinx_m_edo_*.tif'))
    print(f"Found {len(tiff_files)} GeoTIFF files")
    
    template = tiff_files[0]
    zone_raster = CACHE_DIR / 'municipality_zones.tif'
    
    # Create zone raster if needed
    if not zone_raster.exists():
        create_zone_raster(template, MUNI_GEOJSON, zone_raster)
    else:
        print(f"Using cached zone raster: {zone_raster}")
    
    # Read zone raster once
    print("Loading zone raster...")
    zone_data, width, height = read_int_raster(zone_raster)
    unique_zones = set(z for z in zone_data if z > 0)
    print(f"  Found {len(unique_zones)} municipality zones")
    
    # Process all tiffs
    timeseries = defaultdict(lambda: defaultdict(list))
    
    for i, tiff_path in enumerate(tiff_files):
        date = parse_date_from_filename(tiff_path.name)
        year = date.year
        
        value_data, _, _ = read_raw_raster(tiff_path)
        stats = calculate_zonal_stats(zone_data, value_data)
        
        for zone_id, zone_stats in stats.items():
            timeseries[zone_id][year].append({
                'date': date.strftime('%Y-%m-%d'),
                'mean': zone_stats['mean'],
                'min': zone_stats['min'],
                'max': zone_stats['max']
            })
        
        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(tiff_files)} tiffs...")
    
    print(f"\nCalculating summaries...")
    
    # Calculate summaries
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
    
    # Save outputs
    metadata = {
        'source': 'Copernicus European Drought Observatory (EDO)',
        'indicator': 'Combined Drought Index (CDI)',
        'description': 'CDI integrates SPI, soil moisture anomaly, and fAPAR anomaly',
        'scale': '0=none, 1=watch, 2=warning, 3=alert',
        'period': '2012-2023',
        'processed': datetime.now().isoformat()
    }
    
    # Save summary
    summary_file = OUTPUT_DIR / 'edo_municipality_summary.json'
    with open(summary_file, 'w') as f:
        json.dump({'metadata': metadata, 'municipalities': muni_summary}, f)
    print(f"Saved: {summary_file}")
    
    # Save time series
    ts_file = OUTPUT_DIR / 'edo_municipality_timeseries.json'
    ts_data = {k: dict(v) for k, v in timeseries.items()}
    with open(ts_file, 'w') as f:
        json.dump({'metadata': metadata, 'municipalities': ts_data}, f)
    print(f"Saved: {ts_file}")
    
    # Print stats
    if muni_summary:
        overall_means = [v['overall']['mean'] for v in muni_summary.values()]
        print(f"\nCDI Distribution:")
        print(f"  Min:    {min(overall_means):.3f}")
        print(f"  Max:    {max(overall_means):.3f}")
        print(f"  Mean:   {statistics.mean(overall_means):.3f}")

if __name__ == '__main__':
    main()

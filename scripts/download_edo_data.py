#!/usr/bin/env python3
"""
Download EDO (European Drought Observatory) data for Austria
https://drought.emergency.copernicus.eu/
"""
import os
import requests
import json

# Austria bounding box (approximate)
AUSTRIA_BBOX = {
    'west': 9.5,
    'south': 46.3,
    'east': 17.2,
    'north': 49.0
}

# EDO indicators available
EDO_INDICATORS = [
    'spi-1',   # Standardized Precipitation Index 1-month
    'spi-3',   # SPI 3-month
    'spi-12',  # SPI 12-month
    'spei-1',  # Standardized Precipitation-Evapotranspiration Index
    'spei-3',
    'spei-12',
    'fapan',   # Fraction of Absorbed Photosynthetically Active Radiation Anomaly
    'sma',     # Soil Moisture Anomaly
    'cdi',     # Combined Drought Indicator
]

OUTPUT_DIR = '/home/exedev/austria-drought-map/data/edo'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# EDO WMS base URL (for reference)
EDO_WMS = "https://drought.emergency.copernicus.eu/geoserver/wms"

print("EDO Data Download Script")
print("=" * 50)
print(f"Austria bounding box: {AUSTRIA_BBOX}")
print(f"Output directory: {OUTPUT_DIR}")
print(f"Available indicators: {EDO_INDICATORS}")
print()
print("NOTE: EDO data requires browser-based download or WCS access")
print("Visit: https://drought.emergency.copernicus.eu/tumbo/edo/download/")
print()
print("Saving indicator metadata...")

# Save metadata
metadata = {
    'source': 'Copernicus European Drought Observatory (EDO)',
    'url': 'https://drought.emergency.copernicus.eu/',
    'austria_bbox': AUSTRIA_BBOX,
    'indicators': {
        'spi': 'Standardized Precipitation Index - deviation of precipitation from long-term mean',
        'spei': 'Standardized Precipitation-Evapotranspiration Index - accounts for temperature effects',
        'fapan': 'Vegetation stress indicator based on satellite data',
        'sma': 'Soil Moisture Anomaly from satellite/model data',
        'cdi': 'Combined Drought Indicator - integrates multiple indicators'
    }
}

with open(f'{OUTPUT_DIR}/edo_metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)

print(f"Saved: {OUTPUT_DIR}/edo_metadata.json")

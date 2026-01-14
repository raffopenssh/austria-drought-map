#!/usr/bin/env python3
"""Create GeoPackage with all drought risk data."""

import json
import geopandas as gpd
import pandas as pd
from pathlib import Path

DATA_DIR = Path('../web/data')
OUTPUT = DATA_DIR / 'austria_drought_risk.gpkg'

# Load municipalities with risk
print("Loading municipalities...")
gdf = gpd.read_file(DATA_DIR / 'municipalities_risk.geojson')
gdf.to_file(OUTPUT, layer='municipalities', driver='GPKG')
print(f"  Added {len(gdf)} municipalities")

# Load hydropower plants
print("Loading hydropower plants...")
with open(DATA_DIR / 'powerplants.json') as f:
    pp = json.load(f)

pp_gdf = gpd.GeoDataFrame(
    pp,
    geometry=gpd.points_from_xy([p['lon'] for p in pp], [p['lat'] for p in pp]),
    crs='EPSG:4326'
)
pp_gdf.to_file(OUTPUT, layer='hydropower_plants', driver='GPKG')
print(f"  Added {len(pp_gdf)} hydropower plants")

# Load groundwater stations
print("Loading groundwater stations...")
with open(DATA_DIR / 'gw_stations_trends.json') as f:
    gw = json.load(f)

gw_with_coords = [s for s in gw if 'lat' in s and 'lon' in s]
gw_gdf = gpd.GeoDataFrame(
    gw_with_coords,
    geometry=gpd.points_from_xy([s['lon'] for s in gw_with_coords], [s['lat'] for s in gw_with_coords]),
    crs='EPSG:4326'
)
gw_gdf.to_file(OUTPUT, layer='groundwater_stations', driver='GPKG')
print(f"  Added {len(gw_gdf)} groundwater stations")

print(f"\nGeoPackage saved: {OUTPUT}")
print(f"Size: {OUTPUT.stat().st_size / 1024 / 1024:.1f} MB")

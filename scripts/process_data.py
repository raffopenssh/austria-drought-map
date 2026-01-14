#!/usr/bin/env python3
"""
Process Austrian hydrological data to create drought risk indicators.
Data sources:
- Groundwater levels (gw)
- Precipitation (nlv)
- Surface water/river discharge (owf)
- Springs/water sources (qu)
- Hydropower plants
- Municipality boundaries
"""

import os
import json
import re
import glob
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import geopandas as gpd
from shapely.geometry import Point
from scipy import stats

DATA_DIR = Path('../data')
OUTPUT_DIR = Path('../web/data')

def parse_ehyd_csv(filepath, value_col=1):
    """
    Parse eHYD CSV file format.
    Returns DataFrame with date index and values.
    """
    try:
        with open(filepath, 'r', encoding='latin-1') as f:
            lines = f.readlines()
        
        # Find the data start (after "Werte:" line)
        data_start = 0
        for i, line in enumerate(lines):
            if 'Werte:' in line or line.strip().startswith('01.'):
                data_start = i + 1 if 'Werte:' in line else i
                break
        
        # Parse data lines
        dates = []
        values = []
        
        for line in lines[data_start:]:
            line = line.strip()
            if not line or 'Lücke' in line:
                continue
            
            parts = line.split(';')
            if len(parts) >= 2:
                try:
                    # Parse date (format: DD.MM.YYYY HH:MM:SS)
                    date_str = parts[0].strip()
                    date_match = re.match(r'(\d{2}\.\d{2}\.\d{4})', date_str)
                    if date_match:
                        date = pd.to_datetime(date_match.group(1), format='%d.%m.%Y')
                        
                        # Parse value
                        val_str = parts[value_col].strip().replace(',', '.')
                        if val_str and not any(x in val_str for x in ['Lücke', '-']):
                            val = float(val_str)
                            dates.append(date)
                            values.append(val)
                except (ValueError, IndexError):
                    continue
        
        if dates:
            return pd.DataFrame({'value': values}, index=pd.DatetimeIndex(dates))
        return None
    except Exception as e:
        return None

def get_station_coords(metadata_file):
    """
    Extract coordinates from station metadata file.
    """
    try:
        with open(metadata_file, 'r', encoding='latin-1') as f:
            content = f.read()
        
        # Look for geographic coordinates (Bessel)
        lat_match = re.search(r'Breite.*?(\d{2})\s+(\d{2})\s+(\d{2})', content)
        lon_match = re.search(r'Länge.*?(\d{2})\s+(\d{2})\s+(\d{2})', content)
        
        if lat_match and lon_match:
            lat = float(lat_match.group(1)) + float(lat_match.group(2))/60 + float(lat_match.group(3))/3600
            lon = float(lon_match.group(1)) + float(lon_match.group(2))/60 + float(lon_match.group(3))/3600
            return lon, lat
        
        # Try BMN coordinates
        bmn_match = re.search(r'(\d+),00\s+-\s+(\d+),00', content)
        if bmn_match:
            # BMN M34 to WGS84 rough conversion
            y = float(bmn_match.group(1))
            x = float(bmn_match.group(2))
            # Very rough conversion - should use proper transformation
            lon = 9.0 + (y - 100000) / 111000 * 1.5
            lat = 46.0 + (x - 200000) / 111000
            return lon, lat
            
        return None, None
    except:
        return None, None

def parse_station_list(csv_file):
    """
    Parse the messstellen CSV file.
    """
    try:
        df = pd.read_csv(csv_file, sep=';', encoding='latin-1')
        return df
    except:
        return None

def calculate_trend(series, min_years=20):
    """
    Calculate linear trend using Mann-Kendall and Sen's slope.
    Returns trend per decade.
    """
    if series is None or len(series) < min_years * 12:
        return None, None
    
    try:
        # Resample to yearly means
        yearly = series.resample('Y').mean().dropna()
        if len(yearly) < min_years:
            return None, None
        
        x = np.arange(len(yearly))
        y = yearly.values
        
        # Sen's slope estimator
        slope, intercept, _, _, _ = stats.linregress(x, y)
        
        # Trend per decade
        trend_per_decade = slope * 10
        
        # Calculate significance
        _, p_value = stats.kendalltau(x, y)
        
        return trend_per_decade, p_value
    except:
        return None, None

def process_groundwater_data():
    """
    Process groundwater level data.
    """
    print("Processing groundwater data...")
    
    stations = []
    gw_dir = DATA_DIR / 'gw'
    
    # Parse station list
    station_list = parse_station_list(gw_dir / 'messstellen_gw.csv')
    if station_list is not None:
        for _, row in station_list.iterrows():
            try:
                station_id = str(row.get('hzbnr01', row.get('dbmsnr', '')))
                x = row.get('xrkko09', row.get('x', None))
                y = row.get('yhkko10', row.get('y', None))
                
                if pd.notna(x) and pd.notna(y):
                    # Convert Austrian coordinates to WGS84 (rough approximation)
                    # Using MGI Austria GK M34 approximation
                    if isinstance(x, str):
                        x = float(x.replace(',', '.'))
                        y = float(y.replace(',', '.'))
                    
                    # Rough BMN to WGS84
                    lon = 9.0 + (x - 100000) / 70000
                    lat = 46.0 + (y - 100000) / 110000
                    
                    if 9 < lon < 18 and 46 < lat < 49:
                        stations.append({
                            'station_id': station_id,
                            'name': str(row.get('mstnam02', '')),
                            'lon': lon,
                            'lat': lat,
                            'gw_area': str(row.get('gwgeb03', '')),
                            'gw_body': str(row.get('gwkoerpe04', ''))
                        })
            except Exception as e:
                continue
    
    # Process time series for each station
    monthly_dir = gw_dir / 'Grundwasserstand-Monatsmittel'
    if monthly_dir.exists():
        processed = 0
        for csv_file in monthly_dir.glob('*.csv'):
            station_id = csv_file.stem.split('-')[-1]
            
            series = parse_ehyd_csv(csv_file)
            if series is not None and len(series) > 100:
                trend, p_value = calculate_trend(series['value'])
                
                # Find matching station
                for stn in stations:
                    if stn['station_id'] == station_id:
                        stn['trend_per_decade'] = trend
                        stn['trend_p_value'] = p_value
                        stn['mean_level'] = series['value'].mean()
                        stn['std_level'] = series['value'].std()
                        stn['data_years'] = len(series) / 12
                        stn['recent_mean'] = series['value'][-60:].mean() if len(series) >= 60 else None
                        stn['historic_mean'] = series['value'][:60].mean() if len(series) >= 60 else None
                        processed += 1
                        break
        
        print(f"  Processed {processed} groundwater stations with time series")
    
    return [s for s in stations if 'trend_per_decade' in s]

def process_surface_water_data():
    """
    Process surface water discharge data.
    """
    print("Processing surface water data...")
    
    stations = []
    owf_dir = DATA_DIR / 'owf'
    
    # Parse station list
    station_list = parse_station_list(owf_dir / 'messstellen_owf.csv')
    if station_list is not None:
        for _, row in station_list.iterrows():
            try:
                station_id = str(row.get('hzbnr01', row.get('dbmsnr', '')))
                x = row.get('x', None)
                y = row.get('y', None)
                
                if pd.notna(x) and pd.notna(y):
                    if isinstance(x, str):
                        x = float(x.replace(',', '.'))
                        y = float(y.replace(',', '.'))
                    
                    # Rough BMN to WGS84
                    lon = 9.0 + (x - 100000) / 70000
                    lat = 46.0 + (y - 100000) / 110000
                    
                    if 9 < lon < 18 and 46 < lat < 49:
                        stations.append({
                            'station_id': station_id,
                            'lon': lon,
                            'lat': lat
                        })
            except:
                continue
    
    # Process discharge time series
    q_dir = owf_dir / 'Q-Tagesmittel'
    if q_dir.exists():
        processed = 0
        for csv_file in q_dir.glob('*.csv'):
            station_id = csv_file.stem.split('-')[-1]
            
            series = parse_ehyd_csv(csv_file)
            if series is not None and len(series) > 365 * 10:
                # Resample to monthly
                monthly = series.resample('M').mean()
                trend, p_value = calculate_trend(monthly['value'])
                
                for stn in stations:
                    if stn['station_id'] == station_id:
                        stn['q_trend_per_decade'] = trend
                        stn['q_p_value'] = p_value
                        stn['mean_discharge'] = series['value'].mean()
                        stn['data_years'] = len(series) / 365
                        processed += 1
                        break
        
        print(f"  Processed {processed} surface water stations")
    
    return [s for s in stations if 'q_trend_per_decade' in s]

def process_precipitation_data():
    """
    Process precipitation data.
    """
    print("Processing precipitation data...")
    
    stations = []
    nlv_dir = DATA_DIR / 'nlv'
    
    # Parse station list
    station_list = parse_station_list(nlv_dir / 'messstellen_alle.csv')
    if station_list is not None:
        for _, row in station_list.iterrows():
            try:
                station_id = str(row.get('hzbnr01', row.get('dbmsnr', '')))
                x = row.get('x', None)
                y = row.get('y', None)
                
                if pd.notna(x) and pd.notna(y):
                    if isinstance(x, str):
                        x = float(x.replace(',', '.'))
                        y = float(y.replace(',', '.'))
                    
                    # Rough BMN to WGS84
                    lon = 9.0 + (x - 100000) / 70000
                    lat = 46.0 + (y - 100000) / 110000
                    
                    if 9 < lon < 18 and 46 < lat < 49:
                        stations.append({
                            'station_id': station_id,
                            'lon': lon,
                            'lat': lat
                        })
            except:
                continue
    
    # Process precipitation time series
    precip_dir = nlv_dir / 'N-Tagessummen'
    if precip_dir.exists():
        processed = 0
        for csv_file in list(precip_dir.glob('*.csv'))[:200]:  # Limit for speed
            station_id = csv_file.stem.split('-')[-1]
            
            series = parse_ehyd_csv(csv_file)
            if series is not None and len(series) > 365 * 10:
                # Calculate yearly totals
                yearly = series.resample('Y').sum()
                trend, p_value = calculate_trend(yearly['value'])
                
                for stn in stations:
                    if stn['station_id'] == station_id:
                        stn['precip_trend'] = trend
                        stn['precip_p_value'] = p_value
                        stn['mean_annual_precip'] = yearly['value'].mean()
                        processed += 1
                        break
        
        print(f"  Processed {processed} precipitation stations")
    
    return [s for s in stations if 'precip_trend' in s]

def load_powerplants():
    """
    Load hydropower plant data.
    """
    print("Loading power plants...")
    
    pp_file = DATA_DIR / 'powerplants.json'
    with open(pp_file, 'r') as f:
        data = json.load(f)
    
    plants = []
    for marker in data.get('markers', []):
        plant_type = marker.get('type', '')
        
        # Filter for hydropower plants
        if any(x in plant_type for x in ['Laufkraftwerk', 'Pumpspeicher', 'Speicherkraftwerk']):
            try:
                lat = float(marker.get('latitude', 0))
                lon = float(marker.get('longitude', 0))
                
                if 9 < lon < 18 and 46 < lat < 49:
                    mw = marker.get('mw', '0')
                    if isinstance(mw, str):
                        mw = float(mw.replace(',', '.')) if mw.replace(',', '.').replace('.', '').isdigit() else 0
                    
                    plants.append({
                        'lat': lat,
                        'lon': lon,
                        'type': plant_type,
                        'mw': mw,
                        'region': marker.get('region', ''),
                        'river': marker.get('feed', ''),
                        'area': marker.get('area', '')
                    })
            except:
                continue
    
    print(f"  Loaded {len(plants)} hydropower plants")
    return plants

def load_municipalities():
    """
    Load Austrian municipality boundaries.
    """
    print("Loading municipalities...")
    
    gdf = gpd.read_file(DATA_DIR / 'gemeinden.geojson')
    print(f"  Loaded {len(gdf)} municipalities")
    return gdf

def assign_to_municipalities(municipalities, points, point_type):
    """
    Assign point data to municipalities using spatial join.
    """
    if not points:
        return municipalities
    
    # Create GeoDataFrame from points
    points_gdf = gpd.GeoDataFrame(
        points,
        geometry=[Point(p['lon'], p['lat']) for p in points],
        crs='EPSG:4326'
    )
    
    # Spatial join
    joined = gpd.sjoin(points_gdf, municipalities, how='left', predicate='within')
    
    return joined

def calculate_municipality_risk(municipalities, gw_data, sw_data, precip_data, powerplants):
    """
    Calculate drought risk score for each municipality.
    """
    print("Calculating municipality risk scores...")
    
    results = []
    
    for idx, muni in municipalities.iterrows():
        geom = muni.geometry
        name = muni.get('name', f'Municipality_{idx}')
        iso = muni.get('iso', '')
        
        # Find stations within or near municipality
        muni_gw = []
        muni_sw = []
        muni_precip = []
        muni_pp = []
        
        # Check groundwater stations
        for stn in gw_data:
            pt = Point(stn['lon'], stn['lat'])
            if geom.contains(pt) or geom.distance(pt) < 0.1:
                muni_gw.append(stn)
        
        # Check surface water
        for stn in sw_data:
            pt = Point(stn['lon'], stn['lat'])
            if geom.contains(pt) or geom.distance(pt) < 0.1:
                muni_sw.append(stn)
        
        # Check precipitation
        for stn in precip_data:
            pt = Point(stn['lon'], stn['lat'])
            if geom.contains(pt) or geom.distance(pt) < 0.1:
                muni_precip.append(stn)
        
        # Check power plants
        for pp in powerplants:
            pt = Point(pp['lon'], pp['lat'])
            if geom.contains(pt) or geom.distance(pt) < 0.05:
                muni_pp.append(pp)
        
        # Calculate risk indicators
        gw_trend = np.mean([s['trend_per_decade'] for s in muni_gw if s.get('trend_per_decade')]) if muni_gw else None
        sw_trend = np.mean([s['q_trend_per_decade'] for s in muni_sw if s.get('q_trend_per_decade')]) if muni_sw else None
        precip_trend = np.mean([s['precip_trend'] for s in muni_precip if s.get('precip_trend')]) if muni_precip else None
        
        # Power plant impact
        hydro_capacity = sum(pp['mw'] for pp in muni_pp)
        pump_storage = sum(pp['mw'] for pp in muni_pp if 'Pumpspeicher' in pp.get('type', ''))
        
        result = {
            'name': name,
            'iso': iso,
            'centroid_lon': geom.centroid.x,
            'centroid_lat': geom.centroid.y,
            'gw_stations': len(muni_gw),
            'gw_trend': gw_trend,
            'sw_stations': len(muni_sw),
            'sw_trend': sw_trend,
            'precip_stations': len(muni_precip),
            'precip_trend': precip_trend,
            'hydro_plants': len(muni_pp),
            'hydro_capacity_mw': hydro_capacity,
            'pump_storage_mw': pump_storage
        }
        
        results.append(result)
    
    return results

def calculate_risk_scores(muni_data):
    """
    Calculate normalized risk scores.
    """
    print("Normalizing risk scores...")
    
    df = pd.DataFrame(muni_data)
    
    # Normalize trends (negative = declining = higher risk)
    # GW trend: negative means declining water table (bad)
    gw_valid = df['gw_trend'].notna()
    if gw_valid.any():
        gw_min = df.loc[gw_valid, 'gw_trend'].min()
        gw_max = df.loc[gw_valid, 'gw_trend'].max()
        if gw_max != gw_min:
            df['gw_risk'] = 1 - (df['gw_trend'] - gw_min) / (gw_max - gw_min)
        else:
            df['gw_risk'] = 0.5
    else:
        df['gw_risk'] = np.nan
    
    # SW trend: negative means declining discharge (bad for recharge)
    sw_valid = df['sw_trend'].notna()
    if sw_valid.any():
        sw_min = df.loc[sw_valid, 'sw_trend'].min()
        sw_max = df.loc[sw_valid, 'sw_trend'].max()
        if sw_max != sw_min:
            df['sw_risk'] = 1 - (df['sw_trend'] - sw_min) / (sw_max - sw_min)
        else:
            df['sw_risk'] = 0.5
    else:
        df['sw_risk'] = np.nan
    
    # Precip trend: negative means less rainfall (bad)
    precip_valid = df['precip_trend'].notna()
    if precip_valid.any():
        p_min = df.loc[precip_valid, 'precip_trend'].min()
        p_max = df.loc[precip_valid, 'precip_trend'].max()
        if p_max != p_min:
            df['precip_risk'] = 1 - (df['precip_trend'] - p_min) / (p_max - p_min)
        else:
            df['precip_risk'] = 0.5
    else:
        df['precip_risk'] = np.nan
    
    # Hydro impact: higher capacity = potentially higher impact on groundwater
    hydro_valid = df['hydro_capacity_mw'] > 0
    if hydro_valid.any():
        h_max = df.loc[hydro_valid, 'hydro_capacity_mw'].max()
        if h_max > 0:
            df['hydro_risk'] = df['hydro_capacity_mw'] / h_max
        else:
            df['hydro_risk'] = 0
    else:
        df['hydro_risk'] = 0
    
    # Combined risk score (weighted average)
    weights = {'gw_risk': 0.4, 'sw_risk': 0.2, 'precip_risk': 0.2, 'hydro_risk': 0.2}
    
    risk_cols = ['gw_risk', 'sw_risk', 'precip_risk', 'hydro_risk']
    df['combined_risk'] = 0
    df['risk_weight_sum'] = 0
    
    for col, weight in weights.items():
        valid = df[col].notna()
        df.loc[valid, 'combined_risk'] += df.loc[valid, col] * weight
        df.loc[valid, 'risk_weight_sum'] += weight
    
    df['combined_risk'] = df['combined_risk'] / df['risk_weight_sum'].replace(0, 1)
    
    # Heat pump risk (based on GW trend and depth change)
    df['heat_pump_risk'] = df['gw_risk'].fillna(0.5)  # Use GW risk as proxy
    
    return df

def main():
    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load data
    municipalities = load_municipalities()
    gw_data = process_groundwater_data()
    sw_data = process_surface_water_data()
    precip_data = process_precipitation_data()
    powerplants = load_powerplants()
    
    # Calculate municipality-level aggregates
    muni_data = calculate_municipality_risk(municipalities, gw_data, sw_data, precip_data, powerplants)
    
    # Calculate risk scores
    risk_df = calculate_risk_scores(muni_data)
    
    # Save processed data
    print("\nSaving processed data...")
    
    # Save as JSON for web visualization
    risk_df.to_json(OUTPUT_DIR / 'municipality_risk.json', orient='records')
    
    # Save groundwater stations
    with open(OUTPUT_DIR / 'gw_stations.json', 'w') as f:
        json.dump(gw_data, f)
    
    # Save power plants
    with open(OUTPUT_DIR / 'powerplants.json', 'w') as f:
        json.dump(powerplants, f)
    
    # Save surface water
    with open(OUTPUT_DIR / 'sw_stations.json', 'w') as f:
        json.dump(sw_data, f)
    
    # Copy municipalities GeoJSON
    import shutil
    shutil.copy(DATA_DIR / 'gemeinden.geojson', OUTPUT_DIR / 'gemeinden.geojson')
    
    print(f"\nData processing complete!")
    print(f"  Municipalities: {len(risk_df)}")
    print(f"  GW stations: {len(gw_data)}")
    print(f"  SW stations: {len(sw_data)}")
    print(f"  Precip stations: {len(precip_data)}")
    print(f"  Power plants: {len(powerplants)}")
    
    # Summary stats
    print(f"\nRisk score summary:")
    print(f"  Mean combined risk: {risk_df['combined_risk'].mean():.3f}")
    print(f"  High risk municipalities (>0.7): {len(risk_df[risk_df['combined_risk'] > 0.7])}")
    
    return risk_df

if __name__ == '__main__':
    main()

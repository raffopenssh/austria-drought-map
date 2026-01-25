#!/usr/bin/env python3
"""
Process WISE water quality data for Austria drought map webapp.
Combines monitoring sites with quality status information.

IMPORTANT: Status codes in WISE WFD2022:
- gwChemicalStatusValue/gwQuantitativeStatusValue: '2' = Good, '3' = Unknown
- The "Poor/Failing" status is indicated by gwAtRiskChemical='Yes'
- swEcologicalStatusOrPotentialValue: 1=High, 2=Good, 3=Moderate, 4=Poor, 5=Bad
"""

import json
from collections import Counter, defaultdict

def load_json(filepath):
    with open(filepath) as f:
        return json.load(f)

def main():
    # Load monitoring sites
    sites = load_json('data/water_quality/wise_wfd2022_monitoring_sites_austria.json')
    print(f"Loaded {len(sites['features'])} monitoring sites")
    
    # Load river quality
    river_quality = load_json('data/water_quality/wise_wfd2022_river_quality_austria.json')
    print(f"Loaded {len(river_quality['features'])} river water bodies")
    
    # Load groundwater chemical status
    gw_chemical = load_json('data/water_quality/wise_wfd2022_groundwater_chemical_austria.json')
    print(f"Loaded {len(gw_chemical['features'])} groundwater bodies")
    
    # Create water body lookup from river quality
    river_lookup = {}
    for f in river_quality['features']:
        attrs = f['attributes']
        wb_code = attrs.get('euSurfaceWaterBodyCode')
        if wb_code:
            river_lookup[wb_code] = {
                'name': attrs.get('surfaceWaterBodyName', 'Unknown'),
                'ecologicalStatus': attrs.get('swEcologicalStatusOrPotentialValue'),
                'chemicalStatus': attrs.get('swChemicalStatusValue'),
                'qualityElementStatus': attrs.get('qeStatusOrPotentialValue'),
                'naturalOrHMWB': attrs.get('naturalAWBHMWB'),
                'length_km': attrs.get('cLength')
            }
    print(f"  River lookup: {len(river_lookup)} water bodies")
    
    # Create groundwater body lookup - use euGroundWaterBodyCode
    # IMPORTANT: Status '2' = Good, AtRiskChemical='Yes' = Poor/At Risk
    gw_lookup = {}
    for f in gw_chemical['features']:
        attrs = f['attributes']
        gb_code = attrs.get('euGroundWaterBodyCode')
        if gb_code:
            # Determine actual status: Good vs Poor based on AtRisk flag
            status_value = attrs.get('gwChemicalStatusValue')
            at_risk = attrs.get('gwAtRiskChemical')
            
            if status_value == '3':
                actual_status = 'Unknown'
            elif at_risk == 'Yes':
                actual_status = 'Poor'
            else:
                actual_status = 'Good'
            
            gw_lookup[gb_code] = {
                'name': attrs.get('groundWaterBodyName', 'Unknown'),
                'chemicalStatus': actual_status,
                'chemicalStatusRaw': status_value,
                'atRiskChemical': at_risk,
                'quantitativeStatus': 'Good' if attrs.get('gwQuantitativeStatusValue') == '2' else 'Unknown',
                'chemicalAssessmentYear': attrs.get('gwChemicalAssessmentYear'),
                'area_km2': attrs.get('cArea'),
            }
    print(f"  Groundwater lookup: {len(gw_lookup)} water bodies")
    
    # Process monitoring sites
    output_features = []
    stats = {
        'groundwater': Counter(),
        'river': Counter(),
        'lake': Counter(),
        'gw_matched': 0,
        'river_matched': 0
    }
    
    for f in sites['features']:
        attrs = f['attributes']
        site_type = attrs.get('specialisedZoneType', 'unknown')
        
        feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [attrs.get('lon'), attrs.get('lat')]
            },
            'properties': {
                'id': attrs.get('thematicIdIdentifier'),
                'name': attrs.get('nameText', attrs.get('nameTextInternational', 'Unknown')),
                'siteType': site_type,
                'purpose': attrs.get('purpose'),
                'activityStart': attrs.get('operationalActivityPeriodBegin'),
                'activityEnd': attrs.get('operationalActivityPeriodEnd'),
                'mediaWater': attrs.get('mediaMonitoredWater') == 1,
                'mediaBiota': attrs.get('mediaMonitoredBiota') == 1,
                'mediaSediment': attrs.get('mediaMonitoredSediment') == 1,
                'waterBodyCode': attrs.get('featureOfInterestIdentifier'),
                'lat': attrs.get('lat'),
                'lon': attrs.get('lon')
            }
        }
        
        # Add water body quality info if available
        wb_code = attrs.get('featureOfInterestIdentifier')
        if wb_code:
            if site_type == 'groundWaterBody' and wb_code in gw_lookup:
                wb_info = gw_lookup[wb_code]
                feature['properties']['waterBodyName'] = wb_info['name']
                feature['properties']['chemicalStatus'] = wb_info['chemicalStatus']
                feature['properties']['quantitativeStatus'] = wb_info['quantitativeStatus']
                feature['properties']['chemicalAssessmentYear'] = wb_info['chemicalAssessmentYear']
                feature['properties']['atRiskChemical'] = wb_info['atRiskChemical']
                stats['groundwater'][wb_info['chemicalStatus']] += 1
                stats['gw_matched'] += 1
            elif site_type == 'riverWaterBody' and wb_code in river_lookup:
                wb_info = river_lookup[wb_code]
                feature['properties']['waterBodyName'] = wb_info['name']
                feature['properties']['ecologicalStatus'] = wb_info['ecologicalStatus']
                feature['properties']['chemicalStatus'] = wb_info['chemicalStatus']
                feature['properties']['naturalOrHMWB'] = wb_info['naturalOrHMWB']
                stats['river'][wb_info['ecologicalStatus']] += 1
                stats['river_matched'] += 1
            elif site_type == 'lakeWaterBody':
                stats['lake']['unknown'] += 1
        
        # Only include sites with valid coordinates
        if attrs.get('lat') and attrs.get('lon'):
            output_features.append(feature)
    
    print(f"\nProcessed {len(output_features)} sites with coordinates")
    print(f"  Groundwater sites matched to water body: {stats['gw_matched']}")
    print(f"  River sites matched to water body: {stats['river_matched']}")
    
    # Create GeoJSON output
    geojson = {
        'type': 'FeatureCollection',
        'features': output_features,
        'metadata': {
            'source': 'EEA WISE WFD 2022',
            'countryCode': 'AT',
            'totalSites': len(output_features),
            'sitesByType': {
                'groundwater': sum(1 for f in output_features if f['properties']['siteType'] == 'groundWaterBody'),
                'river': sum(1 for f in output_features if f['properties']['siteType'] == 'riverWaterBody'),
                'lake': sum(1 for f in output_features if f['properties']['siteType'] == 'lakeWaterBody')
            },
            'statusCodeNotes': {
                'groundwater': 'chemicalStatus: Good/Poor/Unknown based on gwAtRiskChemical flag',
                'river': 'ecologicalStatus: 1=High, 2=Good, 3=Moderate, 4=Poor, 5=Bad'
            }
        }
    }
    
    # Save output
    output_path = 'data/water_quality/wise_monitoring_sites_processed.geojson'
    with open(output_path, 'w') as f:
        json.dump(geojson, f)
    print(f"\nSaved to {output_path}")
    
    # Print statistics
    print("\n=== Site Statistics ===")
    print(f"Groundwater sites: {geojson['metadata']['sitesByType']['groundwater']}")
    print(f"River sites: {geojson['metadata']['sitesByType']['river']}")
    print(f"Lake sites: {geojson['metadata']['sitesByType']['lake']}")
    
    print("\n=== Groundwater Chemical Status (CORRECTED) ===")
    for s, c in sorted(stats['groundwater'].items()):
        print(f"  {s}: {c}")
    
    print("\n=== River Ecological Status ===")
    eco_names = {'1': 'High', '2': 'Good', '3': 'Moderate', '4': 'Poor', '5': 'Bad'}
    for s, c in sorted(stats['river'].items()):
        print(f"  {eco_names.get(s, s)}: {c}")

if __name__ == '__main__':
    main()

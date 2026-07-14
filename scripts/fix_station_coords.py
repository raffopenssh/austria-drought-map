#!/usr/bin/env python3
"""Fix flow (OWF) and precipitation (NLV) station coordinates.

Previous pipeline used a crude linear BMN->WGS84 approximation:
    lat = 46 + (x - 150000) / 111000 ; lon = 9 + (y - 100000) / 75000
which ignored the three Gauss-Krueger meridian zones (M28/M31/M34) and
misplaced stations by up to ~100 km.

This script:
- NLV: parses exact geographic coordinates (deg min sec, Bessel 1841 ~= MGI)
  from Stammdaten and transforms MGI (EPSG:4312) -> WGS84.
- OWF: parses BMN Rechtswert/Hochwert, infers the meridian zone from the
  false easting (M28=150km, M31=450km, M34=750km) and transforms
  EPSG:31254/31255/31256 -> WGS84.
Then patches data/flow_analysis.json and data/precipitation_analysis.json
in place (and web/data copies).
"""
import json, re
from pathlib import Path
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
T_MGI = Transformer.from_crs('EPSG:4312', 'EPSG:4326', always_xy=True)
# BMN (Bundesmeldenetz) = Gauss-Krueger with false easting per meridian zone:
# M28 FE=150km -> EPSG:31257, M31 FE=450km -> EPSG:31258, M34 FE=750km -> EPSG:31259
T_BMN = {
    'M28': Transformer.from_crs('EPSG:31257', 'EPSG:4326', always_xy=True),
    'M31': Transformer.from_crs('EPSG:31258', 'EPSG:4326', always_xy=True),
    'M34': Transformer.from_crs('EPSG:31259', 'EPSG:4326', always_xy=True),
}

def bmn_zone(rechtswert):
    if rechtswert < 300000: return 'M28'
    if rechtswert < 600000: return 'M31'
    return 'M34'

def parse_nlv(path):
    """Extract lon/lat from geographic coordinates block (last entry wins)."""
    txt = path.read_text(encoding='latin-1')
    lon = lat = None
    in_block = False
    for line in txt.splitlines():
        if 'Geographische Koordinaten' in line:
            in_block = True; continue
        if in_block:
            m = re.findall(r'(?<![\d.])(\d{1,2})\s+(\d{2})\s+(\d{2})(?![.\d])', line)
            if len(m) == 2:
                (a1, a2, a3), (b1, b2, b3) = m
                lon = int(a1) + int(a2)/60 + int(a3)/3600
                lat = int(b1) + int(b2)/60 + int(b3)/3600
            elif line.strip() and 'gültig' not in line and 'seit' not in line.lower() and lon is not None:
                break
    if lon is None or not (8 < lon < 18 and 46 < lat < 50):
        return None
    if lon is None: return None
    wlon, wlat = T_MGI.transform(lon, lat)
    return round(wlon, 5), round(wlat, 5)

def parse_owf(path):
    """Extract latest BMN coordinates and transform per zone."""
    txt = path.read_text(encoding='latin-1')
    coords = None
    in_block = False
    for line in txt.splitlines():
        if 'Bundesmeldenetz' in line:
            in_block = True; continue
        if in_block:
            m = re.search(r'([\d.,]+)\s*-\s*([\d.,]+)', line)
            if m:
                y = float(m.group(1).replace('.', '').replace(',', '.'))
                x = float(m.group(2).replace('.', '').replace(',', '.'))
                coords = (y, x)  # keep last (most recent)
            elif line.strip() and coords is not None and 'gültig' not in line:
                break
    if coords is None: return None
    y, x = coords
    lon, lat = T_BMN[bmn_zone(y)].transform(y, x)
    if not (9.0 < lon < 17.3 and 46.3 < lat < 49.1):
        return None
    return round(lon, 5), round(lat, 5)

def build_lookup(folder, parser, id_re):
    lut = {}
    for p in sorted(folder.iterdir()):
        m = id_re.search(p.name)
        if not m: continue
        try:
            r = parser(p)
        except Exception:
            r = None
        if r: lut[m.group(1)] = r
    return lut

def patch(file, lut, kept_label):
    data = json.loads(file.read_text())
    fixed = missing = 0
    out = []
    for s in data:
        hzb = str(s.get('hzb'))
        if hzb in lut:
            s['lon'], s['lat'] = lut[hzb]
            fixed += 1
            out.append(s)
        else:
            missing += 1  # drop stations we cannot place correctly
    file.write_text(json.dumps(out))
    print(f"{kept_label}: fixed {fixed}, dropped {missing} (no reliable coords)")
    return out

def main():
    id_re = re.compile(r'-(\d+)\.')
    owf_lut = build_lookup(ROOT/'data/owf/Stammdaten', parse_owf, id_re)
    nlv_lut = build_lookup(ROOT/'data/nlv/Stammdaten', parse_nlv, id_re)
    print(f"OWF coords: {len(owf_lut)}, NLV coords: {len(nlv_lut)}")

    flow = patch(ROOT/'data/flow_analysis.json', owf_lut, 'flow stations')
    precip = patch(ROOT/'data/precipitation_analysis.json', nlv_lut, 'precip stations')

    # sanity
    for name, d in (('flow', flow), ('precip', precip)):
        lats = [s['lat'] for s in d]; lons = [s['lon'] for s in d]
        print(f"{name}: lat {min(lats):.2f}..{max(lats):.2f} lon {min(lons):.2f}..{max(lons):.2f}")

    # copy to web
    (ROOT/'web/data/flow_analysis.json').write_text(json.dumps(flow))
    (ROOT/'web/data/precipitation_analysis.json').write_text(json.dumps(precip))

if __name__ == '__main__':
    main()

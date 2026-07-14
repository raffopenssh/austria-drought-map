#!/usr/bin/env python3
"""Registry of ENTSO-E A73 per-unit hydro plants (AT bidding zone).

Coordinates = tailrace/plant location (OSM), i.e. where turbined water is
RELEASED to the river -> the point from which downstream impact propagates.
`units` maps ENTSO-E `plant` names (naming changed to turbine-unit level in
Dec 2024) onto one physical plant. `psr` per ENTSO-E; `river` = receiving
water body.
"""
PLANTS = {
    # --- Danube run-of-river cascade (upstream -> downstream) ---
    'aschach':      dict(name='Aschach', lat=48.3853, lon=14.0230, mw=324, psr='ror', river='Donau', units=['Aschach']),
    'ottensheim':   dict(name='Ottensheim-Wilhering', lat=48.3160, lon=14.1510, mw=179, psr='ror', river='Donau', units=['Ottensheim-Wilhering']),
    'abwinden':     dict(name='Abwinden-Asten', lat=48.2480, lon=14.4300, mw=168, psr='ror', river='Donau', units=['Abwinden-Asten']),
    'wallsee':      dict(name='Wallsee-Mitterkirchen', lat=48.1660, lon=14.6950, mw=210, psr='ror', river='Donau', units=['Wallsee-Mitterkirchen']),
    'ybbs':         dict(name='Ybbs-Persenbeug', lat=48.1900, lon=15.0690, mw=236, psr='ror', river='Donau', units=['Ybbs-Persenbeug']),
    'melk':         dict(name='Melk', lat=48.2230, lon=15.3040, mw=187, psr='ror', river='Donau', units=['Melk']),
    'altenwoerth':  dict(name='Altenwörth', lat=48.3759, lon=15.8564, mw=328, psr='ror', river='Donau', units=['Altenwörth']),
    'greifenstein': dict(name='Greifenstein', lat=48.3552, lon=16.2432, mw=293, psr='ror', river='Donau', units=['Greifenstein']),
    'freudenau':    dict(name='Freudenau', lat=48.1760, lon=16.4810, mw=172, psr='ror', river='Donau', units=['Freudenau']),
    # --- Drau ---
    'annabruecke':  dict(name='Annabrücke', lat=46.5610, lon=14.4800, mw=90, psr='ror', river='Drau', units=['Annabrücke']),
    # --- Kaprun / Salzach group ---
    'kaprun_haupt': dict(name='Kaprun-Hauptstufe', lat=47.2600, lon=12.7390, mw=260, psr='res', river='Kapruner Ache', units=['Kaprun-Hauptstufe']),
    'kaprun_ober':  dict(name='Kaprun-Oberstufe (Limberg)', lat=47.1971, lon=12.7193, mw=160, psr='ps', river='Wasserfallboden (Kapruner Ache)', units=['Kaprun-Oberstufe']),
    'limberg2':     dict(name='Limberg II', lat=47.1990, lon=12.7220, mw=480, psr='ps', river='Wasserfallboden (Kapruner Ache)', units=['Limberg II', 'Limberg II TU 1', 'Limberg II TU 2']),
    'limberg3':     dict(name='Limberg III', lat=47.1980, lon=12.7250, mw=480, psr='ps', river='Wasserfallboden (Kapruner Ache)', units=['Limberg III TU 1', 'Limberg III TU 2']),
    'schwarzach':   dict(name='Kaprun-Schwarzach (Flusskraftwerk)', lat=47.3154, lon=13.1397, mw=138, psr='res', river='Salzach', units=['Kaprun-Schwarzach']),
    # --- Malta / Möll group (Kärnten) ---
    'malta_ober':   dict(name='Malta-Oberstufe', lat=47.0659, lon=13.3527, mw=120, psr='ps', river='Galgenbichl (Malta)', units=['Malta-Oberstufe']),
    'malta_haupt':  dict(name='Malta-Hauptstufe', lat=46.8710, lon=13.3290, mw=730, psr='ps', river='Möll (Rottau)', units=['Malta-Hauptstufe', 'Malta-Hauptstufe TU 1', 'Malta-Hauptstufe TU 2', 'Malta-Hauptstufe TU 3', 'Malta-Hauptstufe TU 4']),
    'reisseck2':    dict(name='Reißeck II', lat=46.8954, lon=13.3440, mw=430, psr='ps', river='Möll (Kolbnitz)', units=['Reisseck 2', 'Reisseck 2 TU 1', 'Reisseck 2 TU 2']),
    # --- Ziller group (Tirol) ---
    'mayrhofen':    dict(name='Mayrhofen', lat=47.1580, lon=11.8510, mw=355, psr='res', river='Ziller', units=['Mayrhofen']),
    'haeusling':    dict(name='Häusling', lat=47.1460, lon=11.9670, mw=360, psr='ps', river='Zillergründl/Stillup (Ziller)', units=['Häusling', 'Haeusling TU 11', 'Haeusling TU 12']),
    'rosshag':      dict(name='Roßhag', lat=47.0870, lon=11.7740, mw=231, psr='ps', river='Zemmbach (Ziller)', units=['Roßhag']),
    'gerlos':       dict(name='Gerlos', lat=47.2340, lon=11.8990, mw=200, psr='res', river='Gerlosbach (Ziller)', units=['Gerlos', 'Gerlos TU 5']),
}
PSR_LABEL = {'ror': 'Run-of-river', 'res': 'Reservoir', 'ps': 'Pumped storage'}
PSR_ENTSOE = {'ror': 'Hydro Run-of-river and poundage',
              'res': 'Hydro Water Reservoir',
              'ps': 'Hydro Pumped Storage'}

UNIT_TO_PLANT = {}
for pid, p in PLANTS.items():
    for u in p['units']:
        UNIT_TO_PLANT[u] = pid

#!/usr/bin/env python3
"""Build web/data/population.json from Statistik Austria OGD population files.

Input: data/pop/OGD_bevstandjbab2002_BevStand_{YYYY}.csv (2002..2026),
population on Jan 1 per municipality x single-year age x sex, harmonized
to the 2026 Gebietsstand (identical GRGEMAKT code set in every year).
Source: https://data.statistik.gv.at (CC-BY-4.0), dataset
OGD_bevstandjbab2002_BevStand_[year]. Cross-checked against
Bev_2026_Alter_Geschlecht_Gebietseinheiten.ods (Austria 2026 = 9,215,956).

Output per Gemeinde:
  t   : total population per year (list, one per YEAR)
  y65 : population aged 65+ per year (context only; across Gemeinden 65+ share
        correlates -0.62 with growth, so growth is the informative axis)
Gender split & pyramids deliberately omitted: male share is 49.8% +- ~1.5pp
across practically all Gemeinden - no signal for water demand.
Vienna: district codes 9xxxx are kept AND aggregated to 90001 ("Wien"),
matching the choropleth. `alias` maps pre-merger codes used elsewhere in the
app (e.g. 70327 Matrei a.B.) to the merged OGD code (70370).
"""
import csv
import gzip
import json
import os
from collections import defaultdict

BASE = os.path.join(os.path.dirname(__file__), '..')
POP_DIR = os.path.join(BASE, 'data', 'pop')
OUT = os.path.join(BASE, 'web', 'data', 'population.json')
YEARS = list(range(2002, 2027))
LATEST, FIRST = YEARS[-1], YEARS[0]

# municipalities.json / cadastre still carry pre-merger codes for these:
ALIAS = {
    '62252': '62280', '62267': '62280',            # Soechau+Fuerstenfeld -> Fuerstenfeld
    '70327': '70370', '70330': '70370', '70341': '70370',  # Matrei a.B.+Muehlbachl+Pfons
}


def age_from_code(code):
    """GALTEJ112-N => age N-1 (single years 0..99); GALT5J100-21 => 100+."""
    kind, n = code.rsplit('-', 1)
    n = int(n)
    if kind == 'GALTEJ112':
        return n - 1
    if kind == 'GALT5J100' and n == 21:
        return 100
    raise ValueError(code)


def load_year(year):
    """Return {gem_code: {(age, sex): count}} with Vienna 90001 aggregate."""
    data = defaultdict(lambda: defaultdict(int))
    path = os.path.join(POP_DIR, f'OGD_bevstandjbab2002_BevStand_{year}.csv')
    with open(path) as f:
        rd = csv.reader(f, delimiter=';')
        next(rd)
        for _, sex, gem, agec, n in rd:
            g = gem.split('-')[1]
            key = (age_from_code(agec), sex[-1])  # sex: C11-1 male, C11-2 female
            n = int(n)
            data[g][key] += n
            if g.startswith('9'):
                data['90001'][key] += n
    return data


def main():
    names = {}
    with open(os.path.join(POP_DIR, 'gemeinde_names.csv')) as f:
        rd = csv.reader(f, delimiter=';')
        next(rd)
        for row in rd:
            code = row[0].split('-')[1]
            names[code] = row[1].rsplit(' <', 1)[0]
    names['90001'] = 'Wien'

    gems = {}
    for year in YEARS:
        data = load_year(year)
        for g, rec in data.items():
            e = gems.setdefault(g, {'n': names.get(g, g), 't': [], 'y65': []})
            tot = y65 = 0
            for (age, _s), n in rec.items():
                tot += n
                if age >= 65:
                    y65 += n
            e['t'].append(tot)
            e['y65'].append(y65)
        print(year, 'total', sum(v for g, r in data.items() if g != '90001'
                                 for v in r.values()))

    out = {
        'source': 'STATISTIK AUSTRIA, Statistik des Bevoelkerungsstandes '
                  '(data.statistik.gv.at OGD, CC-BY-4.0)',
        'note': 'Population on Jan 1, harmonized to the 2026 Gebietsstand.',
        'years': YEARS,
        'alias': ALIAS,
        'gemeinden': gems,
    }
    js = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
    with open(OUT, 'w') as f:
        f.write(js)
    with gzip.open(OUT + '.gz', 'wt', compresslevel=9) as f:
        f.write(js)
    print(f'{len(gems)} gemeinden -> {OUT} '
          f'({len(js)/1e6:.1f} MB raw, '
          f'{os.path.getsize(OUT + ".gz")/1e6:.1f} MB gz)')


if __name__ == '__main__':
    main()

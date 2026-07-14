#!/bin/bash
# Daily data refresh: eHYD live GW levels (self-backfilling within year),
# ENTSO-E daily hydro MWh, NASA POWER daily precip, power<->GW analysis.
set -u
cd "$(dirname "$0")/.."
mkdir -p logs
{
  echo "=== $(date -Is) ==="
  python3 scripts/fetch_ehyd_live.py
  python3 scripts/fetch_ehyd_pegel.py
  TOKEN=rcv4NYye5cPXOviOKRRR2uf7lkXhLFEZIALehhifL7A
  curl -sG "https://austria-power.exe.xyz/api/entsoe/query" \
    --data-urlencode "token=$TOKEN" --data-urlencode "format=csv" \
    --data-urlencode "sql=SELECT substr(timestamp,1,10) AS day, psr_type, ROUND(SUM(value_mw)/4.0,1) AS mwh FROM generation WHERE psr_type IN ('Hydro Pumped Storage','Hydro Pumped Storage Consumption','Hydro Run-of-river and poundage','Hydro Water Reservoir') GROUP BY 1,2 ORDER BY 1" \
    -o data/hydro_daily_mwh.csv.tmp && mv data/hydro_daily_mwh.csv.tmp data/hydro_daily_mwh.csv
  python3 scripts/fetch_nasa_power_daily.py
  python3 scripts/analyze_power_gw.py
} >> logs/cron_daily.log 2>&1

#!/bin/sh
cd /Users/samuelmorningstar/Trackshift/proto
for i in 1 2 3 4 5 6; do
  echo "== retry $i at $(date) =="
  ../.venv/bin/python extract_extra.py --year 2025 --events Belgium,Britain,Hungary,Zandvoort,Monza --out feat2025 --cache ~/Trackshift/cache2
  n=$(ls feat2025 | grep -c -E "^(Belgium|Britain|Hungary|Zandvoort|Monza)_")
  echo "files for the five events: $n / 25"
  [ "$n" -ge 25 ] && break
  sleep 1500
done
echo "RETRY LOOP DONE"

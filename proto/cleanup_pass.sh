#!/bin/sh
cd /Users/samuelmorningstar/Trackshift/proto
while pgrep -f 'extract_seasons.py --years' >/dev/null; do sleep 60; done
echo "== cleanup pass started $(date) =="
for i in 1 2 3; do
  ../.venv/bin/python extract_seasons.py --years 2025,2024,2023 --cache ~/Trackshift/cache2 --skip LasVegas 2>&1 | grep -v -i warning
  n=$(cat feat2025 feat2024 feat2023 2>/dev/null | wc -l); echo "pass $i complete $(date)"
  miss=$(grep -c FAILED cleanup_pass.log 2>/dev/null); sleep 120
done
echo "ALL SEASONS COMPLETE $(date)"

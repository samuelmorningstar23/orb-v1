#!/bin/sh
# One command after each new Madrid session: pull any new sessions, rebuild the lock, refresh the liquid model. Run from proto/.
cd "$(dirname "$0")"
../.venv/bin/python extract_extra.py --year 2026 --events Madrid --out feat --cache ~/Trackshift/cache2 2>&1 | grep -E "laps in|FAILED|not run|exists|round"
../.venv/bin/python pipeline.py 2>&1 | grep -v -i "warning\|DLASCL" | tail -6
echo "lock rebuilt: $(date)"
../.venv/bin/python make_deck_figs.py 2>&1 | grep -v -i "warning\|DLASCL" | tail -1
../.venv/bin/python build_deck_v5.py 2>&1 | grep -v -i "warning\|DLASCL" | tail -1
echo "figures and deck rebuilt: $(date)"

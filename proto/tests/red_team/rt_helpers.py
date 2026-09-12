"""Shared constants for the red-team acceptance suite (a uniquely named module: `from conftest import ...` would resolve to
whichever suite's conftest.py pytest imported first when the whole tests/ tree runs at a checkpoint)."""
from __future__ import annotations

import sys
from pathlib import Path

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

EVENT, DRIVER, LAP = 'Monza', 'NOR', 12      # a completed 2026 race with a hashed live record and on-disk scenarios

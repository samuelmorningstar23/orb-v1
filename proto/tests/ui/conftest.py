"""Test bootstrap for the Workstream 6 UI suite: put proto/ on sys.path so `app_v2` imports resolve."""
import sys
from pathlib import Path

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

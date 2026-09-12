"""Re-export of the frozen Orb v1 tokens (proto/ui/tokens.py) loaded by file path.

Loading by path avoids the `ui` package-name clash between proto/ui (frozen tokens) and
proto/app_v2/ui (design-system components). Nothing here redefines a token.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

PROTO_ROOT = Path(__file__).resolve().parents[2]
_TOKENS_PATH = PROTO_ROOT / 'ui' / 'tokens.py'
_spec = importlib.util.spec_from_file_location('orb_frozen_tokens', _TOKENS_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

COLORS = dict(_mod.COLORS)
COMPOUNDS = dict(_mod.COMPOUNDS)
COMPOUND_GLYPH = dict(_mod.COMPOUND_GLYPH)
FONT_STACK = _mod.FONT_STACK
SPACING = _mod.SPACING
RADIUS = _mod.RADIUS
BORDER = _mod.BORDER
PRECISION = dict(_mod.PRECISION)
fmt = _mod.fmt

# Extensions (not contradictions) of the frozen set: monospace stack for hashes / tabular numerals,
# and the status palette used by chips. Colours are drawn from COLORS only.
MONO_STACK = 'ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace'
STATUS = {
    'IN SUPPORT': COLORS['live'],
    'NEAR TRAINING SUPPORT': COLORS['decision'],
    'OUT OF SUPPORT, FORECAST WITHHELD': COLORS['critical'],
    'OUT OF SUPPORT': COLORS['critical'],
    'PENDING': COLORS['text_secondary'],
}
STATUS_GLYPH = {  # status is never colour-only
    'IN SUPPORT': '●', 'NEAR TRAINING SUPPORT': '◐', 'OUT OF SUPPORT, FORECAST WITHHELD': '○', 'OUT OF SUPPORT': '○', 'PENDING': '◌',
}
BASE_CSS_PATH = PROTO_ROOT / 'theme' / 'base.css'
PREMIUM_CSS_PATH = PROTO_ROOT / 'theme' / 'premium.css'


def fmt_or_dash(value, kind: str, dash: str = '—') -> str:
    """fmt() with a visible dash for missing values (None / NaN)."""
    try:
        if value is None or value != value:  # NaN check without numpy
            return dash
        return fmt(float(value), kind)
    except (TypeError, ValueError):
        return dash

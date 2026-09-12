"""One decimal convention, from the frozen tokens (ui/tokens.PRECISION). Every displayed number passes through here."""
from __future__ import annotations
import html as _html
from typing import Optional
from app_v2.theme.tokens import fmt, fmt_or_dash, PRECISION

DASH = '—'


def spl(v) -> str:            # seconds per lap of age, 3 decimals, signed
    return fmt_or_dash(v, 'seconds_per_lap')


def secs(v) -> str:           # seconds, 1 decimal, signed
    return fmt_or_dash(v, 'seconds')


def pct(v, signed: bool = False) -> str:
    if v is None or v != v:
        return DASH
    return f'{100 * v:+.0f}%' if signed else f'{100 * v:.0f}%'


def laps(v) -> str:
    if v is None or v != v:
        return DASH
    return f'{int(round(v))}'


def temp(v) -> str:
    if v is None or v != v:
        return DASH
    return f'{v:.{PRECISION["temperature"]}f} °C'


def hash6(h: Optional[str]) -> str:
    return (h or '')[:6] or '------'


def esc(s) -> str:
    return _html.escape('' if s is None else str(s))


def band(lo, hi, kind: str = 'seconds_per_lap') -> str:
    if lo is None or hi is None:
        return DASH
    return f'{fmt(lo, kind)} to {fmt(hi, kind)}'

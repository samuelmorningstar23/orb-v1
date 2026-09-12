"""Orb v1 design tokens (frozen at C0). Single source for colours, type, spacing, precision."""
COLORS = dict(background='#090C11', surface='#11161E', raised='#171D27', border='#272F3B', text='#F3F6FA', text_secondary='#98A3B3', live='#39D0C3', decision='#F0B84B', critical='#F16464')
COMPOUNDS = dict(SOFT='#E10600', MEDIUM='#F2C230', HARD='#D9DEE5', INTERMEDIATE='#3DBE6B', WET='#3B82F6')   # intermediate and wet only when supported
COMPOUND_GLYPH = dict(SOFT='S', MEDIUM='M', HARD='H', INTERMEDIATE='I', WET='W')                     # status is never colour-only
FONT_STACK = 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
SPACING = 8; RADIUS = 14; BORDER = 1
PRECISION = dict(seconds_per_lap=3, seconds=1, percent=0, laps=0, temperature=1)
def fmt(value, kind):
    d = PRECISION[kind]; return f"{value:+.{d}f}" if kind in ('seconds_per_lap', 'seconds') else f"{value:.{d}f}"

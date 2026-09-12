"""Plotly fallback for the Race Twin map. Without a canonical centreline the track is a synthetic closed
loop; two markers (actual car, ghost car) are driven by the lap scrubber and the counterfactual delta."""
from __future__ import annotations
import math
import numpy as np
import plotly.graph_objects as go
from app_v2.theme.tokens import COLORS, COMPOUNDS
from app_v2.theme.plotly_theme import apply, rgba


def synthetic_loop(n: int = 240) -> tuple[np.ndarray, np.ndarray]:
    """A closed loop with straights and a chicane-like wobble: an ellipse modulated so it does not read as a real circuit."""
    t = np.linspace(0, 2 * math.pi, n)
    r = 1.0 + 0.12 * np.sin(3 * t) + 0.05 * np.cos(5 * t)
    return 1.6 * r * np.cos(t), r * np.sin(t)


def position_on_loop(progress: float, x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    i = int((progress % 1.0) * (len(x) - 1))
    return float(x[i]), float(y[i])


def race_twin_map(lap: int, n_laps: int, mean_lap_s: float | None, delta_s: float | None, actual_compound: str, ghost_compound: str, pit_lap: int | None, presentation: bool = False) -> go.Figure:
    x, y = synthetic_loop()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=y, mode='lines', name='synthetic loop (canonical centreline pending Workstream 4)', line=dict(color=COLORS['border'], width=10), hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=x, y=y, mode='lines', line=dict(color=COLORS['raised'], width=6), showlegend=False, hoverinfo='skip'))
    # pit lane: a short inner chord near the start line
    fig.add_trace(go.Scatter(x=[1.45, 1.2, 1.2, 1.45], y=[-0.25, -0.2, 0.2, 0.25], mode='lines', name='pit-lane path (schematic)', line=dict(color=COLORS['text_secondary'], width=2, dash='dot'), hoverinfo='skip'))
    frac = (lap - 1) / max(n_laps, 1)
    ax, ay = position_on_loop(frac, x, y)
    ghost_frac = frac
    if delta_s is not None and mean_lap_s:
        ghost_frac = frac - (delta_s / mean_lap_s) * (0 if pit_lap is None or lap < pit_lap else min((lap - pit_lap) / max(n_laps - pit_lap, 1), 1.0))
    gx, gy = position_on_loop(ghost_frac, x, y)
    ca = COMPOUNDS.get(actual_compound, COLORS['text']); cg = COMPOUNDS.get(ghost_compound, COLORS['decision'])
    fig.add_trace(go.Scatter(x=[gx], y=[gy], mode='markers+text', name=f'ghost car ({ghost_compound.lower()})', marker=dict(color=cg, size=18 if presentation else 14, symbol='circle', line=dict(color=COLORS['background'], width=2), opacity=0.85),
                             text=['G'], textposition='middle center', textfont=dict(color=COLORS['background'], size=10)))
    fig.add_trace(go.Scatter(x=[gx], y=[gy], mode='markers', name='uncertainty halo (pending quantiles)', marker=dict(color=rgba(cg, 0.15), size=40, symbol='circle'), hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=[ax], y=[ay], mode='markers+text', name=f'actual car ({actual_compound.lower()})', marker=dict(color=ca, size=18 if presentation else 14, symbol='circle', line=dict(color=COLORS['text'], width=2)),
                             text=['A'], textposition='middle center', textfont=dict(color=COLORS['background'], size=10)))
    fig.add_annotation(x=x[0], y=y[0], text='S/F', showarrow=False, font=dict(size=10, color=COLORS['text_secondary']), yshift=14)
    d = f'{delta_s:+.1f} s' if delta_s is not None else '—'
    fig.add_annotation(x=0, y=0, text=f'lap {lap}/{n_laps}<br>ghost delta at flag {d}', showarrow=False, font=dict(size=14 if presentation else 12, color=COLORS['text']))
    apply(fig, height=470 if presentation else 420, xaxis=dict(visible=False, scaleanchor='y', scaleratio=1, range=[-2.0, 2.0]), yaxis=dict(visible=False, range=[-1.35, 1.35]), margin=dict(l=8, r=8, t=32, b=8),
          title='Race Twin map · SYNTHETIC LOOP (centreline pending Workstream 4)', showlegend=False)
    return fig

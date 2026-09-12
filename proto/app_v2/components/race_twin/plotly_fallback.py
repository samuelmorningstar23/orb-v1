"""Plotly fallback for the Race Twin map.

`race_twin_map` (Workstream 6's original call) draws the lap-scrubbed two-marker map; with `track` / `pitlane` (Workstream 4 assets)
it uses the canonical centreline instead of the synthetic loop. `race_twin_animation` animates the same 1 Hz frame arrays
the browser player uses (subsampled every `step_s`) with Plotly frames, a play/pause menu and a time slider: slower than the
canvas player but it needs nothing beyond plotly.
"""
from __future__ import annotations
import math
from typing import Any, Optional
import numpy as np
import plotly.graph_objects as go
from app_v2.theme.tokens import COLORS, COMPOUNDS
from app_v2.theme.plotly_theme import apply, rgba

CODE_NAME = {0: 'UNKNOWN', 1: 'SOFT', 2: 'MEDIUM', 3: 'HARD', 4: 'INTERMEDIATE', 5: 'WET'}


def synthetic_loop(n: int = 240) -> tuple[np.ndarray, np.ndarray]:
    """A closed loop with straights and a chicane-like wobble: an ellipse modulated so it does not read as a real circuit."""
    t = np.linspace(0, 2 * math.pi, n)
    r = 1.0 + 0.12 * np.sin(3 * t) + 0.05 * np.cos(5 * t)
    return 1.6 * r * np.cos(t), r * np.sin(t)


def position_on_loop(progress: float, x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    i = int((progress % 1.0) * (len(x) - 1))
    return float(x[i]), float(y[i])


def _as_dict(obj: Any, kind: str) -> Optional[dict]:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    if hasattr(obj, 'to_player_dict'):
        return obj.to_player_dict()
    raise TypeError(f'{kind}: expected a replay dataclass or its dict export')


def _xy_at(track: dict, s: float) -> tuple[float, float]:
    x, y = track['x'], track['y']; L = float(track['L']); n = len(x); g = L / n
    s = s % L; f = s / g; i = int(math.floor(f)) % n; a = f - math.floor(f); j = (i + 1) % n
    return x[i] + a * (x[j] - x[i]), y[i] + a * (y[j] - y[i])


def _xy_pit(pit: dict, sp: float) -> tuple[float, float]:
    s, x, y = pit['s'], pit['x'], pit['y']
    if sp <= s[0]:
        return x[0], y[0]
    if sp >= s[-1]:
        return x[-1], y[-1]
    k = int(np.searchsorted(np.asarray(s), sp, side='right')) - 1
    a = (sp - s[k]) / max(s[k + 1] - s[k], 1e-9)
    return x[k] + a * (x[k + 1] - x[k]), y[k] + a * (y[k + 1] - y[k])


def _halo_xy(track: dict, S90: float, S10: float) -> tuple[list[float], list[float]]:
    L = float(track['L']); g = L / len(track['x']); span = S10 - S90
    if span < 1:
        return [], []
    if span >= L:
        return list(track['x']) + [track['x'][0]], list(track['y']) + [track['y'][0]]
    ss = np.arange(0.0, span, g).tolist() + [span]
    pts = [_xy_at(track, S90 + d) for d in ss]
    return [p[0] for p in pts], [p[1] for p in pts]


def _base_traces(track: Optional[dict], pitlane: Optional[dict]) -> tuple[list[go.Scatter], dict]:
    if track is None:
        x, y = synthetic_loop()
        traces = [go.Scatter(x=x, y=y, mode='lines', name='synthetic loop (canonical centreline pending)', line=dict(color=COLORS['border'], width=10), hoverinfo='skip'),
                  go.Scatter(x=x, y=y, mode='lines', line=dict(color=COLORS['raised'], width=6), showlegend=False, hoverinfo='skip'),
                  go.Scatter(x=[1.45, 1.2, 1.2, 1.45], y=[-0.25, -0.2, 0.2, 0.25], mode='lines', name='pit-lane path (schematic)', line=dict(color=COLORS['text_secondary'], width=2, dash='dot'), hoverinfo='skip')]
        return traces, dict(xr=[-2.0, 2.0], yr=[-1.35, 1.35], sf=(float(x[0]), float(y[0])))
    x = list(track['x']) + [track['x'][0]]; y = list(track['y']) + [track['y'][0]]
    traces = [go.Scatter(x=x, y=y, mode='lines', name='canonical path', line=dict(color=COLORS['border'], width=9), hoverinfo='skip'),
              go.Scatter(x=x, y=y, mode='lines', line=dict(color=COLORS['raised'], width=5), showlegend=False, hoverinfo='skip')]
    if pitlane is not None and pitlane.get('x'):
        traces.append(go.Scatter(x=pitlane['x'], y=pitlane['y'], mode='lines', name=f"pit lane ({pitlane.get('source', 'recorded')})", line=dict(color=COLORS['text_secondary'], width=1.6, dash='dot'), hoverinfo='skip'))
    else:
        traces.append(go.Scatter(x=[], y=[], mode='lines', name='pit lane (none)', hoverinfo='skip'))
    xs = list(track['x']) + (list(pitlane['x']) if pitlane else []); ys = list(track['y']) + (list(pitlane['y']) if pitlane else [])
    px = (max(xs) - min(xs)) * 0.06 + 1; py = (max(ys) - min(ys)) * 0.06 + 1
    return traces, dict(xr=[min(xs) - px, max(xs) + px], yr=[min(ys) - py, max(ys) + py], sf=_xy_at(track, 0.0))


def race_twin_map(lap: int, n_laps: int, mean_lap_s: float | None, delta_s: float | None, actual_compound: str, ghost_compound: str, pit_lap: int | None, presentation: bool = False,
                  track: Any = None, pitlane: Any = None) -> go.Figure:
    """Lap-scrubbed map: the ghost trails or leads by delta_s (spread from pit_lap) along the loop. With `track` the canonical
    centreline replaces the synthetic loop; the halo stays a pending marker until frames are used (race_twin_animation)."""
    tr = _as_dict(track, 'track'); pl = _as_dict(pitlane, 'pitlane')
    base, ext = _base_traces(tr, pl)
    fig = go.Figure(base)
    frac = (lap - 1) / max(n_laps, 1)
    ghost_frac = frac
    if delta_s is not None and mean_lap_s:
        ghost_frac = frac - (delta_s / mean_lap_s) * (0 if pit_lap is None or lap < pit_lap else min((lap - pit_lap) / max(n_laps - pit_lap, 1), 1.0))
    if tr is None:
        x, y = synthetic_loop(); ax, ay = position_on_loop(frac, x, y); gx, gy = position_on_loop(ghost_frac, x, y)
    else:
        L = float(tr['L']); ax, ay = _xy_at(tr, frac * L); gx, gy = _xy_at(tr, ghost_frac * L)
    ca = COMPOUNDS.get(actual_compound, COLORS['text']); cg = COMPOUNDS.get(ghost_compound, COLORS['decision'])
    fig.add_trace(go.Scatter(x=[gx], y=[gy], mode='markers+text', name=f'ghost car ({ghost_compound.lower()})', marker=dict(color=cg, size=18 if presentation else 14, symbol='circle', line=dict(color=COLORS['background'], width=2), opacity=0.85),
                             text=['G'], textposition='middle center', textfont=dict(color=COLORS['background'], size=10)))
    fig.add_trace(go.Scatter(x=[gx], y=[gy], mode='markers', name='uncertainty halo (pending quantiles)', marker=dict(color=rgba(cg, 0.15), size=40, symbol='circle'), hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=[ax], y=[ay], mode='markers+text', name=f'actual car ({actual_compound.lower()})', marker=dict(color=ca, size=18 if presentation else 14, symbol='circle', line=dict(color=COLORS['text'], width=2)),
                             text=['A'], textposition='middle center', textfont=dict(color=COLORS['background'], size=10)))
    fig.add_annotation(x=ext['sf'][0], y=ext['sf'][1], text='S/F', showarrow=False, font=dict(size=10, color=COLORS['text_secondary']), yshift=14)
    d = f'{delta_s:+.1f} s' if delta_s is not None else '—'
    cx, cy = (0, 0) if tr is None else (float(np.mean(tr['x'])), float(np.mean(tr['y'])))
    fig.add_annotation(x=cx, y=cy, text=f'lap {lap}/{n_laps}<br>ghost delta at flag {d}', showarrow=False, font=dict(size=14 if presentation else 12, color=COLORS['text']))
    title = 'Race Twin map · SYNTHETIC LOOP (centreline pending Workstream 4)' if tr is None else f"Race Twin map · canonical path {tr.get('event') or ''} (lap-scrubbed fallback)"
    apply(fig, height=470 if presentation else 420, xaxis=dict(visible=False, scaleanchor='y', scaleratio=1, range=ext['xr']), yaxis=dict(visible=False, range=ext['yr']), margin=dict(l=8, r=8, t=32, b=8),
          title=title, showlegend=False)
    return fig


def race_twin_animation(frames: Any, track: Any, pitlane: Any = None, step_s: int = 5, height: int = 470, presentation: bool = False, max_frames: int = 1200) -> go.Figure:
    """Plotly frame animation of the 1 Hz Race Twin frames (the same arrays as the browser player), subsampled every step_s
    seconds (coarsened further if the race would exceed max_frames). Halo = path segment between the 10-90 % positions."""
    fr = _as_dict(frames, 'frames'); tr = _as_dict(track, 'track'); pl = _as_dict(pitlane, 'pitlane')
    n = len(fr['t']); step = max(int(step_s), 1)
    if n / step > max_frames:
        step = int(math.ceil(n / max_frames))
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    base, ext = _base_traces(tr, pl)
    meta = fr.get('meta', {}); n_laps = meta.get('n_laps') or max(fr['lap_actual'])

    def marks(i: int):
        pitG = fr['cf_pit'][i] == 1 and fr['cf_pit_progress'][i] is not None and pl is not None
        pitA = fr['act_pit'][i] == 1 and fr['act_pit_progress'][i] is not None and pl is not None
        gx, gy = _xy_pit(pl, fr['cf_pit_progress'][i]) if pitG else _xy_at(tr, fr['S_cf'][i])
        ax, ay = _xy_pit(pl, fr['act_pit_progress'][i]) if pitA else _xy_at(tr, fr['S_actual'][i])
        hx, hy = _halo_xy(tr, fr['S_cf_q90'][i], fr['S_cf_q10'][i])
        cg = COMPOUNDS.get(CODE_NAME[fr['compound_cf'][i]], COLORS['decision']); ca = COMPOUNDS.get(CODE_NAME[fr['compound_actual'][i]], COLORS['text'])
        td = fr['time_delta_s'][i]; dd = fr['distance_delta_m'][i]
        status = {4: 'SAFETY CAR', 5: 'RED FLAG', 6: 'VSC', 7: 'VSC ENDING'}.get(fr['track_status'][i], '')
        txt = f"lap {fr['lap_actual'][i]}/{n_laps} · t {int(fr['t'][i]) // 60}:{int(fr['t'][i]) % 60:02d}<br>ghost {td:+.1f} s · {abs(dd):.0f} m {'ahead' if dd >= 0 else 'behind'}" + (f'<br>{status}' if status else '')
        return [go.Scatter(x=hx, y=hy, mode='lines', name='halo 10–90 %', line=dict(color=rgba(cg, 0.28), width=11), hoverinfo='skip'),
                go.Scatter(x=[gx], y=[gy], mode='markers+text', name=f"ghost ({CODE_NAME[fr['compound_cf'][i]].lower()} age {fr['tyre_age_cf'][i]})", marker=dict(color=cg, size=18 if presentation else 14, line=dict(color=COLORS['background'], width=2), opacity=0.85),
                           text=['G'], textposition='middle center', textfont=dict(color=COLORS['background'], size=10)),
                go.Scatter(x=[ax], y=[ay], mode='markers+text', name=f"actual ({CODE_NAME[fr['compound_actual'][i]].lower()} age {fr['tyre_age_actual'][i]})", marker=dict(color=ca, size=18 if presentation else 14, line=dict(color=COLORS['text'], width=2)),
                           text=['A'], textposition='middle center', textfont=dict(color=COLORS['background'], size=10))], txt

    first, txt0 = marks(idx[0])
    fig = go.Figure(base + first)
    nb = len(base)
    cx, cy = float(np.mean(tr['x'])), float(np.mean(tr['y']))
    fig.add_annotation(x=cx, y=cy, text=txt0, showarrow=False, font=dict(size=14 if presentation else 12, color=COLORS['text']), name='readout')
    fig.add_annotation(x=ext['sf'][0], y=ext['sf'][1], text='S/F', showarrow=False, font=dict(size=10, color=COLORS['text_secondary']), yshift=14)
    pframes = []
    for i in idx:
        data, txt = marks(i)
        pframes.append(go.Frame(data=data, traces=[nb, nb + 1, nb + 2], name=str(int(fr['t'][i])), layout=go.Layout(annotations=[dict(x=cx, y=cy, text=txt, showarrow=False, font=dict(size=14 if presentation else 12, color=COLORS['text']))])))
    fig.frames = pframes
    dur = int(1000 * step / 10)     # 10x playback: each subsampled frame shows for step/10 s
    fig.update_layout(updatemenus=[dict(type='buttons', showactive=False, x=0.0, y=-0.04, xanchor='left', yanchor='top', direction='left', bgcolor=COLORS['raised'], bordercolor=COLORS['border'], font=dict(color=COLORS['text']),
                                        buttons=[dict(label='▶ play 10x', method='animate', args=[None, dict(frame=dict(duration=dur, redraw=False), transition=dict(duration=0), fromcurrent=True, mode='immediate')]),
                                                 dict(label='❚❚ pause', method='animate', args=[[None], dict(frame=dict(duration=0, redraw=False), mode='immediate', transition=dict(duration=0))])])],
                      sliders=[dict(active=0, x=0.22, y=-0.04, len=0.78, xanchor='left', yanchor='top', pad=dict(t=0), currentvalue=dict(prefix='race time (s): ', font=dict(size=11, color=COLORS['text_secondary'])), bgcolor=COLORS['raised'], bordercolor=COLORS['border'], tickcolor=COLORS['border'],
                                    font=dict(color=COLORS['text_secondary'], size=9), steps=[dict(method='animate', args=[[f.name], dict(mode='immediate', frame=dict(duration=0, redraw=False), transition=dict(duration=0))], label=f.name if k % max(len(pframes) // 8, 1) == 0 else '') for k, f in enumerate(pframes)])])
    label = meta.get('source', ''); title = f"Race Twin · Plotly fallback · {meta.get('event', '')} {meta.get('driver', '')} · {meta.get('scenario_id', '')}" + (f' · {label}' if label else '')
    apply(fig, height=height + 60, xaxis=dict(visible=False, scaleanchor='y', scaleratio=1, range=ext['xr']), yaxis=dict(visible=False, range=ext['yr']), margin=dict(l=8, r=8, t=32, b=70), title=title, showlegend=False)
    return fig


__all__ = ['synthetic_loop', 'position_on_loop', 'race_twin_map', 'race_twin_animation']

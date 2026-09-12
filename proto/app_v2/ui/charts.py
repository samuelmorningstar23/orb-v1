"""Chart builders on the Orb Plotly template. Inputs are view models; no chart computes a scientific number."""
from __future__ import annotations
import numpy as np
import plotly.graph_objects as go
from app_v2.theme.tokens import COLORS, COMPOUNDS
from app_v2.theme.plotly_theme import apply, rgba

COMPOUND_DASH = {'SOFT': 'solid', 'MEDIUM': 'dash', 'HARD': 'dot', 'INTERMEDIATE': 'dashdot', 'WET': 'longdash'}


def _ages(max_age: float, n: int = 40) -> np.ndarray:
    return np.linspace(0, max(max_age, 5.0), n)


def forecast_vs_live(vm, presentation: bool = False, estimator_label: str = 'PLACEHOLDER', projection: list | None = None) -> go.Figure:
    """Pre-race band, corrected live observations, the live posterior (labelled with its estimator), forward projection, crossover, annotations."""
    fig = go.Figure(); st = vm.state; prior = vm.prior; comp = st.compound if st else prior.compound; lab = estimator_label
    col = COMPOUNDS.get(comp, COLORS['text_secondary'])
    max_age = max([st.tyre_age + 10 if st else 20] + [a for t in vm.comparable for a in t['ages']] + [vm.crossover.get(k, 0) + 2 for k in vm.crossover])
    xs = _ages(max_age)
    lo, hi = prior.band90
    if prior.slope is not None and lo is not None and hi is not None:
        fig.add_trace(go.Scatter(x=np.r_[xs, xs[::-1]], y=np.r_[lo * xs, (hi * xs)[::-1]], fill='toself', fillcolor=rgba(col, 0.12), line=dict(width=0), name='pre-race 90% band (lock)', hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=xs, y=prior.slope * xs, mode='lines', name=f'pre-race forecast {prior.slope:+.3f} s/lap (lock)', line=dict(color=col, width=1.5, dash='dash')))
    for t in vm.comparable:
        fig.add_trace(go.Scatter(x=t['ages'], y=t['losses'], mode='lines', name=f"{t['driver']} (comparable stint)", line=dict(color=COLORS['text_secondary'], width=1), opacity=0.25, showlegend=False, hoverinfo='skip'))
    y_lo, y_hi = -0.6, 2.0
    if prior.slope is not None and hi is not None:
        y_hi = max(y_hi, hi * min(max_age, (st.tyre_age + 10) if st else max_age) + 0.3)
    if st is not None and st.all_ages:
        kept_x = [a for a, k in zip(st.all_ages, st.all_kept) if k]; kept_y = [l for l, k in zip(st.all_losses, st.all_kept) if k]
        if kept_y:
            y_lo, y_hi = min(y_lo, min(kept_y) - 0.3), max(y_hi, max(kept_y) + 0.5)
        if st.post_slope is not None:
            _pr = projection or st.project()
            y_hi = max(y_hi, max(p['hi'] for p in _pr) + 0.3) if _pr else y_hi
        drop_x = [a for a, k in zip(st.all_ages, st.all_kept) if not k]; drop_y_raw = [l for l, k in zip(st.all_losses, st.all_kept) if not k]
        drop_y = [min(max(l, y_lo + 0.15), y_hi - 0.15) for l in drop_y_raw]
        drop_sym = ['triangle-up-open' if l > y_hi - 0.15 else ('triangle-down-open' if l < y_lo + 0.15 else 'circle-open') for l in drop_y_raw]
        fig.add_trace(go.Scatter(x=drop_x, y=drop_y, mode='markers', name='live lap, excluded (flag / pit / traffic / >105%; triangles clipped)', marker=dict(color=COLORS['text_secondary'], size=7, symbol=drop_sym), hovertext=[f'{l:+.1f} s' for l in drop_y_raw]))
        fig.add_trace(go.Scatter(x=kept_x, y=kept_y, mode='markers', name='live lap, corrected (fuel prior removed)', marker=dict(color=COLORS['text'], size=7, symbol='circle')))
        if st.post_slope is not None:
            px = _ages(st.tyre_age + 10, 30); plo, phi = st.band90
            if plo is not None:
                fig.add_trace(go.Scatter(x=np.r_[px, px[::-1]], y=np.r_[plo * px, (phi * px)[::-1]], fill='toself', fillcolor=rgba(COLORS['live'], 0.16 if st.widened else 0.10), line=dict(width=0), name=f'posterior 90% band ({lab})' + (' · widened' if st.widened else ''), hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=px, y=st.post_slope * px, mode='lines', name=f'live posterior {st.post_slope:+.3f} s/lap ({lab})', line=dict(color=COLORS['live'], width=2.5)))
            proj = [dict(h=p['h'], age=p['age'], loss=p['loss'], lo=p['lo'], hi=p['hi']) for p in projection] if projection else st.project()
            fig.add_trace(go.Scatter(x=[p['age'] for p in proj], y=[p['loss'] for p in proj], mode='markers+text', name='forward 1/3/5/10 laps', text=[f"+{p['h']}" for p in proj], textposition='top center', textfont=dict(size=10, color=COLORS['live']),
                                     marker=dict(color=COLORS['live'], size=8, symbol='diamond'), error_y=dict(type='data', symmetric=False, array=[p['hi'] - p['loss'] for p in proj], arrayminus=[p['loss'] - p['lo'] for p in proj], color=rgba(COLORS['live'], 0.5), thickness=1)))
        fig.add_vline(x=st.tyre_age, line=dict(color=COLORS['text_secondary'], width=1, dash='dot'))
        fig.add_annotation(x=st.tyre_age, y=1, yref='paper', text=f'age {st.tyre_age} · lap {st.lap}', showarrow=False, font=dict(size=10, color=COLORS['text_secondary']), yanchor='bottom')
        first_age = st.all_ages[0] if st.all_ages else 0
        for e in st.events_in_stint:
            age = first_age + (e['lap'] - (st.lap - st.laps_in_stint + 1))
            label = {'pit_exit': 'PIT OUT', 'pit_entry': 'PIT IN', 'track_status': 'FLAG'}.get(e['kind'], e['kind'])
            fig.add_annotation(x=age, y=0, yref='paper', text=label, showarrow=False, font=dict(size=9, color=COLORS['decision']), yanchor='bottom', textangle=-90, xanchor='left')
        for f in vm.feedback:
            if st.lap - st.laps_in_stint < int(f['lap']) <= st.lap:
                age = first_age + (int(f['lap']) - (st.lap - st.laps_in_stint + 1))
                fig.add_annotation(x=age, y=0.92, yref='paper', text=f"driver: {f['symptom']} {f['severity']}/5", showarrow=True, arrowcolor=COLORS['decision'], font=dict(size=9, color=COLORS['decision']), ax=0, ay=-18)
    for pair, x in vm.crossover.items():
        if pair.split('-')[0] == comp[0]:
            fig.add_vline(x=x, line=dict(color=COLORS['decision'], width=1, dash='dash'))
            fig.add_annotation(x=x, y=0.5, yref='paper', text=f'crossover {pair} at age {x:.1f} (lock)', showarrow=False, textangle=-90, font=dict(size=9, color=COLORS['decision']), xanchor='right')
    apply(fig, height=470 if presentation else 420, xaxis_title='Tyre age (laps)', yaxis_title='Pace loss vs fresh tyre (s), fuel prior removed', showlegend=not presentation, yaxis=dict(range=[y_lo, y_hi]),
          legend=dict(orientation='h', yanchor='bottom', y=1.0, x=0), margin=dict(l=48, r=16, t=50 if not presentation else 24, b=40))
    return fig


def temperature_history(lock_history, race_series, presentation: bool = False) -> go.Figure:
    fig = go.Figure()
    if lock_history:
        fig.add_trace(go.Bar(x=[s for s, _ in lock_history], y=[t for _, t in lock_history], name='track temperature per session (lock)', marker=dict(color=rgba(COLORS['decision'], 0.55)), text=[f'{t:.1f}' for _, t in lock_history], textposition='outside', textfont=dict(size=10)))
    apply(fig, height=190, showlegend=False, yaxis_title='°C', margin=dict(l=40, r=8, t=24, b=28), title='Track temperature by session (lock events)')
    return fig


def race_temp_series(series) -> go.Figure:
    fig = go.Figure()
    if series:
        fig.add_trace(go.Scatter(x=[l for l, _ in series], y=[t for _, t in series], mode='lines', name='track temperature (race feed, per lap)', line=dict(color=COLORS['decision'], width=2)))
    apply(fig, height=190, showlegend=False, xaxis_title='lap', yaxis_title='°C', margin=dict(l=40, r=8, t=24, b=28), title='Track temperature through the race (recorded feed)')
    return fig


def pre_race_curves(forecasts, n_laps: int | None = None) -> go.Figure:
    fig = go.Figure(); xs = _ages(min(n_laps or 40, 45))
    for f in forecasts:
        col = COMPOUNDS.get(f.compound, COLORS['text_secondary'])
        if f.prediction is None:
            continue
        lo, hi = f.band90
        if lo is not None and hi is not None:
            fig.add_trace(go.Scatter(x=np.r_[xs, xs[::-1]], y=np.r_[lo * xs, (hi * xs)[::-1]], fill='toself', fillcolor=rgba(col, 0.10), line=dict(width=0), name=f'{f.compound.title()} 90% band', hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=xs, y=f.prediction * xs, mode='lines', name=f'{f.compound.title()} {f.prediction:+.3f} s/lap' + ('' if f.issued else ' (fallback)'), line=dict(color=col, width=3, dash=COMPOUND_DASH.get(f.compound, 'solid'))))
        if f.observed is not None:
            fig.add_trace(go.Scatter(x=xs, y=f.observed * xs, mode='lines', name=f'{f.compound.title()} race observed {f.observed:+.3f}', line=dict(color=COLORS['text'], width=1.5, dash=COMPOUND_DASH.get(f.compound, 'solid')), opacity=0.8))
    apply(fig, height=400, xaxis_title='Tyre age (laps)', yaxis_title='Pace loss vs fresh tyre (s)')
    return fig


def ghost_curves(vm) -> go.Figure:
    """Actual (race-derived reference) vs forecast vs counterfactual compound curves, from the lock."""
    fig = go.Figure(); xs = _ages(vm.n_laps or 40)
    f = vm.forecast; col = COMPOUNDS.get(f.compound, COLORS['text_secondary'])
    lo, hi = f.band90
    if f.prediction is not None and lo is not None:
        fig.add_trace(go.Scatter(x=np.r_[xs, xs[::-1]], y=np.r_[lo * xs, (hi * xs)[::-1]], fill='toself', fillcolor=rgba(col, 0.10), line=dict(width=0), name=f'{f.compound.title()} frozen 90% band', hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=xs, y=f.prediction * xs, mode='lines', name=f'{f.compound.title()} frozen forecast {f.prediction:+.3f}', line=dict(color=col, width=2, dash='dash')))
    if f.observed is not None:
        fig.add_trace(go.Scatter(x=xs, y=f.observed * xs, mode='lines', name=f'{f.compound.title()} race-derived reference {f.observed:+.3f}', line=dict(color=col, width=3)))
    if vm.forecast_alt is not None and vm.forecast_alt.prediction is not None:
        a = vm.forecast_alt; ca = COMPOUNDS.get(a.compound, COLORS['text_secondary'])
        fig.add_trace(go.Scatter(x=xs, y=a.prediction * xs, mode='lines', name=f'{a.compound.title()} counterfactual compound, frozen forecast {a.prediction:+.3f}', line=dict(color=ca, width=2, dash='dot')))
        if a.observed is not None:
            fig.add_trace(go.Scatter(x=xs, y=a.observed * xs, mode='lines', name=f'{a.compound.title()} race-derived reference {a.observed:+.3f}', line=dict(color=ca, width=2)))
    fig.add_vline(x=vm.intervention_lap, line=dict(color=COLORS['decision'], width=1, dash='dash'))
    fig.add_annotation(x=vm.intervention_lap, y=1, yref='paper', text=f'intervention lap {vm.intervention_lap}', showarrow=False, font=dict(size=10, color=COLORS['decision']), yanchor='bottom')
    apply(fig, height=300, xaxis_title='Tyre age (laps)', yaxis_title='Pace loss vs fresh tyre (s)', title='Actual vs counterfactual tyre curves (lock)')
    return fig


def cumulative_delta_placeholder(vm, lap: int) -> go.Figure:
    """Cumulative race-time delta: linear ramp to the FIXTURE / lock_v2 summary delta after the intervention lap. PLACEHOLDER until Workstream 2."""
    fig = go.Figure(); n = vm.n_laps or 50
    laps = np.arange(1, n + 1)
    if vm.counterfactual_delta_s is not None:
        y = np.where(laps < vm.intervention_lap, 0.0, (laps - vm.intervention_lap) / max(n - vm.intervention_lap, 1) * vm.counterfactual_delta_s)
        fig.add_trace(go.Scatter(x=laps, y=y, mode='lines', name=f'cumulative delta, {vm.counterfactual_source} summary ({vm.counterfactual_delta_s:+.1f} s at the flag)', line=dict(color=COLORS['decision'], width=2)))
        fig.add_trace(go.Scatter(x=[lap], y=[float(y[min(lap, n) - 1])], mode='markers', name='selected lap', marker=dict(color=COLORS['text'], size=9)))
    fig.add_hline(y=0, line=dict(color=COLORS['border'], width=1))
    apply(fig, height=260, xaxis_title='Lap', yaxis_title='Ghost minus actual (s)', title='Cumulative race-time delta · PLACEHOLDER shape, endpoint from ' + vm.counterfactual_source)
    return fig


def waterfall_placeholder(vm) -> go.Figure:
    """Decomposition Y = B + T + P + I + e. Only the total exists (fixture / lock_v2); the terms are pending Workstream 2."""
    fig = go.Figure()
    total = vm.counterfactual_delta_s
    fig.add_trace(go.Waterfall(x=['baseline B', 'tyre T', 'pit P', 'interaction I', 'residual e', 'total'], measure=['relative', 'relative', 'relative', 'relative', 'relative', 'total'],
                               y=[0, 0, 0, 0, 0, total or 0], text=['pending', 'pending', 'pending', 'pending', 'pending', f'{total:+.1f} s' if total is not None else 'pending'], textposition='outside',
                               connector=dict(line=dict(color=COLORS['border'])), increasing=dict(marker=dict(color=COLORS['critical'])), decreasing=dict(marker=dict(color=COLORS['live'])), totals=dict(marker=dict(color=COLORS['decision']))))
    apply(fig, height=260, showlegend=False, yaxis_title='s', title='Lap decomposition waterfall · terms pending Workstream 2, total from ' + vm.counterfactual_source)
    return fig


def calibration_scatter(rows) -> go.Figure:
    fig = go.Figure()
    mx = max([r.get('obs') or 0 for r in rows] + [r.get('pred_clearstint') or 0 for r in rows] + [0.05]) + 0.02
    fig.add_trace(go.Scatter(x=[0, mx], y=[0, mx], mode='lines', name='perfect', line=dict(color=COLORS['text_secondary'], dash='dot', width=1)))
    for c, col in COMPOUNDS.items():
        s = [r for r in rows if r['compound'] == c]
        if not s:
            continue
        fig.add_trace(go.Scatter(x=[r['pred_clearstint'] for r in s], y=[r['obs'] for r in s], mode='markers', name=f'{c.title()} (filled issued, open fallback)',
                                 marker=dict(color=col, size=11, symbol=['circle' if r['issued'] else 'diamond-open' for r in s]), hovertext=[f"{r['event']} {'issued' if r['issued'] else 'fallback'}" for r in s]))
        fig.add_trace(go.Scatter(x=[r['naive'] for r in s], y=[r['obs'] for r in s], mode='markers', name=f'{c.title()} naive', marker=dict(color=col, size=6, symbol='x', opacity=0.5)))
    apply(fig, height=420, xaxis_title='Predicted from Friday (s/lap per lap of age)', yaxis_title='Observed in the race')
    return fig


# ---- Ghost Strategy panels from Workstream 2's counterfactual outputs ------------------------------------------------------
def cumulative_delta_real(laps, lap_sel: int, source_label: str) -> go.Figure:
    """Cumulative race-time delta (ghost minus actual) per lap with the q10/q90 band, from laps.csv."""
    fig = go.Figure(); x = laps['lap'].to_numpy()
    if 'cumulative_delta_q10' in laps and 'cumulative_delta_q90' in laps:
        fig.add_trace(go.Scatter(x=np.r_[x, x[::-1]], y=np.r_[laps['cumulative_delta_q10'].to_numpy(), laps['cumulative_delta_q90'].to_numpy()[::-1]], fill='toself', fillcolor=rgba(COLORS['decision'], 0.14), line=dict(width=0), name='q10 to q90 (whole-curve sampling)', hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=x, y=laps['cumulative_delta'].to_numpy(), mode='lines', name=f'cumulative delta, mean ({source_label})', line=dict(color=COLORS['decision'], width=2.5)))
    pits = laps[laps['pit_state'].isin(['in_lap', 'out_lap'])] if 'pit_state' in laps else laps.iloc[0:0]
    if len(pits):
        fig.add_trace(go.Scatter(x=pits['lap'], y=pits['cumulative_delta'], mode='markers', name='ghost pit in / out laps', marker=dict(color=COLORS['text'], size=7, symbol='diamond')))
    row = laps[laps['lap'] == lap_sel]
    if len(row):
        fig.add_trace(go.Scatter(x=[lap_sel], y=[float(row['cumulative_delta'].iloc[0])], mode='markers', name='selected lap', marker=dict(color=COLORS['live'], size=10)))
    fig.add_hline(y=0, line=dict(color=COLORS['border'], width=1))
    apply(fig, height=280, xaxis_title='Lap', yaxis_title='Ghost minus actual (s), negative = ghost ahead', title='Cumulative race-time delta (Workstream 2 laps.csv)')
    return fig


def waterfall_real(decomp: dict, source_label: str) -> go.Figure:
    """Decomposition Y = B + T + P + I + e from the engine block (means over sampled curves)."""
    fig = go.Figure()
    vals = [decomp.get('baseline') or 0.0, decomp.get('tyre') or 0.0, decomp.get('pit') or 0.0, decomp.get('interaction') or 0.0]
    total = decomp.get('total')
    text = [f'{v:+.1f} s' for v in vals] + [f'{total:+.1f} s' if total is not None else '—']
    fig.add_trace(go.Waterfall(x=['baseline B (preserved)', 'tyre T', 'pit P', 'interaction + residual', 'total'], measure=['relative', 'relative', 'relative', 'relative', 'total'], y=vals + [total or 0.0], text=text, textposition='outside',
                               connector=dict(line=dict(color=COLORS['border'])), increasing=dict(marker=dict(color=COLORS['critical'])), decreasing=dict(marker=dict(color=COLORS['live'])), totals=dict(marker=dict(color=COLORS['decision']))))
    idc = decomp.get('identity_check_delta_s')
    apply(fig, height=280, showlegend=False, yaxis_title='s', title=f'Lap decomposition ({source_label}) · identity check {idc:+.3f} s' if idc is not None else f'Lap decomposition ({source_label})')
    return fig


def ghost_curves_real(curves: dict, actual: str, replacement: str, forecast_actual, forecast_alt, ilap: int, n_laps: int | None, audit: bool, reference_label: str) -> go.Figure:
    """Audit: leave-one-driver-out Sunday reference curves (solid) with the frozen forecast (dashed). Scenario: frozen forecast only."""
    fig = go.Figure(); xs = _ages(min(n_laps or 40, 45))
    for comp, fc, width in ((actual, forecast_actual, 2), (replacement, forecast_alt, 2)):
        if not comp:
            continue
        col = COMPOUNDS.get(comp, COLORS['text_secondary'])
        if fc is not None and fc.prediction is not None:
            lo, hi = fc.band90
            if lo is not None and hi is not None:
                fig.add_trace(go.Scatter(x=np.r_[xs, xs[::-1]], y=np.r_[lo * xs, (hi * xs)[::-1]], fill='toself', fillcolor=rgba(col, 0.08), line=dict(width=0), name=f'{comp.title()} pre-race 90% band', hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=xs, y=fc.prediction * xs, mode='lines', name=f'{comp.title()} pre-race forecast {fc.prediction:+.3f} (lock)', line=dict(color=col, width=width, dash='dash')))
        c = curves.get(comp) if audit else None
        if c and c.get('slope') is not None:
            fig.add_trace(go.Scatter(x=xs, y=c['slope'] * xs, mode='lines', name=f'{comp.title()} {reference_label} {c["slope"]:+.3f} ± {c.get("sd", 0):.3f} ({c.get("n_laps", "—")} laps)', line=dict(color=col, width=3)))
    fig.add_vline(x=ilap, line=dict(color=COLORS['decision'], width=1, dash='dash'))
    fig.add_annotation(x=ilap, y=1, yref='paper', text=f'intervention lap {ilap}', showarrow=False, font=dict(size=10, color=COLORS['decision']), yanchor='bottom')
    apply(fig, height=280, xaxis_title='Tyre age (laps)', yaxis_title='Pace loss vs fresh tyre (s)', title=('Actual vs counterfactual tyre curves · ' + reference_label) if audit else 'Tyre curves · pre-race forecast only (model-implied)')
    return fig

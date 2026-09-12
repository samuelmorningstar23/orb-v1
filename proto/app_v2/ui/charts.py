"""Chart builders on the Orb Plotly template. Inputs are view models; no chart computes a scientific number."""
from __future__ import annotations
import numpy as np
import plotly.graph_objects as go
from app_v2.theme.tokens import COLORS, COMPOUNDS
from app_v2.theme.plotly_theme import apply, rgba

COMPOUND_DASH = {'SOFT': 'solid', 'MEDIUM': 'dash', 'HARD': 'dot', 'INTERMEDIATE': 'dashdot', 'WET': 'longdash'}


def _ages(max_age: float, n: int = 40) -> np.ndarray:
    return np.linspace(0, max(max_age, 5.0), n)


def live_projection(vm, projection: list | None = None, horizon: int = 5) -> list[dict]:
    """Select existing forecast points; do not extend them past the race or synthesize new ones."""
    if projection is None:
        orb = getattr(vm, 'orb_live', None) or {}
        projection = orb.get('projection')
        if projection is None:
            projection = vm.state.project() if vm.state else []
    remaining = max(int(vm.n_laps) - int(vm.lap), 0) if vm.n_laps else horizon
    return sorted([p for p in projection if 0 < p['h'] <= min(horizon, remaining)
                   and all(p.get(k) is not None and np.isfinite(p[k]) for k in ('age', 'loss', 'lo', 'hi'))], key=lambda p: p['h'])


def forecast_vs_live(vm, presentation: bool = False, estimator_label: str = 'PLACEHOLDER', projection: list | None = None) -> go.Figure:
    """One driver's current stint and supplied next-lap estimates, on the race-lap axis.

    Clean observations are fuel-corrected loss relative to the current fitted fresh-tyre
    baseline. The fitted line is today's estimate, not the history of past forecasts.
    The shaded future interval uses the supplied model bounds without clipping them.
    """
    fig = go.Figure()
    state = vm.state
    if state is None:
        fig.add_annotation(text='Tyre data unavailable', x=.5, y=.5, xref='paper', yref='paper', showarrow=False)
        return apply(fig, height=380, xaxis_title='Race lap', yaxis_title='Tyre pace loss (s)')

    proj = live_projection(vm, projection)
    offset = state.lap - state.tyre_age
    ages = [a for a in state.all_ages if np.isfinite(a)]
    first_age = min(ages) if ages else state.tyre_age
    first_lap = max(1, offset + first_age)
    last_lap = state.lap + (proj[-1]['h'] if proj else 0)
    visible_y = [0.0]
    clean = [(a, y) for a, y, kept in zip(state.all_ages, state.all_losses, state.all_kept)
             if kept and np.isfinite(a) and np.isfinite(y)]
    if clean:
        fig.add_trace(go.Scatter(x=[offset + a for a, _ in clean], y=[y for _, y in clean],
                                customdata=[[a] for a, _ in clean], mode='markers', name='Clean laps', legendrank=1,
                                marker=dict(color=COLORS['text'], size=8, line=dict(color=COLORS['surface'], width=1)),
                                hovertemplate='Race lap %{x:.0f} · tyre age %{customdata[0]:.0f}<br>Clean-lap loss %{y:.2f} s<extra></extra>'))
        visible_y.extend(y for _, y in clean)
    if state.post_slope is not None:
        fit_ages = np.linspace(first_age, state.tyre_age, max(2, min(60, state.laps_in_stint + 1)))
        fit_y = state.post_slope * fit_ages
        fit_name = 'Current fit' if state.kept_laps else 'Pre-race estimate'
        fig.add_trace(go.Scatter(x=offset + fit_ages, y=fit_y, mode='lines', name=fit_name, legendrank=2,
                                line=dict(color=COLORS['live'], width=3),
                                hovertemplate='Race lap %{x:.0f}<br>Current fitted loss %{y:.2f} s<extra></extra>'))
        visible_y.extend(fit_y)
        now_loss = state.post_slope * state.tyre_age
        fig.add_trace(go.Scatter(x=[state.lap], y=[now_loss], mode='markers', name='Now', showlegend=False,
                                marker=dict(color=COLORS['live'], size=9),
                                hovertemplate='Current lap %{x:.0f}<br>Fitted loss %{y:.2f} s<extra></extra>'))
        if proj:
            future_x = [state.lap + p['h'] for p in proj]
            band_x = future_x
            lower, upper = [p['lo'] for p in proj], [p['hi'] for p in proj]
            plo, phi = state.band90
            if plo is not None and phi is not None:
                band_x = [state.lap] + band_x
                lower = [plo * state.tyre_age] + lower
                upper = [phi * state.tyre_age] + upper
            fig.add_trace(go.Scatter(x=band_x + band_x[::-1], y=lower + upper[::-1], mode='lines', fill='toself',
                                    fillcolor=rgba(COLORS['live'], .13), line=dict(width=0), name='90% range', legendrank=4, hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=[state.lap] + future_x, y=[now_loss] + [p['loss'] for p in proj],
                                    mode='lines', name='If you stay out', legendrank=3, line=dict(color=COLORS['live'], width=2, dash='dot'), hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=future_x, y=[p['loss'] for p in proj], mode='markers', name='Forecast points', showlegend=False,
                                    marker=dict(color=COLORS['live'], size=8, symbol='diamond'), customdata=[[p['age'], p['lo'], p['hi']] for p in proj],
                                    hovertemplate='Race lap %{x:.0f} · tyre age %{customdata[0]:.0f}<br>Predicted loss %{y:.2f} s<br>90% range %{customdata[1]:.2f} to %{customdata[2]:.2f} s<extra></extra>'))
            visible_y.extend(lower + upper + [p['loss'] for p in proj])

    fig.add_vline(x=state.lap, line=dict(color=COLORS['text_secondary'], width=1, dash='dot'))
    fig.add_annotation(x=state.lap, y=1.03, yref='paper', text=f'Now · lap {state.lap}', showarrow=False,
                       font=dict(size=11, color=COLORS['text_secondary']), xanchor='right' if not proj else 'center', yanchor='bottom')
    y_min, y_max = min(visible_y), max(visible_y)
    pad = max((y_max - y_min) * .08, .15)
    apply(fig, height=410 if presentation else 380, xaxis_title='Race lap', yaxis_title='Tyre pace loss (s)',
          xaxis=dict(range=[first_lap - .6, max(last_lap, first_lap + 1) + .6], tickformat='.0f', dtick=1 if last_lap - first_lap <= 12 else None, fixedrange=True),
          yaxis=dict(range=[y_min - pad, y_max + pad], ticksuffix=' s', fixedrange=True),
          showlegend=True, hovermode='closest', legend=dict(orientation='h', yanchor='top', y=-.22, x=0, font=dict(size=11)),
          margin=dict(l=56, r=16, t=35, b=85), dragmode=False)
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
            fig.add_trace(go.Scatter(x=np.r_[xs, xs[::-1]], y=np.r_[lo * xs, (hi * xs)[::-1]], mode='lines', fill='toself', fillcolor=rgba(col, 0.10), line=dict(width=0), name=f'{f.compound.title()} 90% band', showlegend=False, hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=xs, y=f.prediction * xs, mode='lines', name=f'{f.compound.title()}' + ('' if f.issued else ' (fallback)'), line=dict(color=col, width=3, dash=COMPOUND_DASH.get(f.compound, 'solid'))))
    apply(fig, height=400, xaxis_title='Laps on the same tyre set', yaxis_title='Tyre pace loss (s)',
          legend=dict(orientation='h', yanchor='top', y=-.2, x=0), margin=dict(l=56, r=16, t=16, b=75))
    return fig


def ghost_curves(vm) -> go.Figure:
    """Actual (race-derived reference) vs forecast vs counterfactual compound curves, from the lock."""
    fig = go.Figure(); xs = _ages(vm.n_laps or 40)
    f = vm.forecast; col = COMPOUNDS.get(f.compound, COLORS['text_secondary'])
    lo, hi = f.band90
    if f.prediction is not None and lo is not None:
        fig.add_trace(go.Scatter(x=np.r_[xs, xs[::-1]], y=np.r_[lo * xs, (hi * xs)[::-1]], mode='lines', fill='toself', fillcolor=rgba(col, 0.10), line=dict(width=0), name=f'{f.compound.title()} frozen 90% band', hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=xs, y=f.prediction * xs, mode='lines', name=f'{f.compound.title()} frozen forecast {f.prediction:+.3f}', line=dict(color=col, width=2, dash='dash')))
    if f.observed is not None:
        fig.add_trace(go.Scatter(x=xs, y=f.observed * xs, mode='lines', name=f'{f.compound.title()} race-derived reference {f.observed:+.3f}', line=dict(color=col, width=3)))
    if vm.forecast_alt is not None and vm.forecast_alt.prediction is not None:
        a = vm.forecast_alt; ca = COMPOUNDS.get(a.compound, COLORS['text_secondary'])
        fig.add_trace(go.Scatter(x=xs, y=a.prediction * xs, mode='lines', name=f'{a.compound.title()} counterfactual compound, frozen forecast {a.prediction:+.3f}', line=dict(color=ca, width=2, dash='dot')))
        if a.observed is not None:
            fig.add_trace(go.Scatter(x=xs, y=a.observed * xs, mode='lines', name=f'{a.compound.title()} race-derived reference {a.observed:+.3f}', line=dict(color=ca, width=2)))
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
def cumulative_delta_real(laps, lap_sel: int, source_label: str, title: str | None = None) -> go.Figure:
    """Cumulative race-time delta (ghost minus actual) per lap with the q10/q90 band, from laps.csv."""
    fig = go.Figure(); x = laps['lap'].to_numpy()
    if 'cumulative_delta_q10' in laps and 'cumulative_delta_q90' in laps:
        fig.add_trace(go.Scatter(x=np.r_[x, x[::-1]], y=np.r_[laps['cumulative_delta_q10'].to_numpy(), laps['cumulative_delta_q90'].to_numpy()[::-1]], mode='lines', fill='toself', fillcolor=rgba(COLORS['decision'], 0.14), line=dict(width=0), name='q10 to q90 (whole-curve sampling)', hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=x, y=laps['cumulative_delta'].to_numpy(), mode='lines', name=f'cumulative delta, mean ({source_label})', line=dict(color=COLORS['decision'], width=2.5)))
    pits = laps[laps['pit_state'].isin(['in_lap', 'out_lap'])] if 'pit_state' in laps else laps.iloc[0:0]
    if len(pits):
        fig.add_trace(go.Scatter(x=pits['lap'], y=pits['cumulative_delta'], mode='markers', name='ghost pit in / out laps', marker=dict(color=COLORS['text'], size=7, symbol='diamond')))
    row = laps[laps['lap'] == lap_sel]
    if len(row):
        fig.add_trace(go.Scatter(x=[lap_sel], y=[float(row['cumulative_delta'].iloc[0])], mode='markers', name='selected lap', marker=dict(color=COLORS['live'], size=10)))
    fig.add_hline(y=0, line=dict(color=COLORS['border'], width=1))
    apply(fig, height=280, xaxis_title='Lap', yaxis_title='Ghost minus actual (s), negative = ghost ahead', title=title or 'Cumulative race-time delta (Workstream 2 laps.csv)')
    return fig


def waterfall_real(decomp: dict, source_label: str, title: str | None = None) -> go.Figure:
    """Decomposition Y = B + T + P + I + e from the engine block (means over sampled curves)."""
    fig = go.Figure()
    vals = [decomp.get('baseline') or 0.0, decomp.get('tyre') or 0.0, decomp.get('pit') or 0.0, decomp.get('interaction') or 0.0]
    total = decomp.get('total')
    text = [f'{v:+.1f} s' for v in vals] + [f'{total:+.1f} s' if total is not None else '—']
    fig.add_trace(go.Waterfall(x=['baseline B (preserved)', 'tyre T', 'pit P', 'interaction + residual', 'total'], measure=['relative', 'relative', 'relative', 'relative', 'total'], y=vals + [total or 0.0], text=text, textposition='outside',
                               connector=dict(line=dict(color=COLORS['border'])), increasing=dict(marker=dict(color=COLORS['critical'])), decreasing=dict(marker=dict(color=COLORS['live'])), totals=dict(marker=dict(color=COLORS['decision']))))
    idc = decomp.get('identity_check_delta_s')
    apply(fig, height=280, showlegend=False, yaxis_title='s', title=title or (f'Lap decomposition ({source_label}) · identity check {idc:+.3f} s' if idc is not None else f'Lap decomposition ({source_label})'))
    return fig


def ghost_curves_real(curves: dict, actual: str, replacement: str, forecast_actual, forecast_alt, ilap: int, n_laps: int | None, audit: bool, reference_label: str) -> go.Figure:
    """Audit: leave-one-driver-out Sunday reference curves (solid) with the frozen forecast (dashed). Scenario: frozen forecast only."""
    fig = go.Figure(); xs = _ages(min(n_laps or 40, 45))
    seen = set()
    for comp, fc, width in ((actual, forecast_actual, 2), (replacement, forecast_alt, 2)):
        if not comp or comp in seen:
            continue
        seen.add(comp)
        col = COMPOUNDS.get(comp, COLORS['text_secondary'])
        if fc is not None and fc.prediction is not None:
            lo, hi = fc.band90
            if lo is not None and hi is not None:
                fig.add_trace(go.Scatter(x=np.r_[xs, xs[::-1]], y=np.r_[lo * xs, (hi * xs)[::-1]], mode='lines', fill='toself', fillcolor=rgba(col, 0.08), line=dict(width=0), name=f'{comp.title()} pre-race 90% band', hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=xs, y=fc.prediction * xs, mode='lines', name=f'{comp.title()} pre-race forecast {fc.prediction:+.3f} (lock)', line=dict(color=col, width=width, dash='dash')))
        c = curves.get(comp) if audit else None
        if c and c.get('slope') is not None:
            fig.add_trace(go.Scatter(x=xs, y=c['slope'] * xs, mode='lines', name=f'{comp.title()} {reference_label} {c["slope"]:+.3f} ± {c.get("sd", 0):.3f} ({c.get("n_laps", "—")} laps)', line=dict(color=col, width=3)))
    apply(fig, height=280, xaxis_title='Tyre age (laps)', yaxis_title='Pace loss vs fresh tyre (s)', title=('Actual vs counterfactual tyre curves · ' + reference_label) if audit else 'Tyre curves · pre-race forecast only (model-implied)')
    return fig

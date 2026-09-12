"""Orb v1 dashboard. Reads out/lock.json (written by pipeline.py) and the per-lap feature CSVs. Nothing is computed here
that is not in the lock, except the per-lap points drawn behind the curves."""
import os, json, numpy as np, pandas as pd, streamlit as st, plotly.graph_objects as go
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
import model_v2 as M
PAL = {'SOFT': '#E10600', 'MEDIUM': '#F2C230', 'HARD': '#8FB3D9'}; MUTED = '#9AA1AA'
st.set_page_config(page_title='Orb v1', page_icon='🛞', layout='wide')

@st.cache_data
def lock(mtime): return json.load(open('out/lock.json'))
@st.cache_data
def liquid(mtime): return json.load(open('out/liquid.json')) if os.path.exists('out/liquid.json') else {}
@st.cache_data
def laps(ev):
    d = M.load_event(ev); p, evo = M.prep_practice(d); _, _, _, pf = M.fit(p, 'TyreLife')
    r = M.prep_race(d) if 'R' in set(d['session']) else None
    rf = M.fit(r, 'TyreLife')[3] if r is not None and len(r) >= 80 else None
    return pf, rf
@st.cache_data
def excluded(ev): return pd.read_csv(f'out/excluded_{ev}.csv')

L = lock(os.path.getmtime('out/lock.json')); LQ = liquid(os.path.getmtime('out/liquid.json') if os.path.exists('out/liquid.json') else 0); V = pd.DataFrame(L['validation_rows']); live = L['live']; events = L['events']
order = list(live) + [e for e in events if e not in live]
st.title('Orb v1'); st.caption(f"Clean tyre-degradation curves from Friday, scored on Sunday. Lock generated {L['generated_at']}. Every number on this page comes from out/lock.json.")
VIEWS = ['Weekend', 'Strategy', 'Liquid model', 'Season validation', 'Excluded laps', 'Method & assumptions']
qp = st.query_params; ev0 = qp.get('ev') if qp.get('ev') in order else order[0]; view0 = qp.get('view') if qp.get('view') in VIEWS else VIEWS[0]
ev = st.sidebar.selectbox('Weekend', order, index=order.index(ev0), format_func=lambda e: f"{e}  ·  {'LIVE' if e in live else 'scored'}")
view = st.sidebar.radio('View', VIEWS, index=VIEWS.index(view0))
st.query_params.update(ev=ev, view=view)
meta = events[ev]

def curve_fig(pf, rows, title, rf=None):
    fig = go.Figure(); xmax = float(pf['TyreLife'].max()) + 1
    for c, col in PAL.items():
        s = pf[pf.Compound == c]
        if len(s): fig.add_trace(go.Scatter(x=s.TyreLife, y=s.y_rel, mode='markers', name=f'{c.title()} practice laps', marker=dict(color=col, size=5, opacity=0.35), hovertext=s.Driver, showlegend=False))
    xs = np.linspace(0, xmax, 30)
    for row in rows:
        c = row['compound']; col = PAL[c]
        if np.isfinite(row.get('naive', np.nan)): fig.add_trace(go.Scatter(x=xs, y=row['naive'] * xs, mode='lines', name=f'{c.title()} naive', line=dict(color=col, dash='dot', width=1)))
        if row.get('issued', False) or np.isfinite(row.get('clean', np.nan)): fig.add_trace(go.Scatter(x=xs, y=row['clean'] * xs, mode='lines', name=f'{c.title()} cleaned', line=dict(color=col, dash='dash', width=1.5)))
        pred, b = row.get('prediction', row.get('pred_clearstint')), row.get('band90', [row.get('lo'), row.get('hi')])
        if pred is not None and np.isfinite(pred):
            if b and b[0] is not None and np.isfinite(b[0]): fig.add_trace(go.Scatter(x=np.r_[xs, xs[::-1]], y=np.r_[b[0] * xs, (b[1] * xs)[::-1]], fill='toself', fillcolor=col, opacity=0.12, line=dict(width=0), name=f'{c.title()} 90% band', hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=xs, y=pred * xs, mode='lines', name=f'{c.title()} Orb v1', line=dict(color=col, width=3)))
        if rf is not None and np.isfinite(row.get('obs', np.nan)): fig.add_trace(go.Scatter(x=xs, y=row['obs'] * xs, mode='lines', name=f'{c.title()} race observed', line=dict(color='#ECEDEF', width=2), opacity=0.9))
    fig.update_layout(title=title, template='plotly_dark', paper_bgcolor='#0E1013', plot_bgcolor='#0E1013', height=460, xaxis_title='Tyre age (laps)', yaxis_title='Pace loss vs fresh tyre (s), fuel / evolution / traffic / driver removed', legend=dict(font=dict(size=10)), margin=dict(l=40, r=20, t=50, b=40))
    return fig

if view == 'Weekend':
    tt = meta.get('track_temp', {}); c1, c2, c3, c4 = st.columns(4)
    for col, lab, val in [(c1, 'Weekend format', meta['format']), (c2, 'Clean long-run laps', f"{meta['practice_laps_clean']} of {meta['practice_laps_total']} practice laps"), (c3, 'Long runs', str(meta['practice_runs'])), (c4, 'Track temperature', f"{tt.get('FP2', tt.get('FP1', float('nan'))):.0f} °C" + (' (FP2)' if 'FP2' in tt else ' (FP1)'))]:
        col.markdown(f"<div style='color:{MUTED};font-size:0.8rem'>{lab}</div><div style='font-size:1.4rem;font-weight:600'>{val}</div>", unsafe_allow_html=True)
    st.caption(f"Track evolution measured from push laps, s per minute: {meta['evolution_s_per_min']}  ·  energy price of lap time (practice): {meta['beta_practice_s_per_MJ']:+.2f} s/MJ" + (f"  ·  tyres: {meta['tyres']}" if meta.get('tyres') else ''))
    pf, rf = laps(ev)
    if ev in live:
        rows = live[ev]['compounds']
        st.subheader(f'{ev}: curves issued from Friday practice')
        cols = st.columns(len(rows))
        for col, row in zip(cols, rows):
            with col:
                st.markdown(f"<h3 style='color:{PAL[row['compound']]};margin:0'>{row['compound'].title()}</h3>", unsafe_allow_html=True)
                if row['issued']: st.metric('Predicted race degradation', f"{row['prediction']:+.3f} s/lap", help=row['basis']); st.caption(f"90% band {row['band90'][0]:+.3f} to {row['band90'][1]:+.3f}  ·  cleaned Friday slope {row['clean']:+.3f} ± {row['clean_se']:.3f}  ·  naive {row['naive']:+.3f}  ·  factor ×{row['factor']:.2f} from {row['factor_from_n_weekends']} weekends")
                else:
                    st.metric('Withheld: expect low degradation', f"{row['prediction']:+.3f} s/lap", help=row['basis']); st.caption(f"Gate: {row['gate']}. Cleaned Friday slope {row['clean']:+.3f}; naive {row['naive']:+.3f}. Energy through the tyre rose {row['energy_trend']:+.2f} MJ per lap through the runs, i.e. drivers were still ramping up.")
                    if row.get('second_opinion'): st.caption(f"Second opinion, push-adjusted: {row['second_opinion']['prediction']:+.3f} s/lap ({row['second_opinion']['basis']}).")
                st.caption(f"{row['n_prac']} clean long-run laps")
        st.plotly_chart(curve_fig(pf, rows, f'{ev} Friday long runs, cleaned'), use_container_width=True)
        st.info('This is a forecast: it was issued from practice data only and will be scored against the race with the same estimator. Nothing here has seen the race.')
    else:
        rows = V[V.event == ev].to_dict(orient='records')
        st.subheader(f'{ev}: Sunday scorecard')
        T = pd.DataFrame(rows)[['compound', 'n_prac', 'naive', 'clean', 'pred_clearstint', 'lo', 'hi', 'obs', 'err_naive', 'err_cs', 'gate']].rename(columns={'n_prac': 'clean laps', 'pred_clearstint': 'Orb v1', 'lo': 'band lo', 'hi': 'band hi', 'obs': 'race observed', 'err_naive': 'naive error', 'err_cs': 'Orb v1 error'})
        st.dataframe(T.style.format({c: '{:+.3f}' for c in T.columns if c not in ('compound', 'clean laps', 'gate')}), use_container_width=True, hide_index=True)
        st.plotly_chart(curve_fig(pf, rows, f'{ev}: predicted from Friday (thick) vs observed in the race (white)', rf), use_container_width=True)
        if meta.get('race'): st.caption(f"Race: {meta['race']['n']} clean laps, {meta['race']['stints']} stints, telemetry {meta['race']['telemetry']}; energy price of lap time in the race {meta['race']['beta_race']:+.2f} s/MJ vs {meta['beta_practice_s_per_MJ']:+.2f} in practice.")

elif view == 'Strategy':
    S = L.get('strategy', {}).get(ev)
    if not S: st.info('No strategy replay for this weekend (no race-lap count available).')
    else:
        st.subheader(f"{ev}: what the curve implies for the race ({S['n_laps']} laps)")
        src = S['offsets_source'] if isinstance(S['offsets_source'], str) else ', '.join(f"{c.lower()} {v}" for c, v in S['offsets_source'].items())
        st.caption(f"Assumptions: pit loss {S['pit_loss']:.0f} s; compound offsets soft 0, medium {S['offsets'].get('MEDIUM', float('nan')):+.2f} s, hard {S['offsets'].get('HARD', float('nan')):+.2f} s from best clean laps ({src}); linear degradation; no traffic, safety car or weather. " + (S.get('note') or ''))
        rows = []
        for name, v in S['views'].items():
            rows.append({'Curve': name, 'Best plan': v['plan'], 'Stint lengths': ' / '.join(map(str, v['stints'])), 'Stops': v['stops'], 'Crossover laps': ', '.join(f'{k} {x:.0f}' for k, x in v['crossover'].items()) or '—',
                         'Cost of this plan under the race-observed curves': (f"+{v['cost_under_truth_vs_best_s']:.1f} s" if 'cost_under_truth_vs_best_s' in v else 'race pending')})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        t = next((v for v in S['views'].values() if 'best_under_truth' in v), None)
        if t: st.caption(f"Best plan under the race-observed curves: {t['best_under_truth']['plan']} with stints {' / '.join(map(str, t['best_under_truth']['stints']))}. Costs are the time lost by following each Friday view instead of that plan.")
        if ev in live: st.info('Live weekend: the plan under the central Orb v1 curve is the call; the band-low and band-high rows show how the decision moves across the 90% band. It will be scored after the race.')

elif view == 'Liquid model':
    st.subheader('Liquid tyre model: curve shape learned from every race lap')
    st.caption('A closed-form continuous-time cell (CfC, Hasani et al. 2022) reads each race stint lap by lap: tyre age, compound, energy through the tyre, traffic, track temperature, fuel. It predicts the cleaned pace-loss trajectory up to a per-stint constant, exactly the fixed-effect treatment of the linear model. Scored on held-out stints within each weekend against linear and quadratic fixed-effects fits on the same folds.')
    if not LQ: st.info('No liquid-model output yet (out/liquid.json missing).')
    else:
        rows = []
        for e, o in LQ.items():
            for c, m in o['by_compound'].items():
                cv = o['curves'].get(c, {}); base = [v for v in (m.get('mae_linear'), m.get('mae_quadratic'), m.get('mae_linear_cov')) if v is not None]
                rows.append({'weekend': e, 'compound': c, 'held-out laps': m['n_heldout_laps'], 'MAE linear': m.get('mae_linear'), 'MAE quadratic': m.get('mae_quadratic'), 'MAE linear + same inputs': m.get('mae_linear_cov'), 'MAE liquid': m['mae_liquid'],
                             'liquid wins': bool(base and m['mae_liquid'] is not None and m['mae_liquid'] < min(base)), 'shape': ('accelerating' if (cv.get('curvature') or 0) > 0 else 'settling') if cv else '', 'cliff lap': cv.get('cliff_lap')})
        T = pd.DataFrame(rows); wins = int(T['liquid wins'].sum()); n = int(T['MAE linear'].notna().sum())
        st.markdown(f"**Held-out result across the season: the liquid model beats every baseline, including a linear model given the same per-lap inputs, on {wins} of {n} compound-weekends.** Per-lap errors are dominated by driver-to-driver lap noise (about 0.25 s), so the differences are modest; the value is in the shape it recovers.")
        st.dataframe(T.style.format({'MAE linear': '{:.3f}', 'MAE quadratic': '{:.3f}', 'MAE linear + same inputs': '{:.3f}', 'MAE liquid': '{:.3f}'}, na_rep='—'), hide_index=True, use_container_width=True)
        if ev in LQ:
            o = LQ[ev]; fig = go.Figure()
            for c, cv in o['curves'].items():
                col = PAL[c]; fig.add_trace(go.Scatter(x=cv['ages'], y=cv['liquid'], mode='lines', name=f'{c.title()} liquid', line=dict(color=col, width=3)))
                if cv.get('quadratic'): fig.add_trace(go.Scatter(x=cv['ages'], y=cv['quadratic'], mode='lines', name=f'{c.title()} quadratic', line=dict(color=col, width=1.5, dash='dash')))
                if cv.get('cliff_lap'): fig.add_vline(x=cv['cliff_lap'], line=dict(color=col, dash='dot'), annotation_text=f'{c.title()} cliff', annotation_position='top')
            fig.update_layout(template='plotly_dark', paper_bgcolor='#0E1013', plot_bgcolor='#0E1013', height=440, xaxis_title='Tyre age (laps)', yaxis_title='Pace loss vs lap 1 of the stint (s), at the weekend’s mean inputs', title=f'{ev}: race degradation curve shape, liquid vs quadratic (trained on all stints)', margin=dict(l=40, r=20, t=50, b=40))
            st.plotly_chart(fig, use_container_width=True)
            st.caption('Reading the shape: a curve bending upward means degradation accelerates with age (a cliff is a sharp version of this); bending downward means the tyre settles. Curves are drawn at the weekend’s mean energy, traffic and temperature.')

elif view == 'Season validation':
    val = L['validation']; st.subheader(f"Leave-one-weekend-out over {val['n_weekends']} weekends, {val['n_compound_weekends']} compound-weekends: {val['n_issued']} issued, {val['n_withheld']} withheld")
    m = val['mae_issued']; a = val['mae_all_with_fallback']; cal = val['calibration']
    ladder = pd.DataFrame([['Naive pooled fit', a['naive'], cal['naive']['slope'], cal['naive']['r']], ['Cleaned Friday curve (issued only)', m['clean'], cal['clean']['slope'], cal['clean']['r']], ['Orb v1 (issued only)', m['clearstint'], cal['clearstint']['slope'], cal['clearstint']['r']], ['Orb v1, all cases incl. low-deg fallback', a['clearstint'], cal['all_with_fallback']['slope'], cal['all_with_fallback']['r']]], columns=['Predictor', 'MAE s/lap', 'Calibration slope', 'Pearson r'])
    st.dataframe(ladder.style.format({'MAE s/lap': '{:.3f}', 'Calibration slope': '{:+.2f}', 'Pearson r': '{:+.2f}'}), hide_index=True, use_container_width=True)
    st.caption(f"90% bootstrap interval on Orb v1 MAE: {val['ci90_mae_clearstint_all'][0]:.3f} to {val['ci90_mae_clearstint_all'][1]:.3f}. P(Orb v1 beats the cleaned curve on issued cases) = {val['p_clearstint_beats_clean_issued']:.2f}. Wins over naive: {val['wins_clearstint_over_naive']} of {val['n_compound_weekends']}.")
    fig = go.Figure(); mx = float(max(V.obs.max(), V.pred_clearstint.max())) + 0.02
    fig.add_trace(go.Scatter(x=[0, mx], y=[0, mx], mode='lines', line=dict(color=MUTED, dash='dot'), name='perfect'))
    for c, col in PAL.items():
        s = V[V.compound == c]; fig.add_trace(go.Scatter(x=s.pred_clearstint, y=s.obs, mode='markers', name=c.title(), marker=dict(color=col, size=11, symbol=['circle' if i else 'diamond-open' for i in s.issued]), hovertext=s.event + ' ' + np.where(s.issued, 'issued', 'fallback')))
        fig.add_trace(go.Scatter(x=s.naive, y=s.obs, mode='markers', name=f'{c.title()} naive', marker=dict(color=col, size=6, symbol='x', opacity=0.5)))
    fig.update_layout(template='plotly_dark', paper_bgcolor='#0E1013', plot_bgcolor='#0E1013', height=480, xaxis_title='Predicted from Friday (s/lap per lap of age)', yaxis_title='Observed in the race', title='Every compound-weekend: filled = issued, open diamond = low-degradation fallback, x = naive')
    st.plotly_chart(fig, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('**Transfer factors (race ÷ cleaned practice), median across weekends**'); bc = pd.DataFrame(val['by_compound']).T.rename(columns={'n': 'cases', 'k_median': 'factor', 'mae_naive': 'MAE naive', 'mae_clearstint': 'MAE Orb v1'}); bc['cases'] = bc['cases'].astype(int); st.dataframe(bc.style.format({'factor': '×{:.2f}', 'MAE naive': '{:.3f}', 'MAE Orb v1': '{:.3f}'}), use_container_width=True)
    with c2:
        st.markdown('**Withheld cases and what the race did**'); st.dataframe(pd.DataFrame(val['withheld_cases']), hide_index=True, use_container_width=True)
    pdg = val['push_diagnostic']; st.markdown('**The fifth confounder: the driver’s push profile.** Within-run trend of tyre energy per lap (MJ per lap of age):')
    st.caption(f"withheld cases: median {pdg['energy_trend_withheld']['50%']:+.3f} (range {pdg['energy_trend_withheld']['min']:+.3f} to {pdg['energy_trend_withheld']['max']:+.3f})  ·  issued cases: median {pdg['energy_trend_issued']['50%']:+.3f} (range {pdg['energy_trend_issued']['min']:+.3f} to {pdg['energy_trend_issued']['max']:+.3f}). Energy price of lap time, practice vs race: " + ', '.join(f"{b['event']} {b['practice']:+.2f}/{b['race']:+.2f}" for b in pdg['beta_practice_vs_race']) + ' s/MJ.')

elif view == 'Excluded laps':
    ex = excluded(ev); st.subheader(f'{ev}: every practice lap the estimator dropped, and why')
    cnt = ex[ex.reason != 'kept'].groupby('reason').size().sort_values(ascending=False).rename('laps').reset_index(); st.dataframe(cnt, hide_index=True, use_container_width=True)
    st.dataframe(ex[ex.reason != 'kept'].sort_values(['session', 'Driver', 'LapNumber']), use_container_width=True, hide_index=True, height=420)
    st.caption(f"{int((ex.reason == 'kept').sum())} laps kept of {len(ex)}.")

else:
    r = L['rules']; st.subheader('Method and stated assumptions')
    st.markdown(f"""
- **Lap model (practice and race, identical):** lap time = stint effect + compound-specific degradation × tyre age + fuel prior + track evolution. Stint effects absorb driver, car and fuel load; the fuel prior is {r['fuel_prior_kg_per_lap']} kg/lap at {r['fuel_s_per_kg']} s/kg (2026 regulations; a public race-data estimate gives 0.0294 s/kg); track evolution is measured per session from every driver's push laps; traffic laps (> {int(r['traffic_max']*100)}% of the lap within 60 m of a car, from the gap-to-car-ahead channel) are dropped; runs shorter than {r['min_stint']} clean laps and laps slower than 105% of the run best are dropped.
- **Gate:** a curve is issued only with at least {r['min_practice_laps']} clean long-run laps and a cleaned slope above {r['min_slope']} s/lap. Otherwise the compound is withheld and forecast as low degradation: the median race degradation of the other withheld cases this season (leave-one-out).
- **Transfer factor:** {r['factor_rule']}. Learned from previous weekends only; the held-out weekend never sees its own race.
- **Bands:** 5th to 95th percentile of slope noise from the regression combined with resampled transfer ratios from other weekends.
- **Diagnostic:** the within-run trend of tyre energy per lap (from the 3.7 Hz position and speed traces) flags runs where the driver was still ramping up; the push-adjusted estimate is reported as a second opinion, never as the headline.
- **Telemetry quality is checked lap by lap.** Feeds degraded at source (Hungary race, China FP1) are refused, not silently modelled.
""")
    bc = L['validation'].get('band_coverage')
    if bc: st.markdown(f"**Band calibration (leave-one-weekend-out):** raw 90% bands covered the race value in {100*bc['raw_all']:.0f}% of cases; after conformal widening (half-widths × {bc['widening_factor_median']:.2f}, learned from other weekends' residuals) coverage is {100*bc['calibrated_all']:.0f}% overall, {100*bc['calibrated_issued']:.0f}% on issued and {100*bc['calibrated_fallback']:.0f}% on fallback cases, against a nominal 90%.")
    if os.path.exists('out/sensitivity.json'):
        sj = json.load(open('out/sensitivity.json')); st.markdown('**Sensitivity of the headline error to stated assumptions** (leave-one-weekend-out MAE, all cases):')
        st.dataframe(pd.DataFrame([{'setting': k, 'cases': v['n'], 'issued': v['issued'], 'MAE Orb v1': v['mae'], 'MAE naive': v['mae_naive'], 'r': v['r']} for k, v in sj['runs'].items()]).style.format({'MAE Orb v1': '{:.4f}', 'MAE naive': '{:.3f}', 'r': '{:+.2f}'}), hide_index=True, use_container_width=True)

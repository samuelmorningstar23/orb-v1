"""Build out/tyreformer/tyreformer_report.html: the results page (numbers read from the evaluation files, charts drawn in
theme-aware SVG in the page). CLI:  python -m tyreformer.report_page
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from tyreformer import OUT, PROTO
from tyreformer.figures import merged, boot_ci, fan_data


def horizon_series(M: pd.DataFrame) -> dict:
    out = {}
    for key, pre in (('estimator', 'kal'), ('tyreformer', 'h')):
        pts = []
        for h in range(1, 6):
            m = M[f'y{h}'].notna() & M[f'kal{h}'].notna() & M['h1_q50'].notna()
            pred = M.loc[m, f'kal{h}'] if key == 'estimator' else M.loc[m, f'h{h}_q50']
            d = pd.DataFrame(dict(race_id=M.loc[m, 'race_id'], e=(pred - M.loc[m, f'y{h}']).abs()))
            lo, hi = boot_ci(d, 'e', n=600)
            pts.append(dict(h=h, mae=float(d['e'].mean()), lo=lo, hi=hi, n=int(len(d))))
        out[key] = pts
    return out


def split_row(name: str, note: str, h: dict) -> dict:
    g = lambda k: h.get(k, {})
    return dict(name=name, note=note, races=h.get('weekends'),
                next1=[g('next1').get('orb_v1_estimator'), g('next1').get('tyreformer')], next5=[g('next5').get('orb_v1_estimator'), g('next5').get('tyreformer')],
                cum5=[g('cum5').get('orb_v1_estimator'), g('cum5').get('tyreformer')],
                cliff5=[g('cliff5').get('orb_v1_estimator_brier'), g('cliff5').get('tyreformer_brier'), g('cliff5').get('climatology_train_rate')],
                cov1=[g('next1').get('coverage90_orb_v1_estimator'), g('next1').get('coverage90_tyreformer')],
                better=[g('next1').get('weekends_tyreformer_better'), g('next1').get('weekends')], ci1=g('next1').get('difference_ci90'), ci5=g('cum5').get('difference_ci90'))


def main() -> int:
    ev = json.loads((OUT / 'evaluation.json').read_text(encoding='utf-8'))
    sealed = json.loads((OUT / 'sealed_holdout_aggregate.json').read_text(encoding='utf-8'))
    figs = json.loads((OUT / 'figures.json').read_text(encoding='utf-8'))
    pre = json.loads((OUT / 'prerace' / 'prerace_eval.json').read_text(encoding='utf-8'))
    ens = json.loads((OUT / 'ensemble.json').read_text(encoding='utf-8'))
    freeze = json.loads((PROTO / 'tyreformer' / 'FREEZE.json').read_text(encoding='utf-8'))
    M26, Mcv = merged('rolling'), merged('cv')
    sel = pre['selection']['chosen_model']
    data = dict(
        splits=[split_row('Sealed holdout', 'aggregate only · frozen before the first look', sealed['head_to_head']),
                split_row('2026, deployment protocol', 'trained on 2023–25 + earlier 2026 races', ev['test_2026_rolling']['head_to_head']),
                split_row('2026, strict temporal', 'no 2026 race in training', ev['test_2026_temporal']['head_to_head']),
                split_row('Cross-validation 2023–25', '5 folds grouped by weekend', ev['cv_2023_2025']['head_to_head'])],
        horizon={'2026': horizon_series(M26), 'cv': horizon_series(Mcv)},
        ladder={'2026': figs['ladder_2026'], 'cv': figs['ladder_cv']},
        fan=fan_data('rolling'),
        facts=dict(origins=ev['data']['origins_by_season'], weekends=ev['data']['weekends_by_season'], targets=ev['data']['horizon_targets'],
                   weights=ens['weights'], frozen_at=freeze['frozen_at'], frozen_files=len(freeze['files']), sealed_ids=ev['sealed_excluded']),
        prerace=dict(model=sel, A=dict(orb=pre['protocols']['A']['metrics']['orb_v1'], learned=pre['protocols']['A']['metrics'][sel], rows=pre['protocols']['A']['n_rows'], weekends=pre['protocols']['A']['n_weekends']),
                     B=dict(orb=pre['protocols']['B']['metrics']['orb_v1'], learned=pre['protocols']['B']['metrics'][sel], rows=pre['protocols']['B']['n_rows'], weekends=pre['protocols']['B']['n_weekends'])))
    html = TEMPLATE.replace('__DATA__', json.dumps(data, default=float))
    p = OUT / 'tyreformer_report.html'
    p.write_text(html, encoding='utf-8')
    print(f'wrote {p} ({len(html) // 1024} KB)')
    return 0


TEMPLATE = r"""<title>Orb TyreFormer</title>
<meta name="description" content="Evaluation of the learned tyre model trained on four Formula 1 seasons, scored against the Orb v1 live estimator.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --ground:#F2F5F7; --surface:#FFFFFF; --raised:#E9EEF2; --rule:#D3DBE2; --ink:#0B1117; --ink2:#4B5864; --ink3:#6B7885;
  --brand:#0B857C; --est:#D35A2A; --tf:#138A63; --tfband:rgba(27,175,122,.16); --tfband2:rgba(27,175,122,.30); --estband:rgba(235,104,52,.14);
  --tree:#2A78D6; --good:#138A63;
  --sans:Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; --mono:"IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --ground:#090C11; --surface:#11161E; --raised:#171D27; --rule:#272F3B; --ink:#F3F6FA; --ink2:#A7B1BE; --ink3:#7D8896;
  --brand:#39D0C3; --est:#E0662F; --tf:#2BBF8A; --tfband:rgba(25,158,112,.20); --tfband2:rgba(25,158,112,.38); --estband:rgba(217,89,38,.18); --tree:#3987E5; --good:#2BBF8A;
}}
:root[data-theme="dark"]{
  --ground:#090C11; --surface:#11161E; --raised:#171D27; --rule:#272F3B; --ink:#F3F6FA; --ink2:#A7B1BE; --ink3:#7D8896;
  --brand:#39D0C3; --est:#E0662F; --tf:#2BBF8A; --tfband:rgba(25,158,112,.20); --tfband2:rgba(25,158,112,.38); --estband:rgba(217,89,38,.18); --tree:#3987E5; --good:#2BBF8A;
}
*{box-sizing:border-box}
body{background:var(--ground); color:var(--ink); font-family:var(--sans); font-size:15px; line-height:1.55; margin:0; -webkit-font-smoothing:antialiased}
.wrap{max-width:1040px; margin:0 auto; padding:48px 28px 72px; display:flex; flex-direction:column; gap:56px}
.eyebrow{font-family:var(--mono); font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--ink3)}
h1{font-size:44px; line-height:1.05; letter-spacing:-.02em; margin:10px 0 14px; font-weight:700; text-wrap:balance}
h1 .tf{color:var(--brand)}
h2{font-size:22px; letter-spacing:-.01em; margin:0 0 6px; font-weight:650; text-wrap:balance}
.lede{font-size:18px; color:var(--ink2); max-width:64ch; margin:0}
p{max-width:68ch; margin:0}
.sub{color:var(--ink2); max-width:72ch}
section{display:flex; flex-direction:column; gap:18px}
.num{font-family:var(--mono); font-variant-numeric:tabular-nums}
.strip{display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1px; background:var(--rule); border:1px solid var(--rule); border-radius:12px; overflow:hidden; margin-top:28px}
.stat{background:var(--surface); padding:18px 20px; display:flex; flex-direction:column; gap:6px}
.stat .k{font-size:13px; color:var(--ink2)}
.stat .v{font-size:34px; font-weight:650; letter-spacing:-.02em; color:var(--ink)}
.stat .v small{font-size:15px; color:var(--ink3); font-weight:500; letter-spacing:0; margin-left:6px}
.stat .d{font-family:var(--mono); font-size:12.5px; color:var(--ink3)}
.label-sealed{display:inline-flex; align-items:center; gap:8px; font-family:var(--mono); font-size:12px; color:var(--ink2); margin-top:10px}
.label-sealed i{width:8px; height:8px; border-radius:50%; background:var(--brand); display:inline-block}
.tablewrap{overflow-x:auto; border:1px solid var(--rule); border-radius:12px; background:var(--surface)}
table{border-collapse:collapse; width:100%; min-width:860px; font-size:14px}
th,td{padding:12px 14px; text-align:right; border-bottom:1px solid var(--rule); white-space:nowrap}
th{font-size:12px; font-weight:500; color:var(--ink3); text-transform:uppercase; letter-spacing:.06em; background:var(--raised)}
th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}
td .split{font-weight:600} td .note{display:block; font-size:12px; color:var(--ink3); font-weight:400; white-space:normal; max-width:26ch}
.pair{font-family:var(--mono); font-variant-numeric:tabular-nums}
.pair .a{color:var(--ink3)} .pair .arrow{color:var(--ink3); margin:0 4px} .pair .b{color:var(--ink); font-weight:500}
.chg{display:block; font-family:var(--mono); font-size:12px; color:var(--good)}
.legend-inline{display:flex; gap:18px; flex-wrap:wrap; font-size:13px; color:var(--ink2)}
.sw{display:inline-block; width:18px; height:3px; border-radius:2px; vertical-align:middle; margin-right:6px}
.panel{background:var(--surface); border:1px solid var(--rule); border-radius:12px; padding:18px 18px 10px}
.panelhead{display:flex; justify-content:space-between; align-items:flex-end; gap:16px; flex-wrap:wrap; margin-bottom:6px}
.seg{display:inline-flex; border:1px solid var(--rule); border-radius:8px; overflow:hidden}
.seg button{font:500 13px var(--sans); color:var(--ink2); background:transparent; border:0; padding:7px 12px; cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--raised); color:var(--ink)}
.seg button:focus-visible{outline:2px solid var(--brand); outline-offset:-2px}
.grid2{display:grid; grid-template-columns:minmax(0,1.15fr) minmax(0,1fr); gap:18px}
svg text{fill:var(--ink2); font-family:var(--sans)}
svg .tick{font-size:11px; fill:var(--ink3); font-family:var(--mono)}
svg .grid{stroke:var(--rule); stroke-width:1}
svg .lbl{font-size:12px; fill:var(--ink)}
.tip{position:fixed; pointer-events:none; background:var(--raised); color:var(--ink); border:1px solid var(--rule); border-radius:8px; padding:8px 10px; font-size:12.5px; font-family:var(--mono); box-shadow:0 6px 24px rgba(0,0,0,.18); z-index:9}
dl{display:grid; grid-template-columns:minmax(160px,220px) minmax(0,1fr); gap:10px 24px; margin:0}
dt{color:var(--ink3); font-size:13px} dd{margin:0; max-width:68ch}
ul.plain{margin:0; padding-left:18px; display:flex; flex-direction:column; gap:8px; max-width:74ch}
pre{background:var(--surface); border:1px solid var(--rule); border-radius:12px; padding:14px 16px; overflow-x:auto; font:12.5px/1.6 var(--mono); color:var(--ink2); margin:0}
.foot{font-size:12.5px; color:var(--ink3); font-family:var(--mono)}
@media (max-width:760px){ .strip{grid-template-columns:1fr} .grid2{grid-template-columns:1fr} h1{font-size:34px} dl{grid-template-columns:1fr} }
@media (prefers-reduced-motion: reduce){ *{transition:none!important} }
</style>

<div class="wrap">
  <header>
    <div class="eyebrow">Orb v1 · Trackshift 2026 · learned tyre model</div>
    <h1>Orb <span class="tf">TyreFormer</span></h1>
    <p class="lede">At the end of every lap it forecasts the car's next ten fuel-corrected lap times on its current tyres, with a 90&nbsp;% band and a cliff risk. It learned from every race and sprint stint of 2023 to 2026, and it is scored on exactly the laps Orb&nbsp;v1's live estimator is scored on.</p>
    <div class="strip" id="strip"></div>
    <div class="label-sealed"><i></i><span id="sealedlabel"></span></div>
  </header>

  <section>
    <h2>Better on every split we could score</h2>
    <p class="sub">Each cell reads Orb v1 live estimator → Orb TyreFormer, mean absolute error in seconds, on identical forecast origins and targets. Brier scores are for the cliff within five laps; the base rate is a constant forecast.</p>
    <div class="tablewrap"><table id="splits"></table></div>
  </section>

  <section>
    <div class="panelhead">
      <div><h2>Error grows more slowly with horizon</h2><p class="sub">Mean absolute error by laps ahead, with 90&nbsp;% weekend-bootstrap bands.</p></div>
      <div class="seg" role="group" aria-label="Data set"><button type="button" data-set="2026" aria-pressed="true">Every 2026 race</button><button type="button" data-set="cv" aria-pressed="false">2023–25 cross-validation</button></div>
    </div>
    <div class="grid2">
      <div class="panel"><div class="legend-inline"><span><i class="sw" style="background:var(--est)"></i>Orb v1 live estimator</span><span><i class="sw" style="background:var(--tf)"></i>Orb TyreFormer</span></div><svg id="horizon" viewBox="0 0 560 330" role="img" aria-label="Error by horizon"></svg></div>
      <div class="panel"><div class="legend-inline"><span>Next-lap error on the same origins</span></div><svg id="ladder" viewBox="0 0 480 330" role="img" aria-label="Next-lap error by model"></svg></div>
    </div>
  </section>

  <section>
    <h2 id="fantitle">One stint, one forecast</h2>
    <p class="sub" id="fansub"></p>
    <div class="panel"><div class="legend-inline"><span><i class="sw" style="background:var(--ink3);height:8px;width:8px;border-radius:50%"></i>clean laps seen</span><span><i class="sw" style="border:1.5px solid var(--ink);height:9px;width:9px;border-radius:50%;background:transparent"></i>what happened next</span><span><i class="sw" style="background:var(--tf)"></i>TyreFormer median, 50&nbsp;% and 90&nbsp;% band</span><span><i class="sw" style="background:var(--est)"></i>Orb v1 estimator</span></div><svg id="fan" viewBox="0 0 1000 360" role="img" aria-label="Forecast fan for one stint"></svg></div>
  </section>

  <section>
    <h2>How it was tested</h2>
    <ul class="plain">
      <li><strong>Model selection</strong> used only 5-fold cross-validation of 2023–2025, grouped by weekend. That covered seven transformer configurations, the tree ablation, the blend weights and the conformal band widths.</li>
      <li><strong>2026 was never used for a choice.</strong> The strict test trains on 2023–2025 only. The deployment protocol forecasts race <em>r</em> with a model trained on 2023–2025 plus the 2026 races held before <em>r</em>. One early single-seed probe on 2026 checked the pipeline before any tuning.</li>
      <li><strong>Sealed holdout.</strong> Six weekends are refused by every loader. The model was frozen with <span class="num" id="frozen"></span>, then scored once. Only pooled numbers were written.</li>
      <li><strong>Baseline.</strong> The baseline is the real Orb v1 live estimator. Run with the product's priors, it reproduces its published prefix evaluation exactly. Everywhere else it gets leave-one-out priors.</li>
    </ul>
  </section>

  <section>
    <h2>What is inside</h2>
    <dl id="facts"></dl>
  </section>

  <section>
    <h2>Where it is weaker</h2>
    <ul class="plain">
      <li>It uses public timing and telemetry-derived data only. Tyre temperatures, pressures and wear are never observed; the model infers their effect from lap times and energy proxies.</li>
      <li>The cliff label is dominated by lap-to-lap noise. TyreFormer's probability is calibrated where the estimator's is not, but it is only slightly better than a constant base rate. Show it as a risk, not a call.</li>
      <li>2026 is a regulation change. Next-lap bands cover 85–88&nbsp;% there, against 90&nbsp;% in cross-validation.</li>
      <li>The estimator's 2026 priors are leave-one-out within the season, so they draw on later 2026 weekends. That is a small edge in the estimator's favour.</li>
    </ul>
  </section>

  <section>
    <h2>Companion: learned practice-to-race transfer</h2>
    <p class="sub" id="presub"></p>
    <div class="tablewrap"><table id="pre" style="min-width:640px"></table></div>
  </section>

  <section>
    <h2>Reproduce</h2>
    <pre>cd proto
../.venv/bin/python -m tyreformer.data --out out/tyreformer/cache/samples_dev_v3.npz
../.venv/bin/python -m tyreformer.train --experiment cv|temporal|rolling|production   # flags in out/tyreformer/logs/train_*.json
../.venv/bin/python -m tyreformer.gbm --experiment cv|temporal|rolling|production
../.venv/bin/python -m tyreformer.blend && ../.venv/bin/python -m tyreformer.evaluate
../.venv/bin/python -m tyreformer.sealed verify
../.venv/bin/python -m pytest tests/tyreformer -q</pre>
    <p class="foot">Sources: out/tyreformer/evaluation.json, sealed_holdout_aggregate.json, prerace/prerace_eval.json, tyreformer/FREEZE.json.</p>
  </section>
</div>
<div class="tip" id="tip" hidden></div>

<script>
const D = __DATA__;
const $ = s => document.querySelector(s);
const f3 = v => v == null ? '—' : v.toFixed(3);
const pct = (a, b) => (100 * (b / a - 1)).toFixed(0) + ' %';
const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs, parent, text) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text != null) e.textContent = text; if (parent) parent.appendChild(e); return e; };
const tip = $('#tip');
function showTip(ev, html){ tip.innerHTML = html; tip.hidden = false; const x = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8); tip.style.left = x + 'px'; tip.style.top = (ev.clientY + 14) + 'px'; }
function hideTip(){ tip.hidden = true; }

// headline strip: sealed holdout
const S0 = D.splits[0];
$('#strip').innerHTML = [
  ['Next-lap error', S0.next1, 's'], ['5-lap cumulative error', S0.cum5, 's'], ['Cliff risk, Brier score', S0.cliff5, '']
].map(([k, v, u]) => `<div class="stat"><div class="k">${k}</div><div class="v num">${f3(v[1])}<small>${u ? u + ' ' : ''}from ${f3(v[0])}</small></div><div class="d">${pct(v[0], v[1])} vs the Orb v1 live estimator</div></div>`).join('');
$('#sealedlabel').textContent = `sealed holdout, aggregate only · ${S0.races} weekends · model frozen ${D.facts.frozen_at.slice(0, 16).replace('T', ' ')} IST before scoring`;
$('#frozen').textContent = `${D.facts.frozen_files} files hashed at ${D.facts.frozen_at.slice(11, 16)} IST`;

// splits table
const pair = (v, extra) => `<span class="pair"><span class="a">${f3(v[0])}</span><span class="arrow">→</span><span class="b">${f3(v[1])}</span></span><span class="chg">${pct(v[0], v[1])}${extra || ''}</span>`;
$('#splits').innerHTML = `<thead><tr><th>Split</th><th>Races</th><th>Next lap</th><th>5 laps ahead</th><th>5-lap cumulative</th><th>Cliff Brier (base rate)</th><th>Next-lap 90 % band covers</th><th>Races better</th></tr></thead><tbody>` +
  D.splits.map(r => `<tr><td><span class="split">${r.name}</span><span class="note">${r.note}</span></td><td class="num">${r.races}</td><td>${pair(r.next1)}</td><td>${pair(r.next5)}</td><td>${pair(r.cum5)}</td>` +
  `<td><span class="pair"><span class="a">${f3(r.cliff5[0])}</span><span class="arrow">→</span><span class="b">${f3(r.cliff5[1])}</span></span><span class="chg" style="color:var(--ink3)">base rate ${f3(r.cliff5[2])}</span></td>` +
  `<td class="num">${(100 * r.cov1[1]).toFixed(1)} %<span class="chg" style="color:var(--ink3)">estimator ${(100 * r.cov1[0]).toFixed(1)} %</span></td><td class="num">${r.better[0]}/${r.better[1]}</td></tr>`).join('') + '</tbody>';

// horizon chart
function drawHorizon(set){
  const svg = $('#horizon'); svg.innerHTML = '';
  const H = D.horizon[set], W = 560, Ht = 330, m = {l:48, r:150, t:16, b:40};
  const all = [...H.estimator, ...H.tyreformer];
  const lo = Math.floor(Math.min(...all.map(p => p.lo)) * 20) / 20, hi = Math.ceil(Math.max(...all.map(p => p.hi)) * 20) / 20;
  const x = h => m.l + (h - 1) / 4 * (W - m.l - m.r), y = v => Ht - m.b - (v - lo) / (hi - lo) * (Ht - m.t - m.b);
  for (let v = lo; v <= hi + 1e-9; v += 0.05){ el('line', {x1:m.l, x2:W - m.r, y1:y(v), y2:y(v), class:'grid'}, svg); el('text', {x:m.l - 8, y:y(v) + 4, 'text-anchor':'end', class:'tick'}, svg, v.toFixed(2)); }
  for (let h = 1; h <= 5; h++) el('text', {x:x(h), y:Ht - m.b + 20, 'text-anchor':'middle', class:'tick'}, svg, '+' + h);
  el('text', {x:(m.l + W - m.r) / 2, y:Ht - 4, 'text-anchor':'middle', class:'tick'}, svg, 'laps ahead');
  [['estimator', 'var(--est)', 'var(--estband)', 'Orb v1 estimator'], ['tyreformer', 'var(--tf)', 'var(--tfband)', 'TyreFormer']].forEach(([k, c, band, name]) => {
    const pts = H[k];
    el('path', {d:'M' + pts.map(p => `${x(p.h)},${y(p.hi)}`).join('L') + 'L' + pts.slice().reverse().map(p => `${x(p.h)},${y(p.lo)}`).join('L') + 'Z', fill:band, stroke:'none'}, svg);
    el('path', {d:'M' + pts.map(p => `${x(p.h)},${y(p.mae)}`).join('L'), fill:'none', stroke:c, 'stroke-width':2.2}, svg);
    pts.forEach(p => { const dot = el('circle', {cx:x(p.h), cy:y(p.mae), r:4.5, fill:c, stroke:'var(--surface)', 'stroke-width':2}, svg);
      const hit = el('circle', {cx:x(p.h), cy:y(p.mae), r:14, fill:'transparent'}, svg);
      hit.addEventListener('mousemove', ev => showTip(ev, `${name}, +${p.h} lap${p.h > 1 ? 's' : ''}<br>${p.mae.toFixed(3)} s [${p.lo.toFixed(3)}, ${p.hi.toFixed(3)}]<br>n = ${p.n.toLocaleString()}`)); hit.addEventListener('mouseleave', hideTip); });
    const last = pts[4]; el('text', {x:x(5) + 12, y:y(last.mae) + 4, class:'lbl'}, svg, `${name} ${last.mae.toFixed(3)} s`);
  });
}
// ladder chart
function drawLadder(set){
  const svg = $('#ladder'); svg.innerHTML = '';
  const L = D.ladder[set];
  const rows = [['current pace', L['current pace (persistence)'], 'var(--ink3)'], ['pre-race slope only', L['pre-race slope only'], 'var(--ink3)'], ['Orb v1 live estimator', L['Orb v1 live estimator'], 'var(--est)'],
                ['gradient-boosted trees', L['gradient-boosted trees'], 'var(--tree)'], ['transformer', L['transformer'], 'var(--tf)'], ['TyreFormer ensemble', L['Orb TyreFormer ensemble'], 'var(--tf)']];
  const W = 480, m = {l:156, r:64, t:10, b:40}, bh = 30, gap = 16;
  const max = Math.ceil(Math.max(...rows.map(r => r[1])) * 10) / 10;
  const x = v => m.l + v / max * (W - m.l - m.r);
  for (let v = 0; v <= max + 1e-9; v += 0.1){ el('line', {x1:x(v), x2:x(v), y1:m.t, y2:m.t + rows.length * (bh + gap) - gap, class:'grid'}, svg); el('text', {x:x(v), y:m.t + rows.length * (bh + gap) + 12, 'text-anchor':'middle', class:'tick'}, svg, v.toFixed(1)); }
  rows.forEach(([name, v, c], i) => { const yy = m.t + i * (bh + gap);
    el('text', {x:m.l - 10, y:yy + bh / 2 + 4, 'text-anchor':'end', class:'lbl'}, svg, name);
    el('rect', {x:m.l, y:yy, width:Math.max(0, x(v) - m.l), height:bh, rx:4, fill:c, opacity:name === 'transformer' ? .55 : 1}, svg);
    el('text', {x:x(v) + 6, y:yy + bh / 2 + 4, class:'tick', style:'fill:var(--ink)'}, svg, v.toFixed(3) + ' s'); });
  el('text', {x:(m.l + W - m.r) / 2, y:328, 'text-anchor':'middle', class:'tick'}, svg, `next-lap error, s · n = ${L.n.toLocaleString()} origins, ${L.weekends} races`);
}
function setData(set){ document.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.set === set))); drawHorizon(set); drawLadder(set); }
document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => setData(b.dataset.set)));
setData('2026');

// fan chart
(function(){
  const F = D.fan, svg = $('#fan'), W = 1000, Ht = 360, m = {l:56, r:24, t:20, b:44};
  $('#fantitle').textContent = `One stint, one forecast: ${F.event} ${F.season}, ${F.driver}`;
  $('#fansub').textContent = `${F.compound.toLowerCase()} tyres, forecast made at the end of lap ${F.origin_lap} by a model that never trained on this race. A typical stint, chosen by rule: clearly degrading, with a 5-lap error near the median.`;
  const laps = [...F.past.map(p => p[0]), ...F.future.map(p => p[0]), ...F.tyreformer.map(p => p.lap)];
  const vals = [...F.past.map(p => p[1]), ...F.future.map(p => p[1]), ...F.tyreformer.flatMap(p => [p.q05, p.q95]), ...F.estimator.map(p => p.mean)];
  const x0 = Math.min(...laps) - 0.5, x1 = Math.max(...laps) + 0.5, y0 = Math.floor(Math.min(...vals) * 2) / 2, y1 = Math.ceil(Math.max(...vals) * 2) / 2;
  const x = l => m.l + (l - x0) / (x1 - x0) * (W - m.l - m.r), y = v => Ht - m.b - (v - y0) / (y1 - y0) * (Ht - m.t - m.b);
  for (let v = y0; v <= y1 + 1e-9; v += 0.5){ el('line', {x1:m.l, x2:W - m.r, y1:y(v), y2:y(v), class:'grid'}, svg); el('text', {x:m.l - 8, y:y(v) + 4, 'text-anchor':'end', class:'tick'}, svg, v.toFixed(1)); }
  for (let l = Math.ceil(x0); l <= x1; l += 2) el('text', {x:x(l), y:Ht - m.b + 20, 'text-anchor':'middle', class:'tick'}, svg, l);
  el('text', {x:(m.l + W - m.r) / 2, y:Ht - 6, 'text-anchor':'middle', class:'tick'}, svg, 'race lap · fuel-corrected lap time, s');
  el('line', {x1:x(F.origin_lap + 0.5), x2:x(F.origin_lap + 0.5), y1:m.t, y2:Ht - m.b, stroke:'var(--rule)', 'stroke-width':1.5, 'stroke-dasharray':'3 4'}, svg);
  el('text', {x:x(F.origin_lap + 0.5) + 8, y:m.t + 12, class:'tick'}, svg, `forecast at end of lap ${F.origin_lap}`);
  const T = F.tyreformer;
  el('path', {d:'M' + T.map(p => `${x(p.lap)},${y(p.q95)}`).join('L') + 'L' + T.slice().reverse().map(p => `${x(p.lap)},${y(p.q05)}`).join('L') + 'Z', fill:'var(--tfband)'}, svg);
  el('path', {d:'M' + T.map(p => `${x(p.lap)},${y(p.q75)}`).join('L') + 'L' + T.slice().reverse().map(p => `${x(p.lap)},${y(p.q25)}`).join('L') + 'Z', fill:'var(--tfband2)'}, svg);
  el('path', {d:'M' + T.map(p => `${x(p.lap)},${y(p.q50)}`).join('L'), fill:'none', stroke:'var(--tf)', 'stroke-width':2.4}, svg);
  el('path', {d:'M' + F.estimator.map(p => `${x(p.lap)},${y(p.mean)}`).join('L'), fill:'none', stroke:'var(--est)', 'stroke-width':2.4, 'stroke-dasharray':'8 5'}, svg);
  F.past.forEach(p => el('circle', {cx:x(p[0]), cy:y(p[1]), r:5, fill:'var(--ink3)'}, svg));
  F.future.forEach(p => el('circle', {cx:x(p[0]), cy:y(p[1]), r:5.5, fill:'var(--surface)', stroke:'var(--ink)', 'stroke-width':1.8}, svg));
  T.forEach(p => { const actual = F.future.find(q => q[0] === p.lap); const est = F.estimator.find(q => q.lap === p.lap);
    const hit = el('rect', {x:x(p.lap - 0.5), y:m.t, width:x(p.lap + 0.5) - x(p.lap - 0.5), height:Ht - m.t - m.b, fill:'transparent'}, svg);
    hit.addEventListener('mousemove', ev => showTip(ev, `lap ${p.lap}<br>TyreFormer ${p.q50.toFixed(2)} s (90 %: ${p.q05.toFixed(2)}–${p.q95.toFixed(2)})` + (est ? `<br>estimator ${est.mean.toFixed(2)} s` : '') + (actual ? `<br>actual ${actual[1].toFixed(2)} s` : '<br>no clean lap')));
    hit.addEventListener('mouseleave', hideTip); });
})();

// facts
const fx = D.facts, o = fx.origins, w = fx.weekends;
const total = Object.values(o).reduce((a, b) => a + b, 0);
$('#facts').innerHTML = [
  ['Training data', `${total.toLocaleString()} forecast origins with ${fx.targets.toLocaleString()} future-lap targets, from ${Object.keys(w).map(k => `${w[k]} weekends of ${k}`).join(', ')}. That is every race and sprint lap on disk except the sealed weekends (${fx.sealed_ids.join(', ')}).`],
  ['Per-lap inputs', 'Lap time against the current level, clean flag, tyre age, race progress, traffic share, track status, pit and deletion flags, compound, tyre energy and its lateral and longitudinal split, full-throttle share, sector losses against the stint best, feed quality, and how the rest of the field\'s laps just changed.'],
  ['Per-forecast context', 'Stint and tyre-set state, track temperature and its change since practice, rain, season, sprint flag, the weekend\'s Orb v1 pre-race forecast for every compound, compound pace offsets, and the Pirelli C-number nomination (verified for 82 of 82 weekends from Pirelli and Formula 1 sources).'],
  ['Transformer', '24-lap window plus a context token; 3 pre-norm layers, width 96, 4 heads, 468,278 parameters. A circuit embedding is dropped to "unknown" half the time in training, so a new circuit such as Madrid still works. Outputs: monotone quantiles for 10 horizons, 3- and 5-lap sums, and cliff probabilities. About 40 seconds per model on an M2 Max; 3 seeds each.'],
  ['Ensemble', `Gradient-boosted median experts for 1 to 5 laps. Blend weight on the trees: ${Object.entries(fx.weights).map(([k, v]) => `${k.replace('h', '+')} ${v}`).join(', ')}. The transformer's bands move with the blended median, then split-conformal margins set them to 90 %.`],
  ['Live use', 'tyreformer.infer forecasts one car at the end of one lap and refuses any lap completed later. Tests assert the live forecast equals the scored replay.']
].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');

// pre-race companion
const P = D.prerace;
$('#presub').textContent = `A small regularised model (${P.model}) predicts each compound's race degradation, in seconds per lap per lap of tyre age. It uses practice, the Orb v1 forecast, the Pirelli C-number and earlier seasons of the same circuit. Across four seasons it beats Orb v1, much of it by shrinking toward typical degradation. On 2026 alone it does not beat Orb v1, so treat it as a second opinion.`;
$('#pre').innerHTML = `<thead><tr><th>Protocol</th><th>Compound-weekends</th><th>MAE, Orb v1 → learned</th><th>Correlation, Orb v1 → learned</th></tr></thead><tbody>` +
  [['Leave one weekend out, 2023–2026', P.A], ['Trained 2023–25, tested on 2026', P.B]].map(([n, r]) =>
  `<tr><td>${n}</td><td class="num">${r.rows} (${r.weekends} weekends)</td><td class="pair"><span class="a">${r.orb.mae.toFixed(4)}</span><span class="arrow">→</span><span class="b">${r.learned.mae.toFixed(4)}</span></td><td class="pair"><span class="a">${r.orb.pearson_r.toFixed(2)}</span><span class="arrow">→</span><span class="b">${r.learned.pearson_r.toFixed(2)}</span></td></tr>`).join('') + '</tbody>';
</script>
"""

if __name__ == '__main__':
    raise SystemExit(main())

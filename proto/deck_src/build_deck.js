// Orb v1 briefing deck, rebuilt 13 Sep 2026 from what is on disk now. Every figure on a slide is read from an artefact at
// build time (the locks, out/validation, out/tyreformer, out/counterfactual, the red-team reports, deck_src/assets); none
// is typed. Wide 16:9 canvas, Arial throughout (true to width on every viewer, including the Quick Look render used for QA).
//
//   node build_deck.js                      writes ../out/Orb_v1_Mentor_Briefing.pptx
//   DECK_OUT=/tmp/x.pptx node build_deck.js  test build elsewhere
//
// Inputs made by the scripts next to this file: assets/shot_*.png (product_shots.py), assets/season_effects.json
// (season_effects.py) and assets/regulations.json (the cited 2022-2026 rule history).
const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PROTO = path.resolve(__dirname, '..') + '/';
const OUT = PROTO + 'out/';
const ASSETS = __dirname + '/assets/';
const FILE = process.env.DECK_OUT || OUT + 'Orb_v1_Mentor_Briefing.pptx';
const readJSON = p => JSON.parse(fs.readFileSync(p, 'utf8').replace(/([:\[,])\s*-?(?:NaN|Infinity)\b/g, '$1null'));   // Python json.dump writes bare NaN
const exists = p => fs.existsSync(p);

const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE';   // 13.333 x 7.5 in
pres.title = 'Orb v1: live tyre intelligence'; pres.author = 'Team Orb v1'; pres.company = 'TrackShift 2026';
const W = 13.333, MX = 0.6, CW = W - 2 * MX;

// the product's own design tokens (ui/tokens.py): the deck and the dashboard read as one system
const C = { bg: '090C11', surf: '11161E', raised: '171D27', border: '272F3B', text: 'F3F6FA', muted: '98A3B3', dim: '6B7585', teal: '39D0C3', mint: '8FE9DC', amber: 'F0B84B', crit: 'F16464', soft: 'E10600', medium: 'F2C230', hard: 'D9DEE5', grid: '1E2530' };
const COMP = { SOFT: C.soft, MEDIUM: C.medium, HARD: C.hard };
const F = 'Arial', MONO = 'Courier New';

// ---------------------------------------------------------------- text fit and claim guard
let SLIDE_NO = 0;
const FIT = [], TEXT_BY_SLIDE = {};
function flat(text) { return Array.isArray(text) ? text.map(r => (typeof r === 'string' ? r : r.text) + ((r.options && r.options.breakLine) ? '\n' : '')).join('') : String(text); }
function wrapLines(text, w, pt, bold) {
  const cw = pt * (bold ? 0.55 : 0.49) / 72, maxChars = Math.max(1, Math.floor(w / cw));
  return String(text).split('\n').reduce((lines, para) => {
    let cur = 0, n = 1;
    para.split(/\s+/).filter(Boolean).forEach(wd => { if (!cur) cur = wd.length; else if (cur + 1 + wd.length <= maxChars) cur += 1 + wd.length; else { n += 1; cur = wd.length; } });
    return lines + n;
  }, 0);
}
function log(text) { (TEXT_BY_SLIDE[SLIDE_NO] = TEXT_BY_SLIDE[SLIDE_NO] || []).push(text); }
function T(s, text, o) {
  const opts = Object.assign({ fontFace: F, fontSize: 14, color: C.text, margin: 0, valign: 'top', isTextBox: true }, o);
  const plain = flat(text);
  const paraGap = Array.isArray(text) ? (text.length - 1) * ((text[0].options && text[0].options.paraSpaceAfter) || 0) / 72 : 0;
  const need = wrapLines(plain, opts.w, opts.fontSize, opts.bold) * opts.fontSize * 1.2 / 72 + paraGap;
  if (need > opts.h + 0.03) FIT.push(`slide ${SLIDE_NO}: needs ${need.toFixed(2)} in, box ${opts.h.toFixed(2)} in: "${plain.slice(0, 60).replace(/\n/g, ' ')}"`);
  log(plain);
  s.addText(text, opts);
}
function bullets(s, items, o) {
  const size = o.fontSize || 13, gap = (o.gap == null ? 5 : o.gap) / 72, lh = size * 1.2 / 72, w = o.w - 0.24, dotC = o.dotColor || C.teal;
  let y = o.y;
  items.forEach(t => {
    const h = wrapLines(t, w, size, false) * lh;
    s.addShape(pres.shapes.OVAL, { x: o.x + 0.02, y: y + lh / 2 - 0.035, w: 0.07, h: 0.07, fill: { color: dotC }, line: { color: dotC, width: 0 } });
    T(s, t, { x: o.x + 0.24, y, w, h: h + 0.02, fontSize: size, color: o.color || C.text });
    y += h + gap;
  });
  if (y - gap > o.y + o.h + 0.03) FIT.push(`slide ${SLIDE_NO}: list needs ${(y - gap - o.y).toFixed(2)} in, box ${o.h.toFixed(2)} in`);
}
function titleSize(t) { return t.length <= 50 ? 30 : t.length <= 58 ? 26 : t.length <= 66 ? 23 : 21; }
function fitSize(t, w, max, min) { return Math.max(min, Math.min(max, Math.floor((w - 0.05) * 72 / (String(t).length * 0.58)))); }

function slide(kicker, title, sub, notes) {
  const s = pres.addSlide(); SLIDE_NO += 1;
  s.background = { color: C.bg };
  if (kicker) T(s, kicker.toUpperCase(), { x: MX, y: 0.42, w: CW, h: 0.26, fontSize: 11, bold: true, color: C.teal, charSpacing: 2 });
  if (title) T(s, title, { x: MX, y: 0.7, w: CW, h: 0.6, fontSize: titleSize(title), bold: true });
  if (sub) T(s, sub, { x: MX, y: 1.3, w: CW, h: 0.42, fontSize: 15, color: C.muted });
  T(s, 'ORB V1  ·  TrackShift 2026  ·  Tyre Degradation Intelligence', { x: MX, y: 7.05, w: 8, h: 0.22, fontSize: 9, color: C.dim });
  T(s, String(SLIDE_NO), { x: W - MX - 1, y: 7.05, w: 1, h: 0.22, fontSize: 9, color: C.dim, align: 'right' });
  if (notes) { s.addNotes(notes); log(notes); }
  return s;
}
function card(s, x, y, w, h, fill) { s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill || C.surf }, line: { color: C.border, width: 0.75 }, rectRadius: 0.08 }); }
function label(s, text, x, y, w, color) { T(s, text.toUpperCase(), { x, y, w, h: 0.24, fontSize: 10, bold: true, color: color || C.muted, charSpacing: 1.5 }); }
function dot(s, x, y, n, color, d) { d = d || 0.36; s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color }, line: { color, width: 0 } }); T(s, String(n), { x, y, w: d, h: d, fontSize: 12, bold: true, color: C.bg, align: 'center', valign: 'middle' }); }
function tyre(s, x, y, comp, d) { d = d || 0.4; s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: C.bg }, line: { color: COMP[comp], width: 2.5 } }); T(s, comp[0], { x, y, w: d, h: d, fontSize: Math.round(d * 30), bold: true, color: C.text, align: 'center', valign: 'middle' }); }
function stat(s, x, y, w, big, lab, color, size, boxPt) {
  const pt = size || fitSize(big, w, 40, 18), h = Math.max(pt, boxPt || 0) * 1.22 / 72;
  T(s, big, { x, y, w, h, fontSize: pt, bold: true, color: color || C.text, valign: 'bottom' });
  T(s, lab, { x, y: y + h + 0.04, w, h: 0.62, fontSize: 12, color: C.muted });
}
function tile(s, x, y, w, h, big, lab, color, size) { card(s, x, y, w, h); stat(s, x + 0.18, y + 0.14, w - 0.36, big, lab, color, size); }
function img(s, file, x, y, w, h, frame) { if (frame) s.addShape(pres.shapes.RECTANGLE, { x: x - 0.02, y: y - 0.02, w: w + 0.04, h: h + 0.04, fill: { color: C.border }, line: { color: C.border, width: 0 } }); s.addImage({ path: file, x, y, w, h }); }
function table(s, rows, x, y, w, colW, size, rowH) {
  const data = rows.map((r, i) => r.map(c => ({ text: String(c), options: { bold: i === 0, color: i === 0 ? C.muted : C.text, fill: { color: i === 0 ? C.raised : C.surf }, fontFace: F, fontSize: size || 11, valign: 'middle' } })));
  const o = { x, y, w, colW, border: { type: 'solid', color: C.border, pt: 0.5 }, margin: 0.06 };
  if (rowH) o.rowH = rowH;
  s.addTable(data, o);
  log(rows.map(r => r.join(' | ')).join('\n'));
}
function chartBase(extra) {
  return Object.assign({ fontFace: F, chartArea: { fill: { color: C.bg } }, plotArea: { fill: { color: C.bg } }, catAxisLabelColor: C.muted, valAxisLabelColor: C.muted, catAxisLabelFontSize: 11, valAxisLabelFontSize: 10,
    catAxisLineShow: false, valAxisLineShow: false, valGridLine: { color: C.grid, size: 0.5 }, catGridLine: { style: 'none' }, showLegend: true, legendPos: 'b', legendColor: C.muted, legendFontSize: 11,
    showValue: true, dataLabelColor: C.text, dataLabelFontSize: 10, titleColor: C.text, titleFontSize: 13, showTitle: true }, extra);
}

// ---------------------------------------------------------------- evidence, read once
const median = a => { const s = [...a].sort((x, y) => x - y), n = s.length; return n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : null; };
const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
const sgn = (v, d) => (Number(Math.abs(v).toFixed(d)) === 0 ? '' : (v < 0 ? '−' : '+')) + Math.abs(v).toFixed(d);   // typographic minus; no sign on a value that rounds to zero
const pct = v => `${Math.round(v * 100)}%`;
const f3 = v => v.toFixed(3), f2 = v => v.toFixed(2), f1 = v => v.toFixed(1);
const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'];
const nice = n => n.toLocaleString('en-GB');

const LOCK = readJSON(OUT + 'lock.json'), LOCK2 = readJSON(OUT + 'lock_v2.json');
const MAD2 = LOCK2.pre_race_forecast.events.Madrid, MAD = MAD2.compounds;
const ROWS = LOCK.validation_rows, WH = ROWS.filter(r => !r.issued), ISS = ROWS.filter(r => r.issued);
const HM = ROWS.find(r => r.event === 'Hungary' && r.compound === 'MEDIUM');
const WOBS = WH.map(r => r.obs), NWH = WH.length;
const WH_MED = median(WOBS), WH_LT06 = WOBS.filter(o => o < 0.06).length, WH_COVER = WH.filter(r => r.lo <= r.obs && r.obs <= r.hi).length;
const WH_FB = mean(WH.map(r => Math.abs(r.err_cs))), WH_NV = mean(WH.map(r => Math.abs(r.err_naive)));
const WRONG = WH.filter(r => r.clean < 0), N_WRONG = WRONG.length, N_WRONG_UP = WRONG.filter(r => (r.energy_trend || 0) > 0).length;
const NEG = WH.filter(r => r.energy_trend != null && r.energy_trend < 0), N_NEG = NEG.length;
const PUSH = ISS.filter(r => r.push_adj != null), N_PUSH = PUSH.length;
const PUSH_POOLED = PUSH.reduce((a, r) => a + r.clean - r.push_adj, 0) / PUSH.reduce((a, r) => a + r.clean - r.obs, 0);
const PUSH_WORD = PUSH_POOLED >= 0.6 && PUSH_POOLED < 0.72 ? 'about two-thirds' : `about ${pct(PUSH_POOLED)}`;
const TREND_WH = median(WH.filter(r => r.energy_trend != null).map(r => r.energy_trend)), TREND_ISS = median(ISS.filter(r => r.energy_trend != null).map(r => r.energy_trend));
const BETAS = {}; LOCK.validation.push_diagnostic.beta_practice_vs_race.forEach(b => { BETAS[b.event] = [b.practice, b.race]; });
const BETA_WITHIN = Math.max(...['Austria', 'Barcelona'].map(e => Math.abs(BETAS[e][0] - BETAS[e][1]))).toFixed(2);
const RULES = LOCK.rules, FUEL_KG_LAP = RULES.fuel_prior_kg_per_lap, FUEL_S_KG = RULES.fuel_s_per_kg;
const EVO = (LOCK.live.Madrid.meta || {}).evolution_s_per_min || {};
const FRI = ['FP1', 'FP2'].filter(k => EVO[k] != null).map(k => -EVO[k] * 60);
const MAD_EVO_TXT = FRI.length ? `${Math.min(...FRI).toFixed(1)} to ${Math.max(...FRI).toFixed(1)} s per hour at Madrid on Friday` : 'measured per session';

// strategy replay: every weekend the lock scores
const views = ev => (LOCK.strategy[ev] || {}).views || {};
const SC = Object.keys(LOCK.strategy).filter(ev => views(ev)['Naive fit'] && views(ev)['Orb v1'] && views(ev)['Naive fit'].cost_under_truth_vs_best_s != null && views(ev)['Orb v1'].cost_under_truth_vs_best_s != null);
const N_SC = SC.length, SC_BEATS = SC.filter(ev => views(ev)['Orb v1'].cost_under_truth_vs_best_s < views(ev)['Naive fit'].cost_under_truth_vs_best_s).length;
const SC_MISS = SC.filter(ev => views(ev)['Orb v1'].cost_under_truth_vs_best_s >= views(ev)['Naive fit'].cost_under_truth_vs_best_s).sort((a, b) => views(b)['Orb v1'].cost_under_truth_vs_best_s - views(a)['Orb v1'].cost_under_truth_vs_best_s);
const MISS_TXT = SC_MISS.map(ev => `${ev} (${sgn(views(ev)['Orb v1'].cost_under_truth_vs_best_s, 0)} s against ${sgn(views(ev)['Naive fit'].cost_under_truth_vs_best_s, 0)} s for naive)`).join(' and ');

// liquid ablation (lap-weighted reduction stated with its basis, never as a bare percentage)
function liquid() { try { const liq = readJSON(OUT + 'liquid.json'); const cells = []; Object.entries(liq).forEach(([ev, d]) => Object.entries(d.by_compound).forEach(([c, m]) => cells.push([ev, c, m.mae_linear, m.mae_quadratic, m.mae_linear_cov, m.mae_liquid, m.n_heldout_laps]))); const full = cells.filter(x => x.slice(2, 6).every(y => y != null)); const ok = full.filter(x => x[4] >= 1e-6); const red = sub => 1 - sub.reduce((a, x) => a + x[4] * x[6], 0) / sub.reduce((a, x) => a + x[2] * x[6], 0); return { n: full.length, wins: full.filter(x => x[5] < Math.min(x[2], x[3], x[4])).length, redExcl: red(ok) }; } catch (e) { return null; } }
const LQ = liquid();
const LQ_TXT = LQ ? `Per-lap inputs cut the age-only error by ${LQ.redExcl >= 0.2 && LQ.redExcl < 0.3 ? 'about a quarter' : 'a measurable share'}; the continuous-time network on the same inputs beat the best simple baseline in only ${LQ.wins} of ${LQ.n} cells. Reported, not deployed.` : 'Liquid ablation file missing.';

// scorecards (out/validation), written by the evaluation suite
const GS = readJSON(OUT + 'validation/ghost_scorecard.json'), LS = readJSON(OUT + 'validation/live_scorecard.json');
const DEV = GS.development_pool.forecast, S26 = GS.development_pool.by_season['2026'].forecast, ROLL = GS.rolling_origin_2026.pooled, SEAL = GS.sealed_holdout.aggregate;
const SEAL_F = SEAL.forecast, HS = GS.development_pool.hidden_stop.pooled, REG = GS.development_pool.regret;
const LP = k => LS.pooled[k].estimate;
const V2 = LOCK2.validation, CAL = V2.calibration;

// learned practice-to-race transfer (out/tyreformer/prerace/PRERACE.md, predictions_A.csv / _B.csv)
function preraceMae(file) {
  const lines = fs.readFileSync(file, 'utf8').trim().split('\n'), h = lines[0].split(','), idx = k => h.indexOf(k);
  const rows = lines.slice(1).map(l => l.split(','));
  const mae = k => mean(rows.map(r => Math.abs(parseFloat(r[idx(k)]) - parseFloat(r[idx('obs')]))).filter(v => !Number.isNaN(v)));
  return { n: rows.length, orb: mae('orb_v1'), clim: mae('climatology'), huber: mae('huber_obs'), naive: mae('naive') };
}
const PRE_A = preraceMae(OUT + 'tyreformer/prerace/predictions_A.csv'), PRE_B = preraceMae(OUT + 'tyreformer/prerace/predictions_B.csv');

// Orb TyreFormer (out/tyreformer), frozen before any sealed weekend was loaded
const TF = readJSON(OUT + 'tyreformer/evaluation.json'), TFS = readJSON(OUT + 'tyreformer/sealed_holdout_aggregate.json'), TFFIG = readJSON(OUT + 'tyreformer/figures.json');
const TF_FREEZE = readJSON(PROTO + 'tyreformer/FREEZE.json');
const TF26 = TF.test_2026_rolling.head_to_head, TFSH = TFS.head_to_head;
const TF_ORIGINS = Object.values(TF.data.origins_by_season).reduce((a, b) => a + b, 0), TF_WEEKENDS = Object.values(TF.data.weekends_by_season).reduce((a, b) => a + b, 0);
const TF_DEV_ORIGINS = ['2023', '2024', '2025'].reduce((a, y) => a + TF.data.origins_by_season[y], 0), TF_2026_ORIGINS = TF.data.origins_by_season['2026'];

// counterfactual scenarios on disk (every one passed its identity check before it was written)
const CF = OUT + 'counterfactual/';
const scen = dir => fs.readdirSync(dir).filter(d => exists(dir + d + '/summary.json'));
const SC_REF = scen(CF), SC_PRE = scen(CF + 'pre_race/');
const SIM_RACES = [...new Set([...SC_REF, ...SC_PRE].map(d => d.split('_')[0]))].sort();
const ID = readJSON(PROTO + 'evaluation/red_team/identity_checks_report.json'), CONS = readJSON(PROTO + 'evaluation/red_team/consistency_probe_report.json');
const LEAK = readJSON(PROTO + 'evaluation/red_team/leakage_audit_report.json');
const C6 = fs.readFileSync(PROTO + 'checkpoints/C6/checkpoint.md', 'utf8');
const C6_PYTEST = (C6.match(/pytest: passed (\d+), skipped (\d+), xfailed (\d+)/) || []).slice(1).map(Number);
const C6_GATE = (C6.match(/release gate (\d+)\/(\d+)/) || []).slice(1).map(Number), C6_REH = (C6.match(/rehearsal (\d+) s (\d+)\/(\d+)/) || []).slice(1).map(Number);
const CHECKPOINTS = ['C0', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6'].map(c => { const j = readJSON(PROTO + `checkpoints/${c}/checkpoint.json`); return [c, j.decision, (j.at || '').slice(5, 16).replace('T', ' ')]; });
const MANIFEST = readJSON(PROTO + 'evaluation/holdout/sealed_holdout_manifest.json');
const hm = ts => ts.slice(11, 16);

// Madrid frozen forecast provenance: refuse to build if the published files and the lock disagree
const fileSha = name => crypto.createHash('sha256').update(fs.readFileSync(OUT + name)).digest('hex');
const FROZEN = readJSON(OUT + 'forecast_Madrid_2026.json'), FC_SHA = fileSha('forecast_Madrid_2026.json'), PDF_SHA = fileSha('forecast_Madrid_2026.pdf'), SIDECAR_SHA = fileSha('forecast_Madrid_2026.sha256');
const SIDECAR = fs.readFileSync(OUT + 'forecast_Madrid_2026.sha256', 'utf8').split('\n');
const listed = f => ((SIDECAR.find(l => l.trim().endsWith(f)) || '').trim().split(/\s+/)[0]) || null;
if (listed('forecast_Madrid_2026.json') !== FC_SHA || listed('forecast_Madrid_2026.pdf') !== PDF_SHA || FROZEN.lock_sha256 !== fileSha('lock.json') || FROZEN.lock_v2_sha256 !== fileSha('lock_v2.json') || FROZEN.lock_v2_forecast_hash !== LOCK2.shared.forecast_hash) throw new Error('Frozen Madrid provenance does not match the lock files');
FROZEN.compounds.forEach(c => { const v = MAD[c.compound]; if (!v || Math.abs(v.prediction - c.prediction_s_per_lap) > 0.000051 || v.n_prac !== c.clean_practice_laps || v.issued !== c.issued) throw new Error('Madrid frozen compound disagrees with lock v2'); });
const SESS = FROZEN.sessions_used || [], ISSUED_HM = hm(FROZEN.issued_at), FORECAST_HASH = LOCK2.shared.forecast_hash.replace(/^sha256:/, '');

// season facts and the cited rule history
const SE = readJSON(ASSETS + 'season_effects.json');
const REGS = exists(ASSETS + 'regulations.json') ? readJSON(ASSETS + 'regulations.json') : null;
if (!REGS && !process.env.DECK_OUT) throw new Error('assets/regulations.json is missing: the rule-history slides need their cited sources');
const SHOT = n => ASSETS + `shot_${n}.png`;

// ================================================================= 1 title
{ const s = pres.addSlide(); SLIDE_NO += 1; s.background = { color: C.bg };
  s.addNotes('Orb v1 turns public timing data into three things a strategist uses: a clean tyre-degradation curve from Friday, a live pit call on Sunday that only sees laps already run, and an audit afterwards that replays the race with a different tyre plan. Friday lies twice: about what the tyre did, and about what it will do on Sunday. We correct the first lie and learn the second.');
  T(s, 'TRACKSHIFT 2026  ·  TYRE DEGRADATION INTELLIGENCE', { x: MX, y: 0.55, w: CW, h: 0.28, fontSize: 12, bold: true, color: C.teal, charSpacing: 2 });
  T(s, 'Orb v1', { x: MX, y: 0.9, w: 8, h: 1.1, fontSize: 64, bold: true });
  T(s, 'Clean tyre curves from Friday. A live pit call on Sunday. An honest audit after the flag.', { x: MX, y: 2.05, w: CW, h: 0.45, fontSize: 22 });
  T(s, 'Friday lies twice. We correct the lie you can measure and learn the one you cannot.', { x: MX, y: 2.6, w: CW, h: 0.4, fontSize: 16, italic: true, color: C.mint });
  T(s, 'Samuel Christ  ·  A Vydehi  ·  IIT Madras', { x: MX, y: 3.12, w: CW, h: 0.36, fontSize: 18, bold: true });
  T(s, 'Team Orb v1  ·  TrackShift 2026, Plaksha University, 12 to 13 September 2026', { x: MX, y: 3.5, w: CW, h: 0.28, fontSize: 12, color: C.muted });
  T(s, 'Idea-round entry: ClearStint. Disclosed pre-work: the estimator and a six-weekend validation (5 September); the rest was built at Plaksha.', { x: MX, y: 3.8, w: CW, h: 0.26, fontSize: 11, color: C.dim });
  img(s, SHOT('ghost_3d'), MX, 4.3, CW, CW * 360 / 1840, true);
  T(s, 'Ghost Strategy, Monza 2026: the recorded car and the changed tyre plan on the same circuit, rendered offline from recorded positions (current build).', { x: MX, y: 6.76, w: CW, h: 0.28, fontSize: 10, color: C.dim }); }

// ================================================================= 2 problem
{ const s = slide('The problem', 'Friday practice is a biased sample of the race', 'A Friday lap time mixes five things, and only one of them is the tyre',
    `A practice lap time is not a tyre measurement. Hungary 2026, medium: a straight line through Friday laps says ${f3(HM.naive)} s per lap of tyre age; the race showed ${f3(HM.obs)}. A plan built on that line costs ${sgn(views('Hungary')['Naive fit'].cost_under_truth_vs_best_s, 0)} s against the best plan in the replay. Five things pollute the lap and only one of them is the tyre. Sources: out/lock.json validation_rows (Hungary MEDIUM), strategy.Hungary.`);
  const ratio = Math.round(HM.naive / HM.obs);
  stat(s, 0.6, 1.95, 2.9, f3(HM.naive), 'Hungary 2026 medium, s per lap of tyre age, from a straight line through Friday laps', C.muted, 44);
  stat(s, 3.7, 1.95, 2.6, f3(HM.obs), 'what the race showed, same estimator on race laps', C.medium, 44);
  stat(s, 6.5, 1.95, 1.7, `${ratio}×`, 'too high', C.crit, 44);
  stat(s, 8.4, 1.95, 4.3, `${sgn(views('Hungary')['Naive fit'].cost_under_truth_vs_best_s, 0)} s`, 'cost of racing the Friday line against the best plan, Hungary replay', C.crit, 44);
  [['The tyre wearing', 'what we want: a little slower every lap of age'], ['Fuel burning off', `${FUEL_KG_LAP} kg a lap in 2026, worth about ${f3(FUEL_KG_LAP * FUEL_S_KG)} s a lap, pulling the other way (more before 2026: slide 13)`], ['Track evolution', `rubber goes down and everyone gets faster: ${MAD_EVO_TXT}`], ['Traffic', 'within 60 m of another car the lap is slow for reasons that are not the tyre'], ['The driver', 'warming up, learning the circuit, pushing harder or easing off']]
    .forEach(([h, d], i) => { const y = 3.85 + i * 0.6; dot(s, 0.6, y + 0.04, i + 1, i === 0 ? C.medium : C.teal); T(s, [{ text: h + '   ', options: { bold: true, color: C.text } }, { text: d, options: { color: C.muted } }], { x: 1.15, y, w: 11.5, h: 0.46, fontSize: 15, valign: 'middle' }); }); }

// ================================================================= 3 the solution
{ const s = slide('The solution', 'One engine, three jobs: forecast, call, audit', 'The same cleaned estimator runs on practice and race laps; every screen reads one locked, hashed file',
    `Before the race Orb v1 cleans every practice lap and publishes a hashed race curve with a band and a pit plan. During the race the Live Predictor updates the tyre state lap by lap from laps already run. After the race Ghost Strategy replays the driver's own laps with a different tyre plan and every forecast is scored. Scale: ${DEV.n_weekends} weekends and ${DEV.n_compound_weekends} compound-weekends scored across 2023 to 2026 (out/validation/ghost_scorecard.json), ${SC_REF.length + SC_PRE.length} prepared strategy simulations over ${SIM_RACES.length} races (out/counterfactual), ${nice(TF_ORIGINS)} learned-model forecast origins (out/tyreformer/evaluation.json), and ${MANIFEST.holdout_count} sealed weekends (evaluation/holdout).`);
  const jobs = [['Before the race', 'Forecast', 'Clean every practice lap, refuse weak signal, learn the Friday-to-Sunday ratio, publish a hashed race curve with a band and a pit plan.', 'Screen: Forecast'],
    ['During the race', 'Live call', 'Update the tyre state every lap from laps already run; rank pit actions by modelled gain, 80% range and probability.', 'Screens: Live Predictor, Decision board'],
    ['After the race', 'Audit', 'Replay the driver’s own race with a different stop on the 3D Race Twin; score every forecast against the race.', 'Screens: Ghost Strategy, Validation']];
  jobs.forEach(([k, h, d, scr], i) => { const x = 0.6 + i * 4.19; card(s, x, 1.95, 3.75, 2.85); label(s, k, x + 0.25, 2.12, 3.3, C.teal); T(s, h, { x: x + 0.25, y: 2.42, w: 3.3, h: 0.5, fontSize: 24, bold: true }); T(s, d, { x: x + 0.25, y: 3.0, w: 3.3, h: 1.2, fontSize: 13, color: C.muted }); T(s, scr, { x: x + 0.25, y: 4.3, w: 3.3, h: 0.3, fontSize: 12, color: C.mint });
    if (i < 2) T(s, '→', { x: x + 3.77, y: 3.05, w: 0.4, h: 0.5, fontSize: 24, color: C.dim, align: 'center' }); });
  [[`${DEV.n_weekends} / ${DEV.n_compound_weekends}`, 'weekends / compound-weekends scored, 2023 to 2026, each held out'], [nice(SC_REF.length + SC_PRE.length), `prepared strategy simulations across ${WORDS[SIM_RACES.length] || SIM_RACES.length} 2026 races`], [nice(TF_ORIGINS), 'forecast origins the learned model is trained and tested on'], [String(MANIFEST.holdout_count), 'whole weekends sealed before tuning, opened once']]
    .forEach(([b, l], i) => tile(s, 0.6 + i * 3.08, 5.05, 2.9, 1.75, b, l, i === 3 ? C.amber : C.text, 30)); }

// ================================================================= 4 cleaning
{ const s = slide('The science  ·  1 of 3', 'How a lap is cleaned', 'The same regression on practice and race, so the Friday-to-Sunday ratio is a property of the data',
    `Drop laps that cannot inform the tyre; compare each run only to itself so driver, car and fuel load cancel; subtract the stated fuel effect and the measured evolution; what is left is the tyre. Hungary medium goes from ${f3(HM.naive)} to ${f3(HM.clean)} cleaned, and to ${f3(HM.pred_clearstint)} after its held-out Sunday ratio ${f2(HM.k)}, against ${f3(HM.obs)} in the race. Source: out/lock.json validation_rows.`);
  [['Drop what cannot inform the tyre', 'pit, yellow and safety-car laps, deleted laps, laps with over 30% of the distance within 60 m of a car, runs under five laps, broken telemetry; every drop listed with its reason'],
    ['Compare each run only to itself', 'one constant per stint absorbs driver, car, set-up and fuel load (stint fixed effects)'],
    ['Subtract the fuel effect', `a stated prior: ${FUEL_KG_LAP} kg per lap at ${FUEL_S_KG} s per kg in 2026; not estimated from practice, where fuel and tyre age move together`],
    ['Subtract track evolution', 'measured per session from every driver’s push laps against session time'],
    ['What is left is the tyre', 'seconds lost per lap of age, per compound, with a standard error']]
    .forEach(([h, d], i) => { const y = 1.98 + i * 0.95; dot(s, 0.6, y + 0.03, i + 1, C.teal); T(s, [{ text: h + '. ', options: { bold: true, color: C.text } }, { text: d, options: { color: C.muted } }], { x: 1.15, y, w: 6.5, h: 0.88, fontSize: 14 }); });
  card(s, 8.0, 1.95, 4.73, 4.85); label(s, 'Hungary 2026 · medium · s per lap of age', 8.25, 2.12, 4.3);
  [['Straight line through Friday laps', f3(HM.naive), C.muted], ['After cleaning', f3(HM.clean), C.teal], [`× held-out Sunday ratio ${f2(HM.k)}`, f3(HM.pred_clearstint), C.medium], ['Race, same estimator', f3(HM.obs), C.text]]
    .forEach(([l, v, c], i) => { const y = 2.55 + i * 1.02; T(s, v, { x: 8.25, y, w: 1.9, h: 0.62, fontSize: 36, bold: true, color: c }); T(s, l, { x: 10.2, y: y + 0.08, w: 2.35, h: 0.62, fontSize: 13, color: C.muted, valign: 'middle' }); }); }

// ================================================================= 5 push
{ const s = slide('The science  ·  2 of 3', 'The fifth confounder is the driver’s push', 'Tyre demand per lap from the public 3.7 Hz traces: m × (∫v²κ ds + ∫|dv| v)',
    `Some Fridays show a tyre getting faster with age, which wear cannot do. The energy the driver puts through the tyre, computed from public speed and position traces, shows why: where the cleaned Friday slope pointed the wrong way (${N_WRONG} cases) the driver was ramping up in ${N_WRONG_UP === N_WRONG ? 'each of them' : `${N_WRONG_UP} of them`}; the ${N_NEG} falling-trend cases were withheld. The push profile explains ${PUSH_WORD} of the pooled Friday-to-Sunday gap on the ${N_PUSH} issued cases (per-case shares vary widely). It is a diagnostic and second opinion: easing off can itself be a response to degradation. Source: out/lock.json validation_rows, validation.push_diagnostic.`);
  img(s, OUT + 'fig_push.png', 0.6, 1.95, 6.9, 6.9 / 1.576, false);
  card(s, 7.8, 1.95, 4.93, 4.85);
  stat(s, 8.05, 2.12, 2.1, sgn(TREND_WH, 2), 'MJ per lap of age, median energy trend, withheld compounds', C.amber, 34);
  stat(s, 10.35, 2.12, 2.1, sgn(TREND_ISS, 2), 'MJ per lap of age, issued compounds', C.teal, 34);
  bullets(s, [`Wrong-way cleaned slopes: ${N_WRONG_UP} of ${N_WRONG} came with rising energy.`, `Push profile explains ${PUSH_WORD} of the pooled gap on ${N_PUSH} issued cases; per-case shares vary widely.`, `Practice and race energy coefficients differ by at most ${BETA_WITHIN} s/MJ at Austria and Barcelona.`, 'Diagnostic and second opinion, not the predictor.'], { x: 8.05, y: 3.75, w: 4.45, h: 2.9, fontSize: 13, gap: 8 }); }

// ================================================================= 6 learn + refuse
{ const s = slide('The science  ·  3 of 3', 'Learn the second lie, and refuse honestly', 'Transfer factors learned leave-one-weekend-out; a withheld curve is still a forecast',
    `The same estimator runs on race laps, so for every past weekend we know how much Sunday shrank Friday, per compound. For a new weekend the median of the other weekends is applied only when they agree. When Friday has no signal we withhold and forecast low degradation from the other withheld cases: withheld compounds degraded at a median ${f3(WH_MED)} s/lap in the race; ${WH_LT06} of ${NWH} below 0.06 s/lap; the fallback band covered ${WH_COVER} of ${NWH}. Source: out/lock.json, out/lock_v2.json validation.by_compound.`);
  card(s, 0.6, 1.95, 6.1, 2.2); label(s, 'Season transfer factor · race ÷ cleaned Friday', 0.85, 2.12, 5.6);
  [['Soft', `×${f2(V2.by_compound.SOFT.k_median)}`, 'SOFT'], ['Medium', `×${f2(V2.by_compound.MEDIUM.k_median)}`, 'MEDIUM'], ['Hard', 'not applied', 'HARD']].forEach(([c, v, k], i) => { const x = 0.85 + i * 1.95; tyre(s, x, 2.52, k, 0.42); T(s, v, { x: x + 0.52, y: 2.46, w: 1.4, h: 0.5, fontSize: fitSize(v, 1.4, 26, 13), bold: true, valign: 'middle' }); T(s, c, { x: x + 0.52, y: 2.98, w: 1.4, h: 0.3, fontSize: 12, color: C.muted }); });
  T(s, 'applied only when at least three weekends exist and most sit within ±50% of their median', { x: 0.85, y: 3.5, w: 5.6, h: 0.5, fontSize: 12, color: C.muted });
  card(s, 0.6, 4.3, 6.1, 2.5); label(s, 'The gate and the fallback', 0.85, 4.47, 5.6);
  bullets(s, [`Issue a curve only with ${RULES.min_practice_laps}+ clean long-run laps and a cleaned slope above ${sgn(RULES.min_slope, 2)} s/lap`, 'Otherwise withhold, and forecast the median race degradation of the other withheld cases', `Withheld compounds degraded at a median ${f3(WH_MED)} s/lap in the race; ${WH_LT06} of ${NWH} below 0.06; fallback band covered ${WH_COVER} of ${NWH}; fallback error ${f3(WH_FB)} against ${f3(WH_NV)} naive`], { x: 0.85, y: 4.8, w: 5.65, h: 1.95, fontSize: 13, gap: 6 });
  img(s, OUT + 'fig_withheld.png', 7.0, 1.95, 5.73, 5.73 / 1.667, false);
  T(s, 'Withheld compounds and what the race did', { x: 7.0, y: 5.45, w: 5.73, h: 0.3, fontSize: 12, color: C.muted }); }

// ================================================================= 7 proof 2026
{ const s = slide('The proof  ·  2026', `${V2.n_weekends} weekends, ${V2.n_compound_weekends} compound-weekends, each one held out`, 'Mean absolute error against the race-derived reference, s per lap of tyre age',
    `Source: out/lock_v2.json validation. Each weekend is left out of its own training pool. Naive MAE ${f3(V2.mae_all_with_fallback.naive)} against Orb v1 ${f3(V2.mae_all_with_fallback.clearstint)} s/lap; Orb v1 beats the naive line on ${V2.wins_clearstint_over_naive} of ${V2.n_compound_weekends}; calibration r ${f2(CAL.all_with_fallback.r)} and slope ${f2(CAL.all_with_fallback.slope)}.`);
  const rows = [['Naive straight line', CAL.naive, V2.mae_all_with_fallback.naive], ['Cleaned Friday curve, issued', CAL.clean, V2.mae_issued.clean], ['Orb v1, issued', CAL.clearstint, V2.mae_issued.clearstint], ['Orb v1, every case with fallback', CAL.all_with_fallback, V2.mae_all_with_fallback.clearstint]];
  table(s, [['Predictor', 'Cases', 'MAE', 'Calib. slope', 'r'], ...rows.map(([n, c, e]) => [n, c.n, f3(e), sgn(c.slope, 2), f2(c.r)])], 0.6, 1.95, 7.1, [3.3, 0.8, 0.9, 1.3, 0.8], 13, 0.42);
  stat(s, 0.6, 4.35, 2.1, `${V2.wins_clearstint_over_naive}/${V2.n_compound_weekends}`, 'cases where Orb v1 beats the naive line', C.teal, 40, 40);
  stat(s, 2.9, 4.35, 2.8, V2.ci90_mae_clearstint_all.map(f3).join(' to '), '90% bootstrap interval on the error', C.text, 30, 40);
  stat(s, 5.9, 4.35, 1.8, `${WH_LT06}/${NWH}`, 'withheld cases below 0.06 s/lap in the race', C.text, 40, 40);
  img(s, OUT + 'fig_calibration.png', 8.05, 1.95, 4.68, 4.68 / 1.122, false);
  T(s, 'Predicted from Friday against observed in the race: filled = issued, open = fallback, × = naive', { x: 8.05, y: 6.18, w: 4.68, h: 0.5, fontSize: 11, color: C.muted }); }

// ================================================================= 8 wider tests
{ const cats = [`2026, leave one weekend out (${S26.n_compound_weekends})`, `2026, rolling origin (${ROLL.n_compound_weekends})`, `2023 to 2026, three seasons plus (${DEV.n_compound_weekends})`, `Sealed holdout, aggregate only (${SEAL_F.n_compound_weekends})`];
  const s = slide('The proof  ·  harder tests', 'Four tests, including six sealed weekends', 'Mean absolute error, s per lap of tyre age; every forecast made without its own race',
    `Sources: out/validation/ghost_scorecard.json (by_season 2026, rolling_origin_2026.pooled, development_pool, sealed_holdout.aggregate, labelled "sealed holdout, aggregate only"); out/tyreformer/prerace/PRERACE.md for the learned transfer model. The sealed holdout was scored once after the model freeze: ${SEAL.weekends.forecast} weekends forecast, ${SEAL.weekends.weekend_level_abstention} abstained (too few clean practice laps), ${SEAL_F.n_compound_weekends} compound-weekends. Across 2023 to 2026 the calibration correlation is ${f2(DEV.calibration.r)} (${f2(S26.calibration.r)} in 2026) and band coverage ${pct(DEV.band_coverage90.all)}. A per-compound constant, no practice input, scores ${f3(PRE_A.clim)} over those ${PRE_A.n} cases; the learned transfer model scores ${f3(PRE_A.huber)}. Trained on 2023 to 2025 and tested on 2026 it scores ${f3(PRE_B.huber)} against Orb v1 ${f3(PRE_B.orb)}, so it stays a second opinion. One candidate cause of the weaker 2023 to 2025 figures, not yet tested: the fuel assumptions are 2026 values applied to every season (slide 13).`);
  img(s, ASSETS + 'chart_tests.png', 0.6, 1.9, 7.4, 4.95, false);   // drawn by deck_charts.py from the same scorecard
  log(cats.join(' | ') + ` | Orb v1 ${[S26, ROLL, DEV, SEAL_F].map(x => f3(x.mae.orb_v1)).join(' / ')} | naive ${[S26, ROLL, DEV, SEAL_F].map(x => f3(x.mae.naive)).join(' / ')}`);
  card(s, 8.3, 1.95, 4.43, 2.3); label(s, 'Where it weakens', 8.55, 2.12, 4.0, C.amber);
  T(s, `Across 2023 to 2025 Friday says less about Sunday: calibration r ${f2(DEV.calibration.r)} over ${DEV.n_compound_weekends} cases against ${f2(S26.calibration.r)} in 2026, and ${pct(DEV.band_coverage90.all)} band coverage. Every test still beats the naive line.`, { x: 8.55, y: 2.42, w: 3.98, h: 1.75, fontSize: 13, color: C.muted });
  card(s, 8.3, 4.4, 4.43, 2.4); label(s, 'What we did about it', 8.55, 4.57, 4.0, C.teal);
  T(s, `A per-compound constant scores ${f3(PRE_A.clim)} across all ${PRE_A.n} cases. A learned transfer model (robust regression) reaches ${f3(PRE_A.huber)}, but on untouched 2026 it scores ${f3(PRE_B.huber)} against Orb v1's ${f3(PRE_B.orb)}. Kept as a second opinion, not adopted.`, { x: 8.55, y: 4.87, w: 3.98, h: 1.85, fontSize: 13, color: C.muted }); }

// ================================================================= 9 holds up
{ const SENS = readJSON(OUT + 'sensitivity.json').runs, r = k => SENS[k];
  const pair = (a, b, f) => `${f(r(a))} / ${f(r(b))}`;
  const s = slide('The proof  ·  robustness', 'It holds up, and the misses are on the slide', 'Sensitivity to every stated choice, and two honest results',
    `The headline barely moves across every stated choice (out/sensitivity.json). The misses: in the strategy replay ${MISS_TXT}; and the liquid neural network, which did not beat simple baselines given the same inputs (out/liquid.json). The inputs were the discovery, not the network.`);
  table(s, [['Variant (2026, 29 cases)', 'Issued', 'MAE', 'r'], [`Baseline (fuel ${FUEL_KG_LAP} kg/lap, ${FUEL_S_KG} s/kg, traffic 30%, runs 5+)`, r('baseline').issued, f3(r('baseline').mae), f2(r('baseline').r)],
    ['Fuel prior 0.9 or 1.3 kg/lap', pair('fuel 0.9 kg/lap', 'fuel 1.3 kg/lap', x => x.issued), pair('fuel 0.9 kg/lap', 'fuel 1.3 kg/lap', x => f3(x.mae)), pair('fuel 0.9 kg/lap', 'fuel 1.3 kg/lap', x => f2(x.r))],
    ['Fuel cost 0.025 or 0.035 s/kg', pair('0.025 s/kg', '0.035 s/kg', x => x.issued), pair('0.025 s/kg', '0.035 s/kg', x => f3(x.mae)), pair('0.025 s/kg', '0.035 s/kg', x => f2(x.r))],
    ['Traffic threshold 20% or 40%', pair('traffic ≤20%', 'traffic ≤40%', x => x.issued), pair('traffic ≤20%', 'traffic ≤40%', x => f3(x.mae)), pair('traffic ≤20%', 'traffic ≤40%', x => f2(x.r))],
    ['Minimum run 4 or 7 laps', pair('runs ≥4 laps', 'runs ≥7 laps', x => x.issued), pair('runs ≥4 laps', 'runs ≥7 laps', x => f3(x.mae)), pair('runs ≥4 laps', 'runs ≥7 laps', x => f2(x.r))]],
    0.6, 1.95, 7.3, [3.4, 1.05, 1.65, 1.2], 12, 0.62);
  card(s, 8.2, 1.95, 4.53, 2.3); label(s, `${SC_MISS.join(' and ')}: the misses`, 8.45, 2.12, 4.1, C.crit);
  T(s, `Strategy replay: ${MISS_TXT}. At Barcelona our soft prediction ran low and the naive line happened to imply the right plan. Said on stage before anyone asks.`, { x: 8.45, y: 2.42, w: 4.08, h: 1.75, fontSize: 13, color: C.muted });
  card(s, 8.2, 4.4, 4.53, 2.4); label(s, 'Liquid neural network, the ablation', 8.45, 4.57, 4.1, C.teal);
  T(s, `A continuous-time (CfC) cell read each race stint lap by lap, scored on held-out stints. ${LQ_TXT}`, { x: 8.45, y: 4.87, w: 4.08, h: 1.85, fontSize: 13, color: C.muted }); }

// ================================================================= 10 decisions
{ const within = p => pct(REG.plans[p].share_within_5s);
  const s = slide('From curve to call', `Curves become decisions: ${N_SC} races replayed`, 'Every one- and two-stop plan enumerated and costed under race-derived curves; the live board ranks the same actions lap by lap',
    `A curve only matters as a decision. Replayed on the ${N_SC} scored 2026 weekends with the race-derived curves as the reference, Orb v1 beats the naive plan on ${SC_BEATS} of the ${N_SC}; the ${WORDS[SC_MISS.length]} misses are ${MISS_TXT} (out/lock.json strategy). Over ${REG.plans.orb.n} weekends of 2023 to 2026, in a held-out strategy replay under a post-race reference model (out/validation/ghost_scorecard.json regret), the Orb v1 plan finished within 5 s of the hindsight-best plan on ${within('orb')} of weekends, against ${within('naive')} for the naive plan and ${within('observed')} for the strategy actually run; median regret ${f1(REG.plans.orb.median)} s against ${f1(REG.plans.naive.median)} s naive and ${f1(REG.plans.observed.median)} s for the strategy run. Mean regret equals the default plan's (${f1(REG.plans.orb.mean)} against ${f1(REG.plans.default.mean)} s), so the edge is in the typical race, not the worst.`);
  const cost = v => sgn(v.cost_under_truth_vs_best_s, 0) + ' s';
  table(s, [['Race', 'Naive plan', 'Cost', 'Orb v1 plan', 'Cost', 'Best plan'], ...SC.map(ev => { const n = views(ev)['Naive fit'], o = views(ev)['Orb v1']; return [ev, n.plan, cost(n), `${o.plan} ${o.stints.join('/')}`, cost(o), o.best_under_truth.plan]; })],
    0.6, 1.95, 7.3, [1.35, 1.15, 0.95, 1.95, 0.9, 1.0], 11, 0.4);
  tile(s, 8.2, 1.95, 2.18, 1.55, `${SC_BEATS} of ${N_SC}`, '2026 races where the Orb v1 plan beats the naive plan', C.teal, 28);
  tile(s, 10.55, 1.95, 2.18, 1.55, within('orb'), `of ${REG.plans.orb.n} weekends within 5\u00A0s of the hindsight best (naive ${within('naive')})`, C.text, 28);
  label(s, 'Live: the decision board, Barcelona lap 35', 8.2, 3.72, 4.5);
  img(s, SHOT('decision'), 8.2, 4.02, 4.53, 4.53 / 3.079, true);
  T(s, 'Assumptions on screen: linear curves, no safety car, rivals not simulated; rejoin traffic is the observed gap structure, not a position forecast.', { x: 8.2, y: 5.58, w: 4.53, h: 0.75, fontSize: 11, color: C.muted }); }

// ================================================================= 11 to 13: what the rules did to the tyres
// the rule history is cited (assets/regulations.json); every number measured in our data is derived from season_effects.json
const SE_YEARS = Object.keys(SE.degradation).sort(), COMPS = ['SOFT', 'MEDIUM', 'HARD'];
const PAIR = SE.paired_same_circuit['2025_to_2026'];
const REF_LAPS = median(SE_YEARS.map(y => SE.race_laps[y].median_race_laps));
const fuelMask = kg => FUEL_S_KG * kg / REF_LAPS;                   // lap time gained per lap as the fuel burns off
const PRE_KG = SE.fuel.pre_2026_fuel_kg, NOW_KG = SE.fuel.model_fuel_kg;
const REF_BIAS = FUEL_S_KG * (PRE_KG - SE.fuel.model_fuel_kg) / REF_LAPS;   // what a 70 kg reference leaves in a 100 kg season
const rawRange = COMPS.map(c => PAIR[c].median_change), corr100 = COMPS.map(c => PAIR[c].median_change_fuel_adjusted['100']), corr110 = COMPS.map(c => PAIR[c].median_change_fuel_adjusted['110']);
const shares = COMPS.flatMap((c, i) => [(rawRange[i] - corr100[i]) / rawRange[i], (rawRange[i] - corr110[i]) / rawRange[i]]);
const SHARE_LO = Math.round(Math.min(...shares) * 10) * 10, SHARE_HI = Math.round(Math.max(...shares) * 10) * 10;
const range3 = a => `${sgn(Math.min(...a), 3)} to ${sgn(Math.max(...a), 3)}`;
const PAIR_N = [...new Set(COMPS.map(c => PAIR[c].n))].sort().join(' to ');
const FUEL_QA = `Both ways at once: lighter 2026 cars load the tyre less, but a lighter start hides less wear in lap times. On the same circuits, ${SHARE_LO}% to ${SHARE_HI}% of the raw rise from 2025 is that fuel effect (${PAIR_N} circuits per compound).`;
if (REGS) {
  { const srcNotes = REGS.seasons.map(x => `${x.season}: ${x.sources.join(' ')}`).join(' | ');
    const s = slide('Rule changes and the tyre  ·  2022 to 2026', REGS.title, REGS.subtitle,
      `Every change here came from the FIA or Pirelli and moved how tyres wear, heat or get used. ${REGS.method} Checked ${REGS.checked_at}. Caveats: ${(REGS.caveats || []).join('; ')}. Not verified, so not on the slide: ${REGS.not_verified.join('; ')}. Sources by season: ${srcNotes}`);
    REGS.seasons.forEach((sea, i) => { const x = 0.6 + i * 2.458, w = 2.3, last = i === REGS.seasons.length - 1;
      card(s, x, 1.95, w, 4.85, last ? C.raised : C.surf);
      T(s, String(sea.season), { x: x + 0.18, y: 2.08, w: w - 0.36, h: 0.45, fontSize: 24, bold: true, color: last ? C.mint : C.text });
      T(s, sea.headline, { x: x + 0.18, y: 2.55, w: w - 0.36, h: 0.5, fontSize: 12, bold: true, color: C.teal });
      bullets(s, sea.changes, { x: x + 0.16, y: 3.12, w: w - 0.3, h: 2.3, fontSize: 11, gap: 5 });
      label(s, 'Tyre effect', x + 0.18, 5.48, w - 0.36, C.amber);
      T(s, sea.effect, { x: x + 0.18, y: 5.74, w: w - 0.36, h: 0.98, fontSize: 11, color: C.muted }); }); }

  { const d = (y, c) => SE.degradation[y][c].median_fuel_corrected;
    const nRaces = SE_YEARS.map(y => `${y}: ${SE.races_used[y].length}`).join(', ');
    const s = slide('Rule changes and the tyre  ·  measured', 'What the eras did to degradation, in our own data', `Dry races outside the sealed holdout (${nRaces}); 2022 is not in our lap data`,
      `Source: deck_src/season_effects.py over the race lap files (feat2023/, feat2024/, feat2025/, feat/) and the race-derived reference slopes in out/tyreformer/prerace/predictions_A.csv; sealed weekends and wet races excluded. Degradation is the median race-derived slope per compound. The reference subtracts ${NOW_KG} kg of fuel in every season, so seasons before 2026 are corrected to a ${PRE_KG} kg start (+0.03 s/kg x ${PRE_KG - NOW_KG} kg / race laps). Raw medians S/M/H: ${SE_YEARS.map(y => `${y} ${COMPS.map(c => f3(SE.degradation[y][c].median)).join('/')}`).join('; ')}. Corrected: ${SE_YEARS.map(y => `${y} ${COMPS.map(c => f3(d(y, c))).join('/')}`).join('; ')}. Cases per compound: ${SE_YEARS.map(y => `${y} soft ${SE.degradation[y].SOFT.n}, medium ${SE.degradation[y].MEDIUM.n}, hard ${SE.degradation[y].HARD.n}`).join('; ')}. Stint length is the median completed stint ending in a pit stop; stops are pit-lane entries per driver finishing 90% of the distance. Each season races a different mix of circuits, so the fair comparison is the same circuit year on year (next slide).`);
    img(s, ASSETS + 'chart_deg_season.png', 0.6, 1.85, 6.0, 3.45, false);
    img(s, ASSETS + 'chart_stint_season.png', 6.73, 1.85, 6.0, 3.45, false);
    log(`Median race degradation, fuel-corrected ${SE_YEARS.map(y => COMPS.map(c => f3(d(y, c))).join('/')).join(' ')} | Median completed stint ${SE_YEARS.map(y => COMPS.map(c => SE.stint_length[y][c].median).join('/')).join(' ')}`);
    SE_YEARS.forEach((y, i) => { const st = SE.stops[y], x = 0.6 + i * 2.2; card(s, x, 5.45, 2.05, 1.35);
      T(s, y, { x: x + 0.15, y: 5.55, w: 1.8, h: 0.28, fontSize: 12, bold: true, color: C.muted });
      T(s, f2(st.mean), { x: x + 0.15, y: 5.83, w: 1.0, h: 0.5, fontSize: 26, bold: true });
      T(s, `stops per finisher · ${pct(st.one_stop_share)} one\u2011stop`, { x: x + 0.15, y: 6.33, w: 1.85, h: 0.42, fontSize: 10, color: C.muted }); });
    card(s, 9.4, 5.45, 3.33, 1.35);
    T(s, `2026 against 2025, fuel-corrected: soft ${f3(d('2026', 'SOFT'))} vs ${f3(d('2025', 'SOFT'))}, medium ${f3(d('2026', 'MEDIUM'))} vs ${f3(d('2025', 'MEDIUM'))}, hard ${f3(d('2026', 'HARD'))} vs ${f3(d('2025', 'HARD'))}. Calendars differ: same circuits next.`, { x: 9.58, y: 5.55, w: 3.0, h: 1.18, fontSize: 11, color: C.text }); }

  { const fu = REGS.fuel;
    const s = slide('Rule changes and the tyre  ·  fuel', 'Less fuel in 2026: the tyre shows through', fu.subtitle,
      `Facts: ${fu.facts.join('; ')}. Sources: ${fu.sources.join(' ')}. Our arithmetic, for a ${REF_LAPS}-lap race at ${FUEL_S_KG} s/kg (the lock's fuel cost): ${PRE_KG} kg burns off ${f3(fuelMask(PRE_KG))} s a lap, ${NOW_KG} kg ${f3(fuelMask(NOW_KG))} s. Same circuits 2025 to 2026 (deck_src/assets/season_effects.json): raw change in the race-derived slope ${range3(rawRange)}; with 2025 at 100 kg ${range3(corr100)}; at 110 kg ${range3(corr110)}. Circuits: ${COMPS.map(c => `${c.toLowerCase()} ${PAIR[c].circuits.join(', ')}`).join('; ')}. Three or four circuits per compound: indicative, not a season-wide estimate. Implication for Orb: the scorecard race reference subtracts ${NOW_KG} kg in every season, so slopes before 2026 read about ${f3(REF_BIAS)} s/lap low at a ${PRE_KG} kg start; the season charts in this deck are corrected, the scorecards are not yet.`);
    tile(s, 0.6, 1.95, 3.0, 1.6, `${PRE_KG} → ${NOW_KG} kg`, 'race fuel: about 100 kg in 2020; 70 kg is the 2026 target, not a rule', C.text, 30);
    tile(s, 0.6, 3.7, 3.0, 1.6, `${f3(fuelMask(PRE_KG))} → ${f3(fuelMask(NOW_KG))} s`, `gained per lap as fuel burns (${REF_LAPS}-lap race): less wear hidden`, C.teal, 24);
    tile(s, 0.6, 5.45, 3.0, 1.35, `${f2(fuelMask(PRE_KG) * 20)} → ${f2(fuelMask(NOW_KG) * 20)} s`, 'of tyre loss hidden over a 20-lap stint', C.text, 26);
    img(s, ASSETS + 'chart_fuel_pairs.png', 3.85, 1.9, 5.2, 4.95, false);
    log(`Same circuits, 2025 to 2026 | raw ${rawRange.map(f3).join('/')} | 100 kg ${corr100.map(f3).join('/')} | 110 kg ${corr110.map(f3).join('/')}`);
    card(s, 9.3, 1.95, 3.43, 2.55); label(s, 'What the fuel did', 9.5, 2.12, 3.0, C.amber);
    T(s, `On the same circuits degradation rose ${range3(rawRange)} s/lap per lap from 2025. Give 2025 its heavier start and ${SHARE_LO}% to ${SHARE_HI}% of that rise disappears. Pirelli also reports less tyre load from the lighter cars: the first 2026 races were one\u2011stops.`, { x: 9.5, y: 2.42, w: 3.05, h: 2.0, fontSize: 12, color: C.muted });
    card(s, 9.3, 4.65, 3.43, 2.15); label(s, 'What it means for Orb', 9.5, 4.82, 3.0, C.teal);
    T(s, `Our race reference subtracts ${NOW_KG} kg in every season, so pre-2026 slopes read about ${f3(REF_BIAS)} s/lap low. Next: fuel by season.`, { x: 9.5, y: 5.12, w: 3.05, h: 1.6, fontSize: 12, color: C.muted });
    if (SLIDE_NO !== 13) throw new Error(`the fuel slide is ${SLIDE_NO}; slide 2 points to slide 13`); }
} else {
  const s = slide('Rule changes and the tyre', 'PENDING: rule history not yet cited', null, null);
  T(s, 'test build only', { x: MX, y: 2, w: 6, h: 0.5, fontSize: 20, color: C.crit });
}

// ================================================================= 14 Madrid
{ const s = slide('Prospective test', 'Madrid: the frozen forecast', `${SESS.join(', ')} in; published ${ISSUED_HM} IST. Hashed before the race, verifiable after the event.`,
    `Madrid 2026 races on Sunday evening, after the event closes. The forecast was built from ${SESS.join(', ')} and frozen with a hash; nothing in it can change once the race is run. Sources: out/lock_v2.json pre_race_forecast.events.Madrid and the published out/forecast_Madrid_2026.json with its .sha256 sidecar; the build refuses to run if they disagree. Full digests: JSON ${FC_SHA}; PDF ${PDF_SHA}; sidecar ${SIDECAR_SHA}; lock v2 forecast_hash ${FORECAST_HASH}.`);
  img(s, SHOT('prerace'), 0.6, 1.95, 7.6, 7.6 / 2.667, true);
  card(s, 8.5, 1.95, 4.23, 2.85);
  const madRow = comp => { const c = MAD[comp]; return c ? [`${sgn(c.prediction, 3)} s/lap`, `${c.issued ? 'issued' : 'withheld, fallback applies'} · 90% band ${sgn(c.band90[0], 2)} to ${sgn(c.band90[1], 2)} · ${c.n_prac} clean laps`] : ['no curve', 'too few clean practice laps; not in the frozen forecast']; };
  ['SOFT', 'MEDIUM', 'HARD'].forEach((comp, i) => { const [v, d] = madRow(comp), y = 2.12 + i * 0.8; tyre(s, 8.7, y + 0.04, comp, 0.38); T(s, v, { x: 9.2, y, w: 3.4, h: 0.3, fontSize: 15, bold: true }); T(s, d, { x: 9.2, y: y + 0.3, w: 3.4, h: 0.45, fontSize: 10, color: C.muted }); });
  T(s, `Plan ${MAD2.strategy.plan} ${MAD2.strategy.stints.join('/')} · band-high plan ${MAD2.strategy.band_high_plan} · pit loss ${MAD2.strategy.pit_loss_s} s`, { x: 8.7, y: 4.5, w: 3.9, h: 0.26, fontSize: 11, color: C.text });
  label(s, 'Provenance', 0.6, 5.0, 4);
  [`forecast JSON  sha256 ${FC_SHA}`, `forecast PDF   sha256 ${PDF_SHA}`, `sidecar        sha256 ${SIDECAR_SHA}`, `lock v2 forecast_hash  ${FORECAST_HASH}`].forEach((t, i) => T(s, t, { x: 0.6, y: 5.3 + i * 0.3, w: CW, h: 0.26, fontFace: MONO, fontSize: 10, color: C.muted }));
  T(s, 'The race is scored after it is run, against this file, whatever it says.', { x: 0.6, y: 6.55, w: CW, h: 0.3, fontSize: 12, italic: true, color: C.mint }); }

// ================================================================= 15 product
{ const s = slide('The product', 'Five destinations, two modes, one locked core', 'Streamlit dashboard, runs offline; every number traces to the lock, a hashed sidecar or a labelled placeholder',
    `The dashboard opens on an overview with the two modes and the Madrid forecast. Live Predictor makes the call during a race and may only see laps already run; Ghost Strategy audits afterwards. A guided demo walks a newcomer through five steps on prepared races. Consistency probe (evaluation/red_team/consistency_probe_report.json, ${CONS.generated_at}): ${CONS.summary.routes} routes, ${nice(CONS.summary.numbers)} numbers compared with the lock, ${CONS.summary.mismatches} mismatches. C6 rehearsal: ${C6_REH[0]} s, ${C6_REH[1]}/${C6_REH[2]} steps (checkpoints/C6/checkpoint.md).`);
  img(s, SHOT('landing'), 0.6, 1.95, 7.5, 7.5 / 2.077, true);
  [['Overview', 'the two modes and the frozen Madrid forecast'], ['Forecast', 'pre-race curves, bands and the suggested plan'], ['Live Predictor', 'lap-by-lap tyre state and the ranked pit call'], ['Ghost Strategy', 'change the stop, replay it on the 3D Race Twin'], ['Guided demo', 'five steps from a lap to a tyre decision']]
    .forEach(([h, d], i) => { const y = 1.95 + i * 0.73; dot(s, 8.45, y + 0.04, i + 1, C.teal, 0.34); T(s, h, { x: 8.95, y, w: 3.8, h: 0.3, fontSize: 15, bold: true }); T(s, d, { x: 8.95, y: y + 0.3, w: 3.8, h: 0.34, fontSize: 12, color: C.muted }); });
  T(s, 'More tools: Decision board · Driver feedback · Validation · Generalisation', { x: 8.45, y: 5.62, w: 4.28, h: 0.3, fontSize: 11, color: C.dim });
  [[`${CONS.summary.routes} routes · ${nice(CONS.summary.numbers)} numbers`, `checked against the lock, ${CONS.summary.mismatches} mismatches`], [`${C6_REH[1]}/${C6_REH[2]} rehearsal steps`, `five-minute run in ${C6_REH[0]} s, no external requests`], ['Offline', 'recorded races replay locally; no CDN, no live feed needed']]
    .forEach(([b, l], i) => { const x = 0.6 + i * 2.55; card(s, x, 5.95, 2.4, 0.85); T(s, b, { x: x + 0.15, y: 6.02, w: 2.15, h: 0.3, fontSize: 12, bold: true, color: C.mint }); T(s, l, { x: x + 0.15, y: 6.33, w: 2.15, h: 0.42, fontSize: 10, color: C.muted }); }); }

// ================================================================= 16 live
{ const s = slide('Live Predictor', 'The call during the race, from laps already run', 'Monza 2026, Norris, lap 30 of 53, recorded replay',
    `Kalman estimator of tyre intercept and slope per stint, started from the frozen pre-race prior; it may only read laps up to the replay cursor (asserted in code and in the leakage audit). Scorecard: out/validation/live_scorecard.json, prefix evaluation over ${LS.races.join(', ')}: next-lap error ${f3(LP('next1_mae'))} s against ${f3(LP('next1_mae_prior_only'))} s for the prior alone (${nice(LS.pooled.next1_mae.n)} windows); ${pct(LP('coverage90_next1'))} of next laps inside the 90% band; median alert lead ${f1(LP('aw_lead_laps_median'))} laps; ${f2(LP('aw_false_alert_episodes_per_stint'))} false alert episodes per stint; the recommendation changes on ${pct(LP('recommendation_change_rate'))} of laps. Weakness: cliff Brier ${f3(LP('cliff5_brier'))} against ${f3(LP('cliff5_brier_climatology'))} for the base rate, worse than a constant; the learned model on slide 18 addresses it. The driver-feedback ablation has not run: no feedback event has been recorded yet.`);
  img(s, SHOT('live'), 0.6, 1.95, 7.7, 7.7 / 1.861, true);
  const st = [[f3(LP('next1_mae')) + ' s', `next-lap error, against ${f3(LP('next1_mae_prior_only'))} s for the prior alone`, C.teal], [pct(LP('coverage90_next1')), 'of next laps inside the 90% band', C.text], [f1(LP('aw_lead_laps_median')) + ' laps', 'median warning before a detected cliff', C.text], [f2(LP('aw_false_alert_episodes_per_stint')), 'false alert episodes per stint', C.text]];
  st.forEach(([b, l, c], i) => tile(s, 8.6 + (i % 2) * 2.12, 1.95 + Math.floor(i / 2) * 1.62, 2.0, 1.5, b, l, c, 24));
  card(s, 8.6, 5.25, 4.13, 1.55); label(s, 'Honest limit', 8.8, 5.4, 3.7, C.crit);
  T(s, `Cliff warnings are worse than a constant base rate (Brier ${f3(LP('cliff5_brier'))} against ${f3(LP('cliff5_brier_climatology'))}). Scored on ${WORDS[LS.races.length]} replayed races.`, { x: 8.8, y: 5.68, w: 3.75, h: 1.05, fontSize: 12, color: C.muted }); }

// ================================================================= 17 ghost
{ const s = slide('Ghost Strategy', 'Change the stop, see the difference, on the real circuit', 'Monza 2026, Norris: a new medium after lap 24, replayed against the recorded race',
    `Ghost Strategy replays the driver's own laps with a different tyre plan: a single-car tyre and pit-stop simulation on reference curves that exclude this driver; rivals do not react, and it is never a position forecast. The 3D Race Twin is a local software renderer on the recorded XY positions; road width, car size and elevation are schematic. Prepared simulations on disk: ${SC_REF.length} on the historical race reference and ${SC_PRE.length} on the pre-race curve, ${SC_REF.length + SC_PRE.length} in all, across ${SIM_RACES.length} races (${SIM_RACES.join(', ')}); each passed its identity check before it was written (evaluation/red_team/identity_checks_report.json, ${ID.generated_at}: ${ID.summary.passed} passed, ${ID.summary.failed} failed). Races whose reconstruction cannot be reproduced are refused on screen rather than borrowed from another race. Hidden-stop response test (out/validation/ghost_scorecard.json): hide the laps after a real stop and predict them; next-lap error ${f2(HS.next1_mae)} s against ${f2(HS.next1_mae_naive)} s naive over ${nice(HS.n_cases)} stops in ${HS.n_weekends} weekends.`);
  img(s, SHOT('ghost_change'), 0.6, 1.95, 7.7, 7.7 / 6.836, true);
  img(s, SHOT('ghost'), 0.6, 3.22, 7.7, 7.7 / 2.435, true);
  T(s, 'Actual = recorded car · Ghost = changed plan. Modelled tyre time, not rival positions.', { x: 0.6, y: 6.52, w: 7.7, h: 0.3, fontSize: 11, color: C.dim });
  tile(s, 8.6, 1.95, 4.13, 1.5, nice(SC_REF.length + SC_PRE.length), `prepared simulations across ${WORDS[SIM_RACES.length] || SIM_RACES.length} races, historical and pre-race curves`, C.teal, 30);
  tile(s, 8.6, 3.6, 4.13, 1.5, `${ID.summary.passed} / ${ID.summary.failed}`, 'identity checks passed / failed; a failing scenario is refused, never written', C.text, 30);
  tile(s, 8.6, 5.25, 4.13, 1.55, `${f2(HS.next1_mae)} vs ${f2(HS.next1_mae_naive)} s`, `next lap after a hidden real stop, against naive; ${nice(HS.n_cases)} stops`, C.text, 26); }

// ================================================================= 18 TyreFormer
{ const d1 = TF26.next1, d5 = TF26.next5, c5 = TF26.cum5, sh1 = TFSH.next1, sh5 = TFSH.next5, cl = TF26.cliff5, per = TFFIG.ladder_2026['current pace (persistence)'];
  const s = slide('The learned model', 'Orb TyreFormer: a learned forecast, scored head to head', 'Transformer over the lap sequence plus gradient-boosted experts, against the Orb v1 live estimator on identical origins',
    `Orb TyreFormer is an ensemble of a transformer over each stint's lap sequence (distribution, cumulative and cliff heads) and gradient-boosted median experts, with conformal 90% bands (out/tyreformer/EVALUATION.md, MODEL_CARD.md). Data: ${nice(TF_ORIGINS)} forecast origins over ${TF_WEEKENDS} weekends of 2023 to 2026 race and sprint stints (${nice(TF_DEV_ORIGINS)} from 2023 to 2025 for training and selection, ${nice(TF_2026_ORIGINS)} from 2026 for testing); sealed weekends are refused by the data loader. Frozen ${TF_FREEZE.frozen_at.slice(11, 16)} IST before any sealed weekend was loaded (tyreformer/FREEZE.json). Every 2026 race, deployment protocol (2023 to 2025 plus earlier 2026 races), identical origins: next lap ${f3(d1.orb_v1_estimator)} to ${f3(d1.tyreformer)} s, better on ${d1.weekends_tyreformer_better} of ${d1.weekends} races; five laps ahead ${f3(d5.orb_v1_estimator)} to ${f3(d5.tyreformer)} s; five-lap cumulative ${f3(c5.orb_v1_estimator)} to ${f3(c5.tyreformer)} s. For reference, current pace alone scores ${f3(per)} s at the next lap, so the estimator adds little there. Sealed holdout, aggregate only (out/tyreformer/sealed_holdout_aggregate.json): next lap ${f3(sh1.orb_v1_estimator)} to ${f3(sh1.tyreformer)} s on ${sh1.weekends_tyreformer_better} of ${sh1.weekends} weekends; five laps ahead ${f3(sh5.orb_v1_estimator)} to ${f3(sh5.tyreformer)} s; next-lap band coverage ${pct(sh1.coverage90_tyreformer)}. Limit: the cliff probability is calibrated but barely beats a constant base rate (Brier ${f3(cl.tyreformer_brier)} against ${f3(cl.climatology_train_rate)} on 2026). Not the estimator of record and not yet wired into the dashboard.`);
  img(s, OUT + 'tyreformer/fig_tyreformer_horizon.png', 0.6, 1.95, 7.0, 7.0 / 1.739, false);
  T(s, `${nice(TF_DEV_ORIGINS)} forecast origins from 2023 to 2025 for training and selection, ${nice(TF_2026_ORIGINS)} from 2026 for testing. Frozen before any sealed weekend was opened.`, { x: 0.6, y: 6.05, w: 7.0, h: 0.5, fontSize: 12, color: C.muted });
  const cmp = (x, y, w, h, a, b, lab) => { card(s, x, y, w, h); T(s, [{ text: f3(a), options: { color: C.dim } }, { text: '  →  ', options: { color: C.dim } }, { text: f3(b) + ' s', options: { color: C.mint } }], { x: x + 0.2, y: y + 0.12, w: w - 0.4, h: 0.55, fontSize: 26, bold: true }); T(s, lab, { x: x + 0.2, y: y + 0.7, w: w - 0.4, h: h - 0.8, fontSize: 12, color: C.muted }); };
  cmp(7.9, 1.95, 4.83, 1.3, d1.orb_v1_estimator, d1.tyreformer, `next-lap error, every 2026 race, deployment protocol, identical origins; better on ${d1.weekends_tyreformer_better} of ${d1.weekends} races`);
  cmp(7.9, 3.38, 4.83, 1.3, sh1.orb_v1_estimator, sh1.tyreformer, `next-lap error, sealed holdout, aggregate only; better on ${sh1.weekends_tyreformer_better} of ${sh1.weekends} weekends`);
  cmp(7.9, 4.81, 4.83, 1.1, d5.orb_v1_estimator, d5.tyreformer, 'five laps ahead, every 2026 race');
  card(s, 7.9, 6.04, 4.83, 0.78);
  T(s, `Limit: cliff risk is calibrated but barely beats the base rate (Brier ${f3(cl.tyreformer_brier)} vs ${f3(cl.climatology_train_rate)}). Not yet in the dashboard.`, { x: 8.1, y: 6.1, w: 4.45, h: 0.66, fontSize: 11, color: C.muted }); }

// ================================================================= 19 honest
{ const s = slide('Validation discipline', 'How we kept ourselves honest', 'Splits fixed before tuning, freezes before reveals, and automated gates at every checkpoint',
    `Sealed holdout: ${MANIFEST.holdout_count} weekends chosen by rule (${MANIFEST.selection_rule.split(';')[0]}), hashed at ${MANIFEST.selected_at}, prohibited for tuning, opened once after the freeze and quoted only as "sealed holdout, aggregate only". Checkpoints (checkpoints/C*/checkpoint.json): ${CHECKPOINTS.map(c => `${c[0]} ${c[1]} ${c[2]}`).join('; ')}. At C6 the suite ran ${C6_PYTEST[0]} passed, ${C6_PYTEST[1]} skipped, ${C6_PYTEST[2]} xfailed, and the release gate ${C6_GATE[0]}/${C6_GATE[1]}. Leakage audit (${LEAK.generated_at}): ${LEAK.status}, ${Object.keys(LEAK.checks).length} checks. Identity checks (${ID.generated_at}): ${ID.summary.passed} passed, ${ID.summary.failed} failed. Consistency probe (${CONS.generated_at}): ${nice(CONS.summary.numbers)} numbers, ${CONS.summary.mismatches} mismatches. These records describe the commits they ran on; later uncommitted work is certified only when its own gate runs.`);
  [['Development pool', `${DEV.n_weekends} weekends of 2023 to 2026, each forecast with itself left out`, C.muted], ['Rolling origin', 'each 2026 race forecast only from the races before it', C.muted], ['Sealed holdout', `${MANIFEST.holdout_count} whole weekends picked by a fixed rule before any tuning; opened once, aggregate only`, C.amber], ['Prospective', 'Madrid, hashed before the race and scored after it', C.teal]]
    .forEach(([h, d, c], i) => { const y = 1.95 + i * 1.22; card(s, 0.6, y, 5.9, 1.08); T(s, h, { x: 0.82, y: y + 0.12, w: 5.5, h: 0.32, fontSize: 15, bold: true, color: c }); T(s, d, { x: 0.82, y: y + 0.46, w: 5.5, h: 0.55, fontSize: 12, color: C.muted }); });
  label(s, 'Checkpoints, 12 to 13 September', 6.8, 1.95, 5.9);
  CHECKPOINTS.forEach(([c, dec], i) => { const x = 6.8 + i * 0.85; s.addShape(pres.shapes.OVAL, { x: x + 0.12, y: 2.3, w: 0.5, h: 0.5, fill: { color: dec === 'GO' ? C.teal : C.crit }, line: { color: C.bg, width: 0 } }); T(s, c, { x: x + 0.12, y: 2.3, w: 0.5, h: 0.5, fontSize: 11, bold: true, color: C.bg, align: 'center', valign: 'middle' }); T(s, dec, { x, y: 2.86, w: 0.74, h: 0.26, fontSize: 10, bold: true, color: C.muted, align: 'center' }); });
  const gates = [[`${LEAK.status}`, 'leakage audit: the live path cannot import race outcomes'], [`${ID.summary.passed} / ${ID.summary.failed}`, 'counterfactual identity checks passed / failed'], [`${CONS.summary.mismatches} of ${nice(CONS.summary.numbers)}`, 'on-screen numbers disagreeing with the lock'], [`${C6_GATE[0]}/${C6_GATE[1]}`, 'release gate at C6: offline, routes, timing'], [`${C6_PYTEST[0]}`, `tests passed at C6 (${C6_PYTEST[1]} skipped, ${C6_PYTEST[2]} xfailed)`], ['Frozen', 'Orb v1 rules and Orb TyreFormer each frozen before their sealed runs']];
  gates.forEach(([b, l], i) => tile(s, 6.8 + (i % 3) * 2.02, 3.35 + Math.floor(i / 3) * 1.75, 1.9, 1.6, b, l, i === 5 ? C.amber : C.mint, 22)); }

// ================================================================= 20 models by name
{ const s = slide('Under the hood', 'Models and methods, by name', 'What each component is, and how it is validated',
    'Core: stint fixed-effects OLS with physics priors. Transfer: leave-one-weekend-out median ratio with an agreement rule. Gate: selective prediction with a nonparametric fallback. Live: Kalman filter on intercept and slope with fixed regime rules. Counterfactual: iso-context paired replay. Learned: Orb TyreFormer (transformer plus gradient-boosted experts, conformal bands) and a robust-regression transfer model, both second opinions. Ablation: CfC continuous-time cell, reported not deployed. Stack: Python 3.12, NumPy, pandas, statsmodels, scikit-learn, PyTorch, FastF1, Streamlit, Plotly, a local canvas 3D renderer.');
  table(s, [['Component', 'Model or method', 'Validation'],
    ['Degradation curve', 'Stint fixed-effects regression; fuel prior and track evolution removed (FastF1 public timing, 3.7 Hz traces)', 'Weekend holdout; sensitivity sweep'],
    ['Friday to Sunday', 'Per-compound median ratio, weekend left out, agreement rule', `${V2.n_compound_weekends} cases 2026; ${DEV.n_compound_weekends} across 2023 to 2026; sealed holdout`],
    ['Abstention', 'Selective prediction with a leave-one-out median fallback', 'Risk-coverage scorecard'],
    ['Tyre demand index', 'Energy per lap from speed, path curvature and speed changes', 'Feed-quality gates; practice/race scale'],
    ['Strategy', 'Exact one- and two-stop enumeration; posterior Monte Carlo on the live board', `${N_SC} replayed races; regret over ${REG.plans.orb.n} weekends`],
    ['Live estimator', 'Kalman filter on intercept and slope; pre-race prior; pit resets', 'Prefix evaluation: next 1, 3, 5 laps; Brier; alert lead'],
    ['Counterfactual', 'Iso-context paired replay on the recorded safety-car schedule', 'Identity checks; hidden-stop response'],
    ['Orb TyreFormer', 'Transformer (distribution, cumulative, cliff heads) + gradient-boosted medians; conformal bands; PyTorch', 'Weekend-grouped CV; every 2026 race; sealed holdout'],
    ['Learned transfer', 'Robust (Huber) regression on practice features, conformal band', 'Leave-one-weekend-out 2023 to 2026; 2026 temporal test'],
    ['Neural ablation', 'CfC continuous-time cell (Hasani et al.), ncps / PyTorch', 'Stint-grouped folds; not adopted'],
    ['Product', 'Streamlit + Plotly; local canvas 3D Race Twin', 'Consistency probe; release gate; rehearsal']],
    0.6, 1.95, 12.0, [2.05, 6.0, 3.95], 11, 0.4); }

// ================================================================= 21 real data + scaling
{ const s = slide('Real-world viability', 'What team data would add, and where it scales', 'Public prototype today; a team adapter is where measurements replace assumptions',
    'The private feeds a team already has would replace our stated assumptions with measurements and tighten the same model. The method needs only lap times, tyre age, compound and flags, so it runs in a degraded mode on any series with public timing; with telemetry it also measures the push. Every scaling claim here still requires validation in that series.');
  table(s, [['Private data (team only)', 'What it would buy'], ['Fuel mass per lap', 'retires the largest stated assumption, season by season'], ['Tyre pressures and temperatures', 'separates graining, blistering and the cliff; sharper bands and earlier alerts, to be validated'], ['Tread depth after runs', 'the only route to a physical wear number; public mode never shows tread'], ['Engine modes, driver instructions', 'the push becomes measured instead of inferred'], ['Wheel speeds, steering, brake temperatures', 'actual slip and the thermal path']], 0.6, 1.95, 6.4, [2.4, 4.0], 13, 0.8);
  card(s, 7.3, 1.95, 5.43, 4.85); label(s, 'Where it scales', 7.55, 2.12, 5.0, C.teal);
  [['Any Grand Prix, from free data', 'public timing and position traces; one command rebuilds the lock from a fresh clone'], ['Junior series with public timing only', 'lap times, age, compound and flags suffice; more is withheld and bands widen'], ['Race engineers on a laptop', 'runs offline; no cloud, no CDN, a five-minute guided path'], ['Beyond racing: wear from biased samples', 'the pattern (clean the confounders, learn the transfer, refuse weak signal, audit) fits any wear forecast made from noisy early data']]
    .forEach(([h, d], i) => { const y = 2.5 + i * 1.05; dot(s, 7.55, y + 0.03, i + 1, C.teal, 0.34); T(s, h, { x: 8.05, y, w: 4.5, h: 0.3, fontSize: 14, bold: true }); T(s, d, { x: 8.05, y: y + 0.32, w: 4.5, h: 0.65, fontSize: 12, color: C.muted }); }); }

// ================================================================= 22 field
{ const s = slide('Versus the field', 'The public repositories on this brief', 'Checked on 12 September 2026',
    'The field, from a public sweep on the morning of 12 September. PITWALL is the only rival we reviewed with comparable rigour and it concluded the practice curve cannot be delivered; the rest are one weekend, synthetic data, or simulators without a scorecard. We deliver the literal brief at season scale, with abstention, a live forecast and a scored audit.');
  table(s, [['Entry', 'Approach', 'Validation', 'Where we stand'], ['PITWALL', 'Same cleaning idea, 12 events; concluded practice curves do not transfer; predicts the value of a fresh tyre', 'Leave-one-event-out on pit-stop deltas', `We deliver the curve the brief asks for; transfer holds at compound-weekend level in 2026 (r ${f2(S26.calibration.r)}); we say where it weakens`], ['GripTrace', 'One weekend, 2023 Bahrain, soft only; careful; no fuel model', 'Race held out once', `${DEV.n_weekends} weekends, three compounds, a sealed holdout`], ['TyreIQ', 'Gradient boosting on synthetic Bahrain data', 'In-sample on synthetic data', 'Scored on real races the model never saw'], ['Dr.Tyre, TrackShift AI', 'Pipelines with simulators and a voice engineer; constants or synthetic toggles', 'None held out', 'Every number on our screens traces to the lock, a hashed sidecar or a labelled placeholder'], ['TIREX, others', 'Kalman plan (backend only), a negative-result study, skeletons', 'Planned or none', 'Results, freezes and gates']], 0.6, 1.95, CW, [1.9, 4.1, 2.4, 3.73], 11, 0.62);
  card(s, 0.6, 5.15, CW, 1.1, C.raised);
  T(s, 'Among the public repositories we reviewed, we did not find another entry that scores a Friday curve against Sunday across seasons, withholds when it should, removes the driver’s push and forecasts a live weekend.', { x: 0.85, y: 5.3, w: CW - 0.5, h: 0.8, fontSize: 15, italic: true, color: C.mint, valign: 'middle' }); }

// ================================================================= 23 questions
const JURY_QA = [
  ['What did you build here?', 'Three past seasons and seven more 2026 weekends, the gate, the push diagnostic, the dashboard with its 3D Race Twin and guided demo, the sealed holdout and Orb TyreFormer. The estimator was disclosed pre-work.'],
  ['Where is the AI?', `A transfer factor learned across weekends; Orb TyreFormer, a transformer and boosted ensemble beating our live estimator on every 2026 race (${TF26.next1.weekends_tyreformer_better} of ${TF26.next1.weekends}); a CfC network tested and set aside.`],
  ['Does the Friday curve really transfer?', `In 2026, yes: r ${f2(S26.calibration.r)} over ${S26.n_compound_weekends} held-out cases. Across 2023 to 2025 it is weaker (r ${f2(DEV.calibration.r)}), so we show that and keep a learned transfer model as a second opinion.`],
  ['What breaks it?', 'Green tracks and new circuits (the gate withholds, the fallback answers), degraded feeds (refused), wet sessions (excluded), and a new rule era, which needs its own fuel and priors.'],
  ['Where could the race leak into the forecast?', 'Nowhere we left open: factors and fallback come from other weekends, the live path reads only laps already run (audited), and only the scorecard sees the race.'],
  ['Madrid races after we close. What do you show?', `Recorded races replayed lap by lap, and a Madrid forecast hashed before the race (sha256 ${FC_SHA.slice(0, 12)}, ${ISSUED_HM} IST), verifiable after it.`],
  ['Did the 2026 rules change degradation?', FUEL_QA],
  ['Would this work in Formula 2, without telemetry?', 'Yes, in a degraded mode: lap times, age, compound and flags drive the estimator; more is withheld and bands widen. Accuracy there requires validation.']];
{ const s = slide('Questions', `${WORDS[JURY_QA.length][0].toUpperCase() + WORDS[JURY_QA.length].slice(1)} questions we expect, with our one-line answers`, null,
    `${JURY_QA.length} questions we expect, each with the answer we will give. Longer written answers are in The Case and the talk track.`);
  JURY_QA.forEach(([q, a], i) => { const col = i % 2, row = Math.floor(i / 2), x = 0.6 + col * 6.17, y = 1.45 + row * 1.37; dot(s, x, y + 0.02, i + 1, col ? C.teal : C.amber, 0.34);
    T(s, q, { x: x + 0.48, y, w: 5.45, h: 0.3, fontSize: 14, bold: true }); T(s, a, { x: x + 0.48, y: y + 0.33, w: 5.45, h: 0.95, fontSize: 12, color: C.muted }); }); }

// ================================================================= 24 built when + next
{ const s = slide('Disclosure and next steps', 'What was built when, and what comes next', null,
    'Disclosure first. The estimator and the six-weekend validation were pre-work disclosed in the idea round. Everything else was built at Plaksha between 12 and 13 September. Next: wire Orb TyreFormer into the Live Predictor as a labelled second opinion, score Madrid after the race, give each season its own fuel load in the reference, learn the abstention gate, and build the team-data adapter.');
  const cols = [['Disclosed pre-work', '4 to 5 September', C.muted, ['Stint fixed-effects estimator with the fuel prior and evolution', 'Six-weekend validation and the first transfer factors', 'Hungary and Austria strategy replay']],
    ['Built at Plaksha', '12 to 13 September', C.teal, ['Seven more 2026 weekends and three past seasons', 'Gate, fallback, push diagnostic, replay scoring', 'Lock contract, sealed holdout, checkpoints C0 to C6', 'Live Predictor, Ghost Strategy, 3D Race Twin, guided demo', 'Orb TyreFormer and the learned transfer model', 'Rule-era analysis, 2022 to 2026']],
    ['Next', 'after the event', C.amber, ['TyreFormer on the Live Predictor as a labelled second opinion', 'Score the Madrid forecast against the race', 'Season-specific fuel load in the race reference', 'A learned, calibrated abstention gate', 'Team-data adapter: fuel, pressures, temperatures']]];
  cols.forEach(([h, when, c, items], i) => { const x = 0.6 + i * 4.11; card(s, x, 1.5, 3.91, 4.55); T(s, h, { x: x + 0.25, y: 1.68, w: 3.4, h: 0.4, fontSize: 20, bold: true, color: c }); T(s, when, { x: x + 0.25, y: 2.1, w: 3.4, h: 0.3, fontSize: 12, color: C.muted });
    bullets(s, items, { x: x + 0.25, y: 2.6, w: 3.45, h: 3.35, fontSize: 13, gap: 8, dotColor: c }); });
  T(s, 'Friday lies twice. Orb v1 corrects one lie, learns the other, and says so when it cannot tell.', { x: 0.6, y: 6.3, w: CW, h: 0.45, fontSize: 17, italic: true, color: C.mint }); }

// ---------------------------------------------------------------- claim guard: the red team's blocking patterns, per slide
function claimGuard() {
  const map = readJSON(PROTO + 'evaluation/red_team/claim_evidence_map.json');
  const blocking = map.claims.filter(c => ['mismatch', 'exceeds_evidence', 'unverifiable'].includes(c.verdict) && (c.search_in || []).includes('deck'));
  const wording = [['ground truth', /ground[\s-]truth/i, null], ['true degradation', /\btrue degradation\b/i, null], ['tread', /\btread\b/i, /private|team[\s-]only|team data|missing channel|never|no tread|not (?:shown|displayed)/i],
    ['observed race time saved', /observed race[\s-]?time saved|race time saved/i, /never|not/i], ['finishing position', /finish(?:ing)? position/i, /frozen[\s_-]field|only in frozen|never|not simulated|no position/i],
    ['novelty', /no published method|nobody else|no one else|no[\s-]one else|first (?:and only|to deliver)|only (?:system|entry|team) (?:that|to)/i, /public methods we reviewed|we did not find|in the (?:public )?(?:methods|repositories) we reviewed|checked \d+ september|public repositories/i],
    ['energy price constant', /(?:price of lap time|energy price|per megajoule|s\/MJ|s per MJ)[^.]{0,120}(?:\bconstant\b|the same|identical|to two decimals)/i, /consistent scale|tight at|within/i], ['any weather', /works under any weather|under any weather/i, /never|not/i],
    ['every number measured', /every number on (?:our|the) screens? is measured and scored|computes nothing itself/i, null]];
  const problems = [];
  Object.entries(TEXT_BY_SLIDE).forEach(([n, texts]) => { const txt = texts.join('\n');
    blocking.forEach(c => { let re; try { re = new RegExp(c.pattern, 'i'); } catch (e) { return; } const m = txt.match(re); if (!m) return;
      const q = c.qualified_by || [], dq = c.disqualified_by || [];
      if (q.length && q.every(p => new RegExp(p, 'i').test(txt)) && !dq.some(p => new RegExp(p, 'i').test(txt))) return;
      problems.push(`slide ${n}: "${m[0]}" matches blocked claim ${c.id} (${c.verdict})`); });
    wording.forEach(([id, re, allowed]) => { const m = txt.match(re); if (m && !(allowed && allowed.test(txt))) problems.push(`slide ${n}: wording rule ${id}: "${m[0]}"`); }); });
  return problems;
}

async function writeDeck() {
  const problems = claimGuard();
  if (FIT.length) console.log('text-fit warnings:\n  ' + FIT.join('\n  '));
  if (problems.length) throw new Error('claim guard:\n  ' + problems.join('\n  '));
  await pres.writeFile({ fileName: FILE });
  // PptxGenJS emits unused slide-master content-type overrides: remove only orphan metadata, never a referenced part
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(fs.readFileSync(FILE));
  const relations = (await Promise.all(Object.keys(zip.files).filter(n => n.endsWith('.rels')).map(n => zip.file(n).async('string')))).join('\n');
  const contentTypes = await zip.file('[Content_Types].xml').async('string');
  let removed = 0;
  const cleaned = contentTypes.replace(/<Override\b[^>]*PartName="(\/ppt\/slideMasters\/[^"]+)"[^>]*\/>/g, (entry, part) => {
    if (zip.file(part.slice(1))) return entry;
    if (relations.includes(part.split('/').pop())) throw new Error(`Missing referenced master ${part}`);
    removed += 1; return '';
  });
  if (removed) { zip.file('[Content_Types].xml', cleaned); fs.writeFileSync(FILE, await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' })); }
  console.log(`written ${FILE}; ${pres._slides.length} slides; claim guard clean; ${FIT.length} fit warnings; removed ${removed} unused master entries`);
}
writeDeck().catch(error => { console.error(error.message || error); process.exitCode = 1; });

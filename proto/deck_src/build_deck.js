const pptxgen = require('pptxgenjs');
const pres = new pptxgen(); pres.layout = 'LAYOUT_16x9'; pres.title = 'Orb v1 mentor briefing'; pres.author = 'Team Orb v1';
const OUT = require('path').resolve(__dirname, '../out') + '/';
const BG = '0B0E13', SURF = '161A20', LINE = '2B3038', INK = 'ECEDEF', MUTED = '9AA1AA', GOLD = 'F2C230', RED = 'E10600', SLATE = '8FB3D9', TEAL = '39D0C3', CRIT = 'F16464';
const F = 'Calibri';
function base(notes) { const s = pres.addSlide(); s.background = { color: BG }; if (notes) s.addNotes(notes); s.addText('ORB V1  ·  TrackShift 2026  ·  Tyre Degradation Intelligence', { x: 0.5, y: 5.2, w: 6, h: 0.3, fontFace: F, fontSize: 9, color: MUTED, isTextBox: true, margin: 0 }); return s; }
// the title box is 9 x 0.6 in and the subtitle sits at 0.88 in, so a title that wraps to two lines at 28 pt would run into it.
// About 50 characters fit on one line at 28 pt, 58 at 24 pt: shrink the type instead of overlapping (no renderer on this machine to eyeball it).
function titleSize(t) { return t.length <= 48 ? 28 : (t.length <= 56 ? 24 : (t.length <= 64 ? 21 : 19)); }
function title(s, t, sub) { s.addText(t, { x: 0.5, y: 0.3, w: 9, h: 0.6, fontFace: F, fontSize: titleSize(t), bold: true, color: INK, isTextBox: true, margin: 0 }); if (sub) s.addText(sub, { x: 0.5, y: 0.88, w: 9, h: 0.35, fontFace: F, fontSize: 13, color: MUTED, isTextBox: true, margin: 0 }); }
function card(s, x, y, w, h, opts) { s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: (opts && opts.fill) || SURF }, line: { color: LINE, width: 0.75 }, rectRadius: 0.08 }); }
function num(s, x, y, n, color) { s.addShape(pres.shapes.OVAL, { x, y, w: 0.34, h: 0.34, fill: { color: color || GOLD }, line: { color: color || GOLD, width: 0 } }); s.addText(String(n), { x, y, w: 0.34, h: 0.34, fontFace: F, fontSize: 12, bold: true, color: BG, align: 'center', valign: 'middle', isTextBox: true, margin: 0 }); }
function bullets(s, items, x, y, w, h, size) { s.addText(items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1, paraSpaceAfter: 4 } })), { x, y, w, h, fontFace: F, fontSize: size || 12, color: INK, valign: 'top', isTextBox: true, margin: 0 }); }
// a stat value longer than its slot used to overflow sideways into the next stat (e.g. '0.016 to 0.030' at 40 pt needs 3.9 in):
// size it to the slot on the same 0.47-em model, never below 20 pt.
function fitSize(t, w, max, min) { return Math.max(min, Math.min(max, Math.floor((w - 0.2) * 72 / (String(t).length * 0.47)))); }
function statSize(big, w) { return fitSize(big, w, 40, 20); }
function stat(s, x, y, w, big, label, color) { s.addText(big, { x, y, w, h: 0.75, fontFace: F, fontSize: statSize(big, w), bold: true, color: color || INK, isTextBox: true, margin: 0 }); s.addText(label, { x, y: y + 0.72, w, h: 0.5, fontFace: F, fontSize: 11, color: MUTED, isTextBox: true, margin: 0, valign: 'top' }); }
function table(s, rows, x, y, w, colW, size) { const data = rows.map((r, i) => r.map(c => ({ text: String(c), options: { bold: i === 0, color: i === 0 ? INK : INK, fill: { color: i === 0 ? '20252D' : SURF }, fontFace: F, fontSize: size || 11, valign: 'middle' } }))); s.addTable(data, { x, y, w, colW, border: { type: 'solid', color: LINE, pt: 0.5 }, margin: 0.05 }); }
const img = (s, name, x, y, w, h) => s.addImage({ path: OUT + name, x, y, w, h });

// ---- claim support read from the lock (red-team claim map, 12 Sep): every quoted figure below is derived here, not typed ----
const fs = require('fs');
const LOCK = JSON.parse(fs.readFileSync(OUT + 'lock.json', 'utf8').replace(/([:\[,])\s*-?(?:NaN|Infinity)\b/g, '$1null'));   // the lock is written by Python json.dump, which emits bare NaN
const LOCK2 = JSON.parse(fs.readFileSync(OUT + 'lock_v2.json', 'utf8'));
const MAD2 = LOCK2.pre_race_forecast.events.Madrid;
const ROWS = LOCK.validation_rows, WH = ROWS.filter(r => !r.issued), ISS = ROWS.filter(r => r.issued);
const median = a => { const s = [...a].sort((x, y) => x - y), n = s.length; return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; };
const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
const sgn = (v, d) => (v < 0 ? '−' : '+') + Math.abs(v).toFixed(d);   // typographic minus, as elsewhere on the slides
const pct = v => `${Math.round(v * 100)}%`;
const WOBS = WH.map(r => r.obs), NWH = WH.length;
const WH_MED = median(WOBS), WH_LT06 = WOBS.filter(o => o < 0.06).length, WH_COVER = WH.filter(r => r.lo <= r.obs && r.obs <= r.hi).length;
const WH_FB = mean(WH.map(r => Math.abs(r.err_cs))), WH_NV = mean(WH.map(r => Math.abs(r.err_naive)));
const WH_TXT = `withheld compounds degraded at a median ${WH_MED.toFixed(3)} s/lap in the race (range ${sgn(Math.min(...WOBS), 3)} to ${sgn(Math.max(...WOBS), 3)}); ${WH_LT06} of ${NWH} below 0.06 s/lap; the fallback band covered ${WH_COVER} of ${NWH}`;
const WH_CAP = WH_TXT[0].toUpperCase() + WH_TXT.slice(1);
const WH_SLIDE = `Withheld compounds degraded at a median ${WH_MED.toFixed(3)} s/lap in the race; ${WH_LT06} of ${NWH} below 0.06 s/lap; the fallback band covered ${WH_COVER} of ${NWH}`;
const WH_SHORT = `withheld compounds degraded at a median ${WH_MED.toFixed(3)} s/lap in the race, ${WH_LT06} of ${NWH} below 0.06, band covered ${WH_COVER} of ${NWH}`;
const WRONG = WH.filter(r => r.clean < 0), N_WRONG = WRONG.length, N_WRONG_UP = WRONG.filter(r => (r.energy_trend || 0) > 0).length;
const NEG = WH.filter(r => r.energy_trend != null && r.energy_trend < 0), N_NEG = NEG.length, NEG_FEW = NEG.every(r => String(r.gate).startsWith('too few'));
const RAMP_TXT = `where the cleaned Friday slope pointed the wrong way (${N_WRONG} cases), the driver was ramping up in ${N_WRONG_UP === N_WRONG ? 'every one' : `${N_WRONG_UP} of them`}; ${N_NEG} of the ${NWH} withheld compounds show a falling energy trend${NEG_FEW ? ' and were withheld for too few clean laps' : ''}`;
const RAMP_SLIDE = `Where the cleaned slope pointed the wrong way (${N_WRONG} cases) the driver was ramping up in ${N_WRONG_UP === N_WRONG ? 'every one' : `${N_WRONG_UP} of them`}; the ${N_NEG} falling-trend cases were withheld${NEG_FEW ? ' for too few clean laps' : ' on other grounds'}`;
const PUSH = ISS.filter(r => r.push_adj != null), N_PUSH = PUSH.length;
const PUSH_POOLED = PUSH.reduce((a, r) => a + r.clean - r.push_adj, 0) / PUSH.reduce((a, r) => a + r.clean - r.obs, 0);
const PUSH_WORD = PUSH_POOLED >= 0.6 && PUSH_POOLED < 0.72 ? 'about two-thirds' : `about ${pct(PUSH_POOLED)}`;
const PUSH_TXT = `explains ${PUSH_WORD} of the pooled Friday-to-Sunday gap on the ${N_PUSH} issued cases (per-case shares vary widely)`;
const HM = ROWS.find(r => r.event === 'Hungary' && r.compound === 'MEDIUM');
const BETAS = {}; LOCK.validation.push_diagnostic.beta_practice_vs_race.forEach(b => { BETAS[b.event] = [b.practice, b.race]; });
const BETA_WITHIN = Math.max(...['Austria', 'Barcelona'].map(e => Math.abs(BETAS[e][0] - BETAS[e][1]))).toFixed(2);
const cost = (s, v) => ((s.views || {})[v] || {}).cost_under_truth_vs_best_s;
const SC = {}; Object.entries(LOCK.strategy).forEach(([ev, s]) => { const n = cost(s, 'Naive fit'), o = cost(s, 'Orb v1'); if (n != null && o != null) SC[ev] = [n, o]; });
const N_SC = Object.keys(SC).length, SC_BEATS = Object.values(SC).filter(([n, o]) => o < n).length;
const N_SPRINT = Object.keys(SC).filter(ev => (LOCK.events[ev] || {}).format === 'sprint').length;
const SC_MISS = Object.entries(SC).filter(([, [n, o]]) => o >= n).sort((a, b) => b[1][1] - a[1][1]);
const MISS_TXT = SC_MISS.map(([ev, [n, o]]) => `${ev} (${sgn(o, 0)} s against ${sgn(n, 0)} s for naive)`).join(' and ');
const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six'];
const SC_TXT = `beats the naive plan on ${SC_BEATS} of the ${N_SC} scored weekends; the ${WORDS[SC_MISS.length] || SC_MISS.length} misses are ${MISS_TXT}`;
const MISS_TITLE = SC_MISS.map(m => m[0]).join(' and ') + (SC_MISS.length === 1 ? ', the miss' : ', the misses');
const NAIVE_COSTS = Object.values(SC).map(x => x[0]), ORB_COSTS = Object.values(SC).map(x => x[1]);
const MAD = MAD2.compounds;
const MAXTREND = Math.max(...ROWS.filter(r => r.energy_trend != null).map(r => r.energy_trend));
function madHardLaps() { try { const rows = fs.readFileSync(OUT + 'excluded_Madrid.csv', 'utf8').trim().split('\n'); const h = rows[0].split(','), ic = h.indexOf('Compound'), ir = h.indexOf('reason'); return rows.slice(1).filter(r => { const c = r.split(','); return c[ic] === 'HARD' && c.slice(ir).join(',') === 'kept'; }).length; } catch (e) { return null; } }
const MAD_HARD_N = madHardLaps();
const madRow = (label, comp, col, extra) => { const c = MAD[comp]; if (!c) return [label, 'no row', 'not in the lock', col]; return [label, `${sgn(c.prediction, 3)} s/lap`, `${c.issued ? 'issued' : 'withheld (' + c.gate + ')'}; 90% band ${sgn(c.band90[0], 2)} to ${sgn(c.band90[1], 2)}; ${c.n_prac} clean laps${extra(c)}`, col]; };
const MS = LOCK.strategy.Madrid.views, NAME = { S: 'soft', M: 'medium', H: 'hard' };
const stopsWord = k => ({ 1: 'one stop', 2: 'two stops' })[k] || `${k} stops`;
const planTxt = v => `${stopsWord(v.stints.length - 1)}, ${v.plan.split('-').map(x => NAME[x]).join(' then ')}, ${v.stints.join(' / ')} laps`;
const MAD_PLAN_TXT = planTxt(MAD2.strategy), BH = MS['Orb v1, band high'];
const MAD_BAND_TXT = BH ? `the top of the band says ${stopsWord(BH.stints.length - 1)}` : 'no band-high plan in the lock';
const MAD_NOTE_SOFT = MAD.SOFT ? `soft ${MAD.SOFT.issued ? 'issued' : 'withheld'} at ${sgn(MAD.SOFT.prediction, 3)} s/lap with a wide band` : 'soft: no row in the lock';
const MAD_NOTE_MED = MAD.MEDIUM ? `medium ${MAD.MEDIUM.issued ? 'issued' : 'withheld'} because drivers were learning a brand-new circuit, energy rising ${sgn(MAD.MEDIUM.energy_trend, 2)} MJ per lap through runs, ${(MAD.MEDIUM.energy_trend / MAXTREND).toFixed(1)} times the largest within-run ramp seen at an established circuit this season, forecast low degradation (${sgn(MAD.MEDIUM.prediction, 3)} s/lap) by two independent routes` : 'medium: no row in the lock';
function liquid() { try { const liq = JSON.parse(fs.readFileSync(OUT + 'liquid.json', 'utf8')); const cells = []; Object.entries(liq).forEach(([ev, d]) => Object.entries(d.by_compound).forEach(([c, m]) => cells.push([ev, c, m.mae_linear, m.mae_quadratic, m.mae_linear_cov, m.mae_liquid, m.n_heldout_laps]))); const full = cells.filter(x => x.slice(2, 6).every(y => y != null)); const deg = full.filter(x => x[4] < 1e-6), ok = full.filter(x => x[4] >= 1e-6); const red = sub => 1 - sub.reduce((a, x) => a + x[4] * x[6], 0) / sub.reduce((a, x) => a + x[2] * x[6], 0); return { n: full.length, wins: full.filter(x => x[5] < Math.min(x[2], x[3], x[4])).length, redExcl: red(ok), redAll: red(full), nDeg: deg.length, degEvents: [...new Set(deg.map(x => x[0]))].sort().join('/') }; } catch (e) { return null; } }
const LQ = liquid();
const LQ_CUTWORD = LQ ? (LQ.redExcl >= 0.2 && LQ.redExcl < 0.3 ? 'by about a quarter' : `by about ${pct(LQ.redExcl)}`) : '';
// the reduction is a derived word ("about a quarter" for 20 to 30%) with its basis, not a bare percentage: the red-team claim audit
// (liquid_23_pct_10_of_31) cannot verify the bare figure, so the slide carries the basis, the exclusion and the win count
const LQ_TXT = LQ ? `Per-lap inputs cut the age-only error ${LQ_CUTWORD}, lap-weighted, with the ${WORDS[LQ.nDeg] || LQ.nDeg} degenerate ${LQ.degEvents} cells excluded (${pct(LQ.redAll)} with them); the network on top of the same inputs beat the best baseline in only ${LQ.wins} of ${LQ.n} cells.` : 'Liquid ablation numbers unavailable (out/liquid.json missing).';

// ---- Madrid refresh timeline, read from the artefacts (never typed): the lock, the hashed forecast and the refresh.sh logs ----
const PROTO = OUT.replace(/out\/$/, '');
const hm = ts => ts.slice(11, 16);   // HH:MM from an ISO timestamp (IST)
const cap = t => t[0].toUpperCase() + t.slice(1);
const LOCK_HM = hm(LOCK.generated_at);
function forecast() { try { const raw = fs.readFileSync(OUT + 'forecast_Madrid_2026.json'); const Fj = JSON.parse(raw.toString('utf8')); const sha = require('crypto').createHash('sha256').update(raw).digest('hex'); let listed = null; try { listed = ((fs.readFileSync(OUT + 'forecast_Madrid_2026.sha256', 'utf8').split('\n').find(l => l.trim().endsWith('forecast_Madrid_2026.json')) || '').trim().split(/\s+/)[0]) || null; } catch (e) { listed = null; } return { issuedHm: hm(Fj.issued_at), sessions: Fj.sessions_used || [], sha, shaOk: listed === sha }; } catch (e) { return null; } }
function refresh(log, sess) { let txt; try { txt = fs.readFileSync(PROTO + log, 'utf8'); } catch (e) { return { missed: [], landed: null }; } const missed = []; let landed = null; txt.split(/^== .*? start /m).slice(1).forEach(blk => { const start = blk.match(/^\w{3} \w{3} +\d+ (\d\d:\d\d)/), rebuilt = blk.match(/lock rebuilt: \w{3} \w{3} +\d+ (\d\d:\d\d)/); if (new RegExp(`Madrid ${sess}: \\d+ laps`).test(blk) && rebuilt) landed = rebuilt[1]; else if (new RegExp(`\\b${sess}: not run yet`).test(blk) && start) missed.push(start[1]); }); return { missed, landed }; }
const FC = forecast(), FP3 = refresh('refresh_fp3.log', 'FP3'), QR = refresh('refresh_q.log', 'Q'), Q_LANDED = QR.landed || LOCK_HM;
const fileSha = name => require('crypto').createHash('sha256').update(fs.readFileSync(OUT + name)).digest('hex');
const FROZEN = JSON.parse(fs.readFileSync(OUT + 'forecast_Madrid_2026.json', 'utf8'));
const PDF_SHA = fileSha('forecast_Madrid_2026.pdf'), SIDECAR_SHA = fileSha('forecast_Madrid_2026.sha256');
const FORECAST_HASH = LOCK2.shared.forecast_hash.replace(/^sha256:/, '');
if (!FC || !FC.shaOk || FROZEN.lock_sha256 !== fileSha('lock.json') || FROZEN.lock_v2_sha256 !== fileSha('lock_v2.json') || FROZEN.lock_v2_forecast_hash !== LOCK2.shared.forecast_hash) throw new Error('Frozen Madrid provenance does not match lock files');
const listedPdf = fs.readFileSync(OUT + 'forecast_Madrid_2026.sha256', 'utf8').split('\n').find(l => l.trim().endsWith('forecast_Madrid_2026.pdf'));
if (!listedPdf || listedPdf.trim().split(/\s+/)[0] !== PDF_SHA) throw new Error('Frozen Madrid PDF hash mismatch');
FROZEN.compounds.forEach(c => { const v = MAD[c.compound]; if (!v || Math.abs(v.prediction - c.prediction_s_per_lap) > 0.000051 || v.n_prac !== c.clean_practice_laps || v.issued !== c.issued) throw new Error('Madrid frozen compound disagrees with lock v2'); });
const MAD_HASH_LINES = [`JSON SHA256 ${FC.sha}`, `PDF SHA256 ${PDF_SHA}`, `SHA256 sidecar ${SIDECAR_SHA}`, `lock v2 forecast_hash ${FORECAST_HASH}`];
const SESS = FC && FC.sessions.length ? FC.sessions : null;
const SESS_TXT = SESS ? (SESS.length > 1 ? `${SESS.slice(0, -1).join(', ')} and ${SESS[SESS.length - 1]}` : SESS[0]) : 'the sessions in the lock';
const SESS_SHORT = SESS ? SESS.join(', ') : 'sessions per the lock';
const HASH12 = FC ? FC.sha.slice(0, 12) : 'n/a';
const MAD_REFRESH_TXT = (FP3.landed ? `FP3 refresh landed ${FP3.landed}; ` : '') + `qualifying refresh landed ${Q_LANDED} with ${SESS_TXT} in the lock` + (QR.missed.length ? ` (a ${QR.missed.join(' and ')} attempt found the session not yet run)` : '');
const MAD_REFRESHED_TXT = 'refreshed after FP3' + (FP3.landed ? ` (landed ${FP3.landed})` : '') + ` and after qualifying (landed ${Q_LANDED}, ${SESS_TXT} in the lock)`;
const MAD_HASH_TXT = FC ? `hashed forecast published ${FC.issuedHm} IST (sha256 ${HASH12}${FC.shaOk ? '' : ', does not match the published .sha256'})` : 'hashed forecast not yet published';
const MAD_SLIDE_TXT = (FP3.landed ? `FP3 refresh landed ${FP3.landed}; ` : '') + `qualifying refresh landed ${Q_LANDED} (${SESS_SHORT} in the lock); ` + (FC ? `forecast hashed ${FC.issuedHm} IST, sha256 ${HASH12}` : 'forecast not yet published');
// Madrid track evolution, read from the lock (live.Madrid.meta.evolution_s_per_min): a negative s/min is lap times falling, i.e. the track getting faster
const EVO = (LOCK.live.Madrid.meta || {}).evolution_s_per_min || {};
const FRI = ['FP1', 'FP2'].filter(s => EVO[s] != null).map(s => -EVO[s] * 60);   // the Friday sessions
const MAD_EVO_TXT = FRI.length ? `${Math.min(...FRI).toFixed(1) === Math.max(...FRI).toFixed(1) ? Math.min(...FRI).toFixed(1) : `${Math.min(...FRI).toFixed(1)} to ${Math.max(...FRI).toFixed(1)}`} s per hour at Madrid on Friday` : 'the session evolution measured in the lock';

// 1 title
{ const s = pres.addSlide(); s.background = { color: BG }; s.addNotes('Orb v1 issues clean tyre-degradation curves from Friday practice and scores them against the race every Sunday. Friday lies twice: about what the tyre did, and about what it will do on Sunday. We correct the first lie and learn the second.');
  s.addText('ORB V1', { x: 0.5, y: 1.3, w: 9, h: 1.0, fontFace: F, fontSize: 60, bold: true, color: INK, isTextBox: true, margin: 0 });
  s.addText('Live Tyre Intelligence: clean tyre-degradation curves from Friday, scored on Sunday.', { x: 0.5, y: 2.35, w: 9, h: 0.5, fontFace: F, fontSize: 20, color: INK, isTextBox: true, margin: 0 });
  s.addText('Friday lies twice. We correct the lie you can measure and learn the one you cannot.', { x: 0.5, y: 3.12, w: 9, h: 0.45, fontFace: F, fontSize: 15, italic: true, color: GOLD, isTextBox: true, margin: 0 });
  s.addText('Team Orb v1 (registered as FireBolt)  ·  Samuel Christ  ·  TrackShift 2026, Tyre Degradation Intelligence  ·  Plaksha University, 12 to 13 September 2026', { x: 0.5, y: 4.3, w: 9, h: 0.35, fontFace: F, fontSize: 11, color: MUTED, isTextBox: true, margin: 0 });
  s.addText('Submitted to the idea round as ClearStint and renamed. Built on disclosed pre-work from that round (estimator and six-weekend validation, 5 September); everything else built at Plaksha.', { x: 0.5, y: 4.7, w: 9, h: 0.5, fontFace: F, fontSize: 10, color: MUTED, isTextBox: true, margin: 0 });
  [RED, GOLD, SLATE].forEach((c, i) => s.addShape(pres.shapes.RECTANGLE, { x: 0.5 + i * 0.5, y: 0.6, w: 0.4, h: 0.08, fill: { color: c }, line: { color: c, width: 0 } })); }

// 2 problem
{ const s = base('A practice lap time is not a tyre measurement. Hungary: the straight line says 0.285, the race showed 0.042, seven times wrong, and a plan built on that line loses 74 seconds against the best plan. Five things pollute the lap and only one of them is the tyre.');
  title(s, 'The problem: Friday practice is a biased sample of the race', 'A Friday lap time mixes five things, and only one of them is the tyre');
  stat(s, 0.5, 1.45, 2.2, '0.285', 'Hungary 2026 medium: s per lap from a straight line through Friday laps', MUTED); stat(s, 2.9, 1.45, 2.0, '0.042', 'what the race actually showed', GOLD); stat(s, 5.1, 1.45, 1.6, '7×', 'wrong', CRIT); stat(s, 6.9, 1.45, 2.6, '+74 s', 'cost of following the Friday line against the best plan, Hungary replay', CRIT);
  const items = [['The tyre wearing', 'what we want: a little slower every lap'], ['Fuel burning off', 'about 1.1 kg a lap, worth about 0.033 s a lap, pulling the other way'], ['Track evolution', `rubber goes down, everyone gets faster: ${MAD_EVO_TXT}`], ['Traffic', 'within 60 m of another car the lap is slow for reasons that are not the tyre'], ['The driver', 'warming up, learning the track, pushing harder or easing off']];
  items.forEach(([h, d], i) => { const y = 2.85 + i * 0.44; num(s, 0.5, y, i + 1, i === 0 ? GOLD : SLATE); s.addText([{ text: h + '  ', options: { bold: true, color: INK } }, { text: d, options: { color: MUTED } }], { x: 0.95, y, w: 8.5, h: 0.36, fontFace: F, fontSize: 12, valign: 'middle', isTextBox: true, margin: 0 }); }); }

// 3 idea
{ const s = base('Treat Friday as a biased sample and model the bias. Remove what physics and telemetry can measure, learn what they cannot from earlier weekends, refuse when Friday has no signal, and score every prediction against Sunday. Six verbs.');
  title(s, 'The idea: model the bias instead of pretending it is not there', 'Six verbs, the same estimator on practice and race, and a scorecard every Sunday');
  const steps = [['Ingest', 'every lap of every session from the public timing feed'], ['Clean', 'drop untrustworthy laps, compare each run to itself, subtract fuel and track evolution'], ['Gate', 'issue a curve only with 30+ clean laps and a positive cleaned slope'], ['Learn', 'the Sunday-to-Friday ratio per compound from earlier weekends'], ['Forecast', 'the race curve with a band, crossover laps, one stop or two'], ['Score', 'Sunday night, the same estimator on race laps; miss published']];
  steps.forEach(([h, d], i) => { const col = i % 3, row = Math.floor(i / 3); const x = 0.5 + col * 3.05, y = 1.5 + row * 1.75; card(s, x, y, 2.85, 1.55); num(s, x + 0.15, y + 0.15, i + 1); s.addText(h, { x: x + 0.6, y: y + 0.12, w: 2.1, h: 0.4, fontFace: F, fontSize: 18, bold: true, color: INK, isTextBox: true, margin: 0 }); s.addText(d, { x: x + 0.15, y: y + 0.6, w: 2.55, h: 0.9, fontFace: F, fontSize: 11.5, color: MUTED, valign: 'top', isTextBox: true, margin: 0 }); }); }

// 4 clean
{ const s = base(`Step by step: drop laps that cannot inform the tyre; compare each run only to itself so driver, car and fuel load cancel; subtract the known fuel effect and the measured evolution; what is left is the tyre. Hungary medium goes from ${HM.naive.toFixed(3)} to ${HM.clean.toFixed(3)} cleaned, to ${HM.pred_clearstint.toFixed(3)} after its held-out Sunday ratio ${HM.k.toFixed(2)}, against ${HM.obs.toFixed(3)} in the race.`);
  title(s, 'How a lap is cleaned', 'Same regression on practice and race, so the Friday-to-Sunday ratio is a property of the data');
  const rows = [['Drop what cannot inform the tyre', 'pit laps, yellow or safety-car laps, deleted laps, laps with over 30% of the distance within 60 m of a car, cool-down laps, runs under five laps, broken telemetry; every drop listed with its reason'], ['Compare each run only to itself', 'lap 10 of a run against lap 2 of the same run; one constant per stint absorbs driver, car, setup and fuel load (fixed effects)'], ['Subtract the fuel effect', 'a stated prior from the 2026 regulations, 1.1 kg per lap at 0.030 s per kg; not estimated from practice because fuel and age are collinear inside a run'], ['Subtract track evolution', 'measured per session from every driver’s push laps against session time, driver-demeaned'], ['What is left is the tyre', 'seconds lost per lap of age, per compound, with a standard error']];
  rows.forEach(([h, d], i) => { const y = 1.4 + i * 0.68; num(s, 0.5, y + 0.02, i + 1, SLATE); s.addText([{ text: h + '. ', options: { bold: true, color: INK } }, { text: d, options: { color: MUTED } }], { x: 0.95, y, w: 5.2, h: 0.64, fontFace: F, fontSize: 10, valign: 'top', isTextBox: true, margin: 0 }); });
  card(s, 6.5, 1.4, 3.0, 3.5); s.addText('Hungary 2026, medium, s per lap of age', { x: 6.65, y: 1.5, w: 2.7, h: 0.35, fontFace: F, fontSize: 11, bold: true, color: INK, isTextBox: true, margin: 0 });
  [['Straight line through Friday laps', HM.naive.toFixed(3), MUTED], ['After cleaning', HM.clean.toFixed(3), SLATE], [`× held-out Sunday ratio ${HM.k.toFixed(2)}`, HM.pred_clearstint.toFixed(3), GOLD], ['Race, same estimator', HM.obs.toFixed(3), INK]].forEach(([l, v, c], i) => { const y = 1.95 + i * 0.72; s.addText(v, { x: 6.65, y, w: 1.2, h: 0.5, fontFace: F, fontSize: 24, bold: true, color: c, isTextBox: true, margin: 0 }); s.addText(l, { x: 7.85, y: y + 0.05, w: 1.55, h: 0.55, fontFace: F, fontSize: 10, color: MUTED, valign: 'top', isTextBox: true, margin: 0 }); }); }

// 5 fifth confounder
{ const s = base(`Some Fridays show a tyre getting faster with age, which is inconsistent with wear. The energy the driver puts through the tyre, computed from the public speed and position traces, shows why: ${RAMP_TXT}. That is a fifth confounder, measured not assumed, and it ${PUSH_TXT}. Those compounds are withheld.`);
  title(s, 'The discovery: the fifth confounder is the driver’s push profile', 'Tyre demand per lap from the public 3.7 Hz traces, m × (∫v²κ ds + ∫|dv| v)');
  img(s, 'fig_push.png', 0.5, 1.35, 4.9, 3.11);
  card(s, 5.7, 1.35, 3.8, 3.75); stat(s, 5.9, 1.5, 1.7, '+0.10', 'MJ per lap of age, median energy trend on withheld compounds', GOLD); stat(s, 7.7, 1.5, 1.7, '0.00', 'on issued compounds', SLATE);
  bullets(s, [`Wrong-way cleaned slopes: ${N_WRONG_UP} of ${N_WRONG} had rising energy; ${N_NEG} withheld cases had falling trends.`, `Push profile explains ${PUSH_WORD} of the pooled gap on ${N_PUSH} issued cases; per-case shares vary widely.`, `Practice/race energy coefficients differ by at most ${BETA_WITHIN} s/MJ at Austria and Barcelona.`, 'Diagnostic and second opinion. Easing off can respond to degradation.'], 5.9, 2.85, 3.45, 2.2, 10.5); }

// 6 learn + refuse
{ const s = base(`The same estimator runs on race laps, so for every past weekend we know how much Sunday shrank Friday, per compound. For a new weekend the median of the other weekends is applied only when they agree. When Friday has no signal we withhold and forecast low degradation, the typical race value of earlier withheld cases; the ${WH_TXT}.`);
  title(s, 'Learn the second lie, and refuse honestly', 'Transfer factors learned leave-one-weekend-out; withheld is still a forecast');
  card(s, 0.5, 1.4, 4.4, 1.7); s.addText('Season transfer factor, race ÷ cleaned Friday', { x: 0.65, y: 1.5, w: 4.1, h: 0.3, fontFace: F, fontSize: 11, bold: true, color: INK, isTextBox: true, margin: 0 });
  [['Soft', `×${LOCK2.validation.by_compound.SOFT.k_median.toFixed(2)}`, RED], ['Medium', `×${LOCK2.validation.by_compound.MEDIUM.k_median.toFixed(2)}`, GOLD], ['Hard', 'not applied', SLATE]].forEach(([c, v, col], i) => { s.addText(v, { x: 0.65 + i * 1.4, y: 1.85, w: 1.35, h: 0.55, fontFace: F, fontSize: fitSize(v, 1.35, 22, 11), bold: true, color: col, isTextBox: true, margin: 0 }); s.addText(c, { x: 0.65 + i * 1.4, y: 2.4, w: 1.35, h: 0.3, fontFace: F, fontSize: 11, color: MUTED, isTextBox: true, margin: 0 }); });
  s.addText('applied only if at least three weekends exist and a majority sit within ±50% of their median', { x: 0.65, y: 2.7, w: 4.1, h: 0.35, fontFace: F, fontSize: 9.5, color: MUTED, isTextBox: true, margin: 0 });
  card(s, 0.5, 3.3, 4.4, 1.75); s.addText('The gate and the fallback', { x: 0.65, y: 3.4, w: 4.1, h: 0.3, fontFace: F, fontSize: 11, bold: true, color: INK, isTextBox: true, margin: 0 });
  bullets(s, ['Issue only with 30+ clean long-run laps and a cleaned slope above +0.02 s/lap', 'Otherwise withhold, and forecast the median race degradation of the other withheld cases', `${WH_SLIDE}; fallback error ${WH_FB.toFixed(3)} against ${WH_NV.toFixed(3)} naive`], 0.65, 3.75, 4.1, 1.25, 10.5);
  img(s, 'fig_withheld.png', 5.2, 1.4, 4.3, 2.58); s.addText('Withheld compounds and what the race did', { x: 5.2, y: 4.05, w: 4.3, h: 0.3, fontFace: F, fontSize: 10, color: MUTED, isTextBox: true, margin: 0 }); }

// 7 proof
{ const v = LOCK2.validation, c = v.calibration; const s = base(`Source: out/lock_v2.json validation. Development evaluation leaves each weekend out of its own training pool. Naive MAE ${v.mae_all_with_fallback.naive.toFixed(3)} vs Orb v1 ${v.mae_all_with_fallback.clearstint.toFixed(3)} s/lap; wins ${v.wins_clearstint_over_naive}/${v.n_compound_weekends}.`);
  title(s, `The proof: ${v.n_weekends} weekends, ${v.n_compound_weekends} compound-weekends, every one held out`, 'Mean absolute error against the race-derived reference, s per lap of tyre age');
  table(s, [['Predictor', 'Cases', 'MAE', 'Calibration slope', 'r'], ...[['Naive straight line', c.naive, v.mae_all_with_fallback.naive], ['Cleaned Friday curve, issued', c.clean, v.mae_issued.clean], ['Orb v1, issued', c.clearstint, v.mae_issued.clearstint], ['Orb v1, all cases with fallback', c.all_with_fallback, v.mae_all_with_fallback.clearstint]].map(([name, cal, error]) => [name, cal.n, error.toFixed(3), sgn(cal.slope, 2), cal.r.toFixed(2)])], 0.5, 1.4, 5.1, [2.3, 0.6, 0.7, 1.0, 0.5], 11);
  stat(s, 0.5, 3.4, 1.45, `${v.wins_clearstint_over_naive}/${v.n_compound_weekends}`, 'cases where Orb v1 beats the naive line', GOLD); stat(s, 2.05, 3.4, 2.35, v.ci90_mae_clearstint_all.map(x => x.toFixed(3)).join(' to '), '90% bootstrap interval on the error', SLATE); stat(s, 4.5, 3.4, 1.1, `${WH_LT06}/${NWH}`, 'withheld cases below 0.06 s/lap in the race', INK);
  img(s, 'fig_calibration.png', 5.9, 1.3, 3.6, 3.2); s.addText('Predicted from Friday against observed in the race; filled = issued, open = fallback, × = naive', { x: 5.9, y: 4.55, w: 3.6, h: 0.45, fontFace: F, fontSize: 9, color: MUTED, isTextBox: true, margin: 0 }); }

// 8 holds up
{ const s = base(`The headline barely moves across every stated choice. The honest misses are on the slide: in the strategy replay ${MISS_TXT}, with Barcelona the case where the naive line implied the right plan by luck; and the liquid neural network, which tied a linear model given the same inputs; the inputs were the discovery.`);
  title(s, 'It holds up, and the misses are on the slide', 'Sensitivity to every stated choice, and two honest results');
  table(s, [['Variant', 'Issued', 'MAE', 'r'], ['Baseline (fuel 1.1 kg/lap, 0.030 s/kg, traffic 30%, runs 5+)', '16', '0.023', '0.78'], ['Fuel prior 0.9 or 1.3 kg/lap', '14 / 16', '0.026 / 0.023', '0.74 / 0.76'], ['Fuel cost 0.025 or 0.035 s/kg', '14 / 16', '0.025 / 0.023', '0.75 / 0.78'], ['Traffic threshold 20% or 40%', '15 / 16', '0.027 / 0.021', '0.59 / 0.79'], ['Minimum run 4 or 7 laps', '15 / 13', '0.026 / 0.027', '0.70 / 0.65']], 0.5, 1.4, 5.4, [3.0, 0.8, 0.9, 0.7], 10);
  card(s, 6.2, 1.4, 3.3, 1.6); s.addText(MISS_TITLE, { x: 6.35, y: 1.5, w: 3.0, h: 0.3, fontFace: F, fontSize: 12, bold: true, color: CRIT, isTextBox: true, margin: 0 }); s.addText(`Barcelona: our soft prediction ran low and the naive line happened to imply the right plan. In the replay ${MISS_TXT}. Said on stage before anyone asks.`, { x: 6.35, y: 1.85, w: 3.0, h: 1.1, fontFace: F, fontSize: 10.5, color: MUTED, valign: 'top', isTextBox: true, margin: 0 });
  card(s, 6.2, 3.15, 3.3, 1.85); s.addText('Liquid neural network, the ablation', { x: 6.35, y: 3.25, w: 3.0, h: 0.3, fontFace: F, fontSize: 12, bold: true, color: TEAL, isTextBox: true, margin: 0 }); s.addText(`A continuous-time cell read each race stint lap by lap, scored on held-out stints. ${LQ_TXT}`, { x: 6.35, y: 3.6, w: 3.0, h: 1.35, fontFace: F, fontSize: 10.5, color: MUTED, valign: 'top', isTextBox: true, margin: 0 }); }

// 9 decisions
{ const s = base(`A curve only matters as a decision. Replayed on the ${N_SC} scored weekends with the race-derived curves as the reference: the naive plan costs ${Math.min(...NAIVE_COSTS).toFixed(0)} to ${Math.max(...NAIVE_COSTS).toFixed(0)} seconds against the best plan; ours ${Math.min(...ORB_COSTS).toFixed(0)} to ${Math.max(...ORB_COSTS).toFixed(0)}, and Orb v1 ${SC_TXT}.`);
  title(s, 'Curves become decisions: the strategy replay', 'Offsets from practice or qualifying medians, 21 s pit loss, every one- and two-stop plan enumerated, costed under race-derived curves');
  table(s, [['Race', 'Naive plan', 'Cost', 'Orb v1 plan', 'Cost', 'Best plan'], ['Hungary', 'M-H-H', '+74 s', 'S-M-M 16/26/28', '+24 s', 'S-S-M'], ['Monza', 'M-H', '+47 s', 'S-M 44/9', '+0 s', 'S-M'], ['Zandvoort', 'S-M', '+155 s', 'S-S-M 30/32/10', '+2 s', 'S-S-H'], ['Miami', 'M-H-H', '+80 s', 'S-M 40/17', '+6 s', 'S-M'], ['Canada', 'S-H', '+75 s', 'S-S-H 30/32/6', '+30 s', 'S-H'], ['Barcelona', 'S-H-H', '+0 s', 'S-H 12/54', '+55 s', 'S-H-H']], 0.5, 1.4, 5.3, [1.1, 0.9, 0.7, 1.4, 0.6, 0.6], 10);
  img(s, 'fig_strategy.png', 6.0, 1.4, 3.5, 1.96); bullets(s, [`Beats the naive plan on ${SC_BEATS} of the ${N_SC} scored weekends (${N_SPRINT} sprint); the ${WORDS[SC_MISS.length] || SC_MISS.length} misses are ${MISS_TXT}`, 'Assumptions stated on screen: linear curves, no safety car, no traffic', 'Next: pit window and a probability that one stop beats two, from the band'], 6.0, 3.55, 3.5, 1.5, 10.5); }

// 10 madrid: lock-v2 numbers and immutable published-file provenance
{ const s = base(`Madrid: ${MAD_REFRESHED_TXT}. Hashed before the race, verifiable after the event. ${MAD_NOTE_SOFT}; ${MAD_NOTE_MED}. Sources: out/lock_v2.json pre_race_forecast.events.Madrid and frozen forecast_Madrid_2026.json. Full digests: ${MAD_HASH_LINES.join('; ')}.`);
  title(s, 'Madrid: the frozen forecast', `${SESS_SHORT}; published ${FC.issuedHm} IST. Hashed before the race, verifiable after the event.`);
  img(s, 'fig_madrid.png', 0.5, 1.35, 4.8, 2.4);
  card(s, 5.6, 1.35, 3.9, 2.75);
  [madRow('Soft', 'SOFT', RED, c => ''), madRow('Medium', 'MEDIUM', GOLD, c => ''), ['Hard', 'no curve', 'No issued curve in the frozen forecast.', SLATE]].forEach(([c, v, d, col], i) => { const y = 1.5 + i * 0.72; s.addText(c, { x: 5.75, y, w: 1.0, h: 0.25, fontFace: F, fontSize: 11, bold: true, color: col, isTextBox: true, margin: 0 }); s.addText(v, { x: 6.7, y, w: 2.7, h: 0.25, fontFace: F, fontSize: 12, bold: true, color: INK, isTextBox: true, margin: 0 }); s.addText(d, { x: 5.75, y: y + 0.26, w: 3.6, h: 0.44, fontFace: F, fontSize: 8.5, color: MUTED, valign: 'top', isTextBox: true, margin: 0 }); });
  s.addText(`Central: ${MAD2.strategy.plan} ${MAD2.strategy.stints.join('/')}; band-high: ${MAD2.strategy.band_high_plan}. Pit loss ${MAD2.strategy.pit_loss_s} s.`, { x: 5.75, y: 3.74, w: 3.6, h: 0.3, fontFace: F, fontSize: 9, color: INK, isTextBox: true, margin: 0 });
  s.addText(`Qualifying refresh landed ${Q_LANDED} IST. Forecast remains frozen for the race.`, { x: 0.5, y: 3.83, w: 4.8, h: 0.3, fontFace: F, fontSize: 9, color: MUTED, isTextBox: true, margin: 0 });
  MAD_HASH_LINES.forEach((text, i) => s.addText(text, { x: 0.5, y: 4.28 + i * 0.19, w: 9, h: 0.18, fontFace: 'Consolas', fontSize: 8, color: MUTED, isTextBox: true, margin: 0 })); }

// 11 product
{ const s = base('The product is two independent modes on one shared core. Live Predictor makes the call during the race and may only see what exists at that moment. Ghost Strategy audits after the race and replays alternative tyre plans. Same frozen forecast, enforced boundary, sensor mode always on screen.');
  title(s, 'The product: two modes, one core', 'Predict. Monitor. Decide. Prove.');
  card(s, 0.5, 1.4, 9, 0.85, { fill: '20252D' }); s.addText('Degradation Intelligence Engine  →  frozen pre-race forecast with a hash', { x: 0.7, y: 1.5, w: 8.6, h: 0.3, fontFace: F, fontSize: 14, bold: true, color: INK, isTextBox: true, margin: 0 }); s.addText('cleaning, gate, learned transfer, bands, strategy enumeration; every number on screen traces to the lock, a hashed sidecar or a labelled placeholder (the Live Predictor replays the frozen prior and the hashed race file in-process)', { x: 0.7, y: 1.82, w: 8.6, h: 0.35, fontFace: F, fontSize: 10.5, color: MUTED, isTextBox: true, margin: 0 });
  card(s, 0.5, 2.45, 4.4, 2.6); s.addText('Live Predictor: makes the call', { x: 0.65, y: 2.55, w: 4.1, h: 0.35, fontFace: F, fontSize: 14, bold: true, color: TEAL, isTextBox: true, margin: 0 });
  bullets(s, ['Starts from the locked forecast; updates the tyre state every lap from corrected pace, conditions, traffic, engineer-entered driver feedback, team sensors when connected', 'Useful laps remaining, cliff risk, pit window, recommended tyre, and why the call moved', 'Can only read data up to the current timestamp: asserted in code', 'Sensor mode on screen: PUBLIC PROXY or TEAM SENSOR'], 0.65, 2.95, 4.1, 2.05, 10);
  card(s, 5.1, 2.45, 4.4, 2.6); s.addText('Ghost Strategy: audits the model', { x: 5.25, y: 2.55, w: 4.1, h: 0.35, fontFace: F, fontSize: 14, bold: true, color: GOLD, isTextBox: true, margin: 0 });
  bullets(s, ['Historical audit: frozen forecast against the race-derived reference, error, coverage, strategy regret', 'Race Twin: the driver’s own laps replayed with a different tyre plan; real car and ghost car on the circuit; lap-by-lap source of the difference', 'Scenario explorer, model-implied only, supported weather scenarios', 'Neither mode can import the other’s state'], 5.25, 2.95, 4.1, 2.05, 10.5); }

// 12 validation
{ const s = base('Validation without cheating: leave-one-weekend-out for everything shown today; a sealed holdout of six whole weekends chosen by a fixed rule before tuning; the prospective Madrid forecast with a hash; hidden-stop-response tests for the counterfactual; strategy regret against a hindsight oracle. Two scorecards, never merged.');
  title(s, 'How we validate without fooling ourselves', 'Three splits, two scorecards, one rule');
  const cards3 = [['Development pool', 'Whole weekends, leave-one-weekend-out, sensitivity, ablations. The 29 cases shown today.', SLATE], ['Sealed holdout', 'count = clamp(round(0.18 × eligible), 4, 6) = 6 weekends, chosen by metadata only, hashed before any tuning: Canada 2023, Bahrain 2024, Monza 2024, Saudi Arabia 2024, Zandvoort 2024, Qatar 2025. Results revealed only once the model is frozen.', GOLD], ['Prospective', 'Madrid: forecast and hash published before the race; scored after it, whatever it says.', TEAL]];
  cards3.forEach(([h, d, c], i) => { const x = 0.5 + i * 3.05; card(s, x, 1.4, 2.9, 2.05); s.addText(h, { x: x + 0.15, y: 1.5, w: 2.6, h: 0.35, fontFace: F, fontSize: 13, bold: true, color: c, isTextBox: true, margin: 0 }); s.addText(d, { x: x + 0.15, y: 1.9, w: 2.6, h: 1.5, fontFace: F, fontSize: 10, color: MUTED, valign: 'top', isTextBox: true, margin: 0 }); });
  table(s, [['Ghost Strategy scorecard', 'Live Predictor scorecard'], ['Pre-race degradation error and interval coverage; hidden-stop-response: for real stops, hide the post-stop laps and predict the next 1, 3, 5; strategy regret against the hindsight oracle; error by circuit class, driver support, actual weather; abstention coverage', 'Prefix evaluation: reveal data through lap k, predict k+1, k+3, k+5, useful life, recommendation; next-lap and cumulative error, coverage, cliff Brier score, alert lead time, false alerts per stint, recommendation stability, regret; driver-feedback ablation']], 0.5, 3.65, 9, [4.5, 4.5], 9.5); }

// 13 tech stack
{ const s = base('The stack, layer by layer, and why each piece. Public data through FastF1; a per-lap feature layer with the demand index and feed-quality checks; the stint fixed-effects estimator; one lock file; the strategy enumerator; Streamlit and Plotly with a React component for the Race Twin; everything regenerated from the lock.');
  title(s, 'Tech stack', 'Every piece chosen for identifiability, reproducibility and offline operation');
  table(s, [['Layer', 'What', 'Why'], ['Data', 'FastF1 3.8 over Formula 1’s live-timing archive; OpenF1 cross-checks; Pirelli and FIA documents; 2023 to 2026 on disk (about 420 sessions)', 'Free, public, 3.7 Hz telemetry with gap to the car ahead; reproducible for any Grand Prix'], ['Features', 'Per lap: times, sectors, age, compound, flags, deleted laps, pit laps, traffic share within 60 m, tyre demand index on a 10 m arc-length grid, feed-quality counters', 'The demand index is the only public route to the driver’s push; quality counters refuse degraded feeds'], ['Estimator', 'Panel fixed-effects OLS regression (stint fixed effects, compound-specific age slopes), identical on practice and race; fuel-mass prior; measured evolution (Python 3.12, NumPy, pandas)', 'Identifiable, auditable, symmetric'], ['Learning', 'Leave-one-weekend-out median-ratio transfer estimator with an agreement rule; selective prediction with nonparametric fallback; bootstrap intervals; sensitivity grid; live Kalman filter; next: errors-in-variables hierarchical regression on three seasons', 'Learned on training weekends, scored on held-out ones'], ['Lock and contract', 'One JSON manifest with hashed sidecars; pydantic schema; forecast hash; validator', 'No screen can contradict a slide'], ['Strategy', 'Exact one- and two-stop enumeration, offsets from practice or qualifying medians, replay scoring', 'A curve only matters as a decision'], ['Product', 'Streamlit + Plotly shell; React component for the Race Twin; documents generated from the lock', 'Fast to ship, offline, deep links for the demo']], 0.5, 1.35, 9, [1.4, 4.6, 3.0], 8.5);
}

// 14 the AI
{ const s = base('Where the learning actually is: the Friday-to-Sunday correction is learned from data and scored on unseen weekends; the gate is a validated abstention rule; the push covariate is measured; the neural network was tested and reported honestly; the live estimator updates every lap. Next: the correction learned from three seasons with partial pooling, and a learned abstention gate.');
  title(s, 'The AI in it, honestly', 'A cross-validated transfer estimator, selective prediction, a Bayesian state-space (Kalman) live update; a CfC cell tested and set aside');
  const items = [['Learned transfer', 'the Sunday-to-Friday correction per compound is a parameter learned on training weekends and scored on held-out ones (leave-one-weekend-out, r 0.78)', GOLD], ['Selective prediction', `the gate is a validated abstention rule with a scored fallback (${WH_SHORT}); next, a calibrated learned gate with a risk-coverage curve`, TEAL], ['Measured confounder', `the push profile from telemetry energy, an input we did not find in the public methods we reviewed; ${PUSH_TXT}`, SLATE], ['Honest ablation', 'a liquid neural network (MIT CfC) tested on held-out stints: the inputs delivered the gain, the network added nothing; kept as one line', MUTED], ['Live estimation', 'a recursive Bayesian update of the stint slope every lap with explicit process noise so the band can widen; driver feedback shifts regime probabilities', GOLD], ['Next, with three seasons', 'errors-in-variables regression Friday to Sunday with circuit and season effects, about 200 compound-weekends, chronological validation; provider B only if it wins held out', TEAL]];
  items.forEach(([h, d, c], i) => { const col = i % 2, row = Math.floor(i / 2); const x = 0.5 + col * 4.6, y = 1.4 + row * 0.95; num(s, x, y + 0.05, i + 1, c); s.addText([{ text: h + '. ', options: { bold: true, color: INK } }, { text: d, options: { color: MUTED } }], { x: x + 0.45, y, w: 3.95, h: 0.9, fontFace: F, fontSize: 10, valign: 'top', isTextBox: true, margin: 0 }); }); }


// 14b models by name
{ const s = base('The models by their proper names. Core: stint fixed-effects OLS with physics priors. Transfer: leave-one-weekend-out median-ratio estimator with an agreement rule. Gate: selective prediction with a nonparametric fallback. Live: a Kalman filter on intercept and slope with explicit process noise and fixed regime rules. Counterfactual: iso-context additive decomposition. Ablation: a CfC continuous-time recurrent cell, reported not deployed.');
  title(s, 'Models and methods, by name', 'What each component is, how it is estimated, how it is validated');
  table(s, [['Component', 'Model or method', 'Estimation', 'Validation'],
    ['Degradation curve', 'Stint fixed-effects regression; fuel prior and track evolution removed', 'OLS; robust errors planned', 'Weekend holdout; sensitivity sweep'],
    ['Track evolution', 'Driver-demeaned push-lap trend per session', 'OLS', 'Same sensitivity sweep'],
    ['Tyre demand index', 'Telemetry work proxy: speed, curvature and acceleration', 'Deterministic proxy', 'Feed gates; practice/race scale'],
    ['Push adjustment', 'Within-run energy deviation as a regression covariate', 'OLS', 'Held-out diagnostic only'],
    ['Friday-to-Sunday', 'Per-compound median ratio; weekend left out; agreement rule', 'Cross-validated median', '29 cases: r 0.78; slope 0.77'],
    ['Abstention', 'Selective prediction; leave-one-out median fallback', 'Rule + median', 'Risk-coverage scorecard'],
    ['Uncertainty', 'Slope bootstrap × weekend-ratio bootstrap; error CIs', 'Seeded resampling', 'Weekend-bootstrap scorecards'],
    ['Strategy', 'Enumerate 1/2-stop plans; posterior Monte Carlo', 'Exact search', `${N_SC} scored replay weekends`],
    ['Live estimator', 'Kalman intercept/slope; pre-race prior; pit resets; fixed regimes', 'Recursive Bayes', 'Prefix 1/3/5 laps; Brier; lead time'],
    ['Counterfactual', 'Iso-context paired replay; fixed observed SC schedule', 'Whole-curve sampling', 'Identity; hidden-stop; regret'],
    ['Neural ablation', 'CfC continuous-time cell (Hasani et al.); ncps / PyTorch', 'Adam; 3 seeds', 'Stint-grouped 5-fold; not adopted'],
    ['Planned', 'Hierarchical pooling, learned gate, wear/residual and regime models', 'Chronological tests', 'Only adopt after held-out gain']],
    0.5, 1.3, 9, [1.5, 3.6, 1.7, 2.2], 7.5);
}

// 15 provenance + private data
{ const s = base('Where the tech comes from, and what private data would add. Fixed effects from econometrics; physics priors from the regulations; cross-validation and the bootstrap; MIT liquid networks tested and set aside. The private feeds a team has would replace our two stated assumptions with measurements and tighten the same model.');
  title(s, 'Where it comes from, and what real-life data would add', 'Public prototype today; the team adapter is where measurements replace assumptions');
  bullets(s, ['Data: Formula 1’s own live-timing feed via FastF1 (open source) and OpenF1', 'Cleaning: fixed-effects regression, econometrics since the 1970s', 'Physics: fuel burn and its cost from the 2026 regulations; rubber laid on the track', 'Push measurement: energy from speed squared times path curvature plus speed changes, basic mechanics', 'Validation: leave-one-out cross-validation and the bootstrap', 'Liquid networks: MIT (Hasani, Lechner, Rus), tested and reported', 'Prior art: arXiv 2512.00640 (one driver, one race), TUM race simulation'], 0.5, 1.4, 4.2, 3.6, 10.5);
  table(s, [['Private data (team only)', 'What it would buy'], ['Fuel mass per lap', 'retires the largest assumption; rescues low-degradation Fridays'], ['Tyre pressures and temperatures', 'separates graining, blistering and cliff; candidate inputs for sharper bands and earlier alerts; benefit requires validation'], ['Tread depth after runs', 'the only route to a physical wear number'], ['Aero map, ride heights', 'a true friction coefficient from the grip index'], ['Driver instructions, engine modes', 'the second lie becomes measurable instead of learned'], ['Steering, wheel speeds, brake temps', 'actual slip and thermal path']], 5.0, 1.4, 4.5, [1.8, 2.7], 9.5); }

// 16 field
{ const s = base('The field, from a public sweep on the morning of 12 September. PITWALL is the only rival we reviewed with comparable rigour and it concluded the practice curve cannot be delivered; the rest are one weekend, synthetic data, or simulators without a scorecard. We deliver the literal brief, at season scale, with abstention and a live forecast.');
  title(s, 'Versus the field', 'Public repositories on this problem statement, checked 12 September');
  table(s, [['Entry', 'Approach', 'Validation', 'Where we stand'], ['PITWALL', 'Same cleaning idea, 12 events; concluded practice curves do not transfer; dropped tyre age; predicts the value of a fresh tyre', 'Leave-one-event-out on pit-stop deltas', 'We deliver the curve the brief asks for; transfer holds at the compound-weekend level (r 0.78); we strip the push profile; we forecast live'], ['GripTrace', 'One weekend, 2023 Bahrain, soft only; careful; no fuel model', 'Race held out once', 'We went to eleven weekends, three compounds, a validated forecast'], ['TyreIQ', 'Gradient boosting on synthetic Bahrain data', 'In-sample on synthetic data', 'Ours is scored on real races the model never saw'], ['Dr.Tyre, TrackShift AI', 'Pipelines with neon simulators and a Gemini voice engineer; constants or synthetic toggles', 'None held out', 'Every number on our screens traces to the lock, a hashed sidecar or a labelled placeholder, and the forecasts are scored'], ['TIREX, others', 'Kalman plan (backend only), negative-result study, skeletons', 'Planned or none', 'We have results']], 0.5, 1.35, 9, [1.3, 3.2, 1.7, 2.8], 8.5);
  s.addText('One line: among the public repositories we reviewed, we did not find another entry that delivers a Friday curve scored against Sunday across a season, says withheld when it should, removes the driver’s push, and forecasts a live weekend.', { x: 0.5, y: 4.82, w: 9, h: 0.36, fontFace: F, fontSize: 10.5, italic: true, color: GOLD, isTextBox: true, margin: 0 }); }

// 17 jury questions: the one-line answers; the count in the title and the notes is derived from the list, never typed
const JURY_QA = [
  ['What did you build today?', 'Seven new weekends, the fallback rule, the push diagnostic, offsets from practice or qualifying medians, the liquid ablation, the dashboard, Madrid live; the estimator and six weekends were disclosed pre-work.'],
  ['Where is the AI?', 'A transfer factor learned on training weekends and scored on held-out ones; a liquid network tested and reported. What survives the held-out test earns its place.'],
  ['How is this different from a regression on lap times?', 'Same estimator on practice and race, a gate that refuses, a factor learned across the season, a scored fallback, and a push confounder measured from telemetry that we did not find stripped in the public methods we reviewed.'],
  ['What breaks it?', 'Green tracks and new circuits (the gate withholds, the fallback answers); degraded telemetry feeds (refused); wet sessions (excluded); the replay ignores safety cars and traffic and says so.'],
  ['Where could the race leak into the Friday prediction?', 'Nowhere we left open: factors from other weekends only, the fallback from other weekends\' outcomes, offsets from that weekend\'s practice or qualifying; only the scorecard sees the race.'],
  ['The race starts after the event closes; what are you showing?', `A lap-by-lap replay of a race already scored, then Madrid on Sunday evening against a forecast hashed before the race (sha256 ${HASH12}, ${FC ? FC.issuedHm + ' IST' : 'not yet published'}).`],
  ['The 2026 cars are new; does a method tuned on 2026 mean anything?', 'The method is stated priors and measured corrections, not tuned; only the transfer factor is 2026-specific, and the separate past-season scorecards test transfer beyond the current cars.'],
  ['Would this work in Formula 2, without telemetry?', 'Yes, in a degraded mode: lap times, age, compound and flags are enough for the estimator; without telemetry more is withheld and the bands widen, relative accuracy requires validation in that series.']];
const JURY_WORD = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'][JURY_QA.length] || String(JURY_QA.length);
{ const s = base(`${JURY_WORD} questions we expect from the jury, each with the one-line answer we will give; the written answers are in The Case and the talk track. Mentor: tell us which ones we are missing.`);
  title(s, `${JURY_WORD} questions we expect from the jury`, 'The one-line answers; the written versions are in The Case and the talk track. Which ones are we missing?');
  JURY_QA.forEach(([q, a], i) => { const col = i % 2, row = Math.floor(i / 2); const x = 0.5 + col * 4.6, y = 1.4 + row * 0.93; num(s, x, y + 0.05, i + 1, col ? SLATE : GOLD); s.addText([{ text: q + ' ', options: { bold: true, color: INK } }, { text: a, options: { color: MUTED } }], { x: x + 0.45, y, w: 3.95, h: 0.9, fontFace: F, fontSize: 9.5, valign: 'top', isTextBox: true, margin: 0 }); }); }

// 18 built when + ask
{ const s = base('Disclosure first, then the ask. The estimator and the six-weekend validation were pre-work disclosed in the idea round. Everything else was built here. What we would value from the mentor: pressure on the fuel prior and identification, a view on the live-mode design, and what a Haas strategist would want on the decision card.');
  title(s, 'What was built when, and what we would like from you', 'Disclosed pre-work, today’s build, and three questions for the mentor');
  card(s, 0.5, 1.4, 4.4, 3.6); s.addText('Disclosed pre-work (4 to 5 September)', { x: 0.65, y: 1.5, w: 4.1, h: 0.3, fontFace: F, fontSize: 12, bold: true, color: SLATE, isTextBox: true, margin: 0 }); bullets(s, ['The stint fixed-effects estimator with the fuel prior and evolution', 'Six-weekend validation and the first transfer factors', 'Hungary and Austria strategy replay'], 0.65, 1.85, 4.1, 1.0, 10.5);
  s.addText('Built at Plaksha', { x: 0.65, y: 2.9, w: 4.1, h: 0.3, fontFace: F, fontSize: 12, bold: true, color: GOLD, isTextBox: true, margin: 0 }); bullets(s, ['Seven more 2026 weekends and three past seasons on disk', 'The gate and scored fallback, the push diagnostic, compound offsets from practice or qualifying medians, replay scoring', 'The liquid-network ablation, the dashboard, Madrid live', 'The lock contract, sealed holdout, build control; Live Predictor and Ghost Strategy integrated at C4'], 0.65, 3.25, 4.1, 1.7, 10.5);
  card(s, 5.1, 1.4, 4.4, 3.6); s.addText('Three questions for you', { x: 5.25, y: 1.5, w: 4.1, h: 0.3, fontFace: F, fontSize: 12, bold: true, color: TEAL, isTextBox: true, margin: 0 });
  [['1', 'Is a stated fuel prior with a published sensitivity sweep acceptable, or would you insist on estimating fuel from race pit steps?'], ['2', 'On the live decision card: gain, probability, downside, rejoin margin, and why it moved. What would a strategist add or remove?'], ['3', 'For a junior series with two engineers and public timing only, is a withheld-with-fallback answer more useful than a forced curve?']].forEach(([n, q], i) => { const y = 1.95 + i * 1.0; num(s, 5.25, y, n, TEAL); s.addText(q, { x: 5.7, y: y - 0.02, w: 3.65, h: 0.95, fontFace: F, fontSize: 10.5, color: INK, valign: 'top', isTextBox: true, margin: 0 }); }); }

// PptxGenJS emits unused slide-master content-type overrides for this deck.
// Remove only orphan metadata; never delete an actual part or repair a missing relationship target.
async function writeDeck() {
  const fileName = OUT + 'Orb_v1_Mentor_Briefing.pptx';
  await pres.writeFile({ fileName });
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(fs.readFileSync(fileName));
  const relations = (await Promise.all(Object.keys(zip.files).filter(n => n.endsWith('.rels')).map(n => zip.file(n).async('string')))).join('\n');
  const contentTypes = await zip.file('[Content_Types].xml').async('string');
  let removed = 0;
  const cleaned = contentTypes.replace(/<Override\b[^>]*PartName="(\/ppt\/slideMasters\/[^"]+)"[^>]*\/>/g, (entry, part) => {
    if (zip.file(part.slice(1))) return entry;
    if (relations.includes(part.split('/').pop())) throw new Error(`Missing referenced master ${part}`);
    removed += 1;
    return '';
  });
  if (removed) { zip.file('[Content_Types].xml', cleaned); fs.writeFileSync(fileName, await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' })); }
  console.log(`written ${fileName}; ${pres._slides.length} slides; removed ${removed} unused master content-type entries`);
}
writeDeck().catch(error => { console.error(error); process.exitCode = 1; });

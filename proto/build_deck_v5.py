"""Orb v1 Challenge Day deck (PDF via matplotlib). Every number is read from out/lock.json / out/liquid.json."""
import json, os, textwrap, hashlib, numpy as np, pandas as pd, datetime as dt
from pathlib import Path
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.image as mpimg
import theme; from theme import DISPLAY, TEXT, BG, INK, MUTED, RED, GOLD, SLATE, PANEL, LINE
L = json.load(open('out/lock.json')); V = pd.DataFrame(L['validation_rows']); val = L['validation']; S = L['strategy']
LQ = json.load(open('out/liquid.json')) if os.path.exists('out/liquid.json') else {}
L2 = json.loads(Path('out/lock_v2.json').read_text())
val = L2['validation']  # C5: validation summary consumed from lock v2
FC = json.loads(Path('out/forecast_Madrid_2026.json').read_text())
def sha256_file(name): return hashlib.sha256(Path('out', name).read_bytes()).hexdigest()
HASHES = {name: sha256_file(name) for name in ('forecast_Madrid_2026.json', 'forecast_Madrid_2026.pdf', 'forecast_Madrid_2026.sha256')}
LISTED = dict((line.split()[1], line.split()[0]) for line in Path('out/forecast_Madrid_2026.sha256').read_text().splitlines() if line.strip())
assert all(LISTED[n] == HASHES[n] for n in ('forecast_Madrid_2026.json', 'forecast_Madrid_2026.pdf'))
assert FC['lock_sha256'] == sha256_file('lock.json') and FC['lock_v2_sha256'] == sha256_file('lock_v2.json')
assert FC['lock_v2_forecast_hash'] == L2['shared']['forecast_hash']
MAD2 = L2['pre_race_forecast']['events']['Madrid']
WH = V[~V['issued']]; ISS = V[V['issued']]
WH_TXT = f"Withheld compounds: median race-derived reference {WH.obs.median():.3f} s/lap; {(WH.obs < .06).sum()} of {len(WH)} below 0.06; band covered {((WH.lo <= WH.obs) & (WH.obs <= WH.hi)).sum()} of {len(WH)}."
W, H = 13.333, 7.5; TEAM = "Team Orb v1 · Samuel Christ"; N = 10

def new(rule=True):
    fig = plt.figure(figsize=(W, H)); fig.patch.set_facecolor(BG); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis('off')
    for i, c in enumerate([RED, GOLD, SLATE]): ax.add_patch(plt.Rectangle((0.7 + i * 0.5, H - 0.3), 0.42, 0.05, color=c))
    if rule: ax.plot([0.7, W - 0.7], [H - 1.22, H - 1.22], color=LINE, lw=0.8)
    return fig, ax
def T(ax, x, y, s, size=12, color=INK, weight='normal', ha='left', va='top', wrap_in=None, ls=1.35, family=None):
    if wrap_in: cpl = max(10, int(wrap_in * 72 / (size * 0.52))); s = "\n".join(textwrap.fill(p, cpl) if p else "" for p in s.split("\n"))
    ax.text(x, y, s, fontsize=size, color=color, weight=weight, ha=ha, va=va, linespacing=ls, family=family)
def title(ax, s, y=H - 0.5, size=34): T(ax, 0.7, y, s, size=size, weight='bold', family=DISPLAY)
def sub(ax, s, y=H - 1.05, size=13): T(ax, 0.7, y, s, size=size, color=MUTED)
def card(ax, x, y, w, h, fc=PANEL): ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec=LINE, lw=0.8))
def bullets(ax, x, y, items, size=12, wrap_in=5.5, gap=0.35, dot=RED, color=INK):
    for it in items:
        ax.plot([x + 0.08], [y - 0.11], marker='o', ms=4.5, color=dot, ls='none'); T(ax, x + 0.3, y, it, size=size, wrap_in=wrap_in, color=color)
        n = len(textwrap.fill(it, max(10, int(wrap_in * 72 / (size * 0.52)))).split("\n")); y -= gap * 0.55 + n * size * 1.35 / 72
    return y
def img(ax, path, x, y, w=None, h=None):
    im = mpimg.imread(path); ar = im.shape[0] / im.shape[1]
    if w is None: w = h / ar
    if h is None: h = w * ar
    ax.imshow(im, extent=[x, x + w, y, y + h], aspect='auto'); return w, h
def footer(ax, n): T(ax, W - 0.7, 0.35, f"Orb v1 · {TEAM} · TrackShift 2026 · {n}/{N}", size=9, color=MUTED, ha='right', va='bottom')
def table(ax, x, y, cols, rows, cw, size=11, head=MUTED, rowh=0.42):
    for j, h in enumerate(cols): T(ax, x + sum(cw[:j]), y, h, size=size - 1, weight='bold', color=head)
    for i, r in enumerate(rows):
        for j, v in enumerate(r): T(ax, x + sum(cw[:j]), y - rowh * (i + 1), str(v), size=size, color=(INK if j else INK), weight=('bold' if j == 0 else 'normal'))
    return y - rowh * (len(rows) + 1)

figs = []
# 1 title
fig, ax = new(rule=False); figs.append(fig)
T(ax, 0.7, H - 1.6, "Orb v1", size=72, weight='bold', family=DISPLAY)
T(ax, 0.7, H - 3.0, "Clean tyre-degradation curves from Friday, scored on Sunday.", size=22, color=INK)
T(ax, 0.7, H - 3.8, "Friday lies twice. We correct the lie you can measure and learn the one you can't.", size=16, color=MUTED, wrap_in=9)
T(ax, 0.7, 1.9, f"{TEAM}\nTrackShift 2026 · Tyre Degradation Intelligence · Plaksha University, 12–13 September 2026", size=12, color=MUTED)
T(ax, 0.7, 0.9, "Submitted to the idea round as ClearStint, renamed Orb v1. Built on disclosed pre-work from that round (estimator and 6-weekend validation, 5 Sep); everything else on these slides was built at Plaksha.", size=10, color=MUTED, wrap_in=11)
for i, c in enumerate([RED, GOLD, SLATE]): ax.plot([W - 2.6, W - 0.8], [1.3 + i * 0.8, 1.3 + i * 0.8 + (0.9 - 0.35 * i)], color=c, lw=6, solid_capstyle='round')

# 2 the problem
hun = V[(V.event == 'Hungary') & (V.compound == 'MEDIUM')].iloc[0]
fig, ax = new(); figs.append(fig); title(ax, "A Friday lap time is not a tyre measurement"); sub(ax, "lap time = fuel burn + track evolution + traffic + driver + push profile + tyre")
T(ax, 0.7, H - 1.7, f"Hungary 2026, medium tyre", size=13, color=MUTED)
T(ax, 0.7, H - 2.1, f"{hun.naive:+.2f} s/lap", size=44, weight='bold', family=DISPLAY, color=GOLD); T(ax, 0.7, H - 3.05, "a straight line through Friday's long runs", size=12, color=MUTED)
T(ax, 0.7, H - 3.7, f"{hun.obs:+.2f} s/lap", size=44, weight='bold', family=DISPLAY, color=INK); T(ax, 0.7, H - 4.65, f"what the race showed — wrong by {hun.naive / hun.obs:.0f}×", size=12, color=MUTED)
card(ax, 6.6, 1.2, 6.0, 4.9)
T(ax, 6.9, H - 1.65, "Two lies, two fixes", size=15, weight='bold', family=DISPLAY)
bullets(ax, 6.9, H - 2.15, ["Lie one, measurable: fuel, track evolution, traffic, driver and push profile are in the lap time. We strip them, lap by lap, from public telemetry.",
                           "Lie two, not measurable on Friday: drivers attack tyres in practice and manage them on Sunday. We learn how much, per compound, from other weekends in leave-one-weekend-out evaluation, and score it every Sunday.",
                           "When Friday has no signal, the curve is withheld. The fallback uses other withheld cases; its error and coverage remain visible."], size=11.5, wrap_in=5.4)
footer(ax, 2)

# 3 pipeline
fig, ax = new(); figs.append(fig); title(ax, "What Orb v1 does, in six steps"); sub(ax, "Same estimator on practice and race, so the practice-to-race ratio is a property of the data, not of the method")
steps = [("Ingest", "FastF1 timing archive: laps, 3.7 Hz telemetry, weather, race control. Telemetry quality checked lap by lap; degraded feeds refused."),
         ("Clean", "Stint fixed effects absorb driver, car and fuel load. Fuel prior 1.1 kg/lap; track evolution measured from every driver's push laps; traffic laps dropped via gap-to-car-ahead."),
         ("Gate", "A curve is issued only with 30+ clean long-run laps and a positive cleaned slope. Otherwise: withheld, with the reason."),
         ("Learn", "Race ÷ practice ratio per compound from other weekends in leave-one-weekend-out evaluation; applied when a majority agree within ±50%."),
         ("Forecast", "Curve × factor with a 90% band; withheld compounds get the fallback learned from other withheld cases."),
         ("Score", "Sunday night: the race analysed with the same estimator; predicted vs observed, per compound, every weekend.")]
for i, (h, b) in enumerate(steps):
    x = 0.7 + i * 2.02; card(ax, x, 1.5, 1.86, 4.5); T(ax, x + 0.15, 5.75, f"{i + 1}", size=26, weight='bold', family=DISPLAY, color=[RED, GOLD, SLATE, RED, GOLD, SLATE][i]); T(ax, x + 0.15, 5.1, h, size=15, weight='bold', family=DISPLAY); T(ax, x + 0.15, 4.6, b, size=9.8, wrap_in=1.65, color=INK)
footer(ax, 3)

# 4 transfer proof
fig, ax = new(); figs.append(fig); title(ax, "Friday transfers, once you learn how Sunday is managed"); sub(ax, f"{val['n_weekends']} weekends, {val['n_compound_weekends']} compound-weekends, every number leave-one-weekend-out; the held-out weekend never sees its own race")
m = val['mae_issued']; a = val['mae_all_with_fallback']; cal = val['calibration']
rows = [["Naive pooled fit", f"{a['naive']:.3f}", f"{cal['naive']['slope']:+.2f}", f"{cal['naive']['r']:+.2f}"], ["Cleaned Friday curve (issued)", f"{m['clean']:.3f}", f"{cal['clean']['slope']:+.2f}", f"{cal['clean']['r']:+.2f}"],
        ["Orb v1 (issued)", f"{m['clearstint']:.3f}", f"{cal['clearstint']['slope']:+.2f}", f"{cal['clearstint']['r']:+.2f}"], ["Orb v1, all cases incl. fallback", f"{a['clearstint']:.3f}", f"{cal['all_with_fallback']['slope']:+.2f}", f"{cal['all_with_fallback']['r']:+.2f}"]]
y = table(ax, 0.7, H - 1.7, ["", "MAE s/lap", "calib. slope", "r"], rows, [3.4, 1.05, 1.25, 0.6], size=10.5)
bullets(ax, 0.7, y - 0.3, [WH_TXT,
                          f"Orb v1 beats the naive fit on {val['wins_clearstint_over_naive']} of {val['n_compound_weekends']} cases; 90% interval on its error {val['ci90_mae_clearstint_all'][0]:.3f} to {val['ci90_mae_clearstint_all'][1]:.3f} s/lap.",
                          "Season transfer factors: medium ×%.2f and soft ×%.2f; hard not applied. Each held-out weekend uses its own training pool." % (val['by_compound']['MEDIUM']['k_median'], val['by_compound']['SOFT']['k_median'])], size=11, wrap_in=6.3)
img(ax, 'out/fig_calibration.png', 7.7, 1.25, h=4.9)
T(ax, 0.7, 0.75, "One public 2026 analysis concludes practice curves do not transfer. It tests stop-by-stop pit deltas, a target whose spread is about its mean. At the compound-weekend level, with the management factor learned, they do.", size=9, color=MUTED, wrap_in=12)
footer(ax, 4)

# 5 fifth confounder
pdg = val['push_diagnostic']; fig, ax = new(); figs.append(fig); title(ax, "The driver's push profile"); sub(ax, "Tyre energy per lap from position and speed traces; a public proxy")
img(ax, 'out/fig_push.png', 0.6, 2.4, h=3.7); img(ax, 'out/fig_withheld.png', 6.9, 2.4, h=3.7)
wrong = WH[WH.clean < 0]; falling = WH[WH.energy_trend < 0]
bullets(ax, 0.7, 2.25, [f"Where the cleaned slope pointed the wrong way ({len(wrong)} cases), energy rose through the run in {(wrong.energy_trend > 0).sum()}. {len(falling)} withheld cases had falling energy trends, so ramping is not universal.",
                        "Practice and race energy coefficients are estimates, not physical constants. Their event-specific values are reported in the lock; the push-adjusted forecast is a second opinion.",
                        f"On {val['path_b_push_adjusted']['n_withheld_with_push_signal']} withheld cases with a push signal: push-adjusted MAE {val['path_b_push_adjusted']['mae_push_adjusted']:.3f} vs fallback {val['path_b_push_adjusted']['mae_fallback']:.3f} s/lap. This subset differs from the full withheld pool."], size=10.5, wrap_in=11.8, gap=0.25)
footer(ax, 5)

# 6 Madrid: frozen published forecast, lock-v2 data and full digests
fig, ax = new(); figs.append(fig); title(ax, "Madrid: the frozen forecast")
sub(ax, f"{', '.join(FC['sessions_used'])} in the lock; published {FC['issued_at'][11:19]} IST. Hashed before the race, verifiable after the event.")
img(ax, 'out/fig_madrid.png', 0.6, 2.4, h=3.5)
for i, c in enumerate(MAD2['compounds'].values()):
    x0 = 7.6; y0 = 5.7 - i * 1.35; card(ax, x0, y0 - 1.15, 5.1, 1.2)
    T(ax, x0 + .2, y0 - .05, f"{c['compound'].title()}: {c['prediction']:+.3f} s/lap", size=16, weight='bold', family=DISPLAY, color={'SOFT': RED, 'MEDIUM': GOLD}[c['compound']])
    T(ax, x0 + .2, y0 - .43, f"90% band {c['band90'][0]:+.3f} to {c['band90'][1]:+.3f}; n={c['n_prac']} clean practice laps", size=11)
    T(ax, x0 + .2, y0 - .78, 'issued' if c['issued'] else 'withheld: ' + c['gate'], size=9, wrap_in=4.7, color=MUTED)
st = MAD2['strategy']
T(ax, 7.6, 2.75, f"Central plan: {st['plan']} {'/'.join(map(str, st['stints']))}; band-high {st['band_high_plan']}. Pit loss {st['pit_loss_s']:g} s. Hard has no issued curve.", size=10, wrap_in=5.0)
lines = [('JSON SHA256', HASHES['forecast_Madrid_2026.json']), ('PDF SHA256', HASHES['forecast_Madrid_2026.pdf']), ('SHA256 sidecar', HASHES['forecast_Madrid_2026.sha256']), ('lock v2 forecast_hash', L2['shared']['forecast_hash'].removeprefix('sha256:'))]
for i, (label, digest) in enumerate(lines): T(ax, .7, 1.9-i*.3, label + ' ' + digest, size=8.5, family='monospace', color=MUTED)
footer(ax, 6)

# 7 decisions
evs = [e for e, rec in S.items() if all(rec.get('views', {}).get(v, {}).get('cost_under_truth_vs_best_s') is not None for v in ('Orb v1', 'Naive fit'))]
wins = sum(S[e]['views']['Orb v1']['cost_under_truth_vs_best_s'] < S[e]['views']['Naive fit']['cost_under_truth_vs_best_s'] for e in evs)
fig, ax = new(); figs.append(fig); title(ax, "The curve is only useful as a decision"); sub(ax, "Held-out strategy replay under a post-race reference model; development pool, never sealed weekends")
img(ax, 'out/fig_strategy.png', 0.6, 1.6, h=4.1)
bullets(ax, 8.2, H - 1.7, [f"Orb v1's plan beats the naive plan in {wins} of {len(evs)} replays.", f"Hungary: naive +{S['Hungary']['views']['Naive fit']['cost_under_truth_vs_best_s']:.0f} s, Orb v1 +{S['Hungary']['views']['Orb v1']['cost_under_truth_vs_best_s']:.0f} s. Monza: +{S['Monza']['views']['Naive fit']['cost_under_truth_vs_best_s']:.0f} s vs {S['Monza']['views']['Orb v1']['cost_under_truth_vs_best_s']:.0f} s. Zandvoort: +{S['Zandvoort']['views']['Naive fit']['cost_under_truth_vs_best_s']:.0f} s vs +{S['Zandvoort']['views']['Orb v1']['cost_under_truth_vs_best_s']:.0f} s.",
                           "The misses are Barcelona and Australia. The replay is model-implied; it does not claim observed race time saved.",
                           "Offsets from practice or qualifying medians, with a nominal step for implausible measurements; 21 s pit loss; linear curves; no safety car or weather."], size=10.5, wrap_in=4.5)
footer(ax, 7)

# 8 liquid: ablation only, from its original evidence
if LQ:
    cells = [m for o in LQ.values() for m in o['by_compound'].values() if all(m.get(k) is not None for k in ('mae_linear', 'mae_quadratic', 'mae_linear_cov', 'mae_liquid'))]
    wins = sum(m['mae_liquid'] < min(m['mae_linear'], m['mae_quadratic'], m['mae_linear_cov']) for m in cells)
    fig, ax = new(); figs.append(fig); title(ax, "The neural model: an ablation, not the forecast"); sub(ax, "Race stints held out against linear, quadratic and covariate baselines")
    img(ax, 'out/fig_liquid.png', 0.6, 1.5, h=4.4)
    bullets(ax, 7.4, H - 1.7, [f"The network beat the best baseline in {wins} of {len(cells)} evaluated cells with the same per-lap inputs.",
                              "This experiment tests whether a flexible model adds value to the inputs. It does not establish a tyre-wear sensor or a validated cliff detector.",
                              "The deployed pre-race forecast remains the cleaned curve with its learned transfer and explicit fallback. The neural experiment remains an ablation."], size=11, wrap_in=5.3)
    footer(ax, 8)

# 9 product & who
fig, ax = new(); figs.append(fig); title(ax, "The product: Live Predictor and Ghost Strategy"); sub(ax, "Every number traces to the lock, a hashed sidecar, a labelled computation or a placeholder")
bullets(ax, 0.7, H - 1.7, ["Live weekend: issued and withheld cards, bands, the cleaned laps behind the curve, and why a compound was withheld.", "Sunday scorecard: predicted vs observed per compound, the week after.", "Strategy: crossover laps, one-stop vs two-stop, stint lengths, cost under the observed curves.",
                          "Season validation: calibration, transfer factors, issued and withheld compounds.", "Excluded laps: every dropped practice lap with its reason. Method and assumptions: every prior, stated.", "Live Predictor updates a frozen prior from observed laps. Ghost Strategy explains model-implied alternative tyre plans."], size=10.8, wrap_in=5.9, gap=0.28)
card(ax, 7.4, 1.3, 5.2, 4.9); T(ax, 7.65, H - 1.65, "Who this is for", size=15, weight='bold', family=DISPLAY)
bullets(ax, 7.65, H - 2.15, ["Categories with thin data and two engineers: F2, F3, F1 Academy, Indian F4, sim leagues, broadcasters. Public timing in, decision out, for any weekend by name.",
                            "A works team has better data; the method transfers to it, the product serves the rest.",
                            "Beyond the track, the same loop, measure the confounders, gate, learn the transfer, score against race-derived pace-loss references, fits fleet tyre wear and e-rickshaw battery health, where load, road, heat and driver stand in for fuel, evolution, traffic and push."], size=10.5, wrap_in=4.7, gap=0.28)
footer(ax, 9)

# 10 built when, limits, next
fig, ax = new(); figs.append(fig); title(ax, "Built when, what it cannot do yet, and Sunday night"); sub(ax, "Disclosed pre-work vs Challenge Day build, as the rules ask")
card(ax, 0.7, 1.3, 3.9, 4.9); T(ax, 0.95, H - 1.65, "Disclosed pre-work (5 Sep)", size=14, weight='bold', family=DISPLAY)
bullets(ax, 0.95, H - 2.15, ["Feature extraction and the fixed-effects estimator.", "Six-weekend leave-one-out validation and the transfer factor rule.", "Hungary and Austria strategy replay."], size=10.5, wrap_in=3.3)
card(ax, 4.8, 1.3, 3.9, 4.9); T(ax, 5.05, H - 1.65, "Built at Plaksha", size=14, weight='bold', family=DISPLAY)
bullets(ax, 5.05, H - 2.15, [f"{val['n_weekends']} scored weekends incl. sprint format; Madrid live.", "The gate's low-degradation fallback and the push-profile diagnostic.", "Offsets with their measured or nominal basis; strategy replay.", "Liquid model and its ablation.", "Dashboard, lock file, one-command refresh."], size=10.5, wrap_in=3.3, gap=0.25)
card(ax, 8.9, 1.3, 3.75, 4.9); T(ax, 9.15, H - 1.65, "Limits and next", size=14, weight='bold', family=DISPLAY)
sj = json.load(open('out/sensitivity.json'))['runs'] if os.path.exists('out/sensitivity.json') else {}; bc = val.get('band_coverage', {})
bullets(ax, 9.15, H - 2.15, ["Linear curves; fuel prior assumed (a race-data estimate agrees at 0.029 s/kg).",
                            (f"Headline error stays {min(v['mae'] for v in sj.values()):.3f} to {max(v['mae'] for v in sj.values()):.3f} s/lap across fuel prior 0.9–1.3 kg/lap, 0.025–0.035 s/kg, traffic 20–40%, runs 4–7 laps." if sj else "Sensitivity table pending."),
                            (f"Bands: raw 90% bands covered {100*bc['raw_all']:.0f}%; conformally widened leave-one-out they cover {100*bc['calibrated_all']:.0f}%." if bc else "Bands not yet checked."),
                            "Separate development, sealed and prospective evaluation. See the generated scorecards for counts and uncertainty.", "Madrid: hashed before the race, verifiable after the event. The frozen forecast will be checked when race data exists."], size=10, wrap_in=3.15, gap=0.22)
footer(ax, 10)

with PdfPages('out/Orb_v1_ChallengeDay.pdf') as pdf:
    for i, f in enumerate(figs, 1): f.savefig(f'out/slide-{i:02d}.png', dpi=110, facecolor=f.get_facecolor()); pdf.savefig(f, facecolor=f.get_facecolor())
print(f"deck: {len(figs)} slides -> out/Orb_v1_ChallengeDay.pdf")

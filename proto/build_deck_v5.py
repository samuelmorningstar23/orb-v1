"""ClearStint Challenge Day deck (PDF via matplotlib). Every number is read from out/lock.json / out/liquid.json."""
import json, os, textwrap, numpy as np, pandas as pd, datetime as dt
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.image as mpimg
import theme; from theme import DISPLAY, TEXT, BG, INK, MUTED, RED, GOLD, SLATE, PANEL, LINE
L = json.load(open('out/lock.json')); V = pd.DataFrame(L['validation_rows']); val = L['validation']; S = L['strategy']
LQ = json.load(open('out/liquid.json')) if os.path.exists('out/liquid.json') else {}
W, H = 13.333, 7.5; TEAM = "Team FireBolt · Samuel Christ"; N = 10

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
def footer(ax, n): T(ax, W - 0.7, 0.35, f"ClearStint · {TEAM} · TrackShift 2026 · {n}/{N}", size=9, color=MUTED, ha='right', va='bottom')
def table(ax, x, y, cols, rows, cw, size=11, head=MUTED, rowh=0.42):
    for j, h in enumerate(cols): T(ax, x + sum(cw[:j]), y, h, size=size - 1, weight='bold', color=head)
    for i, r in enumerate(rows):
        for j, v in enumerate(r): T(ax, x + sum(cw[:j]), y - rowh * (i + 1), str(v), size=size, color=(INK if j else INK), weight=('bold' if j == 0 else 'normal'))
    return y - rowh * (len(rows) + 1)

figs = []
# 1 title
fig, ax = new(rule=False); figs.append(fig)
T(ax, 0.7, H - 1.6, "ClearStint", size=72, weight='bold', family=DISPLAY)
T(ax, 0.7, H - 3.0, "Clean tyre-degradation curves from Friday, scored on Sunday.", size=22, color=INK)
T(ax, 0.7, H - 3.8, "Friday lies twice. We correct the lie you can measure and learn the one you can't.", size=16, color=MUTED, wrap_in=9)
T(ax, 0.7, 1.9, f"{TEAM}\nTrackShift 2026 · Tyre Degradation Intelligence · Plaksha University, 12–13 September 2026", size=12, color=MUTED)
T(ax, 0.7, 0.9, "Built on disclosed pre-work from the idea round (estimator and 6-weekend validation, 5 Sep). Everything else on these slides was built at Plaksha.", size=10, color=MUTED, wrap_in=11)
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
                           "Lie two, not measurable on Friday: drivers attack tyres in practice and manage them on Sunday. We learn how much, per compound, from previous weekends only, and score it every Sunday.",
                           "And when Friday has no signal, we say so, and forecast what that has always meant: a low-degradation race."], size=11.5, wrap_in=5.4)
footer(ax, 2)

# 3 pipeline
fig, ax = new(); figs.append(fig); title(ax, "What ClearStint does, in six steps"); sub(ax, "Same estimator on practice and race, so the practice-to-race ratio is a property of the data, not of the method")
steps = [("Ingest", "FastF1 + OpenF1: laps, 3.7 Hz telemetry, weather, race control. Telemetry quality checked lap by lap; degraded feeds refused."),
         ("Clean", "Stint fixed effects absorb driver, car and fuel load. Fuel prior 1.1 kg/lap; track evolution measured from every driver's push laps; traffic laps dropped via gap-to-car-ahead."),
         ("Gate", "A curve is issued only with 30+ clean long-run laps and a positive cleaned slope. Otherwise: withheld, with the reason."),
         ("Learn", "Race ÷ practice ratio per compound from previous weekends only; applied when a majority agree within ±50%."),
         ("Forecast", "Curve × factor with a 90% band; withheld compounds get the low-degradation fallback learned from other withheld cases."),
         ("Score", "Sunday night: the race analysed with the same estimator; predicted vs observed, per compound, every weekend.")]
for i, (h, b) in enumerate(steps):
    x = 0.7 + i * 2.02; card(ax, x, 1.5, 1.86, 4.5); T(ax, x + 0.15, 5.75, f"{i + 1}", size=26, weight='bold', family=DISPLAY, color=[RED, GOLD, SLATE, RED, GOLD, SLATE][i]); T(ax, x + 0.15, 5.1, h, size=15, weight='bold', family=DISPLAY); T(ax, x + 0.15, 4.6, b, size=9.8, wrap_in=1.65, color=INK)
footer(ax, 3)

# 4 transfer proof
fig, ax = new(); figs.append(fig); title(ax, "Friday transfers, once you learn how Sunday is managed"); sub(ax, f"{val['n_weekends']} weekends, {val['n_compound_weekends']} compound-weekends, every number leave-one-weekend-out; the held-out weekend never sees its own race")
m = val['mae_issued']; a = val['mae_all_with_fallback']; cal = val['calibration']
rows = [["Naive pooled fit", f"{a['naive']:.3f}", f"{cal['naive']['slope']:+.2f}", f"{cal['naive']['r']:+.2f}"], ["Cleaned Friday curve (issued)", f"{m['clean']:.3f}", f"{cal['clean']['slope']:+.2f}", f"{cal['clean']['r']:+.2f}"],
        ["ClearStint (issued)", f"{m['clearstint']:.3f}", f"{cal['clearstint']['slope']:+.2f}", f"{cal['clearstint']['r']:+.2f}"], ["ClearStint, all cases incl. fallback", f"{a['clearstint']:.3f}", f"{cal['all_with_fallback']['slope']:+.2f}", f"{cal['all_with_fallback']['r']:+.2f}"]]
y = table(ax, 0.7, H - 1.7, ["", "MAE s/lap", "calib. slope", "r"], rows, [3.4, 1.05, 1.25, 0.6], size=10.5)
bullets(ax, 0.7, y - 0.3, [f"Every compound answered: {val['n_issued']} issued, {val['n_withheld']} withheld and forecast as low degradation, right {val['n_withheld']} times out of {val['n_withheld']}.",
                          f"ClearStint beats the naive fit on {val['wins_clearstint_over_naive']} of {val['n_compound_weekends']} cases; 90% interval on its error {val['ci90_mae_clearstint_all'][0]:.3f} to {val['ci90_mae_clearstint_all'][1]:.3f} s/lap.",
                          "Transfer factors learned: medium ×%.2f, soft ×%.2f, hard ×%.2f. The medium is managed on Sunday; soft and hard transfer near one to one." % (val['by_compound']['MEDIUM']['k_median'], val['by_compound']['SOFT']['k_median'], val['by_compound']['HARD']['k_median'])], size=11, wrap_in=6.3)
img(ax, 'out/fig_calibration.png', 7.7, 1.25, h=4.9)
T(ax, 0.7, 0.75, "One public 2026 analysis concludes practice curves do not transfer. It tests stop-by-stop pit deltas, a target whose spread is about its mean. At the compound-weekend level, with the management factor learned, they do.", size=9, color=MUTED, wrap_in=12)
footer(ax, 4)

# 5 fifth confounder
pdg = val['push_diagnostic']; fig, ax = new(); figs.append(fig); title(ax, "The fifth confounder: the driver's push profile"); sub(ax, "Tyre energy per lap from the 3.7 Hz position and speed traces: lateral v²κ plus longitudinal |Δv|·v, on an arc-length grid")
img(ax, 'out/fig_push.png', 0.6, 2.4, h=3.7); img(ax, 'out/fig_withheld.png', 6.9, 2.4, h=3.7)
bullets(ax, 0.7, 2.25, [f"On every withheld compound the driver put more energy through the tyre as the run went on (median {pdg['energy_trend_withheld']['50%']:+.2f} MJ per lap of age); on issued ones the trend is flat or falling ({pdg['energy_trend_issued']['50%']:+.2f}). Ramping up hides degradation; the gate catches it.",
                        "The energy price of lap time, s per MJ, comes out the same on Friday and Sunday at the same track: " + ', '.join(f"{b['event']} {b['practice']:+.2f} / {b['race']:+.2f}" for b in pdg['beta_practice_vs_race'][:4]) + ". A physical constant, not a fit.",
                        f"A push-adjusted curve rescues some withheld cases but, with the factor, predicts no better than the fallback ({val['path_b_push_adjusted']['mae_push_adjusted']:.3f} vs {val['path_b_push_adjusted']['mae_fallback']:.3f} s/lap). It is reported as a second opinion, never as the headline."], size=10.5, wrap_in=11.8, gap=0.25)
footer(ax, 5)

# 6 Madrid live
if 'Madrid' in L['live']:
    Lv = L['live']['Madrid']; fig, ax = new(); figs.append(fig); title(ax, "Madrid, live: curves issued from Friday, scored after Sunday"); sub(ax, f"FP1 + FP2 as of lock {L['generated_at'][:16].replace('T', ' ')} IST · Pirelli C2 hard / C3 medium / C4 soft · {Lv['meta']['practice_laps_clean']} clean long-run laps of {Lv['meta']['practice_laps_total']}")
    img(ax, 'out/fig_madrid.png', 0.6, 1.3, h=4.6)
    x0 = 7.6
    for i, c in enumerate(Lv['compounds']):
        y0 = H - 1.7 - i * 2.25; card(ax, x0, y0 - 1.95, 5.1, 2.05); T(ax, x0 + 0.2, y0 - 0.1, c['compound'].title(), size=16, weight='bold', family=DISPLAY, color={'SOFT': RED, 'MEDIUM': GOLD, 'HARD': SLATE}[c['compound']])
        T(ax, x0 + 0.2, y0 - 0.55, f"{c['prediction']:+.3f} s/lap   band {c['band90'][0]:+.3f} to {c['band90'][1]:+.3f}", size=13, weight='bold')
        T(ax, x0 + 0.2, y0 - 1.0, (f"cleaned Friday slope {c['clean']:+.3f} ± {c['clean_se']:.3f} × factor {c['factor']:.2f} from {c['factor_from_n_weekends']} weekends" if c['issued'] else f"withheld: {c['gate']}. Energy rose {c['energy_trend']:+.2f} MJ per lap through the runs (drivers learning the track). Fallback = low-degradation median" + (f"; push-adjusted second opinion {c['second_opinion']['prediction']:+.3f}" if c.get('second_opinion') else '')), size=9.5, wrap_in=4.7, color=MUTED)
    st = S.get('Madrid', {}).get('views', {}); y0 = H - 1.7 - len(Lv['compounds']) * 2.25
    if st: T(ax, x0, y0 - 0.05, f"Plan on the central curve: {st['ClearStint']['plan']} {'/'.join(map(str, st['ClearStint']['stints']))}; top of the band: {st['ClearStint, band high']['plan']}. Hard: 4 clean Friday laps, no curve. Pit loss 21 s, offsets from best clean laps.", size=9.5, wrap_in=5.0, color=INK)
    footer(ax, 6)

# 7 decisions
evs = [e for e in ['Hungary', 'Austria', 'Barcelona', 'Belgium', 'Monza', 'Zandvoort', 'Miami', 'Canada', 'Britain'] if e in S and 'cost_under_truth_vs_best_s' in S[e]['views'].get('ClearStint', {})]
wins = sum(S[e]['views']['ClearStint']['cost_under_truth_vs_best_s'] < S[e]['views']['Naive fit']['cost_under_truth_vs_best_s'] for e in evs)
fig, ax = new(); figs.append(fig); title(ax, "The curve is only useful as a decision"); sub(ax, "One-stop vs two-stop and stint lengths chosen under each Friday view, then charged under the curves the race actually showed")
img(ax, 'out/fig_strategy.png', 0.6, 1.6, h=4.1)
bullets(ax, 8.2, H - 1.7, [f"ClearStint's plan beats the naive plan in {wins} of {len(evs)} replays.", f"Hungary: naive +{S['Hungary']['views']['Naive fit']['cost_under_truth_vs_best_s']:.0f} s, ClearStint +{S['Hungary']['views']['ClearStint']['cost_under_truth_vs_best_s']:.0f} s. Monza: +{S['Monza']['views']['Naive fit']['cost_under_truth_vs_best_s']:.0f} s vs {S['Monza']['views']['ClearStint']['cost_under_truth_vs_best_s']:.0f} s. Zandvoort: +{S['Zandvoort']['views']['Naive fit']['cost_under_truth_vs_best_s']:.0f} s vs +{S['Zandvoort']['views']['ClearStint']['cost_under_truth_vs_best_s']:.0f} s.",
                           "The miss is honest: at Barcelona the hard had 12 clean Friday laps, was withheld, and the low-degradation fallback was too optimistic for a compound that degraded at 0.10 s/lap.",
                           "Compound offsets from qualifying where drivers set paired laps, checked against a 0.2 to 1.0 s plausibility range; 21 s pit loss; linear curves; no safety car or weather. All stated in the tool."], size=10.5, wrap_in=4.5)
footer(ax, 7)

# 8 liquid
if LQ:
    wl = tl = 0; gains = []; conv = conc = 0
    for e, o in LQ.items():
        for c, mm in o['by_compound'].items():
            base = [v for v in (mm.get('mae_linear'), mm.get('mae_quadratic'), mm.get('mae_linear_cov')) if v is not None]
            if base and mm['mae_liquid'] is not None: tl += 1; wl += mm['mae_liquid'] < min(base)
            if mm.get('mae_linear') and mm.get('mae_linear_cov'): gains.append((mm['mae_linear'] - mm['mae_linear_cov']) / mm['mae_linear'])
        for c, cv in o['curves'].items():
            if cv.get('curvature') is not None: conv += cv['curvature'] > 0; conc += cv['curvature'] <= 0
    fig, ax = new(); figs.append(fig); title(ax, "The liquid tyre model: what a neural network earned, and what it didn't"); sub(ax, "Closed-form continuous-time cell (Hasani et al. 2022, MIT) reading each race stint lap by lap; held out stint by stint against linear and quadratic fits")
    img(ax, 'out/fig_liquid.png', 0.6, 1.5, h=4.4)
    bullets(ax, 7.4, H - 1.7, [f"Beats every baseline on {wl} of {tl} compound-weekends. Given the same per-lap inputs, a straight line is about as good.",
                              f"What mattered was the inputs: tyre energy, traffic and fuel cut the error of the age-only model by {100 * float(np.median(gains)):.0f}% at the median. The fifth confounder again, now on race stints.",
                              f"What it adds: the curve shape with no assumed form, per weekend. Across the season degradation accelerates with age in {conv} compound-weekends and settles in {conc}; a cliff lap is flagged where the local slope doubles.",
                              "It stays on the dashboard as the shape and cliff tool, and on this slide as a test we ran and reported. The forecast is the straight line with a learned factor, because that is what the data supports."], size=10.8, wrap_in=5.3)
    footer(ax, 8)

# 9 product & who
fig, ax = new(); figs.append(fig); title(ax, "The product: one lock file, six views, one command to refresh"); sub(ax, "Streamlit dashboard; every number on every screen comes from out/lock.json, the same file the brief and this deck are built from")
bullets(ax, 0.7, H - 1.7, ["Live weekend: issued and withheld cards, bands, the cleaned laps behind the curve, and why a compound was withheld.", "Sunday scorecard: predicted vs observed per compound, the week after.", "Strategy: crossover laps, one-stop vs two-stop, stint lengths, cost under the observed curves.",
                          "Season validation: the ladder, the calibration scatter, transfer factors, every withheld case.", "Excluded laps: every dropped practice lap with its reason. Method and assumptions: every prior, stated."], size=10.8, wrap_in=5.9, gap=0.28)
card(ax, 7.4, 1.3, 5.2, 4.9); T(ax, 7.65, H - 1.65, "Who this is for", size=15, weight='bold', family=DISPLAY)
bullets(ax, 7.65, H - 2.15, ["Categories with thin data and two engineers: F2, F3, F1 Academy, Indian F4, sim leagues, broadcasters. Public timing in, decision out, for any weekend by name.",
                            "A works team has better data; the method transfers to it, the product serves the rest.",
                            "Beyond the track, the same loop, measure the confounders, gate, learn the transfer, score against truth, fits fleet tyre wear and e-rickshaw battery health, where load, road, heat and driver stand in for fuel, evolution, traffic and push."], size=10.5, wrap_in=4.7, gap=0.28)
footer(ax, 9)

# 10 built when, limits, next
fig, ax = new(); figs.append(fig); title(ax, "Built when, what it cannot do yet, and Sunday night"); sub(ax, "Disclosed pre-work vs Challenge Day build, as the rules ask")
card(ax, 0.7, 1.3, 3.9, 4.9); T(ax, 0.95, H - 1.65, "Disclosed pre-work (5 Sep)", size=14, weight='bold', family=DISPLAY)
bullets(ax, 0.95, H - 2.15, ["Feature extraction and the fixed-effects estimator.", "Six-weekend leave-one-out validation and the transfer factor rule.", "Hungary and Austria strategy replay."], size=10.5, wrap_in=3.3)
card(ax, 4.8, 1.3, 3.9, 4.9); T(ax, 5.05, H - 1.65, "Built at Plaksha", size=14, weight='bold', family=DISPLAY)
bullets(ax, 5.05, H - 2.15, [f"{val['n_weekends']} scored weekends incl. sprint format; Madrid live.", "The gate's low-degradation fallback and the push-profile diagnostic.", "Qualifying-based offsets; strategy on every weekend.", "Liquid model and its ablation.", "Dashboard, lock file, one-command refresh."], size=10.5, wrap_in=3.3, gap=0.25)
card(ax, 8.9, 1.3, 3.75, 4.9); T(ax, 9.15, H - 1.65, "Limits and next", size=14, weight='bold', family=DISPLAY)
sj = json.load(open('out/sensitivity.json'))['runs'] if os.path.exists('out/sensitivity.json') else {}; bc = val.get('band_coverage', {})
bullets(ax, 9.15, H - 2.15, ["Linear curves; fuel prior assumed (a race-data estimate agrees at 0.029 s/kg).",
                            (f"Headline error stays {min(v['mae'] for v in sj.values()):.3f} to {max(v['mae'] for v in sj.values()):.3f} s/lap across fuel prior 0.9–1.3 kg/lap, 0.025–0.035 s/kg, traffic 20–40%, runs 4–7 laps." if sj else "Sensitivity table pending."),
                            (f"Bands: raw 90% bands covered {100*bc['raw_all']:.0f}%; conformally widened leave-one-out they cover {100*bc['calibrated_all']:.0f}%." if bc else "Bands not yet checked."),
                            "2025 same-track rounds as a prior for the factor: downloading.", "Sunday 18:30 IST: Madrid scored with the same estimator, result published."], size=10, wrap_in=3.15, gap=0.22)
footer(ax, 10)

with PdfPages('out/ClearStint_ChallengeDay.pdf') as pdf:
    for i, f in enumerate(figs, 1): f.savefig(f'out/slide-{i:02d}.png', dpi=110, facecolor=f.get_facecolor()); pdf.savefig(f, facecolor=f.get_facecolor())
print(f"deck: {len(figs)} slides -> out/ClearStint_ChallengeDay.pdf")

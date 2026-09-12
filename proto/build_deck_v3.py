import json, textwrap, numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.image as mpimg

S = json.load(open('summary_v2.json')); ST = json.load(open('strategy.json'))
W, H = 13.333, 7.5
DARK, INK, MUTED, RED, GOLD, SLATE, PANEL, ROSE = '#15181D', '#1B1F24', '#5B636E', '#C8102E', '#D9A400', '#3A506B', '#F3F4F6', '#FFF4F5'
plt.rcParams['font.family'] = 'DejaVu Sans'
TEAM = "Team FireBolt  ·  Samuel Christ & Kaushal R"

def new(bg='white'):
    fig = plt.figure(figsize=(W, H)); fig.patch.set_facecolor(bg)
    ax = fig.add_axes([0,0,1,1]); ax.set_xlim(0,W); ax.set_ylim(0,H); ax.axis('off')
    for i,c in enumerate([RED, GOLD, SLATE]): ax.add_patch(plt.Rectangle((0.7+i*0.5, H-0.22), 0.42, 0.06, color=c))   # compound stripe, persistent
    return fig, ax
def T(ax, x, y, s, size=12, color=INK, weight='normal', ha='left', va='top', wrap_in=None, ls=1.35, family=None):
    if wrap_in:
        cpl = max(10, int(wrap_in*72/(size*0.52))); s = "\n".join(textwrap.fill(p, cpl) if p else "" for p in s.split("\n"))
    ax.text(x, y, s, fontsize=size, color=color, weight=weight, ha=ha, va=va, linespacing=ls, family=family)
def title(ax, s, color=INK, y=H-0.6, size=28): T(ax, 0.7, y, s, size=size, color=color, weight='bold')
def card(ax, x, y, w, h, fc=PANEL, ec='none', r=0.12): ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=1))
def bullets(ax, x, y, items, size=12.5, color=INK, wrap_in=5.5, gap=0.4, dot=RED):
    for it in items:
        ax.plot([x+0.08],[y-0.11], marker='o', ms=5, color=dot, ls='none'); T(ax, x+0.3, y, it, size=size, color=color, wrap_in=wrap_in)
        n = len(textwrap.fill(it, max(10,int(wrap_in*72/(size*0.52)))).split("\n")); y -= gap*0.55 + n*size*1.35/72
    return y
def img(ax, path, x, y, w=None, h=None):
    im = mpimg.imread(path); ar = im.shape[0]/im.shape[1]
    if w is None: w = h/ar
    if h is None: h = w*ar
    ax.imshow(im, extent=[x, x+w, y, y+h], aspect='auto'); return w, h
def footer(ax, n, light=False): T(ax, W-0.7, 0.35, f"ClearStint · Team FireBolt · TrackShift 2026 · {n}", size=9, color=('#8A9099' if light else MUTED), ha='right', va='bottom')

mae = S['mae']; ci = S['ci']; n_ev = len(S['events']); pc = S['per_comp']
hun = {r['compound']: r for r in S['per_event'].get('Hungary', [])}
naive_x = hun['MEDIUM']['naive']/hun['MEDIUM']['obs']
impr_A = 100*(1-mae['errC']/mae['errA']); impr_naive = 100*(1-mae['errC']/mae['err_naive'])
kmed = np.median(pc['MEDIUM']['k_values']) if 'MEDIUM' in pc else float('nan')
pages = []

# 1 Title
fig, ax = new(DARK)
T(ax, 0.9, H-1.2, "TRACKSHIFT 2026  ·  AI MOTORSPORT INTELLIGENCE  ·  TYRE DEGRADATION INTELLIGENCE", size=10.5, color='#8A9099', weight='bold')
T(ax, 0.9, H-1.85, "ClearStint", size=62, color='white', weight='bold')
T(ax, 0.9, H-3.15, "Friday lies about Sunday. ClearStint learns the lie.", size=26, color='white', weight='bold')
T(ax, 0.9, H-3.85, "Clean tyre-degradation curves from noisy practice sessions, a season-long loop that learns how practice maps to the race, and a tool that says when it cannot.", size=14.5, color='#C9CED5', wrap_in=8.4)
T(ax, 0.9, H-5.05, f"Working prototype · {S['n_prac_laps']:,} practice laps and {S['n_race_laps']:,} race laps · {n_ev} Grands Prix of 2026 · public data only · nothing tuned on the race", size=12, color=GOLD, wrap_in=8.4)
T(ax, 0.9, 1.0, f"{TEAM}  ·  Idea submission, 5 September 2026", size=12, color='#8A9099', va='bottom')
ax.add_patch(plt.Rectangle((W-3.0, 0), 3.0, H, color=RED, alpha=0.06))
for i,c in enumerate([RED, GOLD, SLATE]): ax.plot([W-2.5, W-0.8],[1.3+i*0.75, 1.3+i*0.75+(0.8-0.35*i)], color=c, lw=6, solid_capstyle='round')
pages.append(fig)

# 2 Big number
fig, ax = new(); title(ax, "How wrong is Friday?")
T(ax, 0.9, H-2.0, f"{naive_x:.0f}×", size=150, color=RED, weight='bold', va='top')
T(ax, 5.6, H-2.25, f"Hungary 2026, medium tyre. A straight line through Friday's long-run laps says it degrades at {hun['MEDIUM']['naive']:+.2f} s per lap. The race showed {hun['MEDIUM']['obs']:+.2f}.", size=15, wrap_in=6.9, ls=1.4)
T(ax, 5.6, H-3.75, "Because a lap time is fuel burn + track evolution + traffic + driver + tyre. Every team on the grid knows this. Only the tyre part is the answer.", size=12.5, color=MUTED, wrap_in=6.9)
card(ax, 0.9, 1.3, 11.55, 1.5, fc=ROSE)
T(ax, 1.15, 2.55, "And even a perfectly cleaned Friday curve is not Sunday's curve.", size=14, weight='bold', color=RED)
T(ax, 1.15, 2.1, "Drivers attack tyres in practice and manage them in the race. On the medium, race degradation ran at roughly 0.4 of the cleaned practice value, on every European weekend we tested. Nobody publicly measures this. We do, and we learn it race by race.", size=11.5, color=INK, wrap_in=11.0)
footer(ax, 2); pages.append(fig)

# 3 Hero validation
fig, ax = new(); title(ax, f"Tested on {n_ev} Grands Prix, leave-one-weekend-out")
T(ax, 0.7, H-1.3, "Fit on practice only. Transfer factors learned from the other weekends. Scored against the race with the same estimator. Mean absolute error in degradation, s/lap per lap of tyre age, with a 90% bootstrap interval.", size=11.5, color=MUTED, wrap_in=12)
rows = [("Naive fit on raw laps", mae['err_naive'], ci['err_naive'], '#9AA1AA'), ("Cleaned practice curve", mae['errA'], ci['errA'], SLATE), ("ClearStint: curve × learned transfer", mae['errC'], ci['errC'], RED)]
for i,(name, v, c_, col) in enumerate(rows):
    y = 4.55 - i*1.05; card(ax, 0.7, y-0.35, 7.6, 0.95, fc=(ROSE if i==2 else PANEL))
    T(ax, 0.95, y+0.45, name, size=12, weight=('bold' if i==2 else 'normal'), color=(RED if i==2 else INK))
    T(ax, 5.75, y+0.52, f"{v:.3f}", size=26, weight='bold', color=col)
    T(ax, 7.05, y+0.32, f"90% CI\n{c_[0]:.3f}–{c_[1]:.3f}", size=9, color=MUTED)
    ax.add_patch(plt.Rectangle((0.95, y-0.2), 6.9*v/mae['err_naive'], 0.16, color=col, alpha=0.85))
T(ax, 0.7, 1.35, f"Probability the transfer step lowers error, bootstrap over weekends: {100*S['p_C_beats_A']:.0f}%. Against a single global factor for all compounds, ClearStint wins {S['wins_C_over_G']} of {S['n_rows']}.", size=10.5, color=INK, wrap_in=7.6, va='bottom')
# per compound table
tx = 8.75; T(ax, tx, H-2.05, "By compound", size=13, weight='bold')
hdr = ["", "n", "Clean", "ClearStint", "Factor"]; cw = [0.95, 0.45, 0.85, 1.05, 0.9]
for j,h in enumerate(hdr): T(ax, tx+sum(cw[:j]), H-2.5, h, size=9.5, weight='bold', color=MUTED)
for i,c in enumerate(['SOFT','MEDIUM','HARD']):
    if c not in pc: continue
    d = pc[c]; yy = H-2.95-i*0.5
    card(ax, tx-0.1, yy-0.3, sum(cw)+0.15, 0.42, fc=(ROSE if d['k_applied'] else 'white'), r=0.05)
    T(ax, tx, yy, c.title(), size=10.5, weight='bold', color={'SOFT':RED,'MEDIUM':GOLD,'HARD':SLATE}[c])
    T(ax, tx+cw[0], yy, str(d['n']), size=10.5); T(ax, tx+sum(cw[:2]), yy, f"{d['mae_A']:.3f}", size=10.5)
    T(ax, tx+sum(cw[:3]), yy, f"{d['mae_C']:.3f}", size=10.5, weight='bold')
    T(ax, tx+sum(cw[:4]), yy, (f"×{np.median(d['k_values']):.2f}" if d['k_applied'] else "none"), size=10.5, color=(RED if d['k_applied'] else MUTED))
T(ax, tx, H-4.6, f"A factor is applied only where a majority of other weekends agree within ±50%. Today that is the medium: its error falls from {pc['MEDIUM']['mae_A']:.3f} to {pc['MEDIUM']['mae_C']:.3f} (90% CI on the gain {pc['MEDIUM']['gain_ci90'][0]:.3f} to {pc['MEDIUM']['gain_ci90'][1]:.3f}). Soft ratios disagree between circuits and hard has two weekends, so their cleaned curves stand unchanged.", size=9.5, color=MUTED, wrap_in=4.2)
neg = sorted({f"{e['event']} {e['compound'].lower()}" for e in S['excluded'] if e['gate'].startswith('no positive')})
T(ax, tx, 1.35, f"Withheld and reported: {S['n_gated_neg']} compound-weekends with no positive cleaned slope ({', '.join(neg)}; season-opening rounds) and {S['n_gated_lown']} with under {S['min_prac']} practice laps.", size=9, color=MUTED, wrap_in=4.2, va='bottom')
footer(ax, 3); pages.append(fig)

# 4 The finding
fig, ax = new(); title(ax, "The medium is the tyre that lies")
T(ax, 0.7, H-1.3, f"Race degradation divided by cleaned practice degradation, one dot per weekend. The medium sits at ×0.35 to ×0.47 on every European weekend (Japan ×0.86). Soft scatters from ×0.3 to ×3; hard has two points near ×1.2. So the model corrects the medium and leaves the others alone, and it says so.", size=12, color=MUTED, wrap_in=6.0)
card(ax, 0.7, 1.5, 5.8, 2.6, fc=ROSE)
T(ax, 0.95, 3.85, "Why, and why it matters", size=13.5, weight='bold', color=RED)
T(ax, 0.95, 3.42, f"We measured tyre energy per lap from the public 3.7 Hz position and speed traces. At {S['energy_event']} practice and race laps carry the same energy ({100*(S['energy_ratio']-1):+.0f}%), so the gap is not drivers pushing harder on Friday. The medium is the compound teams manage on Sunday. A pit wall reading Friday's medium curve at face value plans stints that are far too short. That is the decision on the next slide.", size=11, color=INK, wrap_in=5.3)
w,h = img(ax, 'v2_fig_ratio.png', 6.9, 1.5, w=5.75)
footer(ax, 4); pages.append(fig)

# 5 Saturday night
ev = 'Hungary' if 'Hungary' in ST else list(ST)[0]; st = ST[ev]
fig, ax = new(); title(ax, f"Saturday night, {ev} 2026: the decision")
w,h = img(ax, f'v2_fig_strategy_{ev}.png', 0.7, 1.55, w=11.9)
tab = {t['view']: t for t in st['table']}
T(ax, 0.7, 1.3, f"Follow the naive curve and the race costs you {tab['Naive fit']['cost_vs_truth_s']:+.0f} s against the best plan; the cleaned curve {tab['Clean practice curve']['cost_vs_truth_s']:+.0f} s; ClearStint {tab['ClearStint']['cost_vs_truth_s']:+.0f} s. Assumptions stated on the chart: a {st['n_offsets']['assumed_step_s']:.1f} s pace step between compounds, linear degradation, {st['pit_loss']:.0f} s pit loss; offsets come from qualifying on Challenge Day. Crossovers under ClearStint: " + ', '.join(f"{k} at lap {v:.0f}" for k,v in st['crossover_clearstint'].items()) + ".", size=10.5, color=MUTED, wrap_in=11.9, va='top')
footer(ax, 5); pages.append(fig)

# 6 How it works + stack
fig, ax = new(); title(ax, "How it works")
steps = [("1  Ingest", "FastF1 + OpenF1: laps, stints, compound, tyre age, sectors, weather, 3.7 Hz speed & position, gap to car ahead"),
         ("2  Quality-check", "Per-lap telemetry health. The Hungary race position feed has ≈26 distinct points per lap; we detect that and fall back to timing-only features"),
         ("3  Strip confounders", "Fuel prior (2026: ≈1.1 kg/lap) · track evolution from every driver's push laps · traffic laps dropped via gap data · per-stint effects absorb driver and fuel load"),
         ("4  Clean curve", "Degradation per compound from practice alone. Fixed-effects fit today; hierarchical Bayesian with credible bands on Challenge Day"),
         ("5  Transfer", "Race ÷ practice ratio per compound from previous weekends only, applied only where they agree"),
         ("6  Validate", "After every race: predicted vs observed, per compound and per sector. The scorecard updates the factors")]
for i,(hh,b) in enumerate(steps):
    col, row = i%3, i//3; x = 0.7 + col*4.1; y = 4.35 - row*2.15; hot = i in (4,5)
    card(ax, x, y, 3.8, 1.85, fc=(ROSE if hot else PANEL))
    T(ax, x+0.25, y+1.58, hh, size=13, weight='bold', color=(RED if hot else INK)); T(ax, x+0.25, y+1.15, b, size=10.5, color=MUTED, wrap_in=3.3)
    if col<2: ax.add_patch(FancyArrowPatch((x+3.85, y+0.92), (x+4.05, y+0.92), arrowstyle='-|>', mutation_scale=16, color=MUTED, lw=1.5))
T(ax, 0.7, 1.75, "lap_time = stint_effect + deg[compound]·tyre_age + β·fuel + evo(session_time) + ε        race_deg = k[compound] · deg[compound]", size=10, color=INK, family='DejaVu Sans Mono', va='top')
T(ax, 0.7, 1.3, "Stack: Python 3.12, pandas, NumPy, FastF1 3.8, OpenF1; PyMC for the Bayesian model; scikit-learn; Streamlit dashboard. Everything here is disclosed pre-work; Challenge Day adds the Bayesian fit, a non-linear cliff term, track temperature as a covariate, sprint weekends, and the dashboard.", size=10, color=MUTED, wrap_in=12, va='top')
footer(ax, 6); pages.append(fig)

# 7 Product
fig, ax = new(); title(ax, "What the pit wall gets")
w,h = img(ax, 'v2_fig_sector.png', 0.7, 1.7, w=6.2)
T(ax, 0.7, 1.45, "Sector times split the degradation by part of the lap. A front-limited or traction-limited tyre shows up here on Friday.", size=10.5, color=MUTED, wrap_in=6.2, va='top')
T(ax, 7.4, H-1.35, "Four outputs, one screen", size=15, weight='bold')
bullets(ax, 7.4, H-1.9, ["Race-calibrated degradation curve per compound, with a band and the transfer factor shown, or 'no reliable curve' when the data does not support one.", "Crossover laps and a 1-stop vs 2-stop comparison, as on the previous slide, for the coming race.", "The list of laps excluded and why: traffic, flag, aborted, degraded telemetry.", "Sector-level degradation map: where on the lap the tyre is giving up time."], size=12, wrap_in=5.0)
card(ax, 7.4, 1.45, 5.25, 1.35, fc=ROSE)
T(ax, 7.65, 2.6, "Sunday-night scorecard", size=12.5, weight='bold', color=RED); T(ax, 7.65, 2.22, "Predicted vs actual per compound. It updates the transfer factors, so the tool is better next weekend than this one.", size=10.8, color=MUTED, wrap_in=4.8)
footer(ax, 7); pages.append(fig)

# 8 India first
fig, ax = new(); title(ax, "Off the track: the battery in an e-rickshaw")
T(ax, 0.7, H-1.3, "An e-rickshaw's lead-acid battery pack costs ₹40,000 to ₹60,000 and is replaced every 12 to 18 months; a lithium pack ₹60,000 to ₹1,20,000 every 3 to 5 years. That is the single largest running cost for the well over a million e-rickshaws on Indian roads, and operators replace on a calendar, not on measured health. Replacing six months early wastes about ₹20,000 per vehicle; replacing late strands a driver's day.", size=12, color=MUTED, wrap_in=11.9)
card(ax, 0.7, 2.75, 11.95, 2.35)
for j,hh in enumerate(["", "Confounders to strip", "'Friday' vs 'Sunday'", "Curve wanted"]): T(ax, 1.0+j*3.0, 4.85, hh, size=10.5, weight='bold', color=MUTED)
rows = [("F1 tyre", "Fuel, track evolution, traffic, driver", "Practice long run vs managed race stint", "Pace loss per lap"),
        ("E-rickshaw battery", "Temperature, load, charging habit, route", "Lab cycle test vs real daily duty", "Capacity loss per cycle")]
for i,r in enumerate(rows):
    yy = 4.35 - i*0.7
    for j,v in enumerate(r): T(ax, 1.0+j*3.0, yy, v, size=11.5, weight=('bold' if j==0 else 'normal'), color=(RED if j==0 else INK), wrap_in=2.8)
card(ax, 0.7, 1.3, 11.95, 1.2, fc=ROSE)
T(ax, 0.95, 2.3, "Same estimator, same loop: clean the confounders, learn how the bench curve maps to real duty, and say when the data cannot support a call. First test on the public Severson et al. (2019) dataset (124 cells, charging-policy and temperature confounders; metric: predicted vs measured capacity). Then a pilot with an e-rickshaw fleet operator or leasing lender in Punjab, where Plaksha sits. Beneficiary: the driver who stops paying for a battery on a calendar.", size=10.8, color=INK, wrap_in=11.5)
footer(ax, 8); pages.append(fig)

# 9 Close
fig, ax = new(DARK)
T(ax, 0.9, H-1.2, "Why this wins", size=34, color='white', weight='bold')
pts = [("Constraint is the brief", "Public data only, 3.7 Hz telemetry, no fuel readings, one race feed broken at source. Every gap is estimated, checked or flagged, never ignored."),
       ("Measurable", f"Across {n_ev} Grands Prix, leave-one-weekend-out, degradation error falls from {mae['err_naive']:.3f} to {mae['errC']:.3f} s/lap. On the Hungary replay the naive plan costs {tab['Naive fit']['cost_vs_truth_s']:+.0f} s; ours {tab['ClearStint']['cost_vs_truth_s']:+.0f} s."),
       ("Knows when to stay silent", f"{S['n_gated_neg']+S['n_gated_lown']} of {S['n_all']} compound-weekends withheld and reported. Transfer factors applied only where weekends agree. That is the property a strategist, and a fleet lender, actually wants."),
       ("Feasible, and India-bound", "The pipeline, quality checks and validation harness run today. Challenge Day is the Bayesian model and the dashboard. The same loop then goes to e-rickshaw batteries, with a public dataset already chosen.")]
for i,(hh,b) in enumerate(pts):
    x = 0.9 + (i%2)*6.2; y = H-2.3 - (i//2)*2.15
    ax.add_patch(plt.Circle((x+0.18, y-0.15), 0.16, color=[RED,GOLD,SLATE,'#8A9099'][i]))
    T(ax, x+0.55, y, hh, size=16, color='white', weight='bold'); T(ax, x+0.55, y-0.45, b, size=11.5, color='#C9CED5', wrap_in=5.2)
T(ax, 0.9, 0.9, f"{TEAM}  ·  Tyre Degradation Intelligence  ·  TrackShift 2026", size=12, color='#8A9099', va='bottom')
pages.append(fig)

with PdfPages('ClearStint_TrackShift2026_Idea.pdf') as pdf:
    for i,f in enumerate(pages, 1):
        f.savefig(f'v3slide-{i:02d}.png', dpi=110, facecolor=f.get_facecolor()); pdf.savefig(f, facecolor=f.get_facecolor())
print("deck v3 done", len(pages), "pages")

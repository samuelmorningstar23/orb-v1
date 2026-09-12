import json, textwrap, numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.image as mpimg

S = json.load(open('summary_v2.json'))
W, H = 13.333, 7.5
DARK, INK, MUTED, RED, GOLD, SLATE, PANEL, ROSE = '#15181D', '#1B1F24', '#5B636E', '#C8102E', '#D9A400', '#3A506B', '#F3F4F6', '#FFF4F5'
plt.rcParams['font.family'] = 'DejaVu Sans'

def new(bg='white'):
    fig = plt.figure(figsize=(W, H)); fig.patch.set_facecolor(bg)
    ax = fig.add_axes([0,0,1,1]); ax.set_xlim(0,W); ax.set_ylim(0,H); ax.axis('off'); return fig, ax
def T(ax, x, y, s, size=12, color=INK, weight='normal', ha='left', va='top', wrap_in=None, ls=1.35, family=None):
    if wrap_in:
        cpl = max(10, int(wrap_in*72/(size*0.52))); s = "\n".join(textwrap.fill(p, cpl) if p else "" for p in s.split("\n"))
    ax.text(x, y, s, fontsize=size, color=color, weight=weight, ha=ha, va=va, linespacing=ls, family=family)
def title(ax, s, color=INK, y=H-0.55, size=28): T(ax, 0.7, y, s, size=size, color=color, weight='bold')
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

mae = S['mae']; n_ev = len(S['events']); k = S['k']; ev2 = S['energy_event']; ratio_E = S['energy_ratio']
hun = {r['compound']: r for r in S['per_event'].get('Hungary', [])}
naive_x = (hun['MEDIUM']['naive']/hun['MEDIUM']['obs']) if 'MEDIUM' in hun and hun['MEDIUM']['obs']>0 else None
impr_A = 100*(1-mae['errC']/mae['errA']); impr_naive = 100*(1-mae['errC']/mae['err_naive'])
pages = []

# 1 Title
fig, ax = new(DARK)
T(ax, 0.9, H-1.2, "TRACKSHIFT 2026  ·  AI MOTORSPORT INTELLIGENCE  ·  TYRE DEGRADATION INTELLIGENCE", size=10.5, color='#8A9099', weight='bold')
T(ax, 0.9, H-1.85, "ClearStint", size=62, color='white', weight='bold')
T(ax, 0.9, H-3.15, "Clean tyre degradation curves from noisy practice, a season-long loop that learns how Friday maps to Sunday, and the honesty to say when it cannot.", size=22, color='white', ls=1.3, wrap_in=8.6)
T(ax, 0.9, H-4.75, f"Working prototype · {S['n_prac_laps']:,} practice laps and {S['n_race_laps']:,} race laps · {n_ev} Grands Prix of 2026 · public data only · nothing tuned on the race", size=12.5, color=GOLD, wrap_in=8.4)
T(ax, 0.9, 1.0, "Team FireBolt  ·  Samuel Christ & Kaushal R  ·  Idea submission, 5 September 2026", size=12, color='#8A9099', va='bottom')
ax.add_patch(plt.Rectangle((W-3.0, 0), 3.0, H, color=RED, alpha=0.06))
for i,c in enumerate([RED, GOLD, SLATE]): ax.plot([W-2.5, W-0.8],[1.3+i*0.75, 1.3+i*0.75+(0.8-0.35*i)], color=c, lw=6, solid_capstyle='round')
pages.append(fig)

# 2 Problem
fig, ax = new(); title(ax, "Friday long runs lie about tyre wear, twice")
T(ax, 0.7, H-1.3, "First, every long-run lap time is a sum of things that have nothing to do with the tyre. Second, even a perfectly cleaned Friday curve is not the Sunday curve, because drivers manage tyres in a race and attack them in practice.", size=13.5, color=MUTED, wrap_in=11.8)
cols = [("Fuel burn", "≈1.6 kg lighter every lap. Around 0.05 s/lap of 'improvement' that hides wear.", PANEL, INK),
        ("Track evolution", "Rubber goes down all session. Later laps are faster for reasons unrelated to the tyre.", PANEL, INK),
        ("Traffic", "A lap spent behind a slower car looks like degradation. It is visible in the gap data and rarely removed.", PANEL, INK),
        ("Driver & programme", "Different fuel loads, different run plans. Pooling drivers blurs everything.", PANEL, INK),
        ("Friday ≠ Sunday", "Soft and medium degrade about half as fast in the race as in a cleaned practice run. Hard barely changes. No single-weekend model can know this.", ROSE, RED)]
for i,(h,b,fc,hc) in enumerate(cols):
    x = 0.7 + i*2.45; card(ax, x, 1.75, 2.3, 3.1, fc=fc)
    T(ax, x+0.22, 4.55, h, size=12.2, weight='bold', color=hc); T(ax, x+0.22, 4.12, b, size=10.8, color=MUTED, wrap_in=1.95)
if naive_x:
    T(ax, 0.7, 1.35, f"Hungary 2026: a pooled fit on practice long runs puts medium degradation at {hun['MEDIUM']['naive']:+.2f} s/lap. The race showed {hun['MEDIUM']['obs']:+.2f}. Wrong by {naive_x:.0f}×.", size=12, color=RED, weight='bold', wrap_in=10.8, va='bottom')
footer(ax, 2); pages.append(fig)

# 3 Insight: the gap is systematic
fig, ax = new(); title(ax, "The gap is systematic, so it can be learned")
T(ax, 0.7, H-1.3, f"We cleaned practice data on {n_ev} weekends and measured race degradation with the same estimator. The ratio of race to practice degradation is consistent for medium (≈×{k.get('MEDIUM',float('nan')):.1f}) and hard (≈×{k.get('HARD',float('nan')):.1f}); soft varies more between circuits (median ×{k.get('SOFT',float('nan')):.1f}). A compound-level transfer factor, learned from the season and re-checked after every race, is the product. Where it varies, the scorecard shows it.", size=12.6, color=MUTED, wrap_in=6.0)
card(ax, 0.7, 1.55, 5.8, 2.7, fc=ROSE)
T(ax, 0.95, 4.0, "Why hard transfers and soft does not", size=13.5, weight='bold', color=RED)
T(ax, 0.95, 3.55, f"We measured tyre energy per lap from public 3.7 Hz telemetry. On {ev2}, practice long runs and race laps put the same energy through the tyre ({100*(ratio_E-1):+.0f}%). So the gap is not drivers pushing harder on Friday. It is how the energy is applied: soft and medium are managed thermally on Sunday, while the hard, which published 2026 analysis places below its working window, degrades the same either way. That is a finding, and it tells the model which compounds need a transfer factor and which do not.", size=11, color=INK, wrap_in=5.3)
w,h = img(ax, 'v2_fig_ratio.png', 6.9, 1.55, w=5.75)
footer(ax, 3); pages.append(fig)

# 4 Method
fig, ax = new(); title(ax, "How it works")
steps = [("1  Ingest", "FastF1 + OpenF1: laps, stints, compound, tyre age, sector times, weather, 3.7 Hz speed & position, gap to car ahead"),
         ("2  Quality-check", "Per-lap telemetry health. Stale or jumpy position feeds are detected automatically; affected laps fall back to timing-only features"),
         ("3  Strip confounders", "Fuel prior · track evolution from every driver's push laps · traffic laps dropped via gap data · per-stint effects absorb driver and fuel load"),
         ("4  Clean curve", "Degradation per compound, per weekend, from practice alone. Today a fixed-effects fit; hierarchical Bayesian with credible bands on Challenge Day"),
         ("5  Transfer", "Race ÷ practice ratio per compound, learned from previous weekends only (leave-one-weekend-out). Applied to this Friday's curve"),
         ("6  Validate", "After every race: predicted vs observed per compound, sector by sector. The scorecard updates the transfer factors for next time")]
for i,(h,b) in enumerate(steps):
    col, row = i%3, i//3; x = 0.7 + col*4.1; y = 4.2 - row*2.3; hot = i in (4,5)
    card(ax, x, y, 3.8, 1.95, fc=(ROSE if hot else PANEL))
    T(ax, x+0.25, y+1.65, h, size=13.5, weight='bold', color=(RED if hot else INK)); T(ax, x+0.25, y+1.2, b, size=11, color=MUTED, wrap_in=3.3)
    if col<2: ax.add_patch(FancyArrowPatch((x+3.85, y+0.97), (x+4.05, y+0.97), arrowstyle='-|>', mutation_scale=16, color=MUTED, lw=1.5))
T(ax, 0.7, 1.1, "practice:  lap_time = stint_effect + deg[compound]·tyre_age + β·fuel + evo(session_time) + ε      (traffic laps removed first)\nrace:      race_deg[compound] = k[compound] · deg[compound],   k learned from previous weekends only", size=10.5, color=INK, family='DejaVu Sans Mono', va='bottom', ls=1.5)
footer(ax, 4); pages.append(fig)

# 5 Curves
fig, ax = new(); title(ax, "Same estimator on Friday and Sunday")
w,h = img(ax, 'v2_fig_curves.png', 0.7, 1.45, w=11.9)
T(ax, 0.7, 1.2, "Left: cleaned practice long runs. Right: race stints, cleaned the same way. Because both sides use one estimator, the ratio between them is a property of the tyres and the drivers, not of our method.", size=11, color=MUTED, wrap_in=11.9, va='top')
footer(ax, 5); pages.append(fig)

# 6 Validation
fig, ax = new(); title(ax, f"Tested on {n_ev} Grands Prix, leave-one-weekend-out")
w,h = img(ax, 'v2_fig_validation.png', 0.6, 0.75, w=6.5)
tx = 0.6 + w + 0.5
T(ax, tx, H-1.35, "Mean absolute error vs race, s/lap", size=13.5, weight='bold')
hdr = ["Method", "MAE", "vs ours"]; colw = [2.6, 1.0, 1.1]; ty = H-1.85
for j,hh in enumerate(hdr): T(ax, tx+sum(colw[:j]), ty, hh, size=10.5, weight='bold', color=MUTED)
rows = [("Naive pooled fit", mae['err_naive']), ("Clean practice curve", mae['errA']), ("ClearStint (curve × transfer)", mae['errC'])]
for i,(name,v) in enumerate(rows):
    yy = ty - 0.5*(i+1); card(ax, tx-0.1, yy-0.3, sum(colw)+0.1, 0.42, fc=(ROSE if i==2 else (PANEL if i%2==0 else 'white')), r=0.05)
    T(ax, tx, yy, name, size=11, weight=('bold' if i==2 else 'normal'), color=(RED if i==2 else INK)); T(ax, tx+colw[0], yy, f"{v:.3f}", size=11.5, weight=('bold' if i==2 else 'normal'))
    T(ax, tx+colw[0]+colw[1], yy, ("—" if i==2 else f"−{100*(1-mae['errC']/v):.0f}%"), size=11.5, color=(RED if i<2 else INK), weight='bold')
yb = ty - 2.35
T(ax, tx, yb, f"Transfer factors are learned only from the other weekends, then applied to the held-out one. On the {S['n_rows']} compound-weekends where a curve was issued, ClearStint beats the uncalibrated curve in {S['wins_C_over_A']} and the naive fit in {S['wins_C_over_naive']}.", size=10.5, wrap_in=5.2)
T(ax, tx, yb-1.2, f"Hard compound: where a curve was issued, the clean practice curve alone predicts the race within {S['hard_err']:.3f} s/lap on average, with no calibration.", size=10, color=MUTED, wrap_in=5.2)
neg = sorted({f"{e['event']} {e['compound'].lower()}" for e in S['excluded'] if e['gate'].startswith('no positive')})
T(ax, tx, yb-1.95, f"Withheld, and reported: {S['n_gated_neg']} compound-weekends where the cleaned practice slope was not positive ({', '.join(neg)}), all at season-opening rounds, plus {S['n_gated_lown']} with under {S['min_prac']} practice laps. The tool says 'no reliable curve' there instead of guessing.", size=9.5, color=MUTED, wrap_in=5.2)
footer(ax, 6); pages.append(fig)

# 7 Product
fig, ax = new(); title(ax, "What the pit wall gets")
w,h = img(ax, 'v2_fig_sector.png', 0.7, 1.7, w=6.2)
T(ax, 0.7, 1.45, "Sector times split the degradation by part of the lap. A front-limited or traction-limited tyre shows up here on Friday.", size=10.5, color=MUTED, wrap_in=6.2, va='top')
T(ax, 7.4, H-1.35, "Four outputs, one screen", size=15, weight='bold')
bullets(ax, 7.4, H-1.9, ["Race-calibrated degradation curve per compound, with a credible band and the transfer factor shown explicitly.", "Crossover points: the tyre age at which medium beats soft, hard beats medium, at race pace.", "Stint-length guidance under a chosen risk level, with the list of laps excluded and why (traffic, flag, aborted, degraded telemetry).", "Sector-level degradation map: where on the lap the tyre is giving up time."], size=12, wrap_in=5.0)
card(ax, 7.4, 1.45, 5.25, 1.35, fc=ROSE)
T(ax, 7.65, 2.6, "Post-race scorecard", size=12.5, weight='bold', color=RED); T(ax, 7.65, 2.22, "Predicted vs actual per compound, generated Sunday night. It updates the transfer factors, so the tool gets better every weekend.", size=10.8, color=MUTED, wrap_in=4.8)
footer(ax, 7); pages.append(fig)

# 8 Stack + limits + plan
fig, ax = new(); title(ax, "Stack, honest limits, and the 24 hours")
card(ax, 0.7, 1.45, 4.0, 4.8); T(ax, 0.95, H-1.5, "Tools & data (all open)", size=14, weight='bold')
bullets(ax, 0.95, H-2.0, ["FastF1 3.8 and OpenF1: 2018 to today, verified on every 2026 session used here.", "Python 3.12, pandas, NumPy; PyMC for the hierarchical model; scikit-learn for lap classification.", "Streamlit dashboard, matplotlib/Plotly.", "References: TUMFTM race-simulation, arXiv 2512.00640, Pirelli compound briefings."], size=11, wrap_in=3.5)
card(ax, 4.9, 1.45, 3.75, 4.8, fc=PANEL); T(ax, 5.15, H-1.5, "What we do not know yet", size=14, weight='bold')
bullets(ax, 5.15, H-2.0, [f"At the season-opening rounds (Australia, Japan) the cleaned practice slope for hard and medium was not positive: green tracks and teams still learning the 2026 cars. We withhold a curve there. Modelling that evolution is Challenge Day work.", f"Transfer factors come from {n_ev} weekends and will tighten with every race; the scorecard will show where they drift.", "Fuel load in practice is a prior, not a measurement. Degradation is linear in tyre age today; cliffs need the planned non-linear term."], size=10.6, wrap_in=3.25, dot=SLATE)
card(ax, 8.85, 1.45, 3.8, 4.8, fc=ROSE); T(ax, 9.1, H-1.5, "Challenge Day, 12–13 Sept", size=14, weight='bold', color=RED)
plan = [("H0–H4", "Add sprint weekends; non-linear (cliff) term"), ("H4–H12", "Hierarchical Bayesian fit, credible bands, crossover logic"), ("H12–H18", "Scorecard on all 2026 races; calibration check of the bands"), ("H18–H22", "Dashboard"), ("H22–H24", "Pitch and demo rehearsal")]
yy = H-2.05
for hh,b in plan: T(ax, 9.1, yy, hh, size=11, weight='bold'); T(ax, 10.15, yy, b, size=10.8, color=MUTED, wrap_in=2.4); yy -= 0.78
T(ax, 0.7, 1.0, "Everything in this deck is disclosed pre-work: data pipeline, telemetry quality checks, fixed-effects estimator, validation harness.", size=10.5, color=MUTED, va='bottom')
footer(ax, 8); pages.append(fig)

# 9 Off the track
fig, ax = new(); title(ax, "The same loop, off the track")
T(ax, 0.7, H-1.3, "Isolating true wear from confounders, then learning how a test-bench curve maps to real duty, is the problem behind every battery and tyre fleet in India. The columns change; the method does not.", size=13.5, color=MUTED, wrap_in=11.8)
card(ax, 0.7, 2.75, 11.95, 2.75)
for j,hh in enumerate(["Asset", "Confounders to strip", "'Friday' vs 'Sunday'", "Clean curve wanted"]): T(ax, 1.0+j*3.0, 5.25, hh, size=10.5, weight='bold', color=MUTED)
rows = [("F1 tyre", "Fuel, track evolution, traffic, driver", "Practice long run vs managed race stint", "Pace loss per lap, per compound"),
        ("EV battery (e-rickshaw, delivery fleet)", "Temperature, load, charging policy, route", "Lab cycling vs real duty cycle", "Capacity loss per cycle"),
        ("Truck / bus tyres and brakes", "Load, route, weather, driver style", "Test route vs fleet operation", "Wear per 1,000 km")]
for i,r in enumerate(rows):
    yy = 4.75 - i*0.62
    for j,v in enumerate(r): T(ax, 1.0+j*3.0, yy, v, size=11, weight=('bold' if j==0 else 'normal'), color=(RED if (i==0 and j==0) else INK), wrap_in=2.8)
card(ax, 0.7, 1.35, 11.95, 1.15, fc=ROSE)
T(ax, 0.95, 2.3, "First target after TrackShift: battery state-of-health for EV fleet operators. Validation on the public Severson et al. (2019) fast-charging dataset, 124 cells with charging-policy and temperature confounders, metric = predicted vs measured capacity. Then a pilot with an e-rickshaw fleet in Punjab.", size=11, color=INK, wrap_in=11.5)
footer(ax, 9); pages.append(fig)

# 10 Close
fig, ax = new(DARK)
T(ax, 0.9, H-1.2, "Why this wins", size=34, color='white', weight='bold')
pts = [("Constraint is the brief", "Public data only, 3.7 Hz telemetry, no fuel readings, one race feed broken at source. Every gap is estimated, checked or flagged, never ignored."),
       ("Measurable", f"One number per compound per weekend and a scorecard that says how wrong we were. Across {n_ev} Grands Prix, leave-one-weekend-out, ClearStint cuts error {impr_A:.0f}% vs the cleaned curve alone and {impr_naive:.0f}% vs a naive fit."),
       ("Feasible", "The pipeline, the quality checks and the validation harness already run. Challenge Day is the Bayesian model, the cliff term and the dashboard."),
       ("Beyond the track", "The clean-then-transfer loop ports to EV battery and fleet wear in India, with a public dataset already chosen for the first test.")]
for i,(h,b) in enumerate(pts):
    x = 0.9 + (i%2)*6.2; y = H-2.3 - (i//2)*2.1
    ax.add_patch(plt.Circle((x+0.18, y-0.15), 0.16, color=[RED,GOLD,SLATE,'#8A9099'][i]))
    T(ax, x+0.55, y, h, size=16, color='white', weight='bold'); T(ax, x+0.55, y-0.45, b, size=11.8, color='#C9CED5', wrap_in=5.2)
T(ax, 0.9, 0.9, "Team FireBolt  ·  Samuel Christ & Kaushal R  ·  Tyre Degradation Intelligence  ·  TrackShift 2026", size=12, color='#8A9099', va='bottom')
pages.append(fig)

with PdfPages('ClearStint_TrackShift2026_Idea.pdf') as pdf:
    for i,f in enumerate(pages, 1):
        f.savefig(f'v2slide-{i:02d}.png', dpi=110, facecolor=f.get_facecolor()); pdf.savefig(f, facecolor=f.get_facecolor())
print("deck done", len(pages), "pages")

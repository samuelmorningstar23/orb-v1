import json, textwrap, numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.image as mpimg

R = json.load(open('results.json'))
W, H = 13.333, 7.5
DARK, INK, MUTED, RED, GOLD, SLATE, PANEL = '#15181D', '#1B1F24', '#5B636E', '#C8102E', '#D9A400', '#3A506B', '#F3F4F6'
plt.rcParams['font.family'] = 'DejaVu Sans'

def new(bg='white'):
    fig = plt.figure(figsize=(W, H)); fig.patch.set_facecolor(bg)
    ax = fig.add_axes([0,0,1,1]); ax.set_xlim(0,W); ax.set_ylim(0,H); ax.axis('off')
    return fig, ax
def T(ax, x, y, s, size=12, color=INK, weight='normal', ha='left', va='top', wrap_in=None, ls=1.35, style='normal', family=None):
    if wrap_in:
        cpl = max(10, int(wrap_in*72/(size*0.52)))
        s = "\n".join(textwrap.fill(p, cpl) if p else "" for p in s.split("\n"))
    ax.text(x, y, s, fontsize=size, color=color, weight=weight, ha=ha, va=va, linespacing=ls, style=style, family=family)
def title(ax, s, color=INK, y=H-0.55, size=30):
    T(ax, 0.7, y, s, size=size, color=color, weight='bold')
def card(ax, x, y, w, h, fc=PANEL, ec='none', r=0.12):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=1))
def bullets(ax, x, y, items, size=13, color=INK, wrap_in=5.5, gap=0.42, dot=RED):
    for it in items:
        ax.plot([x+0.08],[y-0.11], marker='o', ms=5, color=dot, ls='none')
        T(ax, x+0.3, y, it, size=size, color=color, wrap_in=wrap_in)
        n = len(textwrap.fill(it, max(10,int(wrap_in*72/(size*0.52)))).split("\n"))
        y -= gap*0.55 + n*size*1.35/72
def footer(ax, n, light=False):
    T(ax, W-0.7, 0.35, f"ClearStint · TrackShift 2026 · {n}", size=9, color=('#8A9099' if light else MUTED), ha='right', va='bottom')

n = R['naive']; o = R['ours']; rc = R['race']
pages = []

# 1 Title
fig, ax = new(DARK)
T(ax, 0.9, H-1.3, "TRACKSHIFT 2026  ·  AI MOTORSPORT INTELLIGENCE  ·  TYRE DEGRADATION INTELLIGENCE", size=11, color='#8A9099', weight='bold')
T(ax, 0.9, H-2.0, "ClearStint", size=64, color='white', weight='bold')
T(ax, 0.9, H-3.35, "Clean tyre degradation curves from noisy practice sessions, validated against race-day pace.", size=22, color='#D6DAE0', ls=1.3, wrap_in=8.6)
T(ax, 0.9, H-4.9, "Built on real 2026 Hungarian GP timing data. Every number in this deck comes from a working prototype.", size=13, color=GOLD, wrap_in=8.6)
T(ax, 0.9, 1.05, "Team ClearStint  ·  Idea submission, 5 September 2026", size=12, color='#8A9099', va='bottom')
ax.add_patch(plt.Rectangle((W-3.0, 0), 3.0, H, color=RED, alpha=0.06))
for i,c in enumerate([RED, GOLD, SLATE]):
    ax.plot([W-2.5, W-0.8],[1.3+i*0.75, 1.3+i*0.75+(0.8-0.35*i)], color=c, lw=6, solid_capstyle='round')
pages.append(fig)

# 2 Problem
fig, ax = new(); title(ax, "Friday long runs lie about tyre wear")
T(ax, 0.7, H-1.35, "A team gets three practice sessions to learn how fast each compound falls off. But every long-run lap time is a sum of things that have nothing to do with the tyre.", size=14, color=MUTED, wrap_in=7.2)
cols = [("Fuel burn", "≈1.6 kg lighter every lap. Roughly 0.05 s/lap of 'improvement' that hides wear."),
        ("Track evolution", "Rubber goes down all session. Later laps are faster for reasons unrelated to the tyre."),
        ("Traffic & push level", "A lap behind a slower car, or a driver lifting to save the tyre, looks like degradation."),
        ("Driver & car", "Each driver runs a different fuel load, programme and pace. Pooling them blurs everything.")]
for i,(h,b) in enumerate(cols):
    x = 0.7 + i*3.05; cy = 2.3; card(ax, x, cy, 2.8, 2.55)
    ax.add_patch(plt.Circle((x+0.45, cy+2.1), 0.2, color=[RED,GOLD,SLATE,INK][i]))
    T(ax, x+0.25, cy+1.75, h, size=14, weight='bold'); T(ax, x+0.25, cy+1.35, b, size=11.5, color=MUTED, wrap_in=2.4)
T(ax, 0.7, 1.15, f"Prototype, 2026 Hungarian GP: a naive fit on FP2 long runs says the medium degrades at {n['MEDIUM']:+.2f} s/lap. The race showed {rc['MEDIUM']:+.2f} s/lap. Off by more than 5×.", size=12.5, color=RED, weight='bold', wrap_in=11.5, va='bottom')
footer(ax, 2); pages.append(fig)

# 3 Gap
fig, ax = new(); title(ax, "What exists today, and the hole in it")
card(ax, 0.7, 1.6, 5.7, 4.6, fc=PANEL)
T(ax, 1.0, H-1.55, "Published state of the art", size=15, weight='bold')
T(ax, 1.0, H-2.0, "arXiv 2512.00640 (Dec 2025), Bayesian state-space model on FastF1 data", size=11.5, color=MUTED, wrap_in=5.2)
bullets(ax, 1.0, H-2.75, ["Lap time = latent tyre pace + fuel. Nothing else.", "Race laps only. One driver, one race.", "Its own limitations section: no traffic, no track evolution, safety cars unhandled.", "Practice sessions are never used as input, which is precisely what the pit wall needs on Friday."], size=12, wrap_in=5.0)
card(ax, 6.9, 1.6, 5.7, 4.6, fc='#FFF4F5')
T(ax, 7.2, H-1.55, "What ClearStint adds", size=15, weight='bold', color=RED)
bullets(ax, 7.2, H-2.2, ["Practice-first: fits on FP1 to FP3 long runs, the data that exists before the race.", "Explicit confounder model: fuel, track evolution, traffic, push/lift, driver, all estimated or removed.", "Hierarchical priors across drivers and compounds so short stints still give stable curves.", "A validation loop: Friday's prediction scored against Sunday's actual pace, every weekend."], size=12, wrap_in=5.0, dot=RED)
T(ax, 0.7, 0.95, "Teams have this in-house and never publish it. There is no open, validated tool. That is the gap.", size=12.5, color=INK, weight='bold', va='bottom')
footer(ax, 3); pages.append(fig)

# 4 Approach pipeline
fig, ax = new(); title(ax, "How it works")
steps = [("1  Ingest", "FastF1 + OpenF1: laps, stints, compound, tyre age, weather, 3.7 Hz telemetry, gaps"),
         ("2  Clean", "Drop in/out laps, yellow flags, deleted laps. Keep stints ≥ 5 laps"),
         ("3  Strip confounders", "Fuel prior · track evolution from push laps · traffic flag from gap to car ahead · push/lift from throttle & brake traces"),
         ("4  Fit", "Hierarchical Bayesian model: per-compound degradation curve, driver & stint effects, full uncertainty"),
         ("5  Deliver", "Clean curves with credible bands, compound crossover laps, stint-length guidance"),
         ("6  Validate", "After the race: predicted vs observed pace per compound. Error feeds back into priors")]
for i,(h,b) in enumerate(steps):
    col, row = i%3, i//3; x = 0.7 + col*4.1; y = 4.05 - row*2.45
    card(ax, x, y, 3.8, 2.05, fc=(PANEL if i!=2 and i!=5 else '#FFF4F5'))
    T(ax, x+0.25, y+1.75, h, size=14, weight='bold', color=(RED if i in (2,5) else INK))
    T(ax, x+0.25, y+1.3, b, size=11.5, color=MUTED, wrap_in=3.3)
    if col<2: ax.add_patch(FancyArrowPatch((x+3.85, y+1.0), (x+4.05, y+1.0), arrowstyle='-|>', mutation_scale=16, color=MUTED, lw=1.5))
T(ax, 0.7, 0.95, "Model core:  lap_time = stint_effect + deg[compound] · f(tyre_age) + β·fuel + evo(t) + traffic + push_level + ε", size=12, color=INK, family='DejaVu Sans Mono', va='bottom')
footer(ax, 4); pages.append(fig)

# 5 Prototype evidence
fig, ax = new(); title(ax, "It already runs on real 2026 data")
img = mpimg.imread('fig1_raw_vs_corrected.png'); iw = 10.9; ih = iw*img.shape[0]/img.shape[1]
ax.imshow(img, extent=[1.2, 1.2+iw, 1.3, 1.3+ih], aspect='auto')
T(ax, 0.7, H-1.2, f"2026 Hungarian GP, FP2. {R['n_fp2']} clean long-run laps across 34 stints and 21 drivers, pulled through FastF1. Left: what a pooled fit sees. Right: the same laps after removing fuel burn, track evolution and driver, with per-stint fixed effects.", size=12.5, color=MUTED, wrap_in=11.9)
T(ax, 0.7, 0.95, "Prototype uses a fixed-effects estimator. The full build replaces it with the hierarchical Bayesian model and adds the traffic and push-level terms.", size=11, color=MUTED, va='bottom', wrap_in=12)
footer(ax, 5); pages.append(fig)

# 6 Validation
fig, ax = new(); title(ax, "Validation: Friday's prediction versus Sunday's pace")
img = mpimg.imread('fig2_validation.png'); iw = 6.3; ih = iw*img.shape[0]/img.shape[1]
ax.imshow(img, extent=[0.6, 0.6+iw, 1.55, 1.55+ih], aspect='auto')
# table
tx, ty = 7.3, H-1.45; colw=[1.35,1.35,1.35,1.35]; hdr=["Compound","Naive fit","ClearStint","Race actual"]
T(ax, tx, ty, "Degradation, s/lap per lap of tyre age", size=13, weight='bold')
ty -= 0.55
for j,h in enumerate(hdr): T(ax, tx+sum(colw[:j]), ty, h, size=11, weight='bold', color=MUTED)
for i,c in enumerate(['SOFT','MEDIUM','HARD']):
    yy = ty - 0.5*(i+1); card(ax, tx-0.1, yy-0.3, 5.5, 0.42, fc=(PANEL if i%2==0 else 'white'), r=0.05)
    T(ax, tx, yy, c.title(), size=11.5, weight='bold', color=[RED,GOLD,SLATE][i])
    T(ax, tx+colw[0], yy, f"{n[c]:+.3f}", size=11.5, color=MUTED); T(ax, tx+colw[0]+colw[1], yy, f"{o[c]:+.3f}", size=11.5, weight='bold'); T(ax, tx+sum(colw[:3]), yy, f"{rc[c]:+.3f}", size=11.5)
ty -= 2.35
T(ax, tx, ty, "Error versus race, s/lap", size=13, weight='bold'); ty -= 0.5
for i,c in enumerate(['SOFT','MEDIUM','HARD']):
    ne = abs(n[c]-rc[c]); oe = abs(o[c]-rc[c]); yy = ty - 0.5*i
    T(ax, tx, yy, c.title(), size=11.5, color=[RED,GOLD,SLATE][i], weight='bold')
    T(ax, tx+colw[0], yy, f"{ne:.3f}", size=11.5, color=MUTED); T(ax, tx+colw[0]+colw[1], yy, f"{oe:.3f}", size=11.5, weight='bold'); T(ax, tx+sum(colw[:3]), yy, f"−{(1-oe/ne)*100:.0f}%", size=11.5, color=RED, weight='bold')
T(ax, 0.7, 0.95, "The remaining Friday-to-Sunday gap is push level: drivers attack long runs on Friday and manage tyres on Sunday. Detecting that from throttle and brake traces is the next model term, and exactly what the validation loop is for.", size=11, color=MUTED, va='bottom', wrap_in=12)
footer(ax, 6); pages.append(fig)

# 7 Product
fig, ax = new(); title(ax, "What the pit wall sees")
card(ax, 0.7, 1.5, 7.2, 4.7, fc=DARK, r=0.15)
T(ax, 1.0, H-1.55, "CLEARSTINT · HUNGARORING · FP2 → RACE FORECAST", size=9.5, color='#8A9099', weight='bold')
axi = fig.add_axes([0.095, 0.27, 0.48, 0.45]); axi.set_facecolor(DARK)
xs = np.arange(0, 31)
for c,col in zip(['SOFT','MEDIUM','HARD'],[RED,GOLD,SLATE]):
    m = o[c]*xs; band = 0.25 + 0.03*xs
    axi.fill_between(xs, m-band, m+band, color=col, alpha=0.18, lw=0); axi.plot(xs, m, color=col, lw=2.2, label=c.title())
for s in axi.spines.values(): s.set_color('#3A3F47')
axi.tick_params(colors='#9AA1AA', labelsize=8); axi.set_xlabel("Tyre age (laps)", color='#9AA1AA', fontsize=9); axi.set_ylabel("Pace loss (s)", color='#9AA1AA', fontsize=9)
axi.grid(color='#2A2F36', lw=0.6); axi.legend(frameon=False, fontsize=8, labelcolor='white')
T(ax, 8.4, H-1.5, "Three outputs, one screen", size=15, weight='bold')
bullets(ax, 8.4, H-2.05, ["Degradation curve per compound with a credible band, not a single line.", "Crossover laps: the tyre age at which medium beats soft, hard beats medium.", "Stint-length guidance under a chosen risk level, plus which laps were excluded and why (traffic, lift, flag)."], size=12, wrap_in=4.0)
card(ax, 8.4, 1.5, 4.25, 1.55, fc='#FFF4F5')
T(ax, 8.65, 2.8, "Post-race scorecard", size=12.5, weight='bold', color=RED)
T(ax, 8.65, 2.42, "Predicted vs actual per compound, per driver. Auto-generated Sunday night.", size=11, color=MUTED, wrap_in=3.8)
footer(ax, 7); pages.append(fig)

# 8 Stack + plan
fig, ax = new(); title(ax, "Stack, data and the 24-hour plan")
card(ax, 0.7, 1.5, 6.0, 4.7)
T(ax, 1.0, H-1.5, "Tools & data (all open)", size=15, weight='bold')
bullets(ax, 1.0, H-2.05, ["FastF1 3.8 and OpenF1 for laps, stints, weather, 3.7 Hz car and position telemetry; 2018 to today, verified on 2026 sessions.", "Python 3.12, pandas, NumPy; PyMC or Stan for the hierarchical model; scikit-learn for push/lift lap classification from telemetry.", "Streamlit dashboard, matplotlib/Plotly charts.", "Reference: TUMFTM race-simulation & racetrack-database, arXiv 2512.00640."], size=11.5, wrap_in=5.3)
card(ax, 7.0, 1.5, 5.65, 4.7, fc='#FFF4F5')
T(ax, 7.3, H-1.5, "Challenge Day, 12 to 13 Sept", size=15, weight='bold', color=RED)
plan = [("H0 to H4", "Pipeline on 3+ 2026 weekends, cleaning rules, traffic & push flags"), ("H4 to H12", "Hierarchical model, credible bands, compound crossover logic"), ("H12 to H18", "Validation loop on every 2026 race so far; error report"), ("H18 to H22", "Dashboard and scorecard"), ("H22 to H24", "Pitch, demo rehearsal")]
yy = H-2.1
for h,b in plan:
    T(ax, 7.3, yy, h, size=11.5, weight='bold'); T(ax, 8.6, yy, b, size=11.5, color=MUTED, wrap_in=3.9); yy -= 0.72
T(ax, 0.7, 0.95, "Everything before Challenge Day is data plumbing and the prototype shown here; disclosed as pre-work per the rules.", size=11, color=MUTED, va='bottom')
footer(ax, 8); pages.append(fig)

# 9 Real world
fig, ax = new(); title(ax, "The same maths, off the track")
T(ax, 0.7, H-1.35, "Isolating true wear from confounders is not a motorsport problem. It is the problem behind every fleet in India that runs on batteries or tyres.", size=14, color=MUTED, wrap_in=11.5)
rows = [("Tyre on a race car", "Fuel, track evolution, traffic, driver", "Pace loss per lap"),
        ("Battery in an e-rickshaw or delivery EV", "Temperature, load, charging pattern, route, driver", "Capacity loss per cycle"),
        ("Tyres and brakes on a bus or truck fleet", "Load, route, weather, driver style", "Wear per 1,000 km")]
card(ax, 0.7, 2.2, 11.95, 3.15)
for j,h in enumerate(["Asset", "Confounders to strip", "Clean curve you want"]): T(ax, 1.0+j*4.0, 5.05, h, size=11, weight='bold', color=MUTED)
for i,r in enumerate(rows):
    yy = 4.5 - i*0.75
    for j,v in enumerate(r): T(ax, 1.0+j*4.0, yy, v, size=12, weight=('bold' if j==0 else 'normal'), color=(RED if (i==0 and j==0) else INK), wrap_in=3.7)
T(ax, 0.7, 1.6, "Target after TrackShift: a state-of-health estimator for EV fleet operators, validated the same way, prediction scored against measured capacity tests. Same code path, different columns.", size=12.5, weight='bold', wrap_in=11.9)
footer(ax, 9); pages.append(fig)

# 10 Close
fig, ax = new(DARK)
T(ax, 0.9, H-1.2, "Why this wins", size=34, color='white', weight='bold')
pts = [("Constraint is the brief", "Public data only, 3.7 Hz telemetry, no fuel readings. We treat every missing channel as something to estimate, not an excuse."),
       ("Measurable", "One number per compound per weekend, and a scorecard that says how wrong we were. Judged by the race, not by us."),
       ("Feasible", "Prototype already runs on 2026 data. Challenge Day is model depth and product, not plumbing."),
       ("Beyond the track", "The estimator ports directly to EV battery and fleet wear in India.")]
for i,(h,b) in enumerate(pts):
    x = 0.9 + (i%2)*6.2; y = H-2.3 - (i//2)*2.0
    ax.add_patch(plt.Circle((x+0.18, y-0.15), 0.16, color=[RED,GOLD,SLATE,'#8A9099'][i]))
    T(ax, x+0.55, y, h, size=16, color='white', weight='bold'); T(ax, x+0.55, y-0.45, b, size=12, color='#C9CED5', wrap_in=5.2)
T(ax, 0.9, 0.9, "Team ClearStint  ·  Tyre Degradation Intelligence  ·  TrackShift 2026", size=12, color='#8A9099', va='bottom')
pages.append(fig)

with PdfPages('ClearStint_TrackShift2026_Idea.pdf') as pdf:
    for i,f in enumerate(pages, 1):
        f.savefig(f'slide-{i:02d}.png', dpi=110, facecolor=f.get_facecolor()); pdf.savefig(f, facecolor=f.get_facecolor())
print("done", len(pages), "pages")

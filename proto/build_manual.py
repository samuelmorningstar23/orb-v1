"""Orb v1 technical manual (simplified) -> out/Orb_v1_Roadmap_and_Manual.pdf, plus out/ROADMAP.md and out/JURY_QUESTIONS.md."""
import json, datetime as dt
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image, KeepTogether
L = json.load(open('out/lock.json')); V = L['validation']
ss = getSampleStyleSheet()
H1 = ParagraphStyle('H1', parent=ss['Heading1'], fontSize=17, spaceBefore=14, spaceAfter=8, textColor=colors.HexColor('#0E1013'))
H2 = ParagraphStyle('H2', parent=ss['Heading2'], fontSize=12.5, spaceBefore=10, spaceAfter=5, textColor=colors.HexColor('#1F2937'))
B = ParagraphStyle('B', parent=ss['BodyText'], fontSize=9.6, leading=13.2, spaceAfter=5)
SM = ParagraphStyle('SM', parent=B, fontSize=8.4, leading=11, textColor=colors.HexColor('#4B5563'))
BUL = ParagraphStyle('BUL', parent=B, leftIndent=12, bulletIndent=2, spaceAfter=2.5)
CELL = ParagraphStyle('CELL', parent=B, fontSize=8.2, leading=10.4, spaceAfter=0)
CELLB = ParagraphStyle('CELLB', parent=CELL, fontName='Helvetica-Bold')
QA_Q = ParagraphStyle('Q', parent=B, fontName='Helvetica-Bold', spaceBefore=6, spaceAfter=2)
def P(t, s=B): return Paragraph(t, s)
def bullets(items): return [Paragraph(t, BUL, bulletText='•') for t in items]
def table(rows, widths, header=True, fs=8.2):
    data = [[Paragraph(str(c), CELLB if (header and i == 0) else CELL) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    t.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#C7CCD4')), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E5E7EB') if header else colors.white),
                           ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4), ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
    return t
def fig(path, width_cm, caption):
    im = Image(path); r = im.imageHeight / im.imageWidth; im.drawWidth = width_cm * cm; im.drawHeight = width_cm * cm * r
    return KeepTogether([im, Spacer(1, 3), P(caption, SM)])

m = V['mae_all_with_fallback']; mi = V['mae_issued']; cal = V['calibration']; bc = V['by_compound']

# ---- claim support computed from the lock (red-team claim map, 12 Sep): every quoted figure below is derived here, not typed ----
import statistics as _st, csv as _csv
_ROWS = L['validation_rows']; _WH = [r for r in _ROWS if not r['issued']]; _ISS = [r for r in _ROWS if r['issued']]
NWH = len(_WH); _WOBS = [r['obs'] for r in _WH]
WH_MED, WH_MIN, WH_MAX = _st.median(_WOBS), min(_WOBS), max(_WOBS)
WH_LT06 = sum(o < 0.06 for o in _WOBS); WH_COVER = sum(r['lo'] <= r['obs'] <= r['hi'] for r in _WH)
WH_FB = _st.mean(abs(r['err_cs']) for r in _WH); WH_NV = _st.mean(abs(r['err_naive']) for r in _WH)
WH_TXT = f'withheld compounds degraded at a median {WH_MED:.3f} s/lap in the race (range {WH_MIN:+.3f} to {WH_MAX:+.3f}); {WH_LT06} of {NWH} below 0.06 s/lap; the fallback band covered {WH_COVER} of {NWH}'
WH_CAP = WH_TXT[0].upper() + WH_TXT[1:]
FB_TXT = f'{WH_FB:.3f} s/lap against {WH_NV:.3f} for the naive line over the {NWH} withheld cases'
_WRONG = [r for r in _WH if r['clean'] < 0]; N_WRONG = len(_WRONG); N_WRONG_UP = sum(1 for r in _WRONG if (r['energy_trend'] or 0) > 0)
_NEG = [r for r in _WH if r['energy_trend'] is not None and r['energy_trend'] < 0]; N_NEG = len(_NEG); NEG_FEW = all(str(r['gate']).startswith('too few') for r in _NEG)
RAMP_TXT = (f'where the cleaned Friday slope pointed the wrong way ({N_WRONG} cases), the driver was ramping up in ' + ('every one' if N_WRONG_UP == N_WRONG else f'{N_WRONG_UP} of them')
            + f'; {N_NEG} of the {NWH} withheld compounds show a falling energy trend' + (' and were withheld for too few clean laps' if NEG_FEW else ''))
RAMP_CAP = RAMP_TXT[0].upper() + RAMP_TXT[1:]
_PD = V['push_diagnostic']; _z = lambda x: 0.0 if abs(x) < 0.005 else x
ET_TXT = f'{_PD["energy_trend_withheld"]["50%"]:+.2f} MJ per lap of age on withheld compounds and {_z(_PD["energy_trend_issued"]["50%"]):.2f} on issued ones'
_PUSH = [r for r in _ISS if r.get('push_adj') is not None]; N_PUSH = len(_PUSH)
PUSH_POOLED = sum(r['clean'] - r['push_adj'] for r in _PUSH) / sum(r['clean'] - r['obs'] for r in _PUSH)
PUSH_WORD = 'about two-thirds' if 0.6 <= PUSH_POOLED < 0.72 else f'about {PUSH_POOLED:.0%}'
PUSH_TXT = f'explains {PUSH_WORD} of the pooled Friday-to-Sunday gap on the {N_PUSH} issued cases ({PUSH_POOLED:.1%} pooled; per-case shares vary widely)'
_B = {b['event']: (b['practice'], b['race']) for b in _PD['beta_practice_vs_race']}
BETA_WITHIN = max(abs(_B[e][0] - _B[e][1]) for e in ('Austria', 'Barcelona'))
BETA_SHORT = f'has a consistent scale Friday to Sunday, within {BETA_WITHIN:.2f} s/MJ at Austria and Barcelona'
BETA_TXT = BETA_SHORT + f' (Austria {_B["Austria"][0]:.3f} against {_B["Austria"][1]:.3f} s per MJ, Barcelona {_B["Barcelona"][0]:.3f} against {_B["Barcelona"][1]:.3f})'
HM = next(r for r in _ROWS if r['event'] == 'Hungary' and r['compound'] == 'MEDIUM')
def _cost(s, view): return (s.get('views', {}).get(view) or {}).get('cost_under_truth_vs_best_s')
SC = {ev: (_cost(s, 'Naive fit'), _cost(s, 'Orb v1')) for ev, s in L['strategy'].items() if _cost(s, 'Naive fit') is not None and _cost(s, 'Orb v1') is not None}
N_SC = len(SC); SC_BEATS = sum(1 for n, o in SC.values() if o < n); SC_MISS = sorted(((ev, n, o) for ev, (n, o) in SC.items() if o >= n), key=lambda x: -x[2])
N_SPRINT = sum(1 for ev in SC if L['events'].get(ev, {}).get('format') == 'sprint')
NV_MIN, NV_MAX = min(n for n, _ in SC.values()), max(n for n, _ in SC.values()); OB_MIN, OB_MAX = min(o for _, o in SC.values()), max(o for _, o in SC.values())
SC_RANGE = f'naive costs {NV_MIN:.0f} to {NV_MAX:.0f} s; Orb v1 {OB_MIN:.0f} to {OB_MAX:.0f} s'
_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six']
MISS_TXT = ' and '.join(f'{ev} ({o:+.0f} s against {n:+.0f} s for naive)' for ev, n, o in SC_MISS)
SC_TXT = f'beats the naive plan on {SC_BEATS} of the {N_SC} scored weekends; the {_WORDS[len(SC_MISS)] if len(SC_MISS) < len(_WORDS) else len(SC_MISS)} misses are {MISS_TXT}'
H_NAIVE_COST, H_ORB_COST = SC['Hungary']
def _liquid():
    try: liq = json.load(open('out/liquid.json'))
    except FileNotFoundError: return None
    cells = [(ev, c, m['mae_linear'], m['mae_quadratic'], m['mae_linear_cov'], m['mae_liquid'], m['n_heldout_laps']) for ev, d in liq.items() for c, m in d['by_compound'].items()]
    full = [x for x in cells if all(y is not None for y in x[2:6])]; deg = [x for x in full if x[4] < 1e-6]; ok = [x for x in full if x[4] >= 1e-6]
    red = lambda sub: 1 - sum(x[4] * x[6] for x in sub) / sum(x[2] * x[6] for x in sub)
    return dict(n=len(full), wins=sum(1 for x in full if x[5] < min(x[2], x[3], x[4])), red_excl=red(ok), red_all=red(full), n_deg=len(deg),
                deg_events='/'.join(sorted({x[0] for x in deg})), med_change=_st.median((x[5] - x[4]) / x[4] for x in ok))
LQ = _liquid()
LQ_WINS = f'{LQ["wins"]} of {LQ["n"]} cells' if LQ else 'n/a (out/liquid.json missing)'
# the reduction is stated as a derived word ("about a quarter" for 20 to 30%) with its basis, not as a bare percentage: the red-team
# claim audit (liquid_23_pct_10_of_31) cannot verify the bare figure, so the documents carry the basis, the exclusion and the win count
LQ_CUTWORD = ('by about a quarter' if 0.2 <= LQ['red_excl'] < 0.3 else f'by about {LQ["red_excl"]:.0%}') if LQ else ''
LQ_CUT = (f'{LQ_CUTWORD}, lap-weighted, with the {_WORDS[LQ["n_deg"]] if LQ["n_deg"] < len(_WORDS) else LQ["n_deg"]} degenerate {LQ["deg_events"]} cells excluded ({LQ["red_all"]:.0%} with them)' if LQ else 'by an amount not available (out/liquid.json missing)')
LQ_MED = f'{LQ["med_change"]:+.0%}' if LQ else 'n/a'
LQ_TXT = f'per-lap inputs cut the age-only error {LQ_CUT}; the network on top of the same inputs beat the best baseline in only {LQ_WINS}'
MAD = {c['compound']: c for c in L['live']['Madrid']['compounds']}
def _mad_hard_laps():
    try: return sum(1 for r in _csv.DictReader(open('out/excluded_Madrid.csv')) if r['Compound'] == 'HARD' and r['reason'] == 'kept')
    except FileNotFoundError: return None
MAD_HARD_N = _mad_hard_laps()
MAD_HARD_TXT = f'no curve, {MAD_HARD_N} clean laps on Friday (excluded-laps table)' if MAD_HARD_N else 'no curve, no long runs on Friday'
def mad_txt(comp, d=3):
    c = MAD.get(comp)
    if c is None: return f'{comp.lower()}: no row in the lock'
    return f'{comp.lower()} {c["prediction"]:+.{d}f} s/lap, {"issued" if c["issued"] else "withheld"}, 90% band {c["band90"][0]:+.2f} to {c["band90"][1]:+.2f}, {c["n_prac"]} clean laps'
_MS = L['strategy']['Madrid']['views']; _NAME = {'S': 'soft', 'M': 'medium', 'H': 'hard'}
_stops = lambda k: {1: 'one stop', 2: 'two stops'}.get(k, f'{k} stops')
def plan_txt(v): return f'{_stops(len(v["stints"]) - 1)}, {" then ".join(_NAME[x] for x in v["plan"].split("-"))}, {" / ".join(map(str, v["stints"]))} laps'
MAD_PLAN_TXT = plan_txt(_MS['Orb v1']); _BH = _MS.get('Orb v1, band high')
MAD_BAND_TXT = f'the top of the band says {_stops(len(_BH["stints"]) - 1)}' if _BH else 'no band-high plan in the lock'
_MAXTREND = max(r['energy_trend'] for r in _ROWS if r['energy_trend'] is not None)
MAD_RAMP_TXT = (f'{MAD["MEDIUM"]["energy_trend"] / _MAXTREND:.1f} times the largest within-run ramp seen at an established circuit this season ({_MAXTREND:+.2f} MJ per lap)' if 'MEDIUM' in MAD else '')
MAD_MED_TXT = (f'Medium: energy through the tyre rose {MAD["MEDIUM"]["energy_trend"]:+.2f} MJ per lap through the runs, {MAD_RAMP_TXT}, which is drivers learning a new track.'
               + (f' The push-adjusted second opinion gives {MAD["MEDIUM"]["second_opinion"]["prediction"]:+.3f} s/lap, agreeing with the fallback.' if MAD.get('MEDIUM', {}).get('second_opinion') else '')) if 'MEDIUM' in MAD else 'Medium: no row in the lock.'
_QP = [(ev, c) for ev, s in L['strategy'].items() for c, src in (s.get('offsets_source') or {}).items() if 'qualifying' in str(src)]
OFFSETS_SRC_TXT = ('in the lock, qualifying supplies ' + '; '.join(f'the {c.lower()} offset at {", ".join(sorted(ev for ev, cc in _QP if cc == c))}' for c in sorted({c for _, c in _QP}))
                   + ', practice or a nominal step supplies the rest') if _QP else 'in the lock, every offset comes from practice or a nominal step'
# ---- Madrid refresh timeline, read from the artefacts (never typed): the lock, the hashed forecast and the refresh.sh logs ----
import hashlib as _hl, datetime as _dt, re as _re
_hm = lambda ts: _dt.datetime.fromisoformat(ts).strftime('%H:%M')
_cap = lambda t: t[0].upper() + t[1:]
LOCK_HM = _hm(L['generated_at'])
def _forecast():
    try: raw = open('out/forecast_Madrid_2026.json', 'rb').read()
    except FileNotFoundError: return None
    F = json.loads(raw); sha = _hl.sha256(raw).hexdigest()
    try: listed = next((ln.split()[0] for ln in open('out/forecast_Madrid_2026.sha256') if ln.strip().endswith('forecast_Madrid_2026.json')), None)
    except FileNotFoundError: listed = None
    return dict(issued_hm=_hm(F['issued_at']), sessions=list(F.get('sessions_used') or []), sha=sha, sha_ok=(listed == sha))
def _refresh(log, sess):
    """From a refresh.sh log: ([HH:MM of attempts that found `sess` not run yet], HH:MM the lock was rebuilt with `sess` fetched)."""
    try: txt = open(log).read()
    except FileNotFoundError: return [], None
    missed, landed = [], None
    for blk in _re.split(r'(?m)^== .*? start ', txt)[1:]:
        start = _re.match(r'\w{3} \w{3} +\d+ (\d\d:\d\d)', blk); rebuilt = _re.search(r'lock rebuilt: \w{3} \w{3} +\d+ (\d\d:\d\d)', blk)
        if _re.search(rf'Madrid {sess}: \d+ laps', blk) and rebuilt: landed = rebuilt.group(1)
        elif _re.search(rf'\b{sess}: not run yet', blk) and start: missed.append(start.group(1))
    return missed, landed
FC = _forecast(); FP3_MISSED, FP3_LANDED = _refresh('refresh_fp3.log', 'FP3'); Q_MISSED, Q_LANDED = _refresh('refresh_q.log', 'Q'); Q_LANDED = Q_LANDED or LOCK_HM
if FC and not FC['sha_ok']: print('WARNING: out/forecast_Madrid_2026.json does not match out/forecast_Madrid_2026.sha256')
_SESS = FC['sessions'] if FC and FC['sessions'] else None
SESS_TXT = ' and '.join(filter(None, [', '.join(_SESS[:-1]), _SESS[-1]])) if _SESS else 'the sessions in the lock'
SESS_SHORT = ', '.join(_SESS) if _SESS else 'sessions per the lock'
HASH12 = FC['sha'][:12] if FC else 'n/a'
MAD_REFRESH_TXT = ((f'FP3 refresh landed {FP3_LANDED}; ' if FP3_LANDED else '') + f'qualifying refresh landed {Q_LANDED} with {SESS_TXT} in the lock'
                   + (f' (a {" and ".join(Q_MISSED)} attempt found the session not yet run)' if Q_MISSED else ''))
MAD_REFRESHED_TXT = 'refreshed after FP3' + (f' (landed {FP3_LANDED})' if FP3_LANDED else '') + f' and after qualifying (landed {Q_LANDED}, {SESS_TXT} in the lock)'
MAD_REFRESHED_SHORT = 'refreshed after ' + (' and '.join({'Q': 'qualifying'}.get(s, s) for s in _SESS if s not in ('FP1', 'FP2')) if _SESS else 'FP3 and qualifying')
MAD_HASH_TXT = (f'hashed forecast published {FC["issued_hm"]} IST (sha256 {HASH12}' + ('' if FC['sha_ok'] else ', does not match the published .sha256') + ')') if FC else 'hashed forecast not yet published'
MAD_HASH_SHORT = f'sha256 {HASH12}, published {FC["issued_hm"]} IST' if FC else 'not yet published'
MAD_HASHED_AT = f'hashed at {FC["issued_hm"]} IST' if FC else 'not yet hashed'
# Madrid track evolution, read from the lock (live.Madrid.meta.evolution_s_per_min): a negative s/min is lap times falling, i.e. the track getting faster
_EVO = (L['live']['Madrid'].get('meta') or {}).get('evolution_s_per_min') or {}
_FRI_S = [s for s in ('FP1', 'FP2') if _EVO.get(s) is not None]   # the Friday sessions
_FRI = [-_EVO[s] * 60 for s in _FRI_S]
MAD_EVO_NUM = (f'{min(_FRI):.1f} s per hour' if f'{min(_FRI):.1f}' == f'{max(_FRI):.1f}' else f'{min(_FRI):.1f} to {max(_FRI):.1f} s per hour') if _FRI else 'the session evolution measured in the lock'
MAD_EVO_TXT = MAD_EVO_NUM + (' at Madrid on Friday' if _FRI else ' at Madrid')
MAD_EVO_BY_SESS = (', '.join(f'{s} {-_EVO[s] * 60:.2f}' for s in _FRI_S) + ' s per hour') if _FRI_S else 'no per-session evolution in the lock'
MAD_EVO_SESS = ' and '.join(_FRI_S) if _FRI_S else 'the Friday sessions'
MAD_LAPS = L['strategy']['Madrid'].get('n_laps')
# ---- the talk track's prepared answers (out/talk_track.md); every roadmap reference to their count derives it from this list ----
TT_QA = [
 ('What did you build today?', 'Seven new weekends including sprint format, the fallback rule, the push diagnostic, compound offsets from practice or qualifying medians, the liquid model and its ablation, the dashboard, Madrid live. The estimator and the first six weekends were disclosed pre-work from the idea round.'),
 ('Where is the AI?', 'The transfer factor is learned from previous weekends and scored on held-out ones. The liquid network was tested honestly and reported. The AI that earns its place is the one that survives the held-out test.'),
 ('How is this different from a regression on lap times?', 'Same estimator on practice and race, a gate that refuses, a factor learned across the season, a fallback that is scored, and a fifth confounder measured from telemetry that, in the public methods and rival repositories we reviewed, we did not find stripped anywhere.'),
 ('What breaks it?', 'Green tracks and new circuits, where drivers ramp up: the gate catches them and the fallback answers. Degraded telemetry feeds: refused, not modelled. Wet sessions: excluded. Safety cars and traffic in the race: the strategy replay ignores them and says so.'),
 ('Where could the race leak into the Friday prediction?', 'Three places, all closed. The transfer factor for a weekend comes from other weekends only; the fallback is the median of other weekends\' withheld outcomes; compound offsets come from that weekend\'s practice or qualifying medians, with a nominal step where the measured step is implausible, all before the race. The only thing that sees the race is the scorecard.'),
 ('The race starts after the event closes. What are you actually showing?', 'A lap-by-lap replay of a race we have already scored, Monza or Hungary: the Friday forecast on screen, the live estimator updating as laps arrive, the band shrinking, the pit call moving or holding. The same code runs on Madrid on Sunday evening, and the forecast it is compared against is hashed before the race (' + MAD_HASH_SHORT + ').'),
 ('The 2026 cars are new. Does a method tuned on 2026 mean anything?', 'The method is not tuned on 2026: it is stated priors and measured corrections. What is 2026-specific is the learned transfer factor, which is why the 2023 to 2025 seasons are being pulled onto disk: if the medium\'s Sunday ratio repeats at the same circuits across seasons it is a property of the tyre and the circuit; if not, of the 2026 car, and we say which.'),
 ('Would this work in Formula 2, where there is no telemetry feed?', 'The estimator needs lap times, tyre age, compound and flags, which F2 timing provides; the fuel and evolution corrections carry over. Without telemetry we lose the traffic flag and the push proxy, so more compounds are withheld and the bands widen. That is the honest degraded mode, and it is still far better than a straight line.')]
NUMWORDS = {4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight', 9: 'Nine', 10: 'Ten'}
N_TT_WORD = NUMWORDS.get(len(TT_QA), str(len(TT_QA)))
S = []
# ---------------- cover ----------------
S += [Spacer(1, 2.2 * cm), P('Orb v1', ParagraphStyle('T', parent=ss['Title'], fontSize=30, leading=36, alignment=0)),
      P('Clean tyre-degradation curves from Friday practice, scored against the race every Sunday.', ParagraphStyle('ST', parent=B, fontSize=13, leading=17, textColor=colors.HexColor('#374151'))),
      Spacer(1, 6), P('Part A: the Challenge Day roadmap, hour by hour, with deliverables, done-criteria, dependencies, fallbacks and the rubric criterion each task serves. Part B: the technical manual, simplified: what we are building, what it does, how it works, what we chose and why, and twenty questions a mentor or jury will ask about technical depth.', B),
      Spacer(1, 10), P('Team Orb v1 &middot; Samuel Christ &middot; TrackShift 2026, Tyre Degradation Intelligence &middot; Plaksha University, 12 to 13 September 2026', SM),
      P(f'Numbers in this document come from the locked results file generated {L["generated_at"]} IST: {V["n_weekends"]} scored 2026 weekends, {V["n_compound_weekends"]} compound-weekends, every figure leave-one-weekend-out. The estimator and the first six weekends are disclosed pre-work from the idea round (4 to 5 September); everything else was built on Challenge Day.', SM),
      Spacer(1, 16),
      P('Contents', H2)] + bullets(['<b>Part A. Roadmap</b>: A1 where we stand; A2 the two hours before building; A3 Saturday build schedule; A4 Sunday; A5 cut list and decision rules; A6 rubric map; A7 after the event', '<b>Part B. Technical manual</b>: 1 summary; 2 the problem; 3 inputs and outputs; 4 how it works; 5 results; 6 choices with pros and cons; 6b competitive landscape with eight questions; 8 twenty jury questions with answers; appendix']) + [PageBreak()]


# ================= PART A: ROADMAP =================
T0 = '11:15'
S += [P('Part A. Roadmap', H1), P('Clock times are IST on Saturday 12 September unless marked Sunday. Build start T0 = 11:15. Anchors that cannot move: Madrid FP3 16:00 to 17:00 (' + ('data landed ' + FP3_LANDED if FP3_LANDED else 'refresh_fp3.log not found') + '), qualifying 19:30 to 20:30 (data landed ' + Q_LANDED + (', after a ' + ' and '.join(Q_MISSED) + ' attempt found the session not yet run' if Q_MISSED else '') + '), race Sunday 18:30, after the event closes. Windows below are the plan; the Status column records what landed, read from the refresh logs and the published forecast. Priorities: P0 must exist for the pitch; P1 makes the pitch stronger; P2 is cut first. Rubric letters: T technical depth 30%, F problem-solution fit 25%, D demo 20%, S scalability and real-world viability 15%, C communication 10%.', SM),
      P('A1. Where we stand at 09:15, updated with what landed since', H2),
      table([['Component', 'Status', 'Evidence'],
             ['Data: 2026 rounds', 'Done: all 14 rounds that exist in the timing data, incl. qualifying sessions; Bahrain and Saudi Arabia do not exist for 2026', 'feat/ (70 session files); China FP1 position feed degraded and refused'],
             ['Data: 2025 rounds', 'Partial: 10 of 14 complete; Belgium (was mislabelled, deleted), Britain, Hungary, Zandvoort, Monza pending on FastF1\'s 500-calls-per-hour limit; automatic retry every 25 min from 09:28', 'feat2025/, retry2025.log'],
             ['Pipeline and lock', f'Done in the morning; lock rebuilt after FP3 ({FP3_LANDED or "time not on record"}) and after qualifying ({Q_LANDED}) with {V["n_weekends"]} scored weekends; generated {L["generated_at"]}', 'pipeline.py, out/lock.json, refresh_fp3.log, refresh_q.log'],
             ['Estimator, gate, fallback, factors, bands', 'Done and validated leave-one-weekend-out', 'out/validation.csv, sensitivity.json'],
             ['Push diagnostic and second opinion', 'Done', 'lock: push_diagnostic, path_b'],
             ['Strategy layer with compound offsets from practice or qualifying medians', f'Done; replay scored on {N_SC} weekends', 'strategy2.py, lock: strategy'],
             ['Liquid model with fair ablation', 'Done (v1 and tuned v2)', 'out/liquid.json, liquid_v2.json'],
             ['Dashboard, six views, URL-addressable', 'Done; last verified 07:40; must be re-launched on the venue laptop', 'app.py, launch.json'],
             ['Deck v1 (10 slides), talk track, figures', f'Done in the morning; figures and the 10-slide deck rebuilt by refresh.sh at each refresh (last {Q_LANDED}); talk track regenerated from the {LOCK_HM} lock by this build', 'out/Orb_v1_ChallengeDay.pdf, talk_track.md, fig_*.png'],
             ['Madrid live forecast', 'Issued from FP1 and FP2 in the morning; ' + MAD_REFRESH_TXT + '; ' + MAD_HASH_TXT, 'lock: live.Madrid; refresh_fp3.log, refresh_q.log; out/forecast_Madrid_2026.json and .sha256'],
             ['This manual', 'Done', 'out/Orb_v1_Roadmap_and_Manual.pdf']], [4.2 * cm, 8.2 * cm, 4.4 * cm]),
      P('A2. The two hours before building (09:15 to 11:15): research, planning and environment only', H2),
      table([['When', 'Task', 'Done when'],
             ['09:15 to 09:45', 'Read Part B once. Mark anything you cannot explain in one sentence; ask me before 11:15.', 'A list of at most five open questions'],
             ['09:45 to 10:15', 'Environment on the venue network: open the dashboard (launch config clearstint-dashboard, port 8501), load ?ev=Madrid&amp;view=Weekend and ?view=Season%20validation, confirm both render. Check retry2025.log after 10:00.', 'Dashboard renders both views; 2025 retry status known'],
             ['10:45 to 11:15', 'Memorise the 90-second mentor version and the ' + N_TT_WORD.lower() + ' prepared answers (talk_track.md). Write the one-sentence disclosure: estimator and six-weekend validation were pre-work disclosed in the idea round; everything else was built here. Confirm the presentation slot and check-in with the organisers.', 'Script said aloud twice under 90 s']], [2.6 * cm, 10.2 * cm, 4 * cm]),
      P('A3. Saturday build schedule from T0', H2)]
ROWS = [
 ['A1', '11:15 to 11:40', '25', 'P0 T F', 'Rebuild the lock with every 2026 weekend that now has a race (adds Monaco; China stays refused). Record every number that changed against deck v1.', 'python pipeline.py; diff summary printed; a changes.md with old and new numbers', 'Dashboard shows the new lock time; changes.md exists', 'None', 'If a new weekend breaks a rule, exclude it and say why in changes.md'],
 ['A2', '11:40 to 12:10', '30', 'P1 T', 'Band coverage check: share and count of 90% bands containing the race value, leave-one-out, issued and fallback separately. Add to the lock and to the validation view.', 'validation.band_coverage in lock; one line on the validation view', 'Numbers appear on the dashboard', 'A1', 'If coverage is poor, widen the factor resampling and report both'],
 ['A3', '12:10 to 12:40', '30', 'P1 D', 'Static HTML export of the dashboard: one self-contained file per view with the Plotly figures and tables, for the case the app cannot run on the venue network.', 'out/static/*.html', 'Opens from the file system with no server', 'A1', 'Skip if the venue network and the app are stable at 12:00'],
 ['A4', '12:30 to 13:00', '30', 'P0 F', 'If a detailed problem brief is released: map every requirement to a view, a number, or a gap. Re-order the rest of this table if needed.', 'requirements.md with a three-column map', 'Every requirement has an owner row', 'Brief', 'If no brief is released, use the public three-sentence statement'],
 ['B1', '13:00 to 13:45', '45', 'P1 T C', 'Barcelona miss: why the soft prediction ran low and the naive line implied the right plan. One paragraph and one figure. Honest misses are a slide.', 'notes/barcelona.md, fig_barcelona.png', 'Paragraph reads in under 30 s', 'A1', 'Cut to one sentence on the strategy slide'],
 ['B2', '13:45 to 14:15', '30', 'P1 T', 'Data-quality slide: the lap-by-lap feed check, Hungary race and China FP1 refused, exclusion counts per reason per weekend.', 'fig_quality.png', 'Figure is legible at slide size', 'A1', 'Use the exclusions view live instead'],
 ['C1', '14:15 to 15:15', '60', 'P0 D C', 'Mentor checkpoint package: the demo path as five URLs in order, the 90-second script with A1 numbers, the ' + N_TT_WORD.lower() + ' prepared answers, the disclosure sentence. Rehearse once at the desk with the dashboard.', 'demo_path.md; script v2', 'Desk run under 90 s with no dead clicks', 'A1', 'None; this is the checkpoint'],
 ['C2', '15:15 to 16:00', '45', 'P0 C', 'Deck v2: update every number from the new lock; add the data-quality slide; keep ten slides.', 'out/Orb_v1_ChallengeDay_v2.pdf', 'Every number matches the lock', 'A1 B2', 'Keep v1 and correct numbers verbally'],
 ['D1', '16:00 to 17:20', '80', 'P1 T S', 'While FP3 runs: 2025 same-track prior table if the 2025 data completed (does the medium factor repeat at the same circuits?); practice-to-sprint test on the six sprint weekends (does Friday predict the Saturday sprint too?).', 'out/prior2025.csv, out/sprint_test.csv, one figure', 'Two tables with leave-one-out numbers', '2025 data', 'If 2025 data is still short, run the sprint test only'],
 ['D2', '17:30 to 18:00', '30', 'P0 D F', 'Madrid FP3 refresh: refresh.sh, re-issue the curves, record what moved and why (expect the medium ramp to shrink as drivers settle; hard may appear). Update the live view and the deck slide.', 'lock with FP3; madrid_changes.md', 'Live view shows FP3 in sessions_in_data', 'FP3 data', 'If data is late, refresh at 18:30; the FP1+FP2 issue stands'],
 ['E2', '18:45 to 19:30', '45', 'P2 T', 'Liquid tab final: tuned v2 numbers, cliff-lap rule sanity check on three weekends, one sentence per weekend on shape.', 'lock or liquid.json updated; tab text', 'Tab numbers match liquid_v2.json', 'None', 'First to cut'],
 ['F1', '19:30 to 20:45', '75', 'P0 S C', 'While qualifying runs: README with the disclosure paragraph, method summary, commands, data sources and limits; make the repository public; requirements.txt pinned.', 'Public repo URL', 'Fresh clone runs pipeline.py on the feature CSVs', 'None', 'Private repo shared with judges on request'],
 ['F2', '20:45 to 21:30', '45', 'P0 D F', 'Madrid qualifying refresh: compound offsets re-derived from practice or qualifying medians (nominal step where implausible), final strategy call (plan, stint lengths, crossover, what flips it), publish the forecast as JSON and a one-page PDF with a timestamp and a SHA-256 hash, and post the hash somewhere public.', 'out/forecast_Madrid.json and .pdf; hash posted', 'Hash matches the file; timestamp before 21:45', 'Qualifying data, D2', 'If qualifying data is late, publish on FP3 numbers and say so'],
 ['G1', '21:30 to 22:30', '60', 'P0 C', 'Deck v3 with the final Madrid slide and the forecast hash; talk track v3.', 'Orb_v1_ChallengeDay_v3.pdf', 'Numbers match the lock and the forecast', 'F2', 'v2 plus a verbal update'],
 ['G2', '22:30 to 23:15', '45', 'P0 C', 'One full timed five-minute run with the dashboard, then fix every dead click and every sentence over 20 words.', 'Run under 5:00', 'Recorded time', 'G1', 'None'],
 ['G3', '23:15 to 06:00', '405', 'P0', 'Sleep. A solo presenter with four hours of sleep loses more points than any P1 task gains.', 'Rest', 'You slept', 'None', 'None']]
# the windows above are the plan; the Status column says what landed, read from the refresh logs and the published forecast (blank where no artefact records it)
STATUS = {'D2': f'Landed {FP3_LANDED} (FP3 in the lock)' if FP3_LANDED else '',
          'F2': (f'Landed {Q_LANDED}: {SESS_SHORT} in the lock; forecast issued {FC["issued_hm"]} IST, sha256 {HASH12}' if FC else f'Landed {Q_LANDED}; forecast not yet published') + (f'; the {" and ".join(Q_MISSED)} attempt found Q not yet run' if Q_MISSED else ''),
          'G1': f'Talk track regenerated from the {LOCK_HM} lock by this build'}
ROWS = [r + [STATUS.get(r[0], '')] for r in ROWS]
ROW_HEAD = ['ID', 'Window', 'Min', 'Prio', 'Task', 'Deliverable', 'Done when', 'Depends', 'Fallback', 'Status']
S += [table([ROW_HEAD] + ROWS, [0.8 * cm, 1.9 * cm, 0.8 * cm, 1.0 * cm, 3.8 * cm, 2.2 * cm, 2.0 * cm, 1.1 * cm, 1.6 * cm, 2.0 * cm]),
      P('A4. Sunday 13 September', H2),
      table([['ID', 'Window', 'Prio', 'Task', 'Done when'],
             ['H1', '06:00 to 07:00', 'P0', 'Deck final check against the lock; print two copies of the deck and one of Part B section 8.', 'No number differs'],
             ['H2', '07:00 to 08:00', 'P0', 'Two timed runs; second one with a friend or another team asking the ' + N_TT_WORD.lower() + ' questions.', 'Both under 5:00'],
             ['H3', '08:00 to 08:30', 'P0', 'Dashboard smoke test on the venue network; static export open in a second tab.', 'Five demo URLs load'],
             ['H4', '08:30 to slot', 'P1', 'Buffer. If the 2025 prior finished overnight, one sentence on the scalability slide. Nothing new is built.', 'Nothing broken'],
             ['H5', 'Presentation', 'P0', 'Five minutes, then Q&amp;A from Part B section 8. Open the dashboard on Madrid live, end on the forecast hash.', 'Done'],
             ['I1', 'After 18:30 race', 'P1', 'Score Madrid with the same estimator; publish the scorecard whatever it says, with the pre-race hash beside it.', 'Scorecard public']], [0.8 * cm, 2.6 * cm, 1 * cm, 9.4 * cm, 3 * cm]),
      P('A5. Cut list and decision rules', H2)] + bullets([
      'Cut in this order if behind: E2 liquid tab, D1 sprint and 2025 tests, A3 static export (only if the app is stable), B1 written note (keep one sentence). Never cut A1, C1, C2, D2, F2, G1, G2, G3, H2, H3.',
      'If the venue network fails: the pipeline and dashboard run offline from the cached data; only FP3 and qualifying refreshes need the network, and they can wait for a phone hotspot.',
      'If FastF1 rate-limits again: the two Madrid refreshes are a handful of calls each and take priority over any 2025 download; kill retry2025.sh before a refresh.',
      'If the 12:30 brief asks for something not on this table: it goes in at A4 and displaces the lowest-priority task still ahead of it.',
      'If a number changes after A1: the deck, the talk track and the manual are regenerated from the lock, never edited by hand.']) + [
      P('A6. Rubric map: which tasks carry which criterion', H2),
      table([['Criterion', 'Weight', 'Carried by', 'What the jury sees'],
             ['Technical depth and innovation', '30%', 'Validation ladder, fifth confounder, ablation, coverage (A1, A2, B1, D1, E2)', 'Leave-one-weekend-out numbers; a measured confounder that, in the public methods and rival repositories we reviewed, we did not find stripped elsewhere; an honest network test'],
             ['Problem-solution fit', '25%', 'Curves from practice, gate and fallback, post-race scorecard, Madrid live (A1, D2, F2)', 'The brief answered literally: clean Friday curves and a validation tool that scores them on Sunday'],
             ['Demo and working prototype', '20%', 'Dashboard, forecast publication (C1, F2, H3)', 'Six views running on real data, a live weekend'],
             ['Scalability and real-world viability', '15%', 'Any Grand Prix by name from free data; F2, F3, F1 Academy, Indian F4; beyond the track (F1, D1)', 'One command per weekend; a customer with two engineers and public timing'],
             ['Presentation and communication', '10%', 'Deck v3, talk track, rehearsals (C2, G1, G2, H2)', 'Five minutes, one story: Friday lies twice']], [3.4 * cm, 1.3 * cm, 6 * cm, 6.1 * cm]),
      P('A7. After the event', H2)] + bullets([
      'Week 1: score Madrid and publish; package as a command-line tool (clearstint &lt;Grand Prix&gt;) that produces the lock and the static views for any weekend since 2018.',
      'Weeks 2 to 4: band coverage over a full season; hierarchical transfer factor with partial pooling across 2025 and 2026; per-lap track temperature; sprint races as a second validation target; OpenF1 intervals for races with degraded position feeds.',
      'Month 2: timing adapters for F2, F3 and F1 Academy; a pilot with a junior team or a broadcaster; beyond the track, the same clean-then-transfer loop on a public battery ageing set, then a fleet pilot in Punjab.']) + [PageBreak(), P('Part B. Technical manual', H1), Spacer(1, 4)]

# ---------------- 1 summary ----------------
S += [P('1. One-page summary', H1),
      P('<b>The problem.</b> Teams want to know how fast each tyre compound will degrade on Sunday, and Friday practice is the only place to measure it before the race. But a Friday lap time is not a tyre measurement. It carries fuel burning off, the track getting faster as rubber goes down, traffic, the car and driver, and how hard the driver was pushing at that moment. A straight line through Friday laps at the 2026 Hungarian Grand Prix says the medium degrades at +0.285 s per lap of tyre age. The race showed +0.042. Seven times wrong.'),
      P('<b>What Orb v1 does.</b> It takes the free public timing and telemetry for any Grand Prix weekend and runs six steps: <b>ingest</b> every lap of every session; <b>clean</b> each lap by removing fuel, track evolution, traffic and the stint it belongs to; <b>gate</b> so that a curve is issued only when Friday really supports one; <b>learn</b>, from previous weekends only, how much Sunday shrinks the Friday number for each compound; <b>forecast</b> the race degradation curve with a band, the crossover laps and a one-stop versus two-stop call; and <b>score</b> itself against the race with the same estimator on Sunday night.'),
      P(f'<b>The proof.</b> Across {V["n_weekends"]} weekends and {V["n_compound_weekends"]} compound-weekends, with every number computed leave-one-weekend-out, the naive line has a mean error of {m["naive"]:.3f} s/lap against the race. Orb v1 has {m["clearstint"]:.3f}. Correlation with the race goes from {cal["naive"]["r"]:.2f} to {cal["all_with_fallback"]["r"]:.2f}. It beats the naive fit on {V["wins_clearstint_over_naive"]} of {V["n_compound_weekends"]} cases. {V["n_issued"]} curves were issued; {V["n_withheld"]} compounds were withheld and forecast as low degradation instead; the {WH_TXT}, and the fallback error was {FB_TXT}.'),
      P('<b>The discovery.</b> We measure the energy a driver puts through the tyre from the public 3.7 Hz traces: ' + RAMP_TXT + '. The median within-run energy trend is ' + ET_TXT + '. That is a fifth confounder, the driver\'s push profile; in the public methods and rival repositories we reviewed, we did not find one that strips it. It is measured, not assumed.'),
      P('<b>Live.</b> Madrid\'s curves were issued this morning from FP1 and FP2 alone, ' + MAD_REFRESHED_TXT + ' to the values shown: ' + mad_txt('SOFT') + '; ' + mad_txt('MEDIUM') + ' (withheld because drivers were learning a new circuit; low degradation forecast by two independent routes); hard: ' + MAD_HARD_TXT + '. ' + _cap(MAD_HASH_TXT) + '; it will be scored after Sunday\'s race.'),
      P('<b>The product.</b> One locked results file feeds a six-view dashboard, the strategy replay, and the deck. It runs for any Grand Prix by name from free data on a laptop.')]
S += [PageBreak()]

# ---------------- 2 problem ----------------
S += [P('2. The problem in plain words', H1),
      P('<b>Friday lies twice.</b> The first lie is about what the tyre did on Friday. Every lap time mixes five things:')]
S += bullets(['<b>Fuel.</b> A 2026 car burns roughly 1.1 kg per lap, and each kilogram is worth about 0.030 s. A long run gets faster by about 0.033 s every lap for that reason alone, which looks like negative degradation.',
              '<b>Track evolution.</b> A green track gets faster as rubber goes down, by ' + MAD_EVO_TXT + ' (' + MAD_EVO_SESS + ' in the lock). Laps later in the session look better than they are.',
              '<b>Traffic.</b> Running within 60 m of another car costs downforce and lap time, and it is not the tyre\'s fault.',
              '<b>The stint.</b> Different drivers, cars, fuel loads and engine modes produce different absolute lap times. Only the change within a stint is about the tyre.',
              '<b>The push profile.</b> Drivers ramp up through a long run when learning a track or nursing a hard compound, and ease off when a soft tyre is going away. The lap time follows the driver as much as the tyre.'])
S += [P(f'The second lie is about Sunday. Even a perfectly cleaned Friday curve is not Sunday\'s curve, because drivers attack tyres in practice and manage them in a race. We measured this with the same estimator on both sides of the weekend: across the season the medium\'s race degradation runs at about {bc["MEDIUM"]["k_median"]:.2f} times its cleaned Friday value, the soft transfers roughly one to one (x{bc["SOFT"]["k_median"]:.2f}), and the hard factor (median x{bc["HARD"]["k_median"]:.2f}) is not applied because weekends disagree. This ratio is learned from previous weekends and applied only where weekends agree.'),
      P(f'<b>Why it matters.</b> A degradation curve is a decision: when to pit, which compound, one stop or two. Replayed on Hungary with the race-derived curves as the reference, the plan implied by the naive Friday line loses {H_NAIVE_COST:.0f} s against the best plan; Orb v1\'s plan loses {H_ORB_COST:.0f} s. Replayed on the {N_SC} scored 2026 weekends ({N_SPRINT} of them sprint weekends), the naive plan costs between {NV_MIN:.0f} and {NV_MAX:.0f} s, Orb v1\'s between {OB_MIN:.0f} and {OB_MAX:.0f} s, and Orb v1 {SC_TXT}.')]

# ---------------- 3 what it does ----------------
S += [P('3. What the product does: inputs and outputs', H1), P('<b>Inputs</b> (all free and public):')]
S += bullets(['FastF1 (v3.8): every lap of every session with compound, tyre age, stint, track status, timing accuracy flags, deleted-lap flags from race control, pit in and out, weather once a minute, and car telemetry (speed, throttle, brake, gear, DRS) plus position at about 3.7 Hz, including the distance to the car ahead.',
              'OpenF1 (optional): gap-to-car-ahead every four seconds in races, pit-lane durations, stints, race-control messages. Used for cross-checks and for races whose position feed is degraded.',
              'Pirelli compound nominations; practice and qualifying laps for compound pace offsets.'])
S += [P('<b>Outputs, per weekend and per compound:</b>')]
S += bullets(['<b>Issued curve:</b> race degradation in s per lap of tyre age, a 90% band, the naive and cleaned Friday slopes for comparison, the transfer factor and how many weekends it was learned from, and the basis in one sentence.',
              '<b>Withheld:</b> the gate reason (too few clean laps, or no positive degradation signal in cleaned practice), a low-degradation forecast with a band, the push diagnostic (energy trend through the runs), and a push-adjusted second opinion where available.',
              '<b>Exclusions:</b> every practice lap the estimator dropped, with its reason, and the counts per reason.',
              '<b>Strategy:</b> compound offsets from practice or qualifying medians (nominal Pirelli-range step where the measured step is implausible), crossover laps, the best one-stop and two-stop plans with stint lengths, and, once the race is run, the time cost of following each Friday view instead of the best plan.',
              '<b>Season validation:</b> the calibration ladder (naive, cleaned, Orb v1), per-compound errors, bootstrap intervals, the list of withheld cases and what the race did, the sensitivity sweep.'])
S += [P('<b>Dashboard views:</b> Weekend (live or scorecard), Strategy, Liquid model, Season validation, Excluded laps, Method &amp; assumptions. Each view is addressable by URL for the demo. Static HTML fallback planned in case the app cannot run.'), PageBreak()]

# ---------------- 4 how it works ----------------
S += [P('4. How it works, step by step', H1),
      P('4.1 Data and quality checks', H2),
      P('For every lap we compute: lap and sector times, tyre age and compound, session time, track status, whether the lap was deleted, pit in/out flags, a traffic share (fraction of the lap spent within 60 m of the car ahead, from the distance-to-car-ahead channel), a tyre-energy proxy, and two feed-quality numbers: how many distinct position points the lap contained and what share of speed samples were stale repeats. Feeds that are degraded at source, such as the Hungary race (about 26 distinct position points per lap instead of about 300) and China FP1, are refused for telemetry-based quantities rather than modelled silently.'),
      P('4.2 The cleaning model', H2),
      P('Laps are first filtered: unknown or wet compounds, deleted laps, pit laps, laps under yellow, safety car or red flags, laps flagged inaccurate by timing, laps without telemetry, laps with more than 30% of the distance in traffic, runs shorter than five clean laps, and laps slower than 105% of the run\'s best (cool-down and aborted laps) are dropped. Every drop is recorded with its reason.'),
      P('Then one regression, in words: <i>lap time = a constant for the stint + degradation rate for the compound &times; tyre age + a fuel term + a track-evolution term</i>. The stint constant absorbs the driver, the car, the fuel load and the engine mode, so only the change within a stint informs the degradation rate. The fuel term is a stated prior from the 2026 regulations (1.1 kg per lap at 0.030 s per kg), not estimated from practice, because within a stint fuel and tyre age move together and cannot be separated; a public estimate from race data gives 0.0294 s per kg. Track evolution is measured per session from every driver\'s push laps (laps within 1% of that driver\'s own best) against session time, and subtracted. The same regression, with fuel from race progress instead of the prior, is applied to the race. Because the estimator is identical on both sides, the practice-to-race ratio is a property of the data, not of the method.'),
      P('4.3 The gate and the fallback', H2),
      P('A curve is issued only if the compound has at least 30 clean long-run laps and its cleaned Friday slope is at least +0.02 s per lap. Otherwise the compound is withheld. Withheld is still a forecast: low degradation, equal to the median race degradation of the other withheld cases this season (leave-one-out), with a 10th to 90th percentile band. Fallback error so far: ' + FB_TXT + '; the ' + WH_TXT + '.'),
      P('4.4 The transfer factor and the bands', H2),
      P(f'For each compound, the ratio of race degradation to cleaned Friday degradation is computed on every completed weekend. For a new weekend the factor is the median of the other weekends\' ratios, applied only if at least three exist and a majority sit within &plusmn;50% of that median; otherwise the cleaned curve is used as is. Season medians: soft &times;{bc["SOFT"]["k_median"]:.2f}, medium &times;{bc["MEDIUM"]["k_median"]:.2f}, hard &times;{bc["HARD"]["k_median"]:.2f} (hard is not applied because weekends disagree). The 90% band combines the regression\'s standard error on the slope with resampled ratios from the other weekends.'),
      P('4.5 Validation protocol', H2),
      P('Leave-one-weekend-out: each weekend is predicted from its own Friday and factors learned from the other weekends only, then compared with the race value from the same estimator. We report the mean absolute error for the naive line, the cleaned curve, and Orb v1; the calibration slope and correlation of predicted against observed; bootstrap intervals over compound-weekends; per-compound errors; and a sensitivity sweep over the fuel prior (0.9 to 1.3 kg per lap), the fuel cost (0.025 to 0.035 s per kg), the traffic threshold (20% to 40%) and the minimum run length (4 to 7 laps). Across that sweep the error stays between 0.021 and 0.027 s/lap.'),
      P('4.6 The fifth confounder: the push profile', H2),
      P('The tyre-energy proxy per lap is mass &times; (the integral of speed squared times path curvature along the lap, plus the integral of the absolute speed change), computed on a uniform 10 m arc-length grid from de-duplicated position samples so that stale packets do not bias curvature. Two uses. First, the within-run trend of energy against tyre age tells us whether the driver was ramping up: on withheld compounds the median trend is +0.10 MJ per lap of age, on issued compounds 0.00. Second, adding the within-run energy deviation as a covariate gives a push-adjusted slope, degradation at constant push, and its coefficient, the energy price of lap time, ' + BETA_TXT + '. The push-adjusted slope is a diagnostic and a second opinion, not the headline predictor, because easing off is partly a consequence of degradation and adjusting for it removes some of the signal we want; the as-driven estimator with the learned factor predicts the race better.'),
      P('4.7 The strategy layer', H2),
      P('Compound pace offsets come from each driver\'s best clean lap per compound in practice or qualifying, whichever the lock records for that weekend (the code tries qualifying first and falls back to practice; ' + OFFSETS_SRC_TXT + '), accepted only if the step is between 0.2 and 1.0 s (practice bests on harder compounds are often heavy-fuel laps), otherwise a nominal Pirelli-range step of 0.6 s per compound. With a 21 s pit loss and linear curves, every one-stop and two-stop plan with two or more compounds is enumerated and the fastest is chosen; crossover laps are where the harder compound becomes faster at equal age. Once the race is run, the plan implied by each Friday view is costed under the race-observed curves, so the naive line, the cleaned curve and Orb v1 are compared as decisions, not just as numbers.'),
      P('4.8 The liquid model', H2),
      P('A closed-form continuous-time cell (CfC, Hasani et al. 2022, the fast form of the liquid time-constant network) reads each race stint lap by lap: tyre age, elapsed laps, compound, energy, traffic, temperature, fuel. It predicts the cleaned pace-loss trajectory up to a per-stint constant, exactly the fixed-effect treatment of the linear model, and is scored on held-out stints within each weekend against linear and quadratic fits on the same folds, and against a linear fit given the same per-lap inputs. Result: the ' + LQ_TXT + ' (median change in held-out error ' + LQ_MED + ', no gain). It is kept as the curve-shape tool (accelerating versus settling, cliff lap) and reported honestly.'),
      P('4.9 The lock file', H2),
      P('pipeline.py writes out/lock.json: rules, per-weekend metadata, every validation row, live forecasts, strategy plans. The dashboard and the deck read from it, so every number on screen traces to the lock, a hashed sidecar or a labelled placeholder; the Live Predictor computes its posterior and ranked actions in-process by deterministic replay of the frozen prior and the hashed race file. Re-running the pipeline after a new session (refresh.sh) regenerates everything.'), PageBreak()]

# ---------------- 5 results ----------------
S += [P('5. Results so far', H1), P('5.1 Calibration ladder, leave-one-weekend-out', H2),
      table([['Predictor', 'Cases', 'MAE (s/lap)', 'Calibration slope', 'Pearson r'],
             ['Naive pooled fit', V['n_compound_weekends'], f'{m["naive"]:.3f}', f'{cal["naive"]["slope"]:+.2f}', f'{cal["naive"]["r"]:+.2f}'],
             ['Cleaned Friday curve, issued cases', V['n_issued'], f'{mi["clean"]:.3f}', f'{cal["clean"]["slope"]:+.2f}', f'{cal["clean"]["r"]:+.2f}'],
             ['Orb v1, issued cases', V['n_issued'], f'{mi["clearstint"]:.3f}', f'{cal["clearstint"]["slope"]:+.2f}', f'{cal["clearstint"]["r"]:+.2f}'],
             ['Orb v1, all cases incl. low-degradation fallback', V['n_compound_weekends'], f'{m["clearstint"]:.3f}', f'{cal["all_with_fallback"]["slope"]:+.2f}', f'{cal["all_with_fallback"]["r"]:+.2f}']], [7.2 * cm, 1.6 * cm, 2.6 * cm, 3 * cm, 2.4 * cm]),
      Spacer(1, 4), P(f'90% bootstrap interval on the Orb v1 error: {V["ci90_mae_clearstint_all"][0]:.3f} to {V["ci90_mae_clearstint_all"][1]:.3f} s/lap. Probability that Orb v1 beats the uncalibrated cleaned curve on issued cases: {V["p_clearstint_beats_clean_issued"]:.2f}. Wins over naive: {V["wins_clearstint_over_naive"]} of {V["n_compound_weekends"]}.', SM),
      Spacer(1, 6), fig('out/fig_calibration.png', 11.5, 'Figure 1. Predicted from Friday against observed in the race, every compound-weekend. Filled circles are issued curves, open diamonds the low-degradation fallback, crosses the naive line. The dashed line is perfect calibration.'),
      P('5.2 Per compound', H2),
      table([['Compound', 'Cases', 'MAE naive', 'MAE Orb v1', 'Transfer factor (median)']] + [[c.title(), bc[c]['n'], f'{bc[c]["mae_naive"]:.3f}', f'{bc[c]["mae_clearstint"]:.3f}', f'x{bc[c]["k_median"]:.2f}'] for c in ['SOFT', 'MEDIUM', 'HARD']], [3 * cm, 1.6 * cm, 2.6 * cm, 3 * cm, 4 * cm]),
      P('5.3 Withheld cases and what the race did', H2),
      table([['Weekend', 'Compound', 'Race degradation (s/lap)']] + [[w['event'], w['compound'].title(), f'{w["obs"]:+.3f}'] for w in V['withheld_cases']], [4 * cm, 3 * cm, 4.5 * cm]),
      Spacer(1, 4), fig('out/fig_push.png', 11.5, 'Figure 2. Within-run trend of tyre energy per lap of age on Friday long runs. Withheld compounds are the ones where drivers were still ramping up (median +0.10 MJ per lap); issued compounds are flat (0.00).'),
      P('5.4 Sensitivity of the headline to the stated choices', H2)]
sens = json.load(open('out/sensitivity.json'))['runs']
S += [table([['Variant', 'Cases', 'Issued', 'MAE Orb v1', 'r']] + [[k, v['n'], v['issued'], f'{v["mae"]:.3f}', f'{v["r"]:+.2f}'] for k, v in sens.items()], [5.5 * cm, 1.6 * cm, 1.6 * cm, 3 * cm, 2 * cm]),
      P('5.5 Strategy replay: cost of following each Friday view, under the race-observed curves', H2)]
rows = [['Race', 'Laps', 'Naive plan', 'Cost', 'Orb v1 plan', 'Cost', 'Best plan']]
for ev, s in L['strategy'].items():
    vs = s['views']
    if 'Orb v1' in vs and 'cost_under_truth_vs_best_s' in vs['Orb v1']:
        rows.append([ev, s['n_laps'], vs['Naive fit']['plan'], f'+{vs["Naive fit"]["cost_under_truth_vs_best_s"]:.0f} s', f'{vs["Orb v1"]["plan"]} {"/".join(map(str, vs["Orb v1"]["stints"]))}', f'+{vs["Orb v1"]["cost_under_truth_vs_best_s"]:.0f} s', vs['Orb v1']['best_under_truth']['plan']])
S += [table(rows, [2.6 * cm, 1.3 * cm, 2.4 * cm, 1.6 * cm, 3.6 * cm, 1.6 * cm, 2.2 * cm]),
      P('Assumptions of the replay: pit loss 21 s, linear curves, no traffic, safety car or weather. Orb v1 ' + SC_TXT + '; at Barcelona the naive line happened to imply the right plan and Orb v1\'s soft prediction was low. The replay ranks Friday views as decisions, which is the only ranking a strategist cares about.', SM),
      P('5.6 Madrid, live: issued from FP1 and FP2, refreshed after FP3 and after qualifying', H2)]
mad = L['live']['Madrid']['compounds']
S += [table([['Compound', 'Clean laps', 'Naive', 'Cleaned Friday', 'Orb v1 forecast', '90% band', 'Basis']] + [[c['compound'].title(), c['n_prac'], f'{c["naive"]:+.3f}', f'{c["clean"]:+.3f}', f'{c["prediction"]:+.3f}', f'{c["band90"][0]:+.3f} to {c["band90"][1]:+.3f}', c['basis']] for c in mad], [1.8 * cm, 1.4 * cm, 1.4 * cm, 1.9 * cm, 2.2 * cm, 2.6 * cm, 5.7 * cm]),
      P(MAD_MED_TXT + ' Hard: ' + MAD_HARD_TXT + '. Strategy on the central curve: ' + MAD_PLAN_TXT + '; ' + MAD_BAND_TXT + '. ' + _cap(MAD_REFRESH_TXT) + '; the table shows the post-qualifying lock. ' + _cap(MAD_HASH_TXT) + ', scored after Sunday\'s race.', SM), PageBreak()]

# ---------------- 6 pros and cons ----------------
S += [P('6. What we chose, and the pros and cons of each choice', H1),
      table([['Choice', 'Why', 'Cost or risk', 'Mitigation'],
             ['Within-stint fixed-effects regression as the core, not a black-box learner', 'Identifiable and transparent; identical on practice and race; a Haas engineer can audit every term', 'Linear in age; no interactions; misses cliffs', 'Quadratic and liquid shape tools flag the exceptions; linear is kept for prediction because it validates best'],
             ['Fuel as a stated prior, not estimated from practice', 'Within a stint fuel and tyre age are collinear; estimating fuel from practice is not identified', 'A wrong prior biases every slope', 'Sensitivity sweep 0.9 to 1.3 kg/lap and 0.025 to 0.035 s/kg: error stays 0.023 to 0.026; external race-data estimate 0.0294 s/kg'],
             ['Track evolution measured from push laps per session', 'Push laps happen at different times on fresh tyres, so time and age separate', 'Long-run evolution may differ from push-lap evolution on green tracks', 'The gate catches it; Madrid medium is the live example'],
             ['Traffic from the distance-to-car-ahead channel, 30% threshold', 'Measured per lap, not guessed', 'Threshold is a choice; NaN gaps drop laps', 'Sweep 20% to 40%: error 0.027 to 0.021; NaN laps excluded, never assumed clean'],
             ['A gate that refuses, plus a scored low-degradation fallback', 'Never silently wrong; the refusal is itself informative', f'{NWH} of {V["n_compound_weekends"]} compounds withheld', 'Fallback error ' + FB_TXT + '; ' + WH_TXT + '; push-adjusted second opinion'],
             ['Transfer factor learned leave-one-weekend-out with an agreement rule', 'Honest out-of-sample number; applied only where weekends agree', 'Ten or so weekends is a small sample; hard never qualifies', 'Bootstrap intervals; 2025 same-track ratios as a prior (downloading)'],
             ['Tyre-energy proxy from public 3.7 Hz traces', 'The only public route to the driver\'s push profile; unique confounder', 'A proxy: no tyre temperatures or pressures; position feeds sometimes degraded', 'Arc-length resampling and stale-sample removal; lap-level quality checks; degraded feeds refused'],
             ['Push-adjusted slope as a diagnostic, not the predictor', 'Easing off is partly caused by degradation; adjusting removes signal', 'Two numbers per compound can confuse', 'Reported as a second opinion with its own factor; the as-driven number is the headline'],
             ['Public data only', 'Reproducible for any Grand Prix by name on a laptop; usable by data-poor categories', 'No fuel flow, tyre temperatures or pressures', 'Stated priors; the method takes those as inputs when a team has them'],
             ['Single lock file feeding dashboard and deck', 'Every number on screen traces to the lock, a hashed sidecar or a labelled placeholder; regeneration is one command', 'Stale lock if a session lands and the pipeline is not rerun', 'refresh.sh; the lock carries its timestamp on every page'],
             ['Streamlit dashboard', 'Fast to build, interactive, URL-addressable views', 'Not a production UI; needs the Python environment', 'Static HTML export as fallback'],
             ['Liquid network tested and reported as an ablation', 'Distinctive AI element; honest', 'No accuracy gain over a linear model with the same inputs', 'Used for curve shape; the inputs finding is the real result'],
             ['Solo presenter', 'One voice, no hand-offs', 'Bandwidth on the day', 'Scripted demo path and URL deep links; deck as PDF'],
            ], [4 * cm, 4.4 * cm, 3.8 * cm, 4.6 * cm]), PageBreak()]


S += [P('6b. Competitive landscape, checked 12 September 09:50 IST', H1),
      P('Public GitHub repositories on the TrackShift 2026 tyre problem, plus the one published paper. Finalist status of each team is unknown. Ratings are our reading of their README and artefacts on that morning.', SM),
      table([['Entry', 'Method and data', 'Validation', 'Practice to race', 'Honesty and gating', 'Live forecast', 'Demo and AI'],
             ['Orb v1 (us)', 'Stint fixed-effects on practice and race; fuel prior, measured evolution, traffic, push profile from telemetry energy; 11 scored 2026 weekends, 29 compound-weekends', 'Leave-one-weekend-out; MAE 0.023 vs 0.137 naive; r 0.78; sensitivity sweep', 'Learned per compound with an agreement rule; validated', 'Gate plus validated low-degradation fallback; exclusions listed', 'Madrid issued from FP1 and FP2, refreshed after FP3 and Q, hashed', 'Six-view dashboard; liquid-network ablation'],
             ['PITWALL (OptimistOtaku)', 'Fixed effects via Frisch-Waugh, cluster-robust errors, fuel estimated from race pit steps, traffic from position; 12 events 2026', 'Leave-one-event-out on stop value; three published falsifications', 'Claims no transfer (measured on pit-stop deltas); model omits tyre age', 'High; states limits', 'None: replays past races', 'pptx deck, 8 figures, single-file fallback demo; no learned model'],
             ['GripTrace (RizaShaik)', 'Covariate regression; traffic under 200 m as covariate; no fuel model; 2023 Bahrain, soft only, 466 practice laps', 'Race held out once for the soft', 'Finds the Friday trend not identifiable', 'High; careful language', 'None', 'Streamlit; no AI element'],
             ['TyreIQ (suganya1703)', 'XGBoost on synthetic 2023 Bahrain data with an assumed cliff', 'In-sample on synthetic data (R-squared 0.98)', 'None', 'Low: data is generated', 'None', 'Streamlit, four tabs, pit advisor; 9 stars'],
             ['Dr.Tyre (Shall We Develop)', 'FastF1 pipeline: fuel, evolution, traffic, ghost baseline; data extent unstated', 'A validation panel; no numbers in README', 'None stated', 'Medium', 'None', 'Vite race simulator with an AI race engineer'],
             ['TIREX (Tanish9022)', 'Planned Kalman state-space with a physics confounder engine; backend phases 1 and 2 only', 'Planned', 'Planned', 'States data-honesty rules', 'None', 'FastAPI backend; no frontend yet'],
             ['TrackShift AI (Icey067)', 'Fixed constants for fuel, evolution and dirty air; simulated toggles', 'In-sample R-squared above 0.94', 'None', 'Low', 'None', 'React, GSAP, Gemini voice debriefs; Cloud Run demo'],
             ['Empirical substantiation (vib06hav)', '2023 to 2025 practice-only associations', 'Sensitivity analyses', 'Concludes not identifiable', 'High', 'None', 'None'],
             ['arXiv 2512.00640 (Cappello, Hoegh)', 'Bayesian state-space, one driver, one race, fuel plus latent pace', 'Against ARIMA on that race', 'Race only', 'Academic', 'None', 'Code public']], [2.6 * cm, 3.6 * cm, 2.6 * cm, 2.2 * cm, 2.1 * cm, 1.9 * cm, 2.2 * cm]),
      P('Where we lead', H2)] + bullets(['Problem-solution fit: we deliver the literal brief, clean practice curves plus a post-race validation tool, on every compound of every weekend. PITWALL pivoted away from the curve; GripTrace and the substantiation study concluded it cannot be found.',
      'Scale and protocol of validation: 29 compound-weekends leave-one-weekend-out with a naive baseline, a calibration slope and a sensitivity sweep. In the public repositories we reviewed, we did not find another entry reporting a season-scale held-out score.',
      'The transfer question answered with data: correlation 0.78 at the compound-weekend level, which is the strategist\'s unit, against PITWALL\'s stop-delta measurement whose noise is as large as its signal.',
      'The fifth confounder, the driver\'s push profile, measured from telemetry energy: ' + RAMP_TXT + '; in the public methods and rival repositories we reviewed, we did not find it.',
      'Refusal as a product feature, with a scored fallback: ' + WH_TXT + '.',
      'A live, time-stamped forecast for this weekend; every other entry we reviewed replays a past race or simulates one.']) + [
      P('Where they lead, and what we do about it', H2)] + bullets(['PITWALL estimates the fuel cost from race pit steps and uses cluster-robust errors. Answer: our fuel prior is a stated assumption whose sensitivity is published, and it agrees with their estimate (0.030 versus 0.0294 s per kg).',
      'PITWALL published falsifications of its own strategy ideas. Answer: our Barcelona and Australia misses and the liquid-network ablation are on the slides, not hidden.',
      'TyreIQ, Dr.Tyre and TrackShift AI have slicker interfaces and race simulators. Answer: our dashboard is plainer but every number on it traces to the lock, a hashed sidecar or a labelled placeholder, and the forecasts are scored; we say that in the first minute.',
      'TIREX\'s Kalman design would give principled per-lap uncertainty. Answer: our bands come from regression error plus resampled factors and are checked by coverage; a state-space model is on the post-event roadmap.']) + [
      P('Eight questions about the competition, with answers', H2)]
for q, a in [
 ('PITWALL says practice curves do not transfer. Why should we believe you and not them?', 'Because we measure the transfer at the unit a strategist uses, the compound-weekend slope, and it correlates with the race at 0.78 leave-one-out. Their measurement is on pit-stop deltas, where the standard deviation is nearly the mean, so almost nothing would correlate. Both findings can be true at the same time; ours is the one that answers the brief.'),
 ('PITWALL estimates fuel from race data and you assume it. Is that not weaker?', 'It is a stated assumption, and its consequences are published: across 0.9 to 1.3 kg per lap and 0.025 to 0.035 s per kg the error stays between 0.023 and 0.026. Their race-data estimate, 0.0294 s per kg, sits inside our sweep. We chose a prior because within a practice stint fuel and age are collinear and estimation from practice is not identified.'),
 ('GripTrace found that the tyre-age trend is not identifiable. Did you find the same?', 'On some weekends, yes: that is exactly what the gate detects, and where the cleaned slope pointed the wrong way we found the reason, the driver ramping up through the run. On the other sixteen compound-weekends the cleaned curve is identifiable and predicts the race. One weekend and one compound cannot tell those two cases apart; twenty-nine can.'),
 ('TyreIQ reports R-squared 0.98. Yours is far lower. Why?', 'Theirs is measured on synthetic data generated with an assumed degradation curve, in sample. Ours is measured against eleven real races the model never saw. A high score on your own synthetic data is not evidence about Sunday.'),
 ('Several rivals have prettier dashboards and race simulators. Why is yours plain?', 'Because a simulator without a scorecard is a story. Every number on our screens traces to the lock, a hashed sidecar or a labelled placeholder, the forecasts are scored against races, the excluded laps are listed, and the Madrid forecast is on record before the race. We would rather be plain and right than animated and unscored.'),
 ('What do you have that no rival has?', 'In the public repositories we reviewed, we did not find any of these four: the fifth confounder measured from telemetry energy, a learned and validated transfer factor, a validated fallback for withheld compounds, and a live time-stamped forecast for this weekend.'),
 ('What have you borrowed from the rivals?', 'PITWALL\'s practice of publishing falsifications, which is why the Barcelona and Australia misses and the network ablation are on our slides; GripTrace\'s care with language about what public data can and cannot support.'),
 ('If PITWALL is in the room, what is your one-sentence answer to them?', 'Friday transfers once you learn how Sunday is managed; here are twenty-nine held-out cases, and here is Madrid on record before the race.')]:
    S += [KeepTogether([P(f'<b>{q}</b>', B), P(a)])]
S += [PageBreak()]

# ---------------- 7 roadmap ----------------
# NOTE: RM is not rendered (section 7 points the reader to Part A); kept derived so no stale typed time survives in this builder.
RM = [
 ('Phase 0. Disclosed pre-work (4 to 5 Sep, idea round)', 'Done', [
   'features.py: per-lap features from telemetry (energy proxy, traffic share, feed quality). model_v2.py: the stint fixed-effects estimator with the 2026 fuel prior and track evolution. make_figs.py: six-weekend validation, leave-one-weekend-out factors, bootstrap. strategy.py: Hungary and Austria replay. Idea deck and form text.']),
 ('Phase 1. Challenge Day, overnight and morning (12 Sep 02:30 to 09:00)', 'Done', [
   'Environment rebuilt (durable venv, cache), 2026 data for all fourteen rounds that exist plus qualifying sessions; Bahrain and Saudi Arabia do not exist in the 2026 timing data.',
   'pipeline.py and the lock file; the low-degradation fallback; the push diagnostic and second opinion; strategy2.py with compound offsets from practice or qualifying medians and the replay scoring; liquid.py with the fair ablation; app.py with six views; deck v1, talk track, sensitivity sweep; Madrid issued from FP1 and FP2.']),
 ('Phase 2. Today, after the 12:30 detailed brief', 'Planned', [
   '12:30. Read the detailed problem prompt. Map every requirement to an existing view or a gap. Decide what changes. Nothing else is built before this.',
   '13:00 to 15:00. Hardening: add Britain and Monaco to the scored set (rerun pipeline), band-coverage check (share of 90% bands containing the race value), Barcelona miss written up, exclusions export per weekend, static HTML fallback of the dashboard.',
   '15:00 to 17:00. Mentor checkpoint: 90-second desk version with the live Madrid view, the calibration ladder and the withheld list. Four prepared answers (what was built today, where is the AI, what is new, what breaks it).',
   'FP3 refresh' + (f' (landed {FP3_LANDED})' if FP3_LANDED else '') + ': refresh.sh, re-issue the curves, record what moved and why (the medium ramp should shrink as drivers settle).',
   f'Qualifying refresh (landed {Q_LANDED}): compound offsets re-derived from practice or qualifying medians, final strategy call, publish the time-stamped forecast as JSON and PDF ({MAD_HASH_TXT}). This is the forecast the jury can verify after the event.',
   'Evening. 2025 same-track prior table when the download completes; practice-to-sprint test on the six sprint weekends; deck v2 with today\'s numbers; three timed five-minute runs.']),
 ('Phase 3. Sunday 13 Sep', 'Planned', [
   '06:00 to 09:00. Deck final; rehearse three times against the clock; README with the disclosure paragraph; repository public.',
   '09:30. Dashboard smoke test on the venue network; static fallback ready.',
   'Presentations. After the 18:30 IST race: score Madrid with the same estimator and publish the scorecard, after the event closes.']),
 ('Phase 4. After the event (v1.0 in four weeks)', 'Proposed', [
   'Command-line tool: clearstint &lt;Grand Prix&gt; produces the lock and the dashboard export for any weekend since 2018.',
   'Band coverage over a full season; a hierarchical model for the transfer factor with partial pooling across seasons; per-lap track temperature as a covariate; sprint races as a second validation target; OpenF1 intervals for races with degraded position feeds.',
   'Adapters for F2, F3 and F1 Academy timing, where two engineers and public data are the norm; a pilot with a junior team or a broadcaster.',
   'Beyond the track: the same clean-then-transfer loop on a public battery ageing set, then a fleet pilot in Punjab.'])]
S += [P('7. Roadmap', H1), P('See Part A at the front of this document: the full clock-based schedule with task IDs, deliverables, done-criteria, dependencies, fallbacks, the cut list and the rubric map.', B), Spacer(1, 6)]

# ---------------- 8 questions ----------------
QA = [
 ('How do you separate fuel burn from tyre degradation when both change monotonically within a stint?', 'We do not try to estimate fuel from practice; within a stint the two are collinear and the estimate is not identified. The fuel term is a stated prior from the 2026 regulations, 1.1 kg per lap at 0.030 s per kg, applied as a known offset. The sensitivity sweep shows the headline error stays between 0.023 and 0.026 s/lap across 0.9 to 1.3 kg per lap and 0.025 to 0.035 s per kg, and an independent public estimate from race data gives 0.0294 s per kg.'),
 ('Why a fixed effect per stint rather than per driver?', 'A stint carries its own fuel load, tyre set, engine mode and driver; a per-driver effect would leave fuel-load differences between runs in the residual and bias the slope. The cost is that we discard the absolute level and keep only the change within a stint, which is exactly what degradation is.'),
 ('How is track evolution identified separately from tyre age?', 'It is measured per session from every driver\'s push laps, laps within 1% of that driver\'s own best, against session time, driver-demeaned. Push laps happen at different times of the session on fresh tyres across drivers, so session time and tyre age are not collinear. At Madrid it was ' + MAD_EVO_NUM + ' on Friday (' + MAD_EVO_BY_SESS + ').'),
 ('How do you detect traffic, and how sensitive is the result to that choice?', 'From the distance-to-car-ahead channel at 3.7 Hz: the share of the lap spent within 60 m of the car ahead. Laps above 30% are dropped; laps without gap data are dropped rather than assumed clean. At 20% the error is 0.027, at 40% it is 0.021.'),
 ('Why leave-one-weekend-out rather than ordinary cross-validation?', 'Because the deployment question is a new weekend with no race yet. A random split would let a weekend\'s own race leak into the factor applied to its Friday. Every number in the deck is computed with the held-out weekend\'s race unseen.'),
 ('Your transfer factor is a median over ten numbers. Is that not fragile?', 'It is small, which is why it is applied only under an agreement rule, at least three weekends with a majority within 50% of the median, why hard never qualifies, and why we show bootstrap intervals: 0.016 to 0.030 on the error. The 2025 same-track ratios are the next test and are downloading.'),
 ('What does withheld mean, and is it not a way to avoid being wrong?', 'It means Friday had fewer than 30 clean long-run laps or no positive cleaned slope. It is still a forecast: low degradation, the median race value of the other withheld cases, leave-one-out. That forecast has an error of ' + FB_TXT + '; the ' + WH_TXT + '. It is scored like everything else.'),
 ('Why does a cleaned practice curve come out negative on some compounds?', 'Because the driver was ramping up. The within-run trend of tyre energy per lap of age is +0.10 MJ per lap at the median on withheld compounds and 0.00 on issued ones. Lap times fall faster than fuel burn explains, and the estimator reads it as negative degradation. We measure that rather than assume it.'),
 ('What is the energy proxy and how do you trust 3.7 Hz position data?', 'Mass times the integral of speed squared times path curvature along the lap, plus the integral of absolute speed change: lateral and longitudinal work through the contact patch. Curvature is computed on a 10 m arc-length grid from de-duplicated samples. Each lap carries a feed-quality check; the Hungary race feed had about 26 distinct points per lap instead of 300, so its energy is pace-estimated and its traffic is unknown, and the pipeline says so.'),
 ('Is the energy covariate not endogenous? Drivers lift because the tyre is degrading.', 'Yes, partly, which is why the push-adjusted slope is a diagnostic and a second opinion and not the predictor. Adjusting for push removes some of the degradation signal we want, and the as-driven estimator with the learned factor predicts the race better: the probability that the push-adjusted version beats it is 0.14.'),
 ('Where is the machine learning?', 'The transfer factor and the fallback are parameters learned on training weekends and scored on held-out weekends. The liquid network was trained and tested with a fair ablation. The AI that earns its place is the part that survives the held-out test.'),
 ('Tell us honestly what the liquid network did.', 'A closed-form continuous-time cell read each race stint lap by lap and predicted the cleaned trajectory, scored on held-out stints. Against age-only fits it wins almost everywhere. Against a linear model given the same per-lap inputs it beats the best baseline in only ' + LQ_WINS + ', and its median gain is about zero (' + LQ_MED + ' change in held-out error). The inputs were the discovery: energy, traffic and fuel cut the age-only error ' + LQ_CUT + '. The network stays as the curve-shape tool.'),
 ('How do you validate the uncertainty bands?', 'By coverage: the share of 90% bands that contain the race value, computed leave-one-out. With 16 issued cases the check is coarse, so it is reported as a count, not a percentage; the band construction combines the regression\'s standard error with resampled transfer ratios from other weekends.'),
 ('How does this fail?', 'New circuits and green tracks, where drivers ramp up: the gate withholds and the fallback answers, and Madrid is the live example. Wet sessions: excluded. Degraded telemetry feeds: refused, not modelled. Safety cars and traffic in the race: the strategy replay ignores them and says so. Compounds with thin running, hard at most European rounds: withheld for too few laps.'),
 ('Why linear degradation curves?', 'Because linear validates best for prediction at the tyre ages actually run. The quadratic and liquid curves split the season 15 accelerating against 13 settling, so there is no single non-linear shape to assume. The shape tools flag the exceptions and the cliff lap where one exists.'),
 ('How does this compare with the published state-space model on public F1 data?', 'That model (arXiv 2512.00640) fits one driver\'s race with fuel and a latent pace, with no practice input, no traffic, no track evolution and no cross-weekend validation. Ours starts from practice, strips four measured confounders and one diagnostic one, and is validated leave-one-weekend-out across eleven weekends. Its code is public and we can run it as a baseline on one race.'),
 ('A public analysis concludes practice curves do not transfer to the race. Your response?', 'That conclusion is measured on stop-by-stop pit deltas, a target whose standard deviation is close to its mean. At the compound-weekend level, with the management factor learned leave-one-out, the correlation between Friday and Sunday is 0.78 against 0.20 for the naive line. The curve transfers once you learn how each compound is managed.'),
 ('What does the strategist actually get on Saturday night?', 'Per compound: the slope, the 90% band, the basis in one sentence, or the withheld reason and the low-degradation forecast. Crossover laps. The best one-stop and two-stop plans with stint lengths and what flips the call. The list of excluded laps with reasons.'),
 ('How and when is the Madrid forecast scored?', 'The forecast was issued from FP1 and FP2 and is time-stamped; ' + MAD_REFRESH_TXT + '; ' + MAD_HASH_TXT + '. After Sunday\'s race, which starts 18:30 IST, after the event closes, the same estimator runs on the race laps and the scorecard is published. We commit to publishing it whether it is right or wrong.'),
 ('What would you need from a team to make this production-grade?', 'Fuel mass per lap, tyre pressures and temperatures, and the driver\'s push instructions. The fuel prior and the energy proxy then become measured inputs, the gate fires less often, and the rest of the method is unchanged. For F2, F3 and F1 Academy, which have public timing and two engineers, it runs as is.')]
S += [P('8. Twenty questions on technical depth, with answers', H1)]
for i, (q, a) in enumerate(QA, 1): S += [KeepTogether([P(f'{i}. {q}', QA_Q), P(a)])]
S += [PageBreak()]

# ---------------- appendix ----------------
S += [P('Appendix', H1), P('A. Files and commands', H2),
      table([['File', 'Role'], ['features.py', 'Per-lap features from telemetry (pre-work)'], ['model_v2.py', 'Stint fixed-effects estimator, practice and race (pre-work)'], ['extract_all.py, extract_more.py, extract_extra.py', 'Download and feature extraction per weekend and year'],
             ['pipeline.py', 'Every weekend -> out/lock.json, results.csv, validation.csv, excluded_&lt;event&gt;.csv'], ['strategy2.py', 'Offsets, plans, crossover, replay scoring'], ['liquid.py', 'CfC shape model with held-out ablation -> out/liquid.json'],
             ['app.py', 'Streamlit dashboard (streamlit run app.py; views at ?ev=&lt;event&gt;&amp;view=&lt;view&gt;)'], ['refresh.sh', 'Pull new Madrid sessions and rebuild the lock'], ['build_deck*.py, talk_track.md', 'Deck and script']], [6 * cm, 10.8 * cm]),
      P('B. Stated assumptions', H2)] + bullets(['Fuel: 1.1 kg per lap in practice at 0.030 s per kg; race fuel 70 kg burned linearly over the race distance.', 'Traffic: laps with more than 30% of the distance within 60 m of the car ahead are dropped.', 'Runs: at least 5 clean laps; laps slower than 105% of the run best dropped.', 'Gate: at least 30 clean laps and a cleaned slope of at least +0.02 s/lap.', 'Transfer factor: median of other weekends, applied only with at least three and a majority within 50%.', 'Strategy: pit loss 21 s; compound offsets from practice or qualifying medians if the step is 0.2 to 1.0 s, else a nominal Pirelli-range step of 0.6 s per compound; linear curves; no safety car, traffic or weather.', (f'Madrid race length {MAD_LAPS} laps (FIA rule, 5.474 km circuit).' if MAD_LAPS else 'Madrid race length: see the lock strategy block.')]) + [
      P('C. Data sources', H2)] + bullets(['FastF1 3.8.3: 2018 to today, laps, telemetry, position, weather, race control. Used for all 2026 rounds that exist (Bahrain and Saudi Arabia do not) and fourteen 2025 rounds.', 'OpenF1: intervals, pit, stints, race control, 2023 onward.', 'Pirelli press releases (compound nominations: Madrid C2 hard, C3 medium, C4 soft). FIA event documents (tyre allocation, pit stop summaries).', 'TUMFTM racetrack-database and race-simulation (track centrelines, published tyre and fuel parameters). Published baseline code: colecappello12/F1_SSM_Paper.']) + [
      P('D. Known limits', H2)] + bullets(['Hard compound is often withheld for too few Friday laps at European rounds.', 'The Hungary race and China FP1 position feeds are degraded at source and are refused for telemetry quantities.', 'Sprint weekends have one practice session; the sprint itself is not yet used as a validation target.', f'Bands are wide where a compound has few runs (Madrid soft: {MAD["SOFT"]["n_prac"] if "SOFT" in MAD else "n/a"} laps).', 'The replay ignores safety cars, traffic and weather, and uses linear curves.'])
doc = SimpleDocTemplate('out/Orb_v1_Roadmap_and_Manual.pdf', pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm, title='Orb v1 roadmap and technical manual', author='Team Orb v1')
def footer(c, d): c.saveState(); c.setFont('Helvetica', 7.5); c.setFillColor(colors.HexColor('#6B7280')); c.drawString(1.8 * cm, 1 * cm, f'Orb v1 roadmap and manual · TrackShift 2026 · numbers from lock {L["generated_at"]}'); c.drawRightString(A4[0] - 1.8 * cm, 1 * cm, str(d.page)); c.restoreState()
doc.build(S, onFirstPage=footer, onLaterPages=footer)
# companions
open('out/ROADMAP.md', 'w').write('# Orb v1 Challenge Day roadmap (IST, Sat 12 Sep unless marked)\n\nBuild start T0 = 11:15. Windows are the plan; the Status column records what landed (from refresh_fp3.log, refresh_q.log and the published forecast): ' + MAD_REFRESH_TXT + '; ' + MAD_HASH_TXT + '; race Sun 18:30.\n\n| ID | Window | Min | Prio | Task | Deliverable | Done when | Depends | Fallback | Status |\n|---|---|---|---|---|---|---|---|---|---|\n' + '\n'.join('| ' + ' | '.join(str(c).replace('&amp;', '&') for c in r) + ' |' for r in ROWS) + '\n\nCut order: E2, D1, A3, B1, E1. Never cut: A1, C1, C2, D2, F2, G1, G2, G3, H2, H3.\n')
open('out/JURY_QUESTIONS.md', 'w').write('# Twenty questions on technical depth\n\n' + '\n'.join(f'**{i}. {q}**\n\n{a}\n' for i, (q, a) in enumerate(QA, 1)))

# ---- talk track (out/talk_track.md): regenerated from the lock so no hand edit can drift from it ----
_NUMW = {5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight', 9: 'Nine', 10: 'Ten'}
_hr = round(HM['naive'] / HM['obs']); _HR = _NUMW.get(_hr, str(_hr))
TT = '\n'.join([
 '# Orb v1 — talk track', '',
 '## 5-minute jury version (one line per slide, numbers from the lock)', '',
 '1. **Title.** "Orb v1 issues clean tyre-degradation curves from Friday practice and scores them against the race every Sunday. Friday lies twice: about what the tyre did, and about what it will do on Sunday. We correct the first lie and learn the second."',
 f'2. **Problem.** "Hungary, medium tyre: a straight line through Friday says {HM["naive"]:+.2f} s per lap of age. The race showed {HM["obs"]:+.2f}. {_HR} times wrong. Every Friday lap carries fuel, track evolution, traffic, the driver, and how hard the driver was pushing."',
 '3. **Six steps.** "Ingest, clean, gate, learn, forecast, score. Same estimator on practice and race, so the practice-to-race ratio is a property of the data, not of our method. And it says \'withheld\' when Friday cannot support a curve."',
 f'4. **Proof.** "{V["n_weekends"]} weekends, {V["n_compound_weekends"]} compound-weekends, every number leave-one-weekend-out. Naive error {m["naive"]:.3f} s/lap, Orb v1 {m["clearstint"]:.3f}. Correlation with the race goes from {cal["naive"]["r"]:.2f} to {cal["all_with_fallback"]["r"]:.2f}. Every compound answered: {V["n_issued"]} issued, {V["n_withheld"]} withheld and forecast as low degradation; the {WH_TXT}."',
 f'5. **Fifth confounder.** "Why do some Fridays show no degradation? Because the driver was ramping up. We measure energy through the tyre from the public 3.7 Hz traces; {RAMP_TXT}. And the energy price of lap time {BETA_SHORT}. That is a measurement, not a fit."',
 f'6. **Madrid live.** "Issued this morning from FP1 and FP2, {MAD_REFRESHED_TXT}: {mad_txt("SOFT", 2)}; {mad_txt("MEDIUM", 2)}, withheld because drivers were learning a new track and forecast low degradation by two independent routes. Plan on the central curve: {MAD_PLAN_TXT}; {MAD_BAND_TXT}. {_cap(MAD_HASH_TXT)}: on record before Sunday\'s race, scored after it, and we will publish the score."',
 f'7. **Decisions.** "A curve only matters as a decision. Replayed on the {N_SC} scored weekends, {N_SPRINT} of them sprint weekends: the naive plan costs {NV_MIN:.0f} to {NV_MAX:.0f} seconds against the best plan; Orb v1\'s costs {OB_MIN:.0f} to {OB_MAX:.0f}, and it {SC_TXT}. Both misses are on the slide and we say why."',
 f'8. **Liquid model.** "We tested a liquid neural network that reads each stint lap by lap. Given the same inputs, a straight line is about as good: the network beat the best baseline in only {LQ_WINS}. The inputs were the discovery: energy, traffic and fuel cut the error of the age-only model {LQ_CUT}. The network stays as the curve-shape tool, and we report the test rather than hide it."',
 '9. **Product.** "One lock file feeds six dashboard views and this deck. For junior categories with two engineers and public timing: F2, F3, F1 Academy, Indian F4, broadcasters. Beyond the track the loop is the same: measure the confounders, gate, learn the transfer, score against the race-derived reference."',
 '10. **Built when.** "The estimator and the six-weekend validation were disclosed pre-work. Everything else on these slides, seven more weekends, the fallback, the push diagnostic, strategy with compound offsets from practice or qualifying medians, the liquid model, the dashboard and Madrid live, was built here. Limits are on the slide. Sunday night, Madrid gets scored."',
 '', '## 90-second mentor-checkpoint version', '',
 f'"Tyre degradation from Friday practice, scored against a race-derived pace-loss reference. The estimator strips fuel, track evolution, traffic and the driver from every lap, issues a curve only when Friday supports one, and learns per compound how much Sunday\'s management shrinks the Friday number, from previous weekends only. Leave-one-weekend-out across {V["n_weekends"]} weekends: error {m["clearstint"]:.3f} versus {m["naive"]:.3f} naive. The new finding today is the fifth confounder, the driver\'s push profile from telemetry energy: {RAMP_TXT}. Withheld is still a forecast: the {WH_TXT}. Madrid\'s curves were issued from FP1 and FP2, {MAD_REFRESHED_SHORT}, {MAD_HASHED_AT}, and will be scored after the race. The dashboard is running; here is Madrid."',
 ''] + [f'## {N_TT_WORD} predictable questions, {N_TT_WORD.lower()} answers', ''] + [f'- **{q}** {a}' for q, a in TT_QA] + [''])
open('out/talk_track.md', 'w').write(TT)
print('built')

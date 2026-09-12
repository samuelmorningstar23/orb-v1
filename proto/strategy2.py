"""Strategy layer: crossover laps and the 1-stop vs 2-stop decision under each degradation view, scored against the race-observed
curves where a race exists. Stated assumptions: compound pace step (from qualifying when available, else 0.6 s nominal), pit loss."""
import itertools, numpy as np
PIT_LOSS = 21.0; OFFSET_STEP = 0.6; MIN_STINT = 6
RACE_LAPS = {'Madrid': 56}   # FIA: smallest number of laps exceeding 305 km; Madring 5.474 km. Stated assumption for the live weekend.

def stint_time(offset, slope, laps): return float(np.sum(offset + slope * np.arange(1, laps + 1)))

def best_plans(offsets, slopes, n_laps, max_stops=2):
    out = []
    comps = [c for c in ['SOFT', 'MEDIUM', 'HARD'] if c in offsets and c in slopes and np.isfinite(slopes[c])]
    for stops in range(1, max_stops + 1):
        for seq in itertools.product(comps, repeat=stops + 1):
            if len(set(seq)) < 2: continue
            best = None
            if stops == 1:
                for a in range(MIN_STINT, n_laps - MIN_STINT + 1):
                    t = stint_time(offsets[seq[0]], slopes[seq[0]], a) + stint_time(offsets[seq[1]], slopes[seq[1]], n_laps - a) + PIT_LOSS
                    if best is None or t < best[0]: best = (t, (a, n_laps - a))
            else:
                for a in range(MIN_STINT, n_laps - 2 * MIN_STINT + 1, 2):
                    for b in range(MIN_STINT, n_laps - a - MIN_STINT + 1, 2):
                        c = n_laps - a - b; t = sum(stint_time(offsets[s], slopes[s], L) for s, L in zip(seq, (a, b, c))) + 2 * PIT_LOSS
                        if best is None or t < best[0]: best = (t, (a, b, c))
            if best: out.append(dict(plan='-'.join(s[0] for s in seq), stops=stops, stints=list(best[1]), time=best[0]))
    out = sorted(out, key=lambda x: x['time']); base = out[0]['time'] if out else 0.0
    for o in out: o['delta_to_best'] = o['time'] - base
    return out

def crossover(offsets, slopes):
    """lap of tyre age at which the slower-but-more-durable compound becomes faster than the faster-but-softer one (same age)."""
    x = {}
    for a, b in [('SOFT', 'MEDIUM'), ('MEDIUM', 'HARD'), ('SOFT', 'HARD')]:
        if a in slopes and b in slopes and np.isfinite(slopes[a]) and np.isfinite(slopes[b]) and slopes[a] > slopes[b]:
            x[f'{a[0]}-{b[0]}'] = float((offsets[b] - offsets[a]) / (slopes[a] - slopes[b]))
    return x

def replay(views, offsets, n_laps, truth=None):
    """for each view (name -> slopes): its best plan; if truth slopes given, cost of that plan evaluated under the truth."""
    res = {}
    truth_plans = best_plans(offsets, truth, n_laps) if truth else None
    for name, slopes in views.items():
        plans = best_plans(offsets, slopes, n_laps)
        if not plans: continue
        top = plans[0]; entry = dict(plan=top['plan'], stints=top['stints'], stops=top['stops'], crossover=crossover(offsets, slopes), alternatives=plans[:4])
        if truth_plans:
            seq = [{'S': 'SOFT', 'M': 'MEDIUM', 'H': 'HARD'}[ch] for ch in top['plan'].split('-')]
            cost = sum(stint_time(offsets[s], truth[s], L) for s, L in zip(seq, top['stints'])) + top['stops'] * PIT_LOSS
            entry['cost_under_truth_vs_best_s'] = float(cost - truth_plans[0]['time']); entry['best_under_truth'] = dict(plan=truth_plans[0]['plan'], stints=truth_plans[0]['stints'])
        res[name] = entry
    return res

def offsets_from_sessions(d, nominal_step=OFFSET_STEP):
    """Compound pace offsets (s/lap, soft = 0) from each driver's best clean lap per compound: qualifying first, practice as fallback,
    nominal step when a compound was not run. Median over drivers who set times on both compounds."""
    import numpy as np, pandas as pd
    clean = d[d['Compound'].isin(['SOFT', 'MEDIUM', 'HARD']) & d['IsAccurate'].astype(bool) & (d['TrackStatus'].astype(str) == '1') & ~d['pit_in'] & ~d['pit_out'] & ~d['deleted'].astype(bool)]
    def best(sessions):
        s = clean[clean['session'].isin(sessions)]
        return s.groupby(['Driver', 'Compound'])['lap_s'].min().unstack() if len(s) else pd.DataFrame()
    q, p = best(['Q', 'SQ']), best(['FP1', 'FP2', 'FP3'])
    offs, src = {'SOFT': 0.0}, {}
    for c, k in [('MEDIUM', 1), ('HARD', 2)]:
        val = None
        for name, tab in [('qualifying', q), ('practice', p)]:
            if 'SOFT' in tab and c in tab:
                both = tab[['SOFT', c]].dropna()
                if len(both) >= 3:
                    v = float((both[c] - both['SOFT']).median())
                    # a plausible adjacent-compound step is 0.2 to 1.0 s; practice 'best' laps on harder compounds are often heavy-fuel long-run laps
                    if 0.2 * k <= v <= 1.0 * k: val, src[c] = v, f'{name} ({len(both)} drivers)'; break
                    else: src[c] = f'{name} value {v:+.2f} s implausible, '
        if val is None: val, src[c] = k * nominal_step, (src.get(c, '') + 'nominal Pirelli-range step')
        offs[c] = val
    return offs, src

"""Whole-season cache + feature extraction for past seasons, resilient to FastF1's client-side rate limit.
Usage: python extract_seasons.py --years 2025,2024,2023 --cache ~/Trackshift/cache2
Writes feat<year>/<Event>_<Session>.csv; skips files that exist; sessions that have not run are skipped.
Event names follow the 2026 convention (Australia, China, ..., Britain, Belgium, Hungary, Zandvoort, Monza) so same-track priors line up."""
import fastf1, pandas as pd, time, os, sys, argparse, datetime as dt, logging, re, socket, signal, requests
socket.setdefaulttimeout(120)
_orig_request = requests.Session.request
def _req_with_timeout(self, *a, **k):
    k.setdefault('timeout', 180); return _orig_request(self, *a, **k)
requests.Session.request = _req_with_timeout          # every FastF1 HTTP call gets a 180 s timeout
class SessionTimeout(Exception): pass
def _alarm(signum, frame): raise SessionTimeout('session exceeded 20 min wall clock')
signal.signal(signal.SIGALRM, _alarm)
from fastf1.req import RateLimitExceededError
from features import session_features
logging.getLogger('fastf1').setLevel(logging.CRITICAL)
ap = argparse.ArgumentParser(); ap.add_argument('--years', default='2025,2024,2023'); ap.add_argument('--cache', default='~/Trackshift/cache2'); ap.add_argument('--sleep', type=int, default=900); ap.add_argument('--worker', type=int, default=0); ap.add_argument('--nworkers', type=int, default=1); a = ap.parse_args()
CACHE = os.path.expanduser(a.cache); os.makedirs(CACHE, exist_ok=True); fastf1.Cache.enable_cache(CACHE)
LOC2NAME = {'Melbourne': 'Australia', 'Shanghai': 'China', 'Suzuka': 'Japan', 'Sakhir': 'Bahrain', 'Jeddah': 'SaudiArabia', 'Miami': 'Miami', 'Imola': 'Imola', 'Monaco': 'Monaco', 'Monte Carlo': 'Monaco',
            'Montréal': 'Canada', 'Montreal': 'Canada', 'Barcelona': 'Barcelona', 'Catalunya': 'Barcelona', 'Spielberg': 'Austria', 'Silverstone': 'Britain', 'Spa-Francorchamps': 'Belgium', 'Spa': 'Belgium',
            'Budapest': 'Hungary', 'Zandvoort': 'Zandvoort', 'Monza': 'Monza', 'Baku': 'Azerbaijan', 'Marina Bay': 'Singapore', 'Singapore': 'Singapore', 'Austin': 'USA', 'Mexico City': 'Mexico',
            'São Paulo': 'Brazil', 'Sao Paulo': 'Brazil', 'Las Vegas': 'LasVegas', 'Lusail': 'Qatar', 'Yas Island': 'AbuDhabi', 'Yas Marina': 'AbuDhabi', 'Abu Dhabi': 'AbuDhabi', 'Madrid': 'Madrid'}
PRIORITY = ['Australia', 'China', 'Japan', 'Miami', 'Canada', 'Monaco', 'Barcelona', 'Austria', 'Britain', 'Belgium', 'Hungary', 'Zandvoort', 'Monza', 'Bahrain', 'SaudiArabia']
IDENT = {'Practice 1': 'FP1', 'Practice 2': 'FP2', 'Practice 3': 'FP3', 'Qualifying': 'Q', 'Sprint Qualifying': 'SQ', 'Sprint Shootout': 'SS', 'Sprint': 'S', 'Race': 'R'}
def name_of(loc):
    for k, v in LOC2NAME.items():
        if k.lower() in str(loc).lower(): return v
    return re.sub(r'[^A-Za-z0-9]', '', str(loc)) or 'Unknown'
def schedule(year):
    best, best_be = None, None
    for be in ['f1timing', 'ergast', 'fastf1']:
        try:
            sc = fastf1.get_event_schedule(year, include_testing=False, backend=be)
            if best is None or len(sc) > len(best): best, best_be = sc, be
        except Exception as e: print(f"  schedule backend {be} failed: {type(e).__name__}", flush=True)
    return best, best_be
def load_with_retry(year, event_name, sn, backend, tries=5):
    for k in range(tries):
        try:
            s = fastf1.get_session(year, event_name, sn, backend=backend); s.load(telemetry=True, weather=True, messages=True); s.laps; return s
        except RateLimitExceededError as e:
            print(f"    rate limit hit ({e}); sleeping {a.sleep}s (try {k+1}/{tries})", flush=True); time.sleep(a.sleep)
        except Exception as e:
            msg = repr(e)
            if 'DataNotLoaded' in msg or 'Connection' in msg or 'Remote end' in msg or 'timed out' in msg.lower():
                print(f"    transient: {msg[:90]}; sleeping 300s (try {k+1}/{tries})", flush=True); time.sleep(300)
            else: raise
    raise RuntimeError('gave up after retries')
now = pd.Timestamp(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
jobs = []
for year in [int(y) for y in a.years.split(',')]:
    sc, be = schedule(year)
    if sc is None: print(f"{year}: NO SCHEDULE", flush=True); continue
    os.makedirs(f'feat{year}', exist_ok=True)
    for _, r in sc.iterrows(): jobs.append((0 if name_of(r['Location']) in PRIORITY else 1, year, name_of(r['Location']), r, be))
    print(f"{year}: {len(sc)} rounds from backend {be}", flush=True)
jobs.sort(key=lambda j: (j[0], -j[1], PRIORITY.index(j[2]) if j[2] in PRIORITY else 99, int(j[3]['RoundNumber'])))
mine = [j for i, j in enumerate(jobs) if i % a.nworkers == a.worker]
print(f"worker {a.worker}/{a.nworkers}: {len(mine)} of {len(jobs)} rounds: {', '.join(f'{y}-{e}' for _, y, e, _, _ in mine)}", flush=True)
for _, year, ev, row, be in mine:
    out_dir = f'feat{year}'
    if True:
        for i in range(1, 6):
            sn = IDENT.get(row.get(f'Session{i}')); sdate = row.get(f'Session{i}DateUtc')
            if sn is None: continue
            if pd.notna(sdate) and pd.Timestamp(sdate) + pd.Timedelta(hours=2) > now: continue
            out = f'{out_dir}/{ev}_{sn}.csv'
            if os.path.exists(out): continue
            t = time.time()
            try:
                signal.alarm(1200)
                s = load_with_retry(year, str(row['EventName']), sn, be)
                if name_of(s.event['Location']) != ev: raise RuntimeError(f"event mismatch: resolved {s.event['Location']}")
                df = session_features(s, ev, sn); w = s.weather_data
                df['track_temp'] = float(w['TrackTemp'].median()) if w is not None and len(w) else float('nan'); df['rain'] = bool(w['Rainfall'].any()) if w is not None and len(w) else False; df['year'] = year
                df.to_csv(out, index=False); print(f"  {year} {ev} {sn}: {len(df)} laps in {time.time()-t:.0f}s", flush=True)
            except Exception as e: print(f"  {year} {ev} {sn}: FAILED {e!r}"[:200], flush=True)
            finally: signal.alarm(0)
print(f"WORKER DONE {a.worker}", flush=True)

"""Environment/data prep (allowed pre-kickoff): cache FastF1 sessions and extract per-lap features for weekends
not yet in feat/, then warm the cache for the six original weekends. Same feature code as extract_all.py,
but race-control messages are loaded so the 'deleted' flag is real."""
import fastf1, pandas as pd, time, os, sys, datetime as dt
from features import session_features
CACHE = os.path.expanduser('~/Trackshift/cache'); os.makedirs(CACHE, exist_ok=True); fastf1.Cache.enable_cache(CACHE)
# (our event name, keyword matched against the schedule's Location column)
NEW = [('Monza','Monza'), ('Madrid','Madrid'), ('Zandvoort','Zandvoort'), ('Bahrain','Sakhir'), ('SaudiArabia','Jeddah')]
OLD = ['Hungary','Austria','Barcelona','Belgium','Japan','Australia']
IDENT = {'Practice 1':'FP1','Practice 2':'FP2','Practice 3':'FP3','Qualifying':'Q','Sprint Qualifying':'SQ','Sprint':'S','Race':'R'}
sched = fastf1.get_event_schedule(2026, include_testing=False)
now = pd.Timestamp(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
os.makedirs('feat', exist_ok=True)

def load(rnd, sn):
    s = fastf1.get_session(2026, rnd, sn); s.load(telemetry=True, weather=True, messages=True); return s

print("PHASE 1: new weekends", flush=True)
for ev, loc in NEW:
    rows = sched[sched['Location'].str.contains(loc, case=False, na=False)]
    if rows.empty: print(f"{ev}: NOT IN SCHEDULE (keyword {loc})", flush=True); continue
    row = rows.iloc[0]; rnd = int(row['RoundNumber'])
    print(f"{ev}: round {rnd} '{row['EventName']}' format={row['EventFormat']}", flush=True)
    for i in range(1, 6):
        sn = IDENT.get(row[f'Session{i}']); sdate = row[f'Session{i}DateUtc']
        if sn is None: continue
        if pd.notna(sdate) and pd.Timestamp(sdate) + pd.Timedelta(hours=2) > now:
            print(f"  {sn}: not run yet or too recent (UTC {sdate})", flush=True); continue
        out = f'feat/{ev}_{sn}.csv'
        if os.path.exists(out): print(f"  {sn}: exists", flush=True); continue
        t = time.time()
        try:
            s = load(rnd, sn); df = session_features(s, ev, sn)
            w = s.weather_data; df['track_temp'] = float(w['TrackTemp'].median()) if w is not None and len(w) else float('nan')
            df['rain'] = bool(w['Rainfall'].any()) if w is not None and len(w) else False
            df.to_csv(out, index=False); print(f"  {ev} {sn}: {len(df)} laps in {time.time()-t:.0f}s", flush=True)
        except Exception as e:
            print(f"  {ev} {sn}: FAILED {e!r}", flush=True)
print("PHASE 1 DONE", flush=True)

if '--phase2' in sys.argv:
    print("PHASE 2: warm cache for original weekends (no CSV changes)", flush=True)
    for ev in OLD:
        for sn in ['FP1','FP2','FP3','Q','R']:
            t = time.time()
            try: load(ev, sn); print(f"  {ev} {sn}: cached in {time.time()-t:.0f}s", flush=True)
            except Exception as e: print(f"  {ev} {sn}: FAILED {e!r}", flush=True)
    print("PHASE 2 DONE", flush=True)

"""Generalised session cache + feature extraction. Usage:
  python extract_extra.py --year 2026 --events China,Miami,Canada,Britain,Monaco --out feat --cache ~/Trackshift/cache2
Events are matched by keyword against Location|EventName|Country in the FastF1 schedule (resolution is printed)."""
import fastf1, pandas as pd, time, os, sys, argparse, datetime as dt
from features import session_features
ap = argparse.ArgumentParser(); ap.add_argument('--year', type=int, default=2026); ap.add_argument('--events', required=True)
ap.add_argument('--out', default='feat'); ap.add_argument('--cache', default='~/Trackshift/cache'); a = ap.parse_args()
CACHE = os.path.expanduser(a.cache); os.makedirs(CACHE, exist_ok=True); fastf1.Cache.enable_cache(CACHE)
KEY = {'Australia':'Melbourne','China':'Shanghai','Japan':'Suzuka','Bahrain':'Sakhir','SaudiArabia':'Jeddah','Miami':'Miami','Canada':'Montr',
       'Monaco':'Monaco','Barcelona':'Barcelona','Austria':'Spielberg','Britain':'Silverstone','Belgium':'Spa-Francorchamps','Hungary':'Budapest',
       'Zandvoort':'Zandvoort','Monza':'Monza','Madrid':'Madrid','Baku':'Baku','Singapore':'Singapore','Austin':'Austin','Mexico':'Mexico',
       'Brazil':'Paulo','LasVegas':'Las Vegas','Qatar':'Lusail','AbuDhabi':'Yas'}
IDENT = {'Practice 1':'FP1','Practice 2':'FP2','Practice 3':'FP3','Qualifying':'Q','Sprint Qualifying':'SQ','Sprint Shootout':'SQ','Sprint':'S','Race':'R'}
try: sched = fastf1.get_event_schedule(a.year, include_testing=False, backend='f1timing')
except Exception: sched = fastf1.get_event_schedule(a.year, include_testing=False)
hay = (sched['Location'].astype(str)+'|'+sched['EventName'].astype(str)+'|'+sched['Country'].astype(str)).str.lower()
now = pd.Timestamp(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)); os.makedirs(a.out, exist_ok=True)
for ev in a.events.split(','):
    kw = KEY.get(ev, ev).lower(); rows = sched[hay.str.contains(kw, regex=False)]
    if rows.empty: print(f"{ev}: NOT IN SCHEDULE (keyword {kw})", flush=True); continue
    row = rows.iloc[0]; rnd = int(row['RoundNumber'])
    print(f"{a.year} {ev}: round {rnd} '{row['EventName']}' format={row['EventFormat']}", flush=True)
    for i in range(1, 6):
        sn = IDENT.get(row[f'Session{i}']); sdate = row[f'Session{i}DateUtc']
        if sn is None: continue
        if pd.notna(sdate) and pd.Timestamp(sdate) + pd.Timedelta(hours=2) > now: print(f"  {sn}: not run yet (UTC {sdate})", flush=True); continue
        out = f'{a.out}/{ev}_{sn}.csv'
        if os.path.exists(out): print(f"  {sn}: exists", flush=True); continue
        t = time.time()
        try:
            s = fastf1.get_session(a.year, str(row['EventName']), sn, backend='f1timing'); assert s.event['Location'] == row['Location'], 'event mismatch'; s.load(telemetry=True, weather=True, messages=True)
            df = session_features(s, ev, sn)
            w = s.weather_data; df['track_temp'] = float(w['TrackTemp'].median()) if w is not None and len(w) else float('nan')
            df['rain'] = bool(w['Rainfall'].any()) if w is not None and len(w) else False
            df['year'] = a.year; df.to_csv(out, index=False); print(f"  {ev} {sn}: {len(df)} laps in {time.time()-t:.0f}s", flush=True)
        except Exception as e:
            print(f"  {ev} {sn}: FAILED {e!r}", flush=True)
print(f"DONE {a.year} {a.events}", flush=True)

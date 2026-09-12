import fastf1, pandas as pd, time, sys, os
from features import session_features
fastf1.Cache.enable_cache(os.path.expanduser('~/Trackshift/cache'))
EVENTS = ['Hungary','Austria','Barcelona','Belgium','Japan','Australia']
os.makedirs('feat', exist_ok=True)
for ev in EVENTS:
    for sn in ['FP1','FP2','FP3','R']:
        out = f'feat/{ev}_{sn}.csv'
        if os.path.exists(out): continue
        t = time.time()
        try:
            s = fastf1.get_session(2026, ev, sn); s.load(telemetry=True, weather=True, messages=False)
            df = session_features(s, ev, sn)
            w = s.weather_data; df['track_temp'] = float(w['TrackTemp'].median()) if w is not None and len(w) else float('nan')
            df['rain'] = bool(w['Rainfall'].any()) if w is not None and len(w) else False
            df.to_csv(out, index=False); print(f"{ev} {sn}: {len(df)} laps in {time.time()-t:.0f}s", flush=True)
        except Exception as e:
            print(f"{ev} {sn}: FAILED {e!r}", flush=True)
print("ALL DONE", flush=True)

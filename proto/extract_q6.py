"""Extract qualifying sessions for the original six weekends from the (already warm) main cache."""
import fastf1, os, time
from features import session_features
fastf1.Cache.enable_cache(os.path.expanduser('~/Trackshift/cache'))
for ev in ['Hungary', 'Austria', 'Barcelona', 'Belgium', 'Japan', 'Australia']:
    out = f'feat/{ev}_Q.csv'
    if os.path.exists(out): print(ev, 'Q exists'); continue
    t = time.time()
    try:
        s = fastf1.get_session(2026, ev, 'Q'); s.load(telemetry=True, weather=True, messages=True); df = session_features(s, ev, 'Q')
        w = s.weather_data; df['track_temp'] = float(w['TrackTemp'].median()) if w is not None and len(w) else float('nan'); df['rain'] = bool(w['Rainfall'].any()) if w is not None and len(w) else False
        df.to_csv(out, index=False); print(f"{ev} Q: {len(df)} laps in {time.time()-t:.0f}s", flush=True)
    except Exception as e: print(f"{ev} Q: FAILED {e!r}", flush=True)
print("Q6 DONE")

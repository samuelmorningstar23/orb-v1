"""Per-lap feature extraction from FastF1 telemetry: tyre-energy proxy, traffic share, push level.
Energy proxy (MJ) = m * [ ∫ v²·κ ds  +  ∫ |dv/dt| ds ]  (lateral + longitudinal work through the contact patch).
Curvature κ is computed on de-duplicated position samples resampled to a uniform 10 m arc-length grid, so stale/jumpy
position packets (common in race sessions) do not bias it. Longitudinal term uses the car-data speed channel only."""
import numpy as np, pandas as pd, fastf1, warnings, logging
warnings.filterwarnings("ignore"); logging.getLogger("fastf1").setLevel(logging.ERROR)
CAR_MASS = 800.0
DS = 10.0  # m

def smooth(x, w=5):
    if len(x) < w or w < 2: return x
    k = np.ones(w)/w; xp = np.pad(x, (w//2, w-1-w//2), mode='edge'); return np.convolve(xp, k, mode='valid')

def lap_energy(tel):
    tel = tel.copy()
    pos = tel[(tel['Source']=='pos') & tel['X'].notna() & tel['Y'].notna()]
    car = tel[(tel['Source']=='car') & tel['Speed'].notna()]
    if len(pos) < 30 or len(car) < 30: return np.nan, np.nan, np.nan
    # --- lateral: path geometry on arc-length grid ---
    x = pos['X'].values/10.0; y = pos['Y'].values/10.0; tp = pos['SessionTime'].dt.total_seconds().values
    step = np.hypot(np.diff(x), np.diff(y)); keep = np.r_[True, step > 1.0]          # drop stale repeats
    x, y, tp = x[keep], y[keep], tp[keep]
    if len(x) < 20: return np.nan, np.nan, np.nan
    s = np.r_[0, np.cumsum(np.hypot(np.diff(x), np.diff(y)))]
    L = s[-1]
    if L < 1000: return np.nan, np.nan, np.nan
    sg = np.arange(0, L, DS); xg = np.interp(sg, s, x); yg = np.interp(sg, s, y); tg = np.interp(sg, s, tp)
    xg, yg = smooth(xg, 5), smooth(yg, 5)
    dx, dy = np.gradient(xg, DS), np.gradient(yg, DS); ddx, ddy = np.gradient(dx, DS), np.gradient(dy, DS)
    kappa = np.abs(dx*ddy - dy*ddx) / np.maximum((dx**2+dy**2)**1.5, 1e-9)
    kappa = np.clip(kappa, 0, 1/15.0)                                                # radius >= 15 m
    # speed on the same grid from car data (time-based interpolation)
    tc = car['SessionTime'].dt.total_seconds().values; vc = car['Speed'].values/3.6
    o = np.argsort(tc); tc, vc = tc[o], vc[o]
    vg = np.interp(tg, tc, vc)
    a_lat = np.clip(vg**2*kappa, 0, 60)
    e_lat = CAR_MASS*np.sum(a_lat)*DS/1e6
    # --- longitudinal: total variation of the de-duplicated speed trace, ∫|dv/dt|·v dt = Σ|Δv|·v  (robust to stale packets) ---
    vk = vc[np.r_[True, np.diff(vc) != 0]]
    if len(vk) < 20: return np.nan, np.nan, np.nan
    vs = smooth(vk, 3); dv = np.abs(np.diff(vs)); dv = np.minimum(dv, 15.0)
    e_long = CAR_MASS*np.sum(dv*(vs[1:]+vs[:-1])/2)/1e6
    quality = dict(pos_distinct=int(len(x)), stale_share=float(np.mean(np.diff(vc) == 0)))
    lap_energy.last_quality = quality
    return e_lat+e_long, e_lat, e_long

def traffic_share(tel, dist_m=60.0):
    d = tel['DistanceToDriverAhead'] if 'DistanceToDriverAhead' in tel else None
    if d is None or d.notna().sum() < 10: return np.nan
    return float((d.dropna() < dist_m).mean())

def session_features(session, event, sess_name):
    rows = []
    for _, lap in session.laps.iterrows():
        if pd.isna(lap['LapTime']): continue
        try: tel = lap.get_telemetry()
        except Exception: continue
        lap_energy.last_quality = {}
        e, el, eg = lap_energy(tel); qd = getattr(lap_energy, 'last_quality', {}) or {}
        rows.append(dict(event=event, session=sess_name, Driver=lap['Driver'], LapNumber=int(lap['LapNumber']), Stint=lap['Stint'],
            Compound=lap['Compound'], TyreLife=lap['TyreLife'], FreshTyre=lap['FreshTyre'], lap_s=lap['LapTime'].total_seconds(),
            s1=lap['Sector1Time'].total_seconds() if pd.notna(lap['Sector1Time']) else np.nan,
            s2=lap['Sector2Time'].total_seconds() if pd.notna(lap['Sector2Time']) else np.nan,
            s3=lap['Sector3Time'].total_seconds() if pd.notna(lap['Sector3Time']) else np.nan,
            t_min=lap['LapStartTime'].total_seconds()/60 if pd.notna(lap['LapStartTime']) else np.nan,
            TrackStatus=lap['TrackStatus'], IsAccurate=bool(lap['IsAccurate']), pit_in=pd.notna(lap['PitInTime']), pit_out=pd.notna(lap['PitOutTime']),
            deleted=bool(lap['Deleted']) if 'Deleted' in lap else False, energy_MJ=e, e_lat=el, e_long=eg, traffic=traffic_share(tel),
            full_throttle=float((tel['Throttle']>=99).mean()) if 'Throttle' in tel else np.nan, n_tel=len(tel),
            pos_distinct=qd.get('pos_distinct', np.nan), stale_share=qd.get('stale_share', np.nan)))
    return pd.DataFrame(rows)

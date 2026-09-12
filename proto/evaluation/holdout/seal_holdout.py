"""Seal the historical holdout with ONE rule: holdout_count = clamp(round(0.18 * eligible_weekends), 4, 6).
Eligible = 2023-2025 weekends with practice + race feature files at seal time that pass feed-quality rules.
Selection uses metadata only (season, circuit class, degradation class, temperature regime, SC presence), seed 2026.
Writes sealed_holdout_manifest.json + .sha256. Per-race results may not be revealed until freeze.json exists (see reveal_conditions)."""
import os, glob, json, hashlib, random, datetime as dt, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); os.chdir(ROOT)
STREET = {'Monaco', 'Singapore', 'Azerbaijan', 'Miami', 'LasVegas', 'SaudiArabia', 'Australia', 'Canada'}
HIGH_DEG = {'Barcelona', 'Bahrain', 'Japan', 'Britain', 'Hungary', 'Zandvoort', 'Qatar', 'Austria'}
LOW_DEG = {'Monza', 'Azerbaijan', 'LasVegas', 'SaudiArabia', 'Monaco', 'Canada', 'Miami'}
rows = []
for year in (2023, 2024, 2025):
    for r in sorted(glob.glob(f'feat{year}/*_R.csv')):
        ev = os.path.basename(r).split('_')[0]; fps = [f for f in glob.glob(f'feat{year}/{ev}_FP*.csv')]
        race = pd.read_csv(r); ok = float((race['pos_distinct'] >= 100).mean()) if 'pos_distinct' in race else 0.0
        fp_laps = sum(len(pd.read_csv(f)) for f in fps)
        eligible = len(fps) >= 1 and len(race) >= 500 and ok >= 0.5 and fp_laps >= 300 and not bool(race['rain'].iloc[0])
        temp = float(race['track_temp'].iloc[0]) if 'track_temp' in race else float('nan')
        sc = bool(race['TrackStatus'].astype(str).str.contains('4|6').any())
        rows.append(dict(race_id=f'{year}_{ev}', season=year, event=ev, eligible=eligible, n_fp=len(fps), fp_laps=int(fp_laps), race_laps=int(len(race)), telemetry_ok=round(ok, 2), wet=bool(race['rain'].iloc[0]),
                         circuit_class='street' if ev in STREET else 'permanent', degradation_class='high' if ev in HIGH_DEG else ('low' if ev in LOW_DEG else 'medium'),
                         temperature_regime=('hot' if temp >= 40 else 'cool' if temp < 30 else 'mild') if temp == temp else 'unknown', track_temp=round(temp, 1) if temp == temp else None, sc_or_vsc=sc))
meta = pd.DataFrame(rows); elig = meta[meta.eligible].reset_index(drop=True)
n = max(4, min(6, round(0.18 * len(elig))))
rng = random.Random(2026); order = list(elig.race_id); rng.shuffle(order); by_id = elig.set_index('race_id')
chosen = []
def used_circuits(): return {by_id.loc[r].event for r in chosen}
def need(pred):
    for rid in order:
        if rid not in chosen and by_id.loc[rid].event not in used_circuits() and pred(by_id.loc[rid]): chosen.append(rid); return
for season in sorted(elig.season.unique()): need(lambda m, s=season: m.season == s)
need(lambda m: m.circuit_class == 'street'); need(lambda m: m.degradation_class == 'high'); need(lambda m: m.degradation_class == 'low')
need(lambda m: m.temperature_regime == 'hot'); need(lambda m: m.temperature_regime == 'cool'); need(lambda m: m.sc_or_vsc)
chosen = chosen[:n]
for rid in order:
    if len(chosen) >= n: break
    if rid not in chosen and by_id.loc[rid].event not in used_circuits(): chosen.append(rid)
manifest = dict(holdout_version='gold-v1.1 (v0 superseded before any evaluation: added no-circuit-twice constraint)', selected_at=dt.datetime.now().isoformat(timespec='seconds'), seed=2026,
                selection_rule='holdout_count = clamp(round(0.18 * eligible_weekends), 4, 6); eligible = 2023-2025 weekends with >=1 practice file, >=300 practice laps, race >=500 laps, race position-telemetry ok share >=0.5, dry; constraints in order: one per season, one street, one high-degradation, one low-degradation, one hot, one cool, one SC/VSC; no circuit twice; fill by seeded shuffle',
                eligible_weekends=int(len(elig)), holdout_count=int(n), race_ids=sorted(chosen), prohibited_for_tuning=True,
                reveal_conditions=dict(model_frozen=False, feature_list_frozen=False, gate_threshold_frozen=False, provider_frozen=False, git_commit=None, note='per-race results may be revealed only when all four are true and a commit is recorded in freeze.json; any tuning after reveal is labelled post_holdout_tuning'),
                metadata={rid: {k: (v.item() if hasattr(v, 'item') else v) for k, v in by_id.loc[rid].drop(['eligible']).items()} for rid in sorted(chosen)},
                eligible_pool=sorted(elig.race_id), ineligible={r.race_id: dict(n_fp=int(r.n_fp), fp_laps=int(r.fp_laps), race_laps=int(r.race_laps), telemetry_ok=float(r.telemetry_ok), wet=bool(r.wet)) for r in meta[~meta.eligible].itertuples()})
body = json.dumps(manifest, indent=1, sort_keys=True, default=str); sha = hashlib.sha256(body.encode()).hexdigest()
open('evaluation/holdout/sealed_holdout_manifest.json', 'w').write(body); open('evaluation/holdout/sealed_holdout_manifest.sha256', 'w').write(sha + '  sealed_holdout_manifest.json\n')
meta.to_csv('evaluation/holdout/weekend_metadata.csv', index=False)
print(f"eligible {len(elig)} of {len(meta)} weekends -> holdout_count {n}"); print("SEALED:", sorted(chosen)); print("sha256", sha[:16] + '...')
for rid in sorted(chosen): m = by_id.loc[rid]; print(f"  {rid:18s} {m.circuit_class:9s} deg={m.degradation_class:6s} temp={m.temperature_regime:5s} SC={bool(m.sc_or_vsc)}")

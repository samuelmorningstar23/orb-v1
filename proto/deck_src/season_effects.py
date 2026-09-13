"""Season-by-season tyre facts for the deck (2023 to 2026), read-only over the race lap files.

Writes deck_src/assets/season_effects.json. Sealed holdout weekends are refused (manifest race_ids), wet races are
skipped, and every figure carries its n. Three measurements:

1. Race degradation per compound per season: the race-derived reference slope (s/lap per lap of tyre age) from
   out/tyreformer/prerace/predictions_A.csv (the scorecard reference, model_v2 race fit). That fit subtracts a 70 kg
   race fuel load for every season, the 2026 assumption. With a heavier start the burn-off masks wear, so the slope is
   also given with a season fuel load F: slope + 0.03 s/kg x (F - 70) / race laps (exact for the model's linear burn).
2. Stints and stops from the race laps: completed stint length per compound (a stint ended by a pit stop), and pit
   stops per driver who finished at least 90 % of the race distance.
3. Fuel masking in raw lap times: 0.03 s/kg x F / race laps, the lap time a car gains per lap from burning fuel.
"""
from __future__ import annotations
import glob, json, statistics as S
from pathlib import Path
import pandas as pd

PROTO = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / 'assets' / 'season_effects.json'
SEALED = set(json.loads((PROTO / 'evaluation' / 'holdout' / 'sealed_holdout_manifest.json').read_text())['race_ids'])
DIRS = {2023: 'feat2023', 2024: 'feat2024', 2025: 'feat2025', 2026: 'feat'}
FUEL_S_PER_KG, MODEL_FUEL_KG = 0.03, 70.0
PRE_2026_FUEL_KG = 100.0   # typical race fuel before 2026 (F1: ~100 kg in 2020; the 2019 cap was 110 kg); 2026 target 70 kg
COMPOUNDS = ('SOFT', 'MEDIUM', 'HARD')


def q(values, p):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def race_files():
    for season, d in DIRS.items():
        for f in sorted(glob.glob(str(PROTO / d / '*_R.csv'))):
            event = Path(f).stem[:-2]
            rid = f'{season}_{event}'
            if rid in SEALED:
                continue
            yield season, event, rid, f


def main():
    laps_by_race, wet, stints, stops = {}, set(), {s: {c: [] for c in COMPOUNDS} for s in DIRS}, {s: [] for s in DIRS}
    one_stop_share = {s: [] for s in DIRS}
    races_used = {s: [] for s in DIRS}
    for season, event, rid, f in race_files():
        d = pd.read_csv(f, usecols=['Driver', 'LapNumber', 'Stint', 'Compound', 'TyreLife', 'pit_in', 'pit_out', 'rain'])
        n_laps = int(d['LapNumber'].max())
        laps_by_race[rid] = n_laps
        if d['rain'].astype(bool).any() or d['Compound'].isin(['INTERMEDIATE', 'WET']).any():
            wet.add(rid)
            continue
        races_used[season].append(event)
        for drv, g in d.groupby('Driver'):
            if g['LapNumber'].max() < 0.9 * n_laps:
                continue
            g = g.sort_values('LapNumber')
            n_stops = int(g['pit_in'].astype(bool).sum())
            stops[season].append(n_stops)
            one_stop_share[season].append(1 if n_stops == 1 else 0)
            for st, sg in g.groupby('Stint'):
                comp = sg['Compound'].iloc[0]
                if comp in COMPOUNDS and bool(sg['pit_in'].astype(bool).iloc[-1]):
                    stints[season][comp].append(int(len(sg)))
    pre = pd.read_csv(PROTO / 'out' / 'tyreformer' / 'prerace' / 'predictions_A.csv')
    pre = pre[~pre['race_id'].isin(SEALED) & ~pre['race_id'].isin(wet) & pre['race_id'].isin(laps_by_race.keys())]
    deg = {}
    for season in DIRS:
        deg[season] = {}
        for comp in COMPOUNDS:
            rows = pre[(pre['season'] == season) & (pre['compound'] == comp)]
            vals = [float(v) for v in rows['obs'] if pd.notna(v)]
            n_laps = [laps_by_race.get(r) for r in rows['race_id']]
            per_lap_fuel = [1.0 / n for n in n_laps if n]
            fuel_kg = PRE_2026_FUEL_KG if season < 2026 else MODEL_FUEL_KG
            corrected = [float(o) + FUEL_S_PER_KG * (fuel_kg - MODEL_FUEL_KG) / laps_by_race[r] for o, r in zip(rows['obs'], rows['race_id']) if pd.notna(o)]
            deg[season][comp] = dict(n=len(vals), median=q(vals, 0.5), p25=q(vals, 0.25), p75=q(vals, 0.75),
                                     median_inverse_laps=q(per_lap_fuel, 0.5), fuel_kg_assumed=fuel_kg, median_fuel_corrected=q(corrected, 0.5))
    # same circuit, same compound, consecutive seasons: the circuit mix changes every year, so compare pairs
    paired = {}
    for a, b in ((2023, 2024), (2024, 2025), (2025, 2026)):
        key = f'{a}_to_{b}'
        paired[key] = {}
        for comp in COMPOUNDS:
            ra = pre[(pre['season'] == a) & (pre['compound'] == comp)].set_index('event')
            rb = pre[(pre['season'] == b) & (pre['compound'] == comp)].set_index('event')
            common = sorted(set(ra.index) & set(rb.index))
            diffs, diffs_fuel = [], {f: [] for f in (100.0, 110.0)}
            for ev in common:
                oa, ob = float(ra.loc[ev, 'obs']), float(rb.loc[ev, 'obs'])
                na, nb = laps_by_race[f'{a}_{ev}'], laps_by_race[f'{b}_{ev}']
                diffs.append(ob - oa)
                for f in diffs_fuel:   # seasons before 2026 carried a heavier start: add the burn-off the 70 kg fit left in
                    fa = f if a < 2026 else MODEL_FUEL_KG
                    fb = f if b < 2026 else MODEL_FUEL_KG
                    adj_a = oa + FUEL_S_PER_KG * (fa - MODEL_FUEL_KG) / na
                    adj_b = ob + FUEL_S_PER_KG * (fb - MODEL_FUEL_KG) / nb
                    diffs_fuel[f].append(adj_b - adj_a)
            paired[key][comp] = dict(circuits=common, n=len(common), median_change=q(diffs, 0.5),
                                     median_change_fuel_adjusted={str(int(f)): q(v, 0.5) for f, v in diffs_fuel.items()},
                                     earlier_median=q([float(ra.loc[e, 'obs']) for e in common], 0.5), later_median=q([float(rb.loc[e, 'obs']) for e in common], 0.5))
    comp_csv = pd.read_csv(PROTO / 'tyreformer' / 'data' / 'pirelli_compounds.csv')
    cnum = {}
    for season in DIRS:
        rows = comp_csv[comp_csv['season'] == season]
        cnum[season] = {c: dict(n=int(rows[c.lower()].notna().sum()), median=q([float(str(x).lstrip('C')) for x in rows[c.lower()].dropna()], 0.5),
                                mean=(lambda v: sum(v) / len(v) if v else None)([float(str(x).lstrip('C')) for x in rows[c.lower()].dropna()])) for c in COMPOUNDS}
    fuel_mask = {}
    for season in DIRS:
        ns = [laps_by_race[r] for r in laps_by_race if r.startswith(str(season)) and r not in wet]
        fuel_mask[season] = dict(median_race_laps=q(ns, 0.5), n_races=len(ns))
    out = dict(
        generated_at=pd.Timestamp.now(tz='Asia/Kolkata').isoformat(timespec='seconds'),
        source='deck_src/season_effects.py over feat2023/, feat2024/, feat2025/, feat/ race files and out/tyreformer/prerace/predictions_A.csv',
        sealed_excluded=sorted(SEALED), wet_races_skipped=sorted(wet), races_used={s: sorted(v) for s, v in races_used.items()},
        units=dict(degradation='s/lap per lap of tyre age (race-derived reference, 70 kg fuel subtracted in every season)', stint='laps', stops='pit stops per driver finishing >= 90% distance'),
        fuel=dict(fuel_s_per_kg=FUEL_S_PER_KG, model_fuel_kg=MODEL_FUEL_KG, pre_2026_fuel_kg=PRE_2026_FUEL_KG, note='bias of the reference slope for a season fuel load F = 0.03 x (F - 70) / race laps; masking in raw lap time = 0.03 x F / race laps'),
        degradation=deg,
        stint_length={s: {c: dict(n=len(v), median=q(v, 0.5), p25=q(v, 0.25), p75=q(v, 0.75)) for c, v in stints[s].items()} for s in DIRS},
        stops={s: dict(n_drivers=len(v), mean=(sum(v) / len(v)) if v else None, median=q(v, 0.5), one_stop_share=(sum(one_stop_share[s]) / len(one_stop_share[s])) if one_stop_share[s] else None) for s, v in stops.items()},
        race_laps=fuel_mask,
        paired_same_circuit=paired,
        pirelli_c_number=cnum,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ('races_used', 'wet_races_skipped', 'stops', 'race_laps')}, indent=0)[:2500])
    print(json.dumps(paired, indent=0)[:3000]); print(json.dumps(cnum))
    for s in DIRS:
        print(s, {c: (round(deg[s][c]['median'], 4) if deg[s][c]['median'] is not None else None, deg[s][c]['n']) for c in COMPOUNDS},
              {c: (out['stint_length'][s][c]['median'], out['stint_length'][s][c]['n']) for c in COMPOUNDS})


if __name__ == '__main__':
    main()

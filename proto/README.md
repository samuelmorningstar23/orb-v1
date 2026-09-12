# Orb v1 — release candidate

TrackShift 2026 · Tyre Degradation Intelligence · Team FireBolt (Samuel Christ).

Orb v1 combines a practice-to-race degradation forecast, a prefix-only Live Predictor, and a Ghost Strategy replay. This checkout contains the frozen Madrid forecast and the C5 scorecards. Start the dashboard from these committed artifacts; use a separate clone for regeneration.

## Disclosure: measured, inferred, and illustrative

Lap timing, compound, tyre age, flags and available telemetry come from public timing feeds via FastF1/OpenF1. Degradation is an estimated lap-time slope, not a direct measurement of rubber wear. Fuel mass and fuel-time cost are stated priors; tyre energy is a kinematic work proxy. Race-reference curves are fitted from race data for retrospective evaluation. Ghost deltas are model-implied, with the chosen traffic and safety-car assumptions shown; they are not observed time saved or a prediction of rivals' responses. Live Predictor replay consumes only the prefix available at the selected lap, with post-race reference fields removed at the service boundary. Contract fixtures and unavailable/stub features are labelled; a fixture is not a measured result. Driver feedback is an input to the posterior, not an independently validated gain in accuracy.

The estimator, feature extraction and initial six-weekend validation were disclosed pre-work from 4–5 September. Later data coverage, product integration and audits were built during the challenge. The sealed holdout had pre-freeze diagnostic dry runs; those runs are not release evidence and their figures are not quoted. The release quotes only **sealed holdout, aggregate only**: MAE 0.0372 versus naive 0.1713 s/lap, coverage 1.00, 5 weekends / 9 compound-weekends. See `out/validation/holdout_aggregate.json`, its freeze provenance and `out/validation/SCORECARDS.md`. Never use the per-race reveal in a presentation.

## Run the frozen dashboard

Python 3.12 is the tested interpreter family. The exact environment is pinned by `python -m pip freeze` in `requirements.txt`; the C6 audit records the interpreter and installation checks. From the repository root:

```sh
python3.12 -m venv .venv
cd proto
../.venv/bin/python -m pip install -r requirements.txt
../.venv/bin/python -m playwright install chromium  # needed for browser tests
../.venv/bin/streamlit run app_v2/streamlit_app.py --server.port 8502 --server.headless true --browser.gatherUsageStats false
```

Open `http://localhost:8502`. Health is `http://localhost:8502/_stcore/health`. Startup uses local committed artifacts; the dashboard must not request external resources. Dependency/browser installation and optional data acquisition need network access before the offline run. The release dashboard does not require an API key.

Feature CSVs under `proto/feat/` are gitignored. A clone alone does not contain the cached timing inputs needed for live replay and pipeline regeneration. Copy the supplied local feature cache into that directory before reproducing the full demo. The C6 reproduction uses the same cached CSVs and records their hashes; no timing-feed download is part of that check. Extra seasons in `feat2023/`, `feat2024/` and `feat2025/` are required only for rebuilding the corresponding evaluation data, not for starting the frozen dashboard.

## Reproduce the pipeline in an isolated clone

Do not run regeneration in the published checkout. It rewrites `out/lock.json`, `out/results.csv`, `out/validation.csv` and exclusion CSVs. It does not publish a replacement Madrid forecast, and it does not automatically rebuild the lock-v2, live or counterfactual sidecars. Keep regenerated scratch outputs separate from the frozen presentation artifacts.

```sh
# Run from the original proto/ directory; choose a new, unused destination.
git clone --no-hardlinks .. /tmp/orb-reproduction
cp -R feat /tmp/orb-reproduction/proto/feat
python3.12 -m venv /tmp/orb-reproduction/.venv
cd /tmp/orb-reproduction/proto
../.venv/bin/python -m pip install -r requirements.txt
../.venv/bin/python pipeline.py
../.venv/bin/streamlit run app_v2/streamlit_app.py --server.port 8510 --server.headless true --browser.gatherUsageStats false
```

The pipeline consumes the cached CSVs without fetching sessions. Its `generated_at` changes on each run. A successful regeneration is a computation check, not a newly approved release snapshot. For a presentation, return to the unchanged committed checkout on port 8502. In particular, never overwrite `out/forecast_Madrid_2026.*`, the sealed manifest pair or `evaluation/holdout/freeze.json` to make a scratch run agree with release provenance.

## Method and evidence

1. Clean practice laps using accuracy, pit/flag/deletion, telemetry, traffic, run-length and cooldown checks. Preserve exclusion reasons.
2. Fit stint fixed effects and compound tyre-age slopes after subtracting the fuel prior and session track evolution. The push/energy adjustment remains a diagnostic.
3. Learn the compound transfer factor from other weekends. If the transfer-factor agreement rule fails, an issued curve keeps factor 1 (the cleaned practice slope). The low-degradation fallback applies to withheld curves. The gate checks clean sample size and the minimum slope; abstention is a first-class output.
4. Update the live intercept/slope posterior from the available prefix. Feedback can change that state; the UI records its source and allows review. Ghost uses a separate, explicitly retrospective or pre-race model-implied path.
5. Read performance from the generated ghost/live/risk-coverage scorecards. C5 scorecard uncertainty uses 90% bootstrap bands resampling whole weekends, with eligible n and weekend counts beside each estimate. A single rolling-origin weekend cannot supply a weekend bootstrap interval; its interval is unavailable, with pooled intervals provided separately. Do not reinterpret legacy pipeline error intervals as the C5 weekend-bootstrap bands.

`out/lock.json` is the frozen numerical evidence source; `out/lock_v2.json` is the typed presentation contract. Published live/counterfactual sidecars provide additional provenance. Runtime prefix estimates are identified as computed rather than silently described as precomputed sidecars. See `schemas/README.md`, `counterfactual/README.md`, and `evaluation/README.md` for the implementation contracts.

## Frozen Madrid forecast

Qualifying refresh began after the two-hour availability window: 12 September 2026 at 21:32:31 IST. Publication was **12 September 2026 at 21:33:14 IST**, using FP1, FP2, FP3 and Q. The forecast is hashed before the race and verifiable afterward; it is not scored race evidence.

| Artifact | SHA-256 |
|---|---|
| `out/forecast_Madrid_2026.json` | `8e5489d5824ae066945225457d0198531db8a8fc246cd6f65d82787f550626ce` |
| `out/forecast_Madrid_2026.pdf` | `ead466275dddd7c23538e8920405e3042dc47ceade621e47b7a7b3c5e19f40a1` |
| `out/forecast_Madrid_2026.sha256` (file digest) | `30a5f06786fc332faf7934d0ed70cadd3bcba697f538939dfa5c8e905afe2c3c` |
| lock-v2 `shared.forecast_hash` | `sha256:66e3201e860b19efc410cac30073d6c12bd7d4f9cb894cd70a445747d3d0451a` |

## Validation and release checks

Keep port 8502 running while testing; screenshot tests otherwise skip. Run from `proto/`:

```sh
../.venv/bin/python -m pytest tests -q -ra
../.venv/bin/python tests/screenshots/release_gate.py --base http://localhost:8502 --out /tmp/orb-c6-capture --report tests/screenshots/c6_release_report.json
../.venv/bin/python evaluation/rehearsal_runner.py --server-proto . --out evaluation/rehearsal --allow-feedback
../.venv/bin/python -m evaluation.red_team.consistency_probe --browser --base http://localhost:8502
../.venv/bin/python -m evaluation.red_team.claim_audit
../.venv/bin/python -m evaluation.red_team.leakage_audit
../.venv/bin/python -m evaluation.red_team.identity_checks
../.venv/bin/python -m evaluation.red_team.build_report --checkpoint C6 --rerun claims
bash release/run_checkpoint.sh C6 AUTO "<verified release evidence>"
```

The rehearsal runs for at least five minutes. It appends one marked feedback event and restores the original log afterward; run it without other feedback writers.

Read `checkpoints/C6/checkpoint.md`; only the lead decides GO after checking results. The expected hash test documents that a generation-time data cutoff can change the hash without a numerical change. One historical adapter baseline is skipped after lock regeneration. Neither justifies ignoring a new failure. `app_v2/PERF.md` and the C6 reports record the browser, keyboard, refusal-state and five-minute rehearsal evidence.

## Data and scope limits

Public timing lacks measured fuel load, carcass temperature and complete private tyre state. Missing telemetry and unsupported scenarios must display a refusal or degraded-mode banner. Replay holds the stated safety-car and rival assumptions fixed; frozen-field traffic simulation is not implemented. Only three weekends contribute to the current live-prefix evaluation. There are no feedback-ablation events in the published scorecard. A good fit to retrospective race-reference slopes is not proof of causal pit-stop benefit, future race position or generalisation to another series. Data access and upstream cache availability are separate from the offline dashboard.

## Eight jury questions

1. **What is measured?** Public timing and available telemetry; degradation, energy and strategy consequences are estimates or proxies, labelled as such.
2. **Can Sunday leak into a Friday prediction?** Compound transfer-factor fitting excludes the held-out weekend; live estimator inputs stop at the selected prefix. Race-reference information is confined to retrospective evaluation and explicitly labelled Ghost views.
3. **Why withhold a curve?** The evidence gate refuses unsupported clean sample size or slope. It reports its reason and the stated fallback instead of forcing an issued curve.
4. **What does a confidence band mean?** The scorecards show a 90% whole-weekend bootstrap interval with sample counts. Forecast bands and single-weekend unavailable intervals have distinct labels.
5. **Does Ghost prove time saved?** No. It compares plans under the stated model and context; the result is model-implied, not observed time saved.
6. **What did the sealed holdout establish?** Only the labelled post-freeze aggregate reported above. It does not license tuning on or presenting per-race results.
7. **What happens without internet or usable telemetry?** The presentation uses local assets. Unusable feed/position/support states display their banners rather than an unsupported result.
8. **How can Madrid be checked later?** Compare the published forecast and its full digests with the later race evidence under a declared evaluation procedure; preserve the pre-race files unchanged.

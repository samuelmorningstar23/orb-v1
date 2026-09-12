# ClearStint — clean tyre-degradation curves from Friday, scored on Sunday

TrackShift 2026 · Tyre Degradation Intelligence · Team FireBolt (Samuel Christ)

ClearStint turns Friday practice into per-compound tyre-degradation curves, says "withheld" when Friday cannot support one,
learns per compound how much Sunday's tyre management shrinks the Friday number from previous weekends only, and scores itself
against the race with the same estimator every Sunday night. Free public data only (FastF1, OpenF1).

## Disclosure of pre-work
The feature extraction (`proto/features.py`), the fixed-effects estimator (`proto/model_v2.py`) and a six-weekend leave-one-out
validation with the transfer-factor rule (`proto/make_figs.py`, `proto/strategy.py`) were built on 4–5 September 2026 for the idea
submission and disclosed there. Everything else was built during the Challenge Day window: the pipeline and lock file, seven more
weekends including sprint format, the low-degradation fallback, the push-profile diagnostic, qualifying-based compound offsets, the
strategy replay on every weekend, the liquid model and its ablation, the dashboard, the brief and Q&A, and the live Madrid forecast.

## Run it
```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r proto/requirements.txt
cd proto
../.venv/bin/python extract_extra.py --year 2026 --events Monza,Madrid --out feat --cache ~/Trackshift/cache   # any weekend by name
../.venv/bin/python pipeline.py            # -> out/lock.json, out/results.csv, out/excluded_<event>.csv
../.venv/bin/python liquid.py              # -> out/liquid.json (optional, ~10 s per weekend on CPU)
../.venv/bin/streamlit run app.py          # dashboard on http://localhost:8501 (views are URL-addressable: ?ev=Madrid&view=Strategy)
../.venv/bin/python build_deck_v5.py       # -> out/ClearStint_ChallengeDay.pdf, every number from the lock
```

## What is in the lock
`out/lock.json` is the single source of truth: per-weekend metadata (sessions, evolution, track temperature, exclusions by reason,
compound offsets), the leave-one-weekend-out validation (MAE ladder, calibration, bootstrap intervals, withheld cases, push
diagnostic), the live weekend's issued and withheld compounds with bands, and the strategy replay. The dashboard, the brief and the
deck read it and compute nothing else.

## Method in one paragraph
lap time = stint effect + compound-specific degradation × tyre age + fuel prior (1.1 kg/lap, 0.030 s/kg) + track evolution measured
per session from every driver's push laps. Traffic laps (>30% of the lap within 60 m of a car, from the gap-to-car-ahead channel),
pit laps, flagged laps, deleted laps, runs under 5 clean laps and laps slower than 105% of the run best are excluded and listed with
their reason. A curve is issued with 30+ clean long-run laps and a positive cleaned slope; the transfer factor is the median race ÷
practice ratio of other weekends, applied when a majority agree within ±50%; withheld compounds are forecast as the median race
degradation of the other withheld cases. Telemetry quality is checked lap by lap and degraded feeds are refused.

# TrackShift 2026 · Idea Submission · form answers (paste as-is)

**Theme:** AI Motorsport Intelligence
**Problem Statement:** Tyre Degradation Intelligence
**Project Title:** ClearStint: clean tyre-degradation curves from practice, plus a season-long loop that learns how Friday maps to Sunday

---

## Describe your proposed solution and what makes it innovative.

At the 2026 Hungarian GP a straight line through Friday's long-run laps says the medium tyre degrades at +0.28 s/lap. The race showed +0.04. Wrong by 7 times. Friday lies about Sunday, twice, and ClearStint fixes both lies.

Lie one: a practice lap time is fuel burn + track evolution + traffic + driver + tyre. ClearStint strips the first four: a physics fuel prior, track evolution measured from every driver's push laps over the session, traffic laps removed using the gap-to-car-ahead telemetry channel, and per-stint effects that absorb driver and fuel-load differences. Telemetry quality is checked lap by lap, because we found the official Hungary race position feed is degraded at source (about 26 distinct points per lap) and a model that does not notice produces nonsense silently.

Lie two, which nobody models publicly: even a perfectly cleaned Friday curve is not Sunday's curve, because drivers attack tyres in practice and manage them in a race. We measured race degradation with the same estimator on 6 conventional 2026 weekends and found the medium's race degradation runs at about 0.4 times its cleaned practice value on every European weekend, while soft and hard transfer roughly one to one. ClearStint learns a transfer factor per compound from previous weekends only, applies it only where weekends agree, and scores itself against the race every Sunday night.

Innovation: the only published model on public F1 data (arXiv 2512.00640) uses race laps only, one driver, one race, and ignores traffic and track evolution. Nothing public uses practice as the input, quantifies the practice-to-race gap, or validates leave-one-weekend-out across a season. A tyre-energy proxy we computed from the public 3.7 Hz traces shows practice and race laps carry the same energy per lap (+2% at Austria), so the gap is management, not push level: a finding a pit wall can use. The product turns the curve into a decision: crossover laps and a one-stop versus two-stop comparison, replayed on Hungary 2026, where following the naive curve costs +74 s and ClearStint's plan +26 s against the best plan. And it says "no reliable curve" when the data cannot support one.

## What technologies, AI/ML models, tools, and datasets do you plan to use?

Free public data only: FastF1 (v3.8) and the OpenF1 API give per-lap timing, sector times, compound and tyre age, stint structure, pit in/out, track status, deleted laps, weather, and 3.7 Hz car telemetry, position and distance-to-car-ahead for every driver in every session, 2018 to today. Already extracted and verified: 1,544 practice laps and 3,177 race laps across 6 2026 weekends (Australia, Japan, Barcelona, Austria, Belgium, Hungary).

Model, today: Python 3.12, pandas, NumPy. A within-stint fixed-effects regression with a 2026 fuel prior (about 1.1 kg/lap) and a track-evolution term, applied identically to practice and race so the transfer ratio is a property of the data, not of the method. Transfer factors are medians over other weekends, applied only when a majority agree within ±50%. Uncertainty by bootstrap over weekends.

Model, Challenge Day: a hierarchical Bayesian model in PyMC (Stan fallback): lap time = stint effect + compound-specific degradation in tyre age with a non-linear cliff term + fuel + track evolution + track temperature + heavy-tailed error; transfer factors as parameters with priors from previous weekends; credible bands on every output; compound offsets estimated from qualifying laps for the crossover and strategy module. Lap-level tyre energy (from arc-length-resampled position and speed) and a scikit-learn push/lift classifier as covariates and diagnostics.

Product: a Streamlit dashboard with the calibrated curves and bands, crossover laps, one-stop versus two-stop comparison with stint lengths, sector-level degradation map, the list of excluded laps with reasons, and the Sunday-night scorecard. Public GitHub repository, reproducible for any Grand Prix weekend by name.

## How will you validate your solution's performance, feasibility, and effectiveness?

The race is the ground truth and nothing is tuned on it. For each of the 6 weekends we fit on practice only, apply transfer factors learned from the other weekends (leave-one-weekend-out), and compare predicted per-lap degradation per compound with the fuel-corrected, traffic-free race value from the same estimator. Over the 12 compound-weekends where a curve was issued: mean absolute error 0.180 s/lap for a naive fit, 0.059 for the cleaned practice curve, 0.028 for ClearStint (90% bootstrap interval 0.016 to 0.042). The gain is concentrated where the factor is applied: medium error falls from 0.089 to 0.014 (90% CI on the gain 0.036 to 0.114); soft and hard are left uncorrected and stand at 0.048 and 0.010. Against a single global factor for all compounds, ClearStint wins 9 of 12.

We refuse to predict when a compound has under 30 clean practice laps or when the cleaned practice slope is not positive, which happened for hard and medium at the two season-opening rounds (Australia, Japan: green tracks, teams learning the 2026 cars). 5 of 17 compound-weekends were withheld and are reported, not hidden; the confounder model for early-season weekends is on the Challenge Day list. On Challenge Day we add sprint weekends, calibration checks of the credible bands (do 90% bands contain the race value 90% of the time), sensitivity of every number to the fuel prior and lap filters, and the error in predicted crossover lap.

Effectiveness is measured as a decision. On Hungary 2026, with stated assumptions (0.6 s pace step between compounds, 21 s pit loss, linear degradation), the plan implied by the naive curve costs +74 s of race time against the best plan under the observed curves; ClearStint's plan costs +26 s. We will repeat this replay for every 2026 race and compare with what the field ran. Feasibility: pipeline, quality checks, estimator, replay and validation harness run today on a laptop from free data; all pre-work is disclosed. Beyond motorsport, the same clean-then-transfer loop goes to e-rickshaw battery state of health, first on the public Severson et al. (2019) dataset (124 cells, charging-policy confounders; metric predicted versus measured capacity), then a pilot with a fleet operator or leasing lender in Punjab.

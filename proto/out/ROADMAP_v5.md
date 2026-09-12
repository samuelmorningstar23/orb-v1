# Orb v1 Live Tyre Intelligence: roadmap v5

*Predict. Monitor. Decide. Prove.* Build contract, 12 Sep 15:20 IST.

## 0. Orb v1
Pre-race prior -> live posterior every lap (telemetry, conditions, traffic, driver feedback, private sensors when available) -> useful life and cliff risk -> ranked pit/compound actions -> Race Twin proof. Six capabilities: all feasible; live telemetry in team mode; driver profile hardest (Phase 2).

## 1. Architecture
PreRaceCurveProvider, LiveTyreStateEstimator, StrategyOptimizer, RaceTwinEngine + adapters + RaceEventSource. Live model: regime-switching Bayesian state-space with process noise, boosted residual, exact optimiser; LNN optional encoder only.

## 2. Sittings
1: Sat 14:15-23:30 Phase 0 with Madrid anchors. 2: Sun pre-slot subset of Phase 1, rest after. 3: post-event Phase 2.

## 3. Phase 0
Race Twin slice (0.1-0.6) + live slice (0.7-0.13): live-state contract, replay estimator with widening, RaceEventSource, driver-feedback input, live comparison graph, action engine, red team, Madrid anchors.

## 4. Phase 1
Live adapters, feedback adapter, inventory, rejoin, histories, prefix validation; Race Twin scale and validation; frozen field behind fallback; dashboard integration; documents.

## 5. Phase 2
Driver profiles; regime-switching estimator; boosted residual; absolute compounds; sensor modes; shape-constrained wear; TUMFTM; multi-agent last.

## 6. Workstreams
Eight workstreams by directory; gates on merge; claims bound to mode.

## 7. Contracts
Five interfaces; live_tyre_state, live_recommendation and driver feedback fields; public-mode display rules.

## 8. Dashboard
Seven routes; main screen is Live Tyre State; Race Twin is proof.

## 9. Validation
Identity; hidden-stop; regret; live-prefix; feedback ablation; profile requirements; sealed and prospective. Parameter policy; wording rules; release gates incl. live additions.

## 10. Story
Predict, Monitor, Decide, Prove.

## 11. Risks
Two slices; public live data licensing; engineer-in-loop on Sunday; honest estimator labels; holdout first; registration name; rehearsal protected.

## 13. Premium dashboard
Streamlit shell + React Race Twin component; tokens; global frame; landing; hero screens; acceptance criteria; Playwright screenshots.

## 14. Build control
Workstream 9; heartbeats; 90-min stops; checkpoints C0-C7; stop-the-line; reviewers; tasks 0.14-0.17; start conditions and waves.

## 12. Ten questions
**1. What does the live system actually see during a race from public data?**

Lap and sector times, car speed, throttle, brake, gear, DRS, gaps and positions, pit events, compound and stint information, track status, weather and team-radio records, plus our derived tyre-demand, traffic and push proxies. No tyre pressures or temperatures; those arrive only through the team adapter, and the screen says which mode it is in.

**2. How does driver feedback change the model without letting a driver talk the model into anything?**

Feedback is a timestamped observation with a confidence, entered or confirmed by the engineer. It shifts the probabilities of tyre regimes, for example from normal degradation toward overheating, and the next laps of telemetry confirm or weaken it. It never adds seconds to a curve directly, and it can be disabled with the result reverting.

**3. Why should the confidence band ever widen during a race?**

Because the world changes: rain, a sharp track-temperature shift, a change in push, a safety car cooling the tyres, suspected damage, a degrading feed, or behaviour outside the training support. A filter with tiny process noise becomes overconfident; ours carries explicit process noise and widening rules that are tested.

**4. What is the difference between the pre-race plan and the live recommendation?**

The pre-race plan is a distribution over strategies locked and hashed before the race: primary plan, pit window, probability against the best two-stop, downside, and the condition that flips it. The live recommendation re-runs the same optimiser after every event with the posterior tyre state and shows which observation moved the call.

**5. How is the live model validated when nobody can see the future?**

Prefix evaluation on held-out races: reveal data through lap k, update, predict the next one, three and five laps and the useful-life range, recommend, then step forward. We report next-lap error, cumulative error, coverage, cliff precision and recall, Brier score, alert lead time, false alerts per stint and recommendation stability.

**6. Why are Live Predictor and Ghost Strategy separate tools?**

Because they answer different questions with different data boundaries. Live Predictor may only see what existed at the current timestamp and makes the call; Ghost Strategy sees the finished race and audits whether the model deserved to make it. The same frozen forecast powers both, the code enforces that neither imports the other, and the jury can see the audit without any live claim leaking into it.

**7. Is the driver profile a ranking of who manages tyres best?**

No. It is a style profile from telemetry plus an outcome profile expressed as residuals after adjusting for car, circuit, compound, temperature and season, under hierarchical shrinkage, compared within weekend against the teammate. Cross-track predictions carry wide intervals and an evidence count, and unseen drivers get the population prior.

**8. Can I change the weather in Ghost Strategy?**

Within supported scenarios, yes: actual historical, the pre-race snapshot, cooler, baseline and hotter dry; damp only where the model has support, wet not at all until a wet model validates. Every scenario carries a support status and the screen says "model-implied scenario, no observed outcome exists". Only actual-weather audits count as evidence.

**9. How do you keep the live demo from being a separate, fragile code path?**

One event interface with three sources, replay, live and recorded-live, emitting identical events. The model and the dashboard cannot tell which is active, so the replay we rehearse is the live path we run on Sunday evening.

**10. What happens to the recommendation when a rival pits?**

The optimiser re-runs, because a rival stop changes the rejoin context and the value of track position. In Phase 0 the rejoin context is the observed gap structure; Phase 1 adds live rejoin and traffic estimation; rival strategic responses are never simulated, and the screen says so.

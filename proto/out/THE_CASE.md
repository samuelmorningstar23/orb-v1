# Orb v1: the case

## 1. The idea
Friday lies twice. We remove the first lie with physics and telemetry, learn the second from earlier weekends, refuse when Friday has no signal, and score ourselves against the race. The push profile, measured from telemetry energy, explains about half of the Friday-to-Sunday gap; the learned management factor covers the rest.

## 2. Stack
FastF1 data; per-lap features incl. an energy proxy and feed-quality checks; stint fixed-effects estimator identical on practice and race; pipeline to a single lock file; strategy replay; learned transfer factors with bootstrap and sensitivity; liquid-network ablation (ncps/PyTorch); Streamlit dashboard; documents generated from the lock.

## 3. Outcomes
Naive 0.137 vs Orb v1 0.023 s/lap; r 0.20 -> 0.78; 28/29 wins; 13/13 withheld were low-degradation races; push profile explains ~half the gap; sensitivity 0.021-0.027; Madrid live.

## 4. Why we win
Technical depth: measured fifth confounder, learned and validated factor, validated abstention, fair ablation. Fit: the literal brief delivered. Demo: real data, live weekend. Scalability: any GP from free data; junior series and broadcasters. Presentation: one story, one file.

## 8. Fourteen jury questions
**1. The 2026 cars are new: fifty-fifty electric power, active aero, narrower tyres. Does a method tuned on 2026 mean anything?**

The method is not tuned on 2026; it is a set of stated priors and measured corrections that apply to any season. What is 2026-specific is the learned transfer factor, and that is exactly why 2023 to 2025 are on disk: if the medium's Sunday ratio repeats at the same circuits across seasons it is a property of the tyre and the circuit; if it does not, it is a property of the 2026 car, and we say which.

**2. How can a fixed effect per stint separate the tyre from the car when the car changes setup between runs?**

It cannot separate levels, and it does not try: each run's level is absorbed. Only the change within a run, lap over lap, informs the slope, and setup does not change mid-run. What a setup change can do is alter how fast the tyre degrades, and that becomes part of the spread between runs that the standard error reports.

**3. Your energy proxy uses position data at 3.7 Hz. Is curvature from that even meaningful?**

Raw curvature from 3.7 Hz points is not, which is why we resample the path onto a uniform 10 m grid after removing stale repeated samples, smooth, and clip the radius at 15 m. The check is empirical: energy per lap is stable across drivers on the same compound, rises when a driver ramps up, and the coefficient linking it to lap time has a consistent scale between Friday and Sunday. Where the feed is degraded, Hungary race, China FP1, the counters catch it and the proxy is refused.

**4. Is the push adjustment not circular? Drivers lift because the tyre is going off.**

Partly, yes, which is why the push-adjusted slope is a diagnostic and a second opinion, never the headline predictor. The as-driven estimator with the learned factor predicts the race better. The diagnostic's value is explanatory: it tells you why a Friday shows no signal and it accounts for about half of the Friday-to-Sunday gap.

**5. Why not a Bayesian hierarchical model, as your idea submission promised?**

Because with eleven weekends the honest first step is the simplest estimator that validates, and it validates. The hierarchical layer is exactly what the three-season download is for: partial pooling of the transfer factor by compound across seasons, with a coverage check on the bands. It is on the roadmap for after the event, not because it is hard, but because it should be built on more than one season.

**6. Where could information leak from the race into the Friday prediction?**

Three places, all closed. The transfer factor for a weekend is computed from other weekends only. The fallback value is the median of other weekends' withheld outcomes. Compound offsets come from that weekend's qualifying, which precedes the race. The only thing that sees the race is the scorecard.

**7. Would this work in Formula 2, where there is no telemetry feed?**

The estimator needs lap times, tyre age and compound, and flags, which F2 timing provides; fuel and evolution corrections carry over. What is lost without telemetry is the traffic flag and the push proxy, so more laps would be withheld and the bands would widen. That is the honest degraded mode, and it is still far better than a straight line.

**8. What happens when Pirelli brings different compounds to a circuit next year?**

The curve is per compound name at that weekend, learned from that weekend's Friday; the transfer factor is per compound role, soft, medium, hard, which is about how drivers treat the role. If the role changes, the agreement rule notices the ratios disagree and stops applying the factor until enough weekends agree again.

**9. Half your withheld cases are hard tyres with too few Friday laps. Is that a method problem or a data problem?**

A data problem that the method reports rather than hides: teams rarely run the hard on Friday at European rounds. The fallback still gives a forecast, and the practice-to-sprint test on sprint weekends adds a second observation of the hard. A team with its own Friday plan could fix it in an afternoon by running the hard.

**10. If you had one more day, what would you build first?**

The per-driver degradation and push profile, teammate against teammate, checked for repeatability across weekends. It answers a question strategists and broadcasters actually ask, who looks after their tyres, and it needs nothing we do not already have.

**11. You say live monitoring, but the race starts after the event closes. What are you actually showing?**

A lap-by-lap replay of a race we have already scored, Monza or Hungary: the Friday forecast on screen, then the live estimator updating at lap 10, 20 and 30, the band shrinking, the alerts firing or not, and the pit call moving or holding. The same code runs on Madrid on Sunday evening from the live-timing stream; the forecast it will be compared against is hashed before the race.

**12. Without tyre sensors, how early can your live mode detect a tyre going off?**

From lap times alone it needs a few laps to separate a change in slope from lap noise, so two to three laps after the change. With a team's temperature and pressure feed the same alert fires on the lap it happens. That latency difference is exactly why the sensor socket is in the design.

**13. Why is a five-parameter formula calibrated at Bahrain worse than what you do?**

Because a calibration is not a validation. A formula fitted at one circuit has no measured error anywhere else, and every alert threshold around it is a human guess. We report the error on 29 held-out cases across eleven circuits and fire alerts only when a measurement leaves a forecast band. If they show an out-of-sample error, we will compare it gladly.

**14. Why not reinforcement learning for the pit decision?**

The decision under our cost model is a small search we solve exactly, so an agent has nothing to learn beyond the enumeration. Learning from history is already done by leave-one-weekend-out and the Sunday-night update, in a form a juror can check. Reinforcement learning becomes worth it with a stochastic race simulator, safety cars, rivals, traffic; a December 2025 paper does that, and it is on our post-event roadmap with that citation.

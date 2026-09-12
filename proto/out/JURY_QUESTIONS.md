# Twenty questions on technical depth

**1. How do you separate fuel burn from tyre degradation when both change monotonically within a stint?**

We do not try to estimate fuel from practice; within a stint the two are collinear and the estimate is not identified. The fuel term is a stated prior from the 2026 regulations, 1.1 kg per lap at 0.030 s per kg, applied as a known offset. The sensitivity sweep shows the headline error stays between 0.023 and 0.026 s/lap across 0.9 to 1.3 kg per lap and 0.025 to 0.035 s per kg, and an independent public estimate from race data gives 0.0294 s per kg.

**2. Why a fixed effect per stint rather than per driver?**

A stint carries its own fuel load, tyre set, engine mode and driver; a per-driver effect would leave fuel-load differences between runs in the residual and bias the slope. The cost is that we discard the absolute level and keep only the change within a stint, which is exactly what degradation is.

**3. How is track evolution identified separately from tyre age?**

It is measured per session from every driver's push laps, laps within 1% of that driver's own best, against session time, driver-demeaned. Push laps happen at different times of the session on fresh tyres across drivers, so session time and tyre age are not collinear. At Madrid it was 0.6 to 0.8 s per hour on Friday (FP1 0.63, FP2 0.76 s per hour).

**4. How do you detect traffic, and how sensitive is the result to that choice?**

From the distance-to-car-ahead channel at 3.7 Hz: the share of the lap spent within 60 m of the car ahead. Laps above 30% are dropped; laps without gap data are dropped rather than assumed clean. At 20% the error is 0.027, at 40% it is 0.021.

**5. Why leave-one-weekend-out rather than ordinary cross-validation?**

Because the deployment question is a new weekend with no race yet. A random split would let a weekend's own race leak into the factor applied to its Friday. Every number in the deck is computed with the held-out weekend's race unseen.

**6. Your transfer factor is a median over ten numbers. Is that not fragile?**

It is small, which is why it is applied only under an agreement rule, at least three weekends with a majority within 50% of the median, why hard never qualifies, and why we show bootstrap intervals: 0.016 to 0.030 on the error. The 2025 same-track ratios are the next test and are downloading.

**7. What does withheld mean, and is it not a way to avoid being wrong?**

It means Friday had fewer than 30 clean long-run laps or no positive cleaned slope. It is still a forecast: low degradation, the median race value of the other withheld cases, leave-one-out. That forecast has an error of 0.023 s/lap against 0.106 for the naive line over the 13 withheld cases; the withheld compounds degraded at a median 0.028 s/lap in the race (range -0.009 to +0.100); 11 of 13 below 0.06 s/lap; the fallback band covered 9 of 13. It is scored like everything else.

**8. Why does a cleaned practice curve come out negative on some compounds?**

Because the driver was ramping up. The within-run trend of tyre energy per lap of age is +0.10 MJ per lap at the median on withheld compounds and 0.00 on issued ones. Lap times fall faster than fuel burn explains, and the estimator reads it as negative degradation. We measure that rather than assume it.

**9. What is the energy proxy and how do you trust 3.7 Hz position data?**

Mass times the integral of speed squared times path curvature along the lap, plus the integral of absolute speed change: lateral and longitudinal work through the contact patch. Curvature is computed on a 10 m arc-length grid from de-duplicated samples. Each lap carries a feed-quality check; the Hungary race feed had about 26 distinct points per lap instead of 300, so its energy is pace-estimated and its traffic is unknown, and the pipeline says so.

**10. Is the energy covariate not endogenous? Drivers lift because the tyre is degrading.**

Yes, partly, which is why the push-adjusted slope is a diagnostic and a second opinion and not the predictor. Adjusting for push removes some of the degradation signal we want, and the as-driven estimator with the learned factor predicts the race better: the probability that the push-adjusted version beats it is 0.14.

**11. Where is the machine learning?**

The transfer factor and the fallback are parameters learned on training weekends and scored on held-out weekends. The liquid network was trained and tested with a fair ablation. The AI that earns its place is the part that survives the held-out test.

**12. Tell us honestly what the liquid network did.**

A closed-form continuous-time cell read each race stint lap by lap and predicted the cleaned trajectory, scored on held-out stints. Against age-only fits it wins almost everywhere. Against a linear model given the same per-lap inputs it beats the best baseline in only 9 of 31 cells, and its median gain is about zero (+2% change in held-out error). The inputs were the discovery: energy, traffic and fuel cut the age-only error by about a quarter, lap-weighted, with the three degenerate Hungary cells excluded (31% with them). The network stays as the curve-shape tool.

**13. How do you validate the uncertainty bands?**

By coverage: the share of 90% bands that contain the race value, computed leave-one-out. With 16 issued cases the check is coarse, so it is reported as a count, not a percentage; the band construction combines the regression's standard error with resampled transfer ratios from other weekends.

**14. How does this fail?**

New circuits and green tracks, where drivers ramp up: the gate withholds and the fallback answers, and Madrid is the live example. Wet sessions: excluded. Degraded telemetry feeds: refused, not modelled. Safety cars and traffic in the race: the strategy replay ignores them and says so. Compounds with thin running, hard at most European rounds: withheld for too few laps.

**15. Why linear degradation curves?**

Because linear validates best for prediction at the tyre ages actually run. The quadratic and liquid curves split the season 15 accelerating against 13 settling, so there is no single non-linear shape to assume. The shape tools flag the exceptions and the cliff lap where one exists.

**16. How does this compare with the published state-space model on public F1 data?**

That model (arXiv 2512.00640) fits one driver's race with fuel and a latent pace, with no practice input, no traffic, no track evolution and no cross-weekend validation. Ours starts from practice, strips four measured confounders and one diagnostic one, and is validated leave-one-weekend-out across eleven weekends. Its code is public and we can run it as a baseline on one race.

**17. A public analysis concludes practice curves do not transfer to the race. Your response?**

That conclusion is measured on stop-by-stop pit deltas, a target whose standard deviation is close to its mean. At the compound-weekend level, with the management factor learned leave-one-out, the correlation between Friday and Sunday is 0.78 against 0.20 for the naive line. The curve transfers once you learn how each compound is managed.

**18. What does the strategist actually get on Saturday night?**

Per compound: the slope, the 90% band, the basis in one sentence, or the withheld reason and the low-degradation forecast. Crossover laps. The best one-stop and two-stop plans with stint lengths and what flips the call. The list of excluded laps with reasons.

**19. How and when is the Madrid forecast scored?**

The forecast was issued from FP1 and FP2 and is time-stamped; FP3 refresh landed 18:11; qualifying refresh landed 21:33 with FP1, FP2, FP3 and Q in the lock (a 21:03 attempt found the session not yet run); hashed forecast published 21:33 IST (sha256 8e5489d5824a). After Sunday's race, which starts 18:30 IST, after the event closes, the same estimator runs on the race laps and the scorecard is published. We commit to publishing it whether it is right or wrong.

**20. What would you need from a team to make this production-grade?**

Fuel mass per lap, tyre pressures and temperatures, and the driver's push instructions. The fuel prior and the energy proxy then become measured inputs, the gate fires less often, and the rest of the method is unchanged. For F2, F3 and F1 Academy, which have public timing and two engineers, it runs as is.

# ClearStint — talk track

## 5-minute jury version (one line per slide, numbers from the lock)

1. **Title.** "ClearStint issues clean tyre-degradation curves from Friday practice and scores them against the race every Sunday. Friday lies twice: about what the tyre did, and about what it will do on Sunday. We correct the first lie and learn the second."
2. **Problem.** "Hungary, medium tyre: a straight line through Friday says +0.28 s per lap of age. The race showed +0.04. Seven times wrong. Every Friday lap carries fuel, track evolution, traffic, the driver, and how hard the driver was pushing."
3. **Six steps.** "Ingest, clean, gate, learn, forecast, score. Same estimator on practice and race, so the practice-to-race ratio is a property of the data, not of our method. And it says 'withheld' when Friday cannot support a curve."
4. **Proof.** "Eleven weekends, twenty-nine compound-weekends, every number leave-one-weekend-out. Naive error 0.137 s/lap, ClearStint 0.023. Correlation with the race goes from 0.2 to 0.78. Every compound answered: sixteen issued, thirteen withheld and forecast as low degradation, and all thirteen were low-degradation races."
5. **Fifth confounder.** "Why do some Fridays show no degradation? Because the driver was ramping up. We measure energy through the tyre from the public 3.7 Hz traces; on every withheld compound it rises through the run. And the price of lap time per megajoule is the same on Friday and Sunday at Austria and Barcelona to two decimals. That is physics, not a fit."
6. **Madrid live.** "Issued this morning from FP1 and FP2, before qualifying: soft +0.10 with a wide band; medium withheld because drivers were learning a new track, forecast low degradation by two independent routes. Plan: one stop, soft then medium; the top of the band says two. Scored after Sunday's race, and we will publish the score."
7. **Decisions.** "A curve only matters as a decision. Replayed on eight races: the naive plan costs 47 to 155 seconds against the best plan; ClearStint's costs 0 to 30, and beats naive in seven of eight. Barcelona is the honest miss and we say why."
8. **Liquid model.** "We tested a liquid neural network that reads each stint lap by lap. Given the same inputs, a straight line is about as good. The inputs were the discovery: energy, traffic and fuel cut the error of the age-only model by 23%. The network stays as the curve-shape tool, and we report the test rather than hide it."
9. **Product.** "One lock file feeds six dashboard views and this deck. For junior categories with two engineers and public timing: F2, F3, F1 Academy, Indian F4, broadcasters. Beyond the track the loop is the same: measure the confounders, gate, learn the transfer, score against truth."
10. **Built when.** "The estimator and the six-weekend validation were disclosed pre-work. Everything else on these slides, seven more weekends, the fallback, the push diagnostic, strategy with qualifying offsets, the liquid model, the dashboard and Madrid live, was built here. Limits are on the slide. Sunday night, Madrid gets scored."

## 90-second mentor-checkpoint version

"Tyre degradation from Friday practice, with the race as ground truth. The estimator strips fuel, track evolution, traffic and the driver from every lap, issues a curve only when Friday supports one, and learns per compound how much Sunday's management shrinks the Friday number, from previous weekends only. Leave-one-weekend-out across eleven weekends: error 0.023 versus 0.137 naive. The new finding today is the fifth confounder, the driver's push profile from telemetry energy: it explains every withheld case, and withheld has meant a low-degradation race thirteen times out of thirteen. Madrid's curves are issued from FP1 and FP2 and will be scored after the race. The dashboard is running; here is Madrid."

## Four predictable questions, four answers

- **What did you build today?** Seven new weekends including sprint format, the fallback rule, the push diagnostic, qualifying-based offsets, the liquid model and its ablation, the dashboard, Madrid live. The estimator and the first six weekends were disclosed pre-work from the idea round.
- **Where is the AI?** The transfer factor is learned from previous weekends and scored on held-out ones. The liquid network was tested honestly and reported. The AI that earns its place is the one that survives the held-out test.
- **How is this different from a regression on lap times?** Same estimator on practice and race, a gate that refuses, a factor learned across the season, a fallback that is validated, and a fifth confounder measured from telemetry that nobody else strips.
- **What breaks it?** Green tracks and new circuits, where drivers ramp up: the gate catches them and the fallback answers. Degraded telemetry feeds: refused, not modelled. Wet sessions: excluded. Safety cars and traffic in the race: the strategy replay ignores them and says so.

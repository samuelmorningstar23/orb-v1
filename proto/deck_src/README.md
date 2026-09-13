# Orb v1 briefing deck source

Rebuilt 13 Sep 2026: 24 slides, 16:9 wide, every figure read from an artefact at build time. Build from `proto/`:

```
../.venv/bin/python deck_src/product_shots.py --capture   # needs the dashboard on :8502; skip --capture to re-crop only
../.venv/bin/python deck_src/season_effects.py            # season facts 2023-2026 from the race lap files
../.venv/bin/python deck_src/deck_charts.py               # chart images from the scorecard and season facts
cd deck_src && npm install && node build_deck.js          # writes ../out/Orb_v1_Mentor_Briefing.pptx
cd .. && ../.venv/bin/python -m evaluation.red_team.claim_audit   # the claim gate test needs a map newer than the deck
```

Inputs: `../out/lock.json`, `../out/lock_v2.json`, `../out/validation/`, `../out/tyreformer/`, `../out/counterfactual/`,
the red-team reports and checkpoint records, `../out/fig_*.png`, and `assets/`:

- `shot_*.png`: cropped dashboard screenshots (`assets/raw/` holds the full captures).
- `season_effects.json`: degradation, stint length and stops per season; same-circuit 2025 to 2026 pairs.
- `chart_*.png`: the four chart images.
- `regulations.json`: the 2022 to 2026 rule history with source URLs, caveats and what could not be verified.
  It is hand-curated from cited research; the slides quote only its verified items.

The build refuses to run when the frozen Madrid forecast files disagree with the locks, and it refuses to write the deck
when a slide matches a claim the red-team claim map blocks for the deck (`evaluation/red_team/claim_evidence_map.json`)
or breaks a wording rule.

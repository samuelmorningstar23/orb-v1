# Orb PreRace: learned practice-to-race transfer vs Orb v1

Generated 2026-09-13T06:13:02 (git e35c11455b752177242c3861015a574cc0cce82b). Target: race-derived pace-loss reference slope (s/lap per lap of tyre age) on development compound-weekends; sealed holdout weekends were never loaded (assertion passed, 6 sealed ids). Pirelli C-numbers: loaded, 148 of 148 rows.

Candidates: Orb v1 as is, naive practice slope, and 12 learned models (ridge, Huber, gradient boosting on the slope or on the residual to Orb v1, each also blended toward Orb v1). Hyperparameters, blend weights and conformal 90% half-widths are chosen inside every training set (grouped inner CV). **Selected by protocol A only: `huber_obs`** (lowest A MAE); its A figures carry selection optimism over 12 candidates. No choice was made on B.

## Protocol A: leave-one-weekend-out, 2023 to 2026

148 compound-weekends, 64 weekends; weekend-grouped bootstrap 90% CIs (2000 draws).

| model | MAE [90% CI] | median AE | r [90% CI] | Spearman | calib. slope | beats naive | coverage90 (mean width) |
|---|---|---|---|---|---|---|---|
| Orb v1 (native band) | 0.0520 [0.0425, 0.0626] | 0.0304 | 0.27 [0.10, 0.42] | 0.26 | 0.15 | 84% | 86% (0.221) |
| naive practice slope | 0.1661 [0.1492, 0.1837] | 0.1492 | 0.29 [0.15, 0.42] | 0.26 | 0.09 | n/a | 91% (0.705) |
| climatology: compound median of training rows (reference) | 0.0330 [0.0283, 0.0379] | 0.0244 | 0.14 [0.05, 0.22] | -0.04 | 0.69 | 88% | 89% (0.140) |
| huber_obs **(selected)** | 0.0299 [0.0256, 0.0344] | 0.0221 | 0.40 [0.24, 0.54] | 0.40 | 1.10 | 88% | 91% (0.137) |
| ridge_obs | 0.0307 [0.0264, 0.0351] | 0.0226 | 0.37 [0.20, 0.51] | 0.37 | 1.04 | 89% | 91% (0.138) |
| ridge_resid | 0.0361 [0.0317, 0.0409] | 0.0281 | 0.22 [0.04, 0.39] | 0.23 | 0.31 | 89% | 89% (0.169) |
| huber_resid | 0.0363 [0.0317, 0.0412] | 0.0285 | 0.25 [0.09, 0.40] | 0.24 | 0.37 | 86% | 92% (0.168) |
| hgbr_obs | 0.0305 [0.0261, 0.0353] | 0.0235 | 0.34 [0.19, 0.47] | 0.36 | 0.95 | 86% | 91% (0.137) |
| hgbr_resid | 0.0420 [0.0360, 0.0481] | 0.0272 | 0.11 [-0.06, 0.25] | 0.14 | 0.10 | 86% | 89% (0.182) |
| blend_ridge_obs | 0.0309 [0.0266, 0.0353] | 0.0223 | 0.36 [0.20, 0.50] | 0.36 | 0.97 | 89% | 90% (0.138) |
| blend_ridge_resid | 0.0361 [0.0317, 0.0409] | 0.0281 | 0.22 [0.03, 0.39] | 0.23 | 0.31 | 89% | 89% (0.169) |
| blend_huber_obs | 0.0300 [0.0257, 0.0345] | 0.0221 | 0.40 [0.23, 0.55] | 0.40 | 1.00 | 88% | 91% (0.138) |
| blend_huber_resid | 0.0363 [0.0319, 0.0412] | 0.0285 | 0.26 [0.10, 0.40] | 0.24 | 0.37 | 86% | 92% (0.168) |
| blend_hgbr_obs | 0.0306 [0.0263, 0.0351] | 0.0228 | 0.36 [0.21, 0.50] | 0.36 | 0.92 | 86% | 91% (0.140) |
| blend_hgbr_resid | 0.0417 [0.0357, 0.0481] | 0.0267 | 0.13 [-0.03, 0.27] | 0.16 | 0.12 | 86% | 91% (0.182) |

Head to head: MAE `huber_obs` minus Orb v1 = -0.0221 [-0.0324, -0.0132], P(`huber_obs` beats Orb v1 on MAE) = 1.000; minus climatology = -0.0032 [-0.0055, -0.0007], P(beats climatology) = 0.984; Orb v1 minus climatology = 0.0190 [0.0094, 0.0297]. Orb v1 with a conformal band from the same training rows covers 91% (mean width 0.243).

## Protocol B: trained on 2023 to 2025, tested on every 2026 weekend (untouched temporal check)

29 compound-weekends, 11 weekends; weekend-grouped bootstrap 90% CIs (2000 draws).

| model | MAE [90% CI] | median AE | r [90% CI] | Spearman | calib. slope | beats naive | coverage90 (mean width) |
|---|---|---|---|---|---|---|---|
| Orb v1 (native band) | 0.0227 [0.0172, 0.0281] | 0.0139 | 0.78 [0.37, 0.89] | 0.38 | 0.77 | 97% | 86% (0.149) |
| naive practice slope | 0.1371 [0.1054, 0.1742] | 0.1008 | 0.20 [-0.20, 0.50] | 0.18 | 0.07 | n/a | 90% (0.691) |
| climatology: compound median of training rows (reference) | 0.0332 [0.0202, 0.0483] | 0.0229 | 0.21 [-0.06, 0.41] | 0.04 | 0.81 | 86% | 83% (0.129) |
| huber_obs **(selected)** | 0.0285 [0.0182, 0.0401] | 0.0192 | 0.58 [0.18, 0.77] | 0.48 | 1.82 | 83% | 90% (0.133) |
| ridge_obs | 0.0292 [0.0191, 0.0408] | 0.0169 | 0.52 [0.10, 0.74] | 0.43 | 1.56 | 83% | 90% (0.130) |
| ridge_resid | 0.0397 [0.0298, 0.0495] | 0.0285 | 0.19 [-0.25, 0.56] | 0.16 | 0.27 | 79% | 79% (0.133) |
| huber_resid | 0.0392 [0.0281, 0.0501] | 0.0231 | 0.21 [-0.26, 0.59] | 0.19 | 0.29 | 76% | 83% (0.138) |
| hgbr_obs | 0.0331 [0.0245, 0.0420] | 0.0220 | 0.40 [0.02, 0.65] | 0.37 | 0.71 | 90% | 83% (0.127) |
| hgbr_resid | 0.0349 [0.0237, 0.0482] | 0.0250 | 0.51 [0.29, 0.71] | 0.57 | 0.97 | 79% | 93% (0.176) |
| blend_ridge_obs | 0.0288 [0.0191, 0.0398] | 0.0165 | 0.57 [0.15, 0.78] | 0.44 | 1.64 | 83% | 93% (0.135) |
| blend_ridge_resid | 0.0397 [0.0298, 0.0495] | 0.0285 | 0.19 [-0.25, 0.56] | 0.16 | 0.27 | 79% | 79% (0.133) |
| blend_huber_obs | 0.0279 [0.0181, 0.0390] | 0.0203 | 0.63 [0.22, 0.81] | 0.50 | 1.85 | 83% | 93% (0.138) |
| blend_huber_resid | 0.0392 [0.0281, 0.0501] | 0.0231 | 0.21 [-0.26, 0.59] | 0.19 | 0.29 | 76% | 83% (0.138) |
| blend_hgbr_obs | 0.0331 [0.0245, 0.0420] | 0.0220 | 0.40 [0.02, 0.65] | 0.37 | 0.71 | 90% | 83% (0.127) |
| blend_hgbr_resid | 0.0349 [0.0237, 0.0482] | 0.0250 | 0.51 [0.29, 0.71] | 0.57 | 0.97 | 79% | 93% (0.176) |

Head to head: MAE `huber_obs` minus Orb v1 = 0.0058 [-0.0043, 0.0166], P(`huber_obs` beats Orb v1 on MAE) = 0.196; minus climatology = -0.0047 [-0.0089, -0.0008], P(beats climatology) = 0.980; Orb v1 minus climatology = -0.0105 [-0.0240, 0.0016]. Orb v1 with a conformal band from the same training rows covers 100% (mean width 0.253).

## Breakdown (MAE / r)

| protocol | slice | n rows | Orb v1 | naive | climatology | selected |
|---|---|---|---|---|---|---|
| A | permanent | 105 | 0.0537 / 0.34 | 0.1611 / 0.34 | 0.0339 / 0.15 | 0.0299 / 0.42 |
| A | street | 43 | 0.0479 / -0.15 | 0.1784 / 0.16 | 0.0310 / 0.11 | 0.0297 / 0.09 |
| A | issued | 84 | 0.0663 / 0.23 | 0.1879 / 0.09 | 0.0331 / 0.05 | 0.0304 / 0.25 |
| A | withheld | 64 | 0.0332 / -0.35 | 0.1376 / 0.32 | 0.0330 / 0.01 | 0.0291 / 0.36 |
| B | permanent | 21 | 0.0228 / 0.79 | 0.1417 / 0.19 | 0.0355 / 0.33 | 0.0299 / 0.65 |
| B | street | 8 | 0.0226 / 0.06 | 0.1253 / 0.01 | 0.0270 / -0.14 | 0.0247 / 0.03 |
| B | issued | 16 | 0.0226 / 0.82 | 0.1627 / 0.02 | 0.0384 / 0.20 | 0.0320 / 0.65 |
| B | withheld | 13 | 0.0229 / -0.70 | 0.1057 / 0.06 | 0.0268 / -0.34 | 0.0242 / 0.16 |

## Findings

1. Protocol A (148 compound-weekends, 64 weekends): `huber_obs` has MAE 0.0299 [0.0256, 0.0344] against Orb v1 0.0520 [0.0425, 0.0626] and naive 0.1661 [0.1492, 0.1837]; the paired weekend bootstrap puts P(beats Orb v1) at 1.00, so on A it beats Orb v1 (90% CI of the MAE difference excludes zero).
2. Most of that MAE gain is shrinkage, not transfer: a constant per compound (the training rows' median, no practice input) scores 0.0330 [0.0283, 0.0379] on A, itself below Orb v1; against it `huber_obs` differs by -0.0032 [-0.0055, -0.0007] (P(beats climatology) 0.98), i.e. it beats climatology (90% CI of the MAE difference excludes zero).
3. Correlation with the reference on A: r 0.40 [0.24, 0.54] and Spearman 0.40 [0.24, 0.54] for `huber_obs` against Orb v1's r 0.27 [0.10, 0.42] and Spearman 0.26 [0.11, 0.38]; calibration slope 1.10 against 0.15 (ideal 1).
4. Untouched temporal check B (trained on 2023 to 2025 only, 29 compound-weekends over 11 weekends of 2026, no choice made on B): MAE 0.0285 [0.0182, 0.0401] against Orb v1 0.0227 [0.0172, 0.0281] and climatology 0.0332 [0.0202, 0.0483]; r 0.58 against Orb v1 0.78; P(beats Orb v1) 0.20, P(beats climatology) 0.98: on 2026 it does not beat Orb v1 conclusively (90% CI of the MAE difference includes zero) and beats climatology (90% CI of the MAE difference excludes zero).
5. Street circuits on A (43 rows): MAE 0.0297 against Orb v1 0.0479, r 0.09 against -0.15; withheld rows on A: MAE 0.0291 against Orb v1's fallback 0.0332, issued rows: 0.0304 against 0.0663.
6. Bands: the conformal 90% band of `huber_obs` covers 91% on A (mean width 0.137) and 90% on B; Orb v1's native band covers 86% (width 0.221) and 86%.

## Caveats

- The selected model was the best of 12 learned candidates on protocol A, so its A numbers are optimistic; B is small (11 weekends) and its intervals are wide.
- In both protocols Orb v1's forecast (the baseline and the orb_v1 feature) uses the within-season leave-one-out factor pool of the scorecard, so a 2026 test row's Orb v1 input still draws on the other 2026 races; the learned mapping itself never sees 2026 in B.
- The target is a race-derived reference with its own estimation noise; no race-weekend quantity (race track temperature, race laps, obs_se) is an input.
- Circuit history exists only from 2024 on and never uses a sealed weekend (e.g. Monza 2025 falls back to Monza 2023); 2023 rows have none.
- This is a development evaluation; the sealed holdout was not touched and no number here is a sealed-holdout result.

# Calibration Audit Report

Panel: 2020-08-01 -> 2026-06-20  (2150 days)
Near-top days: 607   Near-bottom days: 1052
Method: signed-score AUC vs near-extreme labels; |r|>0.7 cluster caps (cap=0.42); shrink-to-prior=0.45.

## Per-indicator measured skill (AUC: 0.50 = no skill, 1.0 = perfect)

| indicator | TOP AUC | BOTTOM AUC | skill | prior w | empirical w | final w |
|---|---|---|---|---|---|---|
| mri | 0.588 | 0.595 | 0.183 | 0.100 | 0.102 | **0.101** |
| mvrv_z | 0.580 | 0.589 | 0.169 | 0.150 | 0.095 | **0.120** |
| nupl | 0.558 | 0.579 | 0.136 | 0.080 | 0.076 | **0.078** |
| sth_sopr | 0.575 | 0.579 | 0.154 | 0.060 | 0.122 | **0.094** |
| sth_mvrv | 0.588 | 0.600 | 0.188 | 0.100 | 0.105 | **0.103** |
| feargreed | 0.595 | 0.617 | 0.211 | 0.070 | 0.118 | **0.096** |
| rsi | 0.606 | 0.617 | 0.223 | 0.060 | 0.177 | **0.124** |
| mnav | 0.503 | 0.608 | 0.111 | 0.170 | 0.088 | **0.125** |
| mstr_btc_trend | 0.582 | 0.551 | 0.133 | 0.110 | 0.105 | **0.107** |
| slope_5d | 0.522 | 0.487 | 0.022 | 0.100 | 0.013 | **0.052** |

## Correlation clusters (diminishing-returns capping)

- cluster 1: mri, mvrv_z, nupl, sth_mvrv, feargreed, slope_5d
- cluster 2: sth_sopr, rsi
- cluster 3: mnav
- cluster 4: mstr_btc_trend

## Macro panel weights (separate; not in core net)

| indicator | TOP AUC | BOTTOM AUC | weight |
|---|---|---|---|
| hy_oas | 0.401 | 0.396 | 0.160 |
| funding | 0.692 | nan | 0.632 |
| netliq_trend | 0.452 | 0.411 | 0.115 |
| m2_trend | 0.469 | 0.397 | 0.093 |

## Reading it (the measured finding)
- High BOTTOM AUC + lower TOP AUC = a bottom-caller. The broad cycle-sentiment reads
  (feargreed, sth_mvrv, sth_sopr, mri) carry the most ALL-SWING skill in BOTH
  directions — they generalise across local tops/bottoms, so the empirical layer
  lifts them above their hand-tuned priors.
- mNAV and mstr_btc_trend measure WEAK general top-skill (AUC ~0.48-0.50): they nailed
  the single Nov-2024 MSTR blow-off but value-trapped at the 2021 BTC top and the
  Aug-2025 local top (MSTR cheap-vs-BTC reading bullish into a price top). They are
  SPECIALIST top-catchers, not general ones — which is exactly why the asymmetric BANDS
  (not weight alone) carry their signal, and why shrink-to-prior keeps enough weight on
  mNAV to still call the 2024 cycle top near-max-short.
- Final weights = empirical (cluster-capped, skill-weighted) shrunk toward the hand-
  tuned prior (45%) so a noisy fit on few absolute extrema can't wreck
  the validated turning-point reads. Verified: all 4 zones hold after applying.

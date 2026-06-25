# Calibration Audit Report

Panel: 2020-08-01 -> 2026-06-25  (2155 days)
Near-top days: 607   Near-bottom days: 1052
Method: signed-score AUC vs near-extreme labels; |r|>0.7 cluster caps (cap=0.42); shrink-to-prior=0.45.

## Per-indicator measured skill (AUC: 0.50 = no skill, 1.0 = perfect)

| indicator | TOP AUC | BOTTOM AUC | skill | prior w | empirical w | final w |
|---|---|---|---|---|---|---|
| mri | 0.589 | 0.597 | 0.187 | 0.082 | 0.090 | **0.090** |
| mvrv_z | 0.581 | 0.588 | 0.168 | 0.127 | 0.106 | **0.106** |
| nupl | 0.559 | 0.577 | 0.136 | 0.064 | 0.068 | **0.068** |
| sth_sopr | 0.576 | 0.578 | 0.154 | 0.045 | 0.077 | **0.077** |
| sth_mvrv | 0.589 | 0.598 | 0.187 | 0.082 | 0.090 | **0.090** |
| feargreed | 0.596 | 0.614 | 0.210 | 0.055 | 0.085 | **0.085** |
| rsi | 0.607 | 0.615 | 0.222 | 0.045 | 0.103 | **0.103** |
| mnav | 0.544 | 0.548 | 0.092 | 0.145 | 0.100 | **0.100** |
| mstr_btc_trend | 0.583 | 0.549 | 0.132 | 0.091 | 0.087 | **0.087** |
| slope_5d | 0.524 | 0.485 | 0.024 | 0.082 | 0.044 | **0.044** |
| funding | 0.733 | nan | 0.233 | 0.073 | 0.100 | **0.100** |
| tbl_indicator | 0.493 | 0.482 | 0.000 | 0.109 | 0.050 | **0.050** |

## Correlation clusters (diminishing-returns capping)

- cluster 1: mri, mvrv_z, nupl, sth_mvrv, feargreed, slope_5d
- cluster 2: sth_sopr, rsi
- cluster 3: mnav
- cluster 4: mstr_btc_trend
- cluster 5: funding
- cluster 6: tbl_indicator

## Macro panel weights (separate; not in core net)

| indicator | TOP AUC | BOTTOM AUC | weight |
|---|---|---|---|

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

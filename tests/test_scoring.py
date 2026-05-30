"""Unit tests for scoring functions. Must pass before dashboard goes live."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from scoring import (
    score_mvrv_z, score_nupl, score_lth_trend, score_sopr,
    score_m2_trend, score_netliq_trend, score_dxy_trend,
    score_hy_oas, score_real_yield,
    score_mnav, score_mstr_btc_trend,
    score_funding, score_ssr,
    compute_composite, WEIGHTS, regime_label,
)


# ---- MVRV-Z ----
def test_mvrv_z_deep_value():
    assert score_mvrv_z(-1.5) == 100
def test_mvrv_z_accum():
    assert score_mvrv_z(1.0) == 85
    assert score_mvrv_z(0.0) == 85  # 0 -> not <0, falls into 0-2 band
def test_mvrv_z_belief():
    assert score_mvrv_z(3.0) == 60
def test_mvrv_z_optimism():
    assert score_mvrv_z(5.0) == 30
def test_mvrv_z_euphoria():
    assert score_mvrv_z(6.5) == 10
def test_mvrv_z_top():
    assert score_mvrv_z(8.0) == 0
def test_mvrv_z_none():
    assert score_mvrv_z(None) is None


# ---- NUPL ----
def test_nupl_capitulation():
    assert score_nupl(-0.1) == 100
def test_nupl_hope():
    assert score_nupl(0.15) == 85
def test_nupl_optimism():
    assert score_nupl(0.4) == 65
def test_nupl_belief():
    assert score_nupl(0.6) == 35
def test_nupl_euphoria():
    assert score_nupl(0.9) == 5


# ---- LTH trend (Liveliness 90d Δ%, INVERTED) ----
# Falling liveliness = LTHs accumulating = bullish (high score)
def test_lth_trend_strong_accumulation():
    # Liveliness dropping fast → LTHs accumulating
    assert score_lth_trend(-7.0) == 100
def test_lth_trend_accumulation():
    assert score_lth_trend(-2.0) == 75
def test_lth_trend_flat():
    assert score_lth_trend(0) == 50
def test_lth_trend_distribution():
    assert score_lth_trend(2.0) == 25
def test_lth_trend_heavy_distribution():
    # Liveliness rising fast → LTHs distributing
    assert score_lth_trend(7.0) == 5


# ---- SOPR ----
def test_sopr_capitulation():
    assert score_sopr(0.95) == 100
def test_sopr_reclaim():
    assert score_sopr(0.99) == 80
def test_sopr_realization():
    assert score_sopr(1.01) == 55
def test_sopr_heavy_profit_taking():
    assert score_sopr(1.04) == 25
def test_sopr_euphoria():
    assert score_sopr(1.08) == 5


# ---- M2 trend ----
def test_m2_trend_strong_expansion():
    assert score_m2_trend(3.0) == 100
def test_m2_trend_mid_expansion():
    assert score_m2_trend(1.5) == 75
def test_m2_trend_slow_expansion():
    assert score_m2_trend(0.5) == 55
def test_m2_trend_mild_contraction():
    assert score_m2_trend(-0.5) == 35
def test_m2_trend_real_contraction():
    assert score_m2_trend(-2.0) == 0


# ---- Net Liquidity trend ----
def test_netliq_trend_strong():
    assert score_netliq_trend(3.0) == 100
def test_netliq_trend_expanding():
    assert score_netliq_trend(1.0) == 70
def test_netliq_trend_contracting():
    assert score_netliq_trend(-1.0) == 40
def test_netliq_trend_heavy_contraction():
    assert score_netliq_trend(-3.0) == 10


# ---- DXY trend (inverse) ----
def test_dxy_falling_hard():
    assert score_dxy_trend(-5.0) == 100  # bullish for BTC
def test_dxy_falling():
    assert score_dxy_trend(-1.0) == 70
def test_dxy_rising():
    assert score_dxy_trend(1.5) == 40
def test_dxy_squeezing():
    assert score_dxy_trend(5.0) == 10


# ---- HY OAS ----
def test_hy_oas_very_tight():
    assert score_hy_oas(2.0) == 90
def test_hy_oas_tight():
    assert score_hy_oas(3.5) == 70
def test_hy_oas_widening():
    assert score_hy_oas(4.5) == 45
def test_hy_oas_stressed():
    assert score_hy_oas(5.5) == 20
def test_hy_oas_crisis():
    assert score_hy_oas(8.0) == 0


# ---- Real yield ----
def test_real_yield_negative():
    assert score_real_yield(-0.5) == 100
def test_real_yield_low_positive():
    assert score_real_yield(0.5) == 80
def test_real_yield_neutral():
    assert score_real_yield(1.5) == 55
def test_real_yield_restrictive():
    assert score_real_yield(2.25) == 30
def test_real_yield_very_restrictive():
    assert score_real_yield(3.0) == 10


# ---- mNAV ----
def test_mnav_structural_cheap():
    assert score_mnav(0.9) == 100
def test_mnav_compressed():
    assert score_mnav(1.2) == 85
def test_mnav_fair():
    assert score_mnav(1.5) == 60
def test_mnav_premium():
    assert score_mnav(2.0) == 35
def test_mnav_high_premium():
    assert score_mnav(2.4) == 15
def test_mnav_top():
    assert score_mnav(3.0) == 0


# ---- MSTR/BTC trend (inverse) ----
def test_mstr_btc_compressing():
    assert score_mstr_btc_trend(-15) == 90
def test_mstr_btc_mild_compression():
    assert score_mstr_btc_trend(-5) == 65
def test_mstr_btc_expansion():
    assert score_mstr_btc_trend(5) == 40
def test_mstr_btc_blowoff():
    assert score_mstr_btc_trend(15) == 15


# ---- Funding ----
def test_funding_negative():
    assert score_funding(-2.0) == 100
def test_funding_neutral_low():
    assert score_funding(2.0) == 80
def test_funding_normal():
    assert score_funding(10.0) == 55
def test_funding_heated():
    assert score_funding(20.0) == 25
def test_funding_extreme():
    assert score_funding(50.0) == 5


# ---- SSR ----
def test_ssr_dry_powder():
    assert score_ssr(3) == 100
def test_ssr_balanced():
    assert score_ssr(8) == 75
def test_ssr_btc_heavy():
    assert score_ssr(15) == 45
def test_ssr_no_powder():
    assert score_ssr(25) == 15


# ---- Composite ----
def test_composite_all_max():
    raw = {k: None for k in WEIGHTS}
    # Set every indicator to its max-bullish raw value
    raw.update({
        "mvrv_z": -1, "nupl": -0.1, "lth_trend": -7, "sopr": 0.95,
        "m2_trend": 3, "netliq_trend": 3, "dxy_trend": -5,
        "hy_oas": 2, "real_yield": -0.5,
        "mnav": 0.9, "mstr_btc_trend": -15,
        "funding": -1, "ssr": 3,
    })
    res = compute_composite(raw)
    # HY OAS only gives 90 not 100, real_yield gives 100, etc. Compute expected.
    expected = (
        0.15*100 + 0.10*100 + 0.05*100 + 0.05*100 +     # cycle = 35
        0.15*100 + 0.10*100 + 0.05*100 +                # macro = 30
        0.10*90 + 0.05*100 +                            # risk = 14
        0.10*100 + 0.05*90 +                            # mstr = 14.5
        0.03*100 + 0.02*100                             # tactical = 5
    )
    # = 35 + 30 + 14 + 14.5 + 5 = 98.5
    assert abs(res["composite"] - 98.5) < 0.5
    assert res["missing"] == []

def test_composite_all_min():
    raw = {
        "mvrv_z": 8, "nupl": 0.9, "lth_trend": 7, "sopr": 1.1,
        "m2_trend": -3, "netliq_trend": -5, "dxy_trend": 5,
        "hy_oas": 8, "real_yield": 3,
        "mnav": 3, "mstr_btc_trend": 20,
        "funding": 60, "ssr": 30,
    }
    res = compute_composite(raw)
    # Compute expected min weighted sum
    expected = (
        0.15*0 + 0.10*5 + 0.05*5 + 0.05*5 +
        0.15*0 + 0.10*10 + 0.05*10 +
        0.10*0 + 0.05*10 +
        0.10*0 + 0.05*15 +
        0.03*5 + 0.02*15
    )
    # = 0 + 0.5 + 0.5 + 0.25 + 0 + 1.0 + 0.5 + 0 + 0.5 + 0 + 0.75 + 0.15 + 0.30 = 4.45
    assert abs(res["composite"] - expected) < 0.5

def test_composite_missing_reweights():
    """If LTH is missing, its weight redistributes proportionally."""
    raw = {
        "mvrv_z": -1, "nupl": -0.1, "lth_trend": None, "sopr": 0.95,
        "m2_trend": 3, "netliq_trend": 3, "dxy_trend": -5,
        "hy_oas": 2, "real_yield": -0.5,
        "mnav": 0.9, "mstr_btc_trend": -15,
        "funding": -1, "ssr": 3,
    }
    res = compute_composite(raw)
    assert "lth_trend" in res["missing"]
    # Without LTH, available_weight = 0.95. Composite should still be near max (~98.5).
    assert res["composite"] > 95

def test_composite_all_missing():
    raw = {k: None for k in WEIGHTS}
    res = compute_composite(raw)
    assert res["composite"] is None
    assert len(res["missing"]) == 13


# ---- Regime labels ----
def test_regime_labels():
    assert "STRONG BULL" in regime_label(85)
    assert "BULL" in regime_label(65)
    assert "NEUTRAL" in regime_label(50)
    assert "RISK-OFF" in regime_label(30)
    assert "MAX RISK" in regime_label(10)
    assert "UNKNOWN" in regime_label(None)


# ---- Weights sanity ----
def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-6

"""Unit tests for the signed net-conviction scoring engine. Must pass before deploy.

The old composite/score_* API was retired (V2_HANDOFF Phase 5). These cover the current
engine: signed per-indicator bands, compute_meters (core net + separate macro), the 5-way
net_zone thresholds, missing-data reweighting, and calibration-config loading.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scoring
from scoring import indicator_score, compute_meters, net_zone, macro_label


# ---- signed per-indicator bands: bottoms positive, tops negative, mid ~0 ----
def test_signed_orientation_mvrv_z():
    assert indicator_score("mvrv_z", -0.5) == 100      # deep value bottom
    assert indicator_score("mvrv_z", 3.5) <= -80        # cycle-top zone strongly short
    assert indicator_score("mvrv_z", None) is None

def test_signed_orientation_mnav():
    assert indicator_score("mnav", 0.8) == 100          # real discount = max long
    assert indicator_score("mnav", 1.15) <= 30          # mild premium != strong long
    assert indicator_score("mnav", 2.8) <= -85          # blow-off premium = max short

def test_rsi_band():
    assert indicator_score("rsi", 18) >= 85             # deep oversold = long
    assert indicator_score("rsi", 50) == 0              # neutral mid
    assert indicator_score("rsi", 78) <= -60            # overbought = short

def test_scores_are_bounded():
    for k in scoring.SPECS:
        for v in (-5, 0, 0.5, 1, 12, 50, 100, 1000):
            s = indicator_score(k, v)
            assert s is None or (-100 <= s <= 100)


# ---- net_zone: 5-way thresholds, extremes saturate to cycle labels ----
def test_net_zone_labels():
    assert net_zone(80)[1] == "LONG-CAPITULATION"
    assert net_zone(40)[1] == "LONG-LOCAL"
    assert net_zone(0)[1] == "NEUTRAL"
    assert net_zone(-40)[1] == "SHORT-LOCAL"
    assert net_zone(-80)[1] == "SHORT-TOP"
    assert net_zone(None)[1] == "UNKNOWN"

def test_net_zone_boundaries():
    assert net_zone(65)[0] == "LONG"
    assert net_zone(64.9)[1] == "LONG-LOCAL"
    assert net_zone(-65)[0] == "SHORT"
    assert net_zone(-64.9)[1] == "SHORT-LOCAL"

def test_net_zone_confidence_is_magnitude():
    assert net_zone(77)[2] == 77
    assert net_zone(-77)[2] == 77
    assert net_zone(150)[2] == 100        # clamped


# ---- compute_meters: core net excludes macro; macro reported separately ----
def test_compute_meters_core_vs_macro():
    raw = {"mvrv_z": -0.5, "mnav": 0.8, "feargreed": 20, "rsi": 20,   # core, max long
           "hy_oas": 2.0, "funding": -1.0}                            # macro
    m = compute_meters(raw)
    assert m["net_conviction"] is not None and m["net_conviction"] > 60
    assert m["zone"] == "LONG"
    # macro keys must NOT leak into the core contributions
    assert "hy_oas" not in m["contributions"]
    assert "funding" not in m["contributions"]
    assert "hy_oas" in m["macro_contributions"]
    assert m["macro_score"] is not None

def test_compute_meters_top_reads_short():
    raw = {"mvrv_z": 3.5, "mnav": 2.8, "feargreed": 85, "rsi": 80, "nupl": 0.72}
    m = compute_meters(raw)
    assert m["net_conviction"] < -50
    assert m["zone"] == "SHORT"
    assert m["read"] in ("SHORT-LOCAL", "SHORT-TOP")

def test_compute_meters_all_missing():
    m = compute_meters({k: None for k in scoring.SPECS})
    assert m["net_conviction"] is None
    assert m["zone"] == "UNKNOWN"

def test_compute_meters_reweights_on_missing():
    """Net is a weight-normalized mean over AVAILABLE indicators — dropping some still
    yields a valid score (no blanks), and the denominator only counts what's present."""
    full = compute_meters({"mvrv_z": -0.5, "mnav": 0.8, "feargreed": 20, "rsi": 20})
    partial = compute_meters({"mvrv_z": -0.5, "mnav": 0.8})  # two missing
    assert full["net_conviction"] is not None
    assert partial["net_conviction"] is not None
    # both should still read strongly long (all inputs are long-leaning)
    assert partial["net_conviction"] > 50

def test_bull_bear_split():
    m = compute_meters({"mvrv_z": -0.5, "mnav": 2.8})  # one long, one short core
    assert m["bull_sum"] >= 0
    assert m["bear_sum"] <= 0


# ---- macro_label thresholds ----
def test_macro_label():
    assert macro_label(40) == "Tailwind"
    assert macro_label(0) == "Neutral"
    assert macro_label(-40) == "Headwind"
    assert macro_label(None) == "—"


# ---- calibration-config loading (the empirical override layer) ----
def test_calibration_config_loads_and_applies():
    cfg = scoring._load_calibration()
    if cfg is None:
        return  # config optional; seed weights used when absent
    assert "core_w" in cfg and isinstance(cfg["core_w"], dict)
    # whatever core_w the config defines, compute_meters must use it without error
    m = compute_meters({"mvrv_z": -0.5, "mnav": 0.8, "rsi": 20})
    assert m["net_conviction"] is not None

def test_effective_specs_has_all_core_indicators():
    specs = scoring._effective_specs()
    for k in ("mri", "mvrv_z", "nupl", "sth_sopr", "sth_mvrv", "feargreed", "rsi",
              "mnav", "slope_5d", "mstr_btc_trend"):
        assert k in specs and "band" in specs[k]

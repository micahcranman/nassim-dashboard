"""Scoring engine — single SIGNED directional score per indicator.

Each indicator maps to one score in [-100, +100]:
    +100 = maximally bullish  (capitulation / bottom → accumulate / go long)
       0 = neutral mid-cycle  (no edge)
    -100 = maximally bearish  (euphoria / top → distribute / hedge / short)

This replaces the old long/short pair (which double-counted and biased everything long).
Mid-cycle now reads ~0, tops read negative, bottoms read positive — so the oscillator
actually flags shorts at transitions and tops.

Asymmetry (per Micah: "MRI calls bottoms well, tops poorly") lives in the BAND SHAPE:
an indicator that's a weak top-caller only reaches a shallow negative (e.g. MRI floors
near -45, not -100). Each indicator has ONE weight = its overall importance.

net_conviction = Σ(weight·score) / Σ(weight over available indicators), range [-100,+100].
Zones: > +LONG_ZONE → LONG, < -SHORT_ZONE → SHORT, else NEUTRAL.

`calibration_config.json` (from scripts/calibrate_weights.py) overrides weights and/or
bands when present — that's the empirical tuning layer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Dict, Any

_CONFIG_PATH = Path(__file__).resolve().parent / "calibration_config.json"

LONG_ZONE = 25.0
SHORT_ZONE = 25.0  # symmetric: net < -25 = short


def _signed(value: float, bands) -> float:
    """bands: ascending list of (upper_exclusive, score); last upper = inf. Returns the
    score of the first band whose upper bound exceeds value."""
    for upper, score in bands:
        if value < upper:
            return float(score)
    return float(bands[-1][1])


# Signed bands: + bullish/bottom, - bearish/top. Centered so mid-cycle ≈ 0.
#
# WEIGHTS use diminishing-returns clustering (per Micah): correlated signals share a
# capped budget instead of each getting full weight. The BTC-cycle cluster (MRI/MVRV/
# NUPL/STH-SOPR/STH-MVRV/F&G) is ~6 collinear reads of the same thing → collectively
# capped, so it can't bully the score bullish whenever BTC merely isn't at a CYCLE top.
# The MSTR-specific + structural cluster (mNAV/slope/MSTR-BTC) is boosted because THAT's
# what called the Nov-2025 MSTR top. Three budgets: cycle ≈0.36, MSTR-structural ≈0.42,
# macro ≈0.22. (calibrate_weights.py will replace these empirically.)
#
SPECS: Dict[str, Dict[str, Any]] = {
    # --- BTC cycle cluster ---
    "mri": {  # <12 Q-fire. Strong bottom-caller, WEAK top-caller (floors at -50).
        "band": [(12, 100), (20, 82), (30, 55), (45, 28), (65, 0), (80, -22), (92, -38), (float("inf"), -50)],
        "w": 0.11,
    },
    "mvrv_z": {  # recent-cycle TOPS sit at z≈3-3.5 (not 7 like 2017) → band steepened so the
                 # top zone reads strongly negative instead of a lukewarm -35.
        "band": [(0, 100), (0.5, 85), (1, 60), (1.8, 25), (2.3, -20), (2.8, -50), (3.2, -72), (3.8, -90), (float("inf"), -100)],
        "w": 0.16,
    },
    "nupl": {  # >0.65 = top-of-cycle greed; <0.25 = capitulation
        "band": [(0, 100), (0.2, 70), (0.35, 40), (0.5, 5), (0.58, -25), (0.65, -55), (0.72, -78), (float("inf"), -95)],
        "w": 0.09,
    },
    "sth_sopr": {
        "band": [(0.97, 90), (1.0, 45), (1.02, 0), (1.04, -35), (1.06, -70), (float("inf"), -95)],
        "w": 0.06,
    },
    "sth_mvrv": {  # cohort: <1 tourists underwater (bottom); >1.3 piling in (top)
        "band": [(0.9, 100), (1.0, 65), (1.1, 25), (1.25, 0), (1.4, -35), (1.6, -65), (float("inf"), -90)],
        "w": 0.10,
    },
    "feargreed": {  # fear reliable at bottoms; greed slightly less so at tops (floors at -75)
        "band": [(25, 92), (40, 55), (50, 18), (58, 0), (70, -32), (82, -58), (float("inf"), -75)],
        "w": 0.07,
    },
    "rsi": {  # BTC RSI-14 momentum. Oversold (<30) = capitulation long; overbought (>70) =
              # blow-off short; mid (45-55) ≈ 0. A fast transition read the slow value metrics lag.
        "band": [(20, 90), (30, 62), (40, 32), (47, 12), (53, 0), (60, -12), (70, -35), (80, -65), (float("inf"), -88)],
        "w": 0.07,
    },
    # --- MSTR-specific + structural cluster (the MSTR-top catcher) ---
    "mnav": {  # MUST require a real DISCOUNT (<1.0) for max-long. A 1.0-1.3x PREMIUM is NOT
               # cheap → near-zero (was +30, a false long-lean that dragged the Nov-2021 BTC top
               # up to only -34 and the Aug-2025 top to neutral); >2.3 blowoff = max short.
        "band": [(0.85, 100), (1.0, 80), (1.1, 30), (1.25, 5), (1.5, -12), (1.9, -42), (2.3, -72), (2.7, -90), (float("inf"), -100)],
        "w": 0.18,
    },
    "slope_5d": {  # MA200 5d slope %. CONTRARIAN-on-magnitude: a steep + slope = blowoff /
                   # exhaustion (short), a steep - slope = capitulation (long), flat ≈ 0. The old
                   # band was PROCYCLICAL (+slope→+score) and actively fought every top — it read
                   # +70 at the Nov-2024 cycle top. (Its v8.5 hedge-gate role lives in strategy_state.)
        "band": [(-5, 88), (-3, 60), (-1.5, 30), (-0.6, 10), (0.6, -8), (1.5, -28), (3, -52), (5, -75), (float("inf"), -90)],
        "w": 0.11,
    },
    "mstr_btc_trend": {  # 50d %: a BLOWOFF vs BTC (Nov-2024 +48%) = top; mild MSTR underperformance
                         # is NOT a bottom — it value-trapped long into the 2021 & Aug-2025 tops. Only
                         # DEEP underperformance (<-30%) earns real long; mild (-3..-20%) reads ~0.
        "band": [(-35, 50), (-20, 22), (-8, 5), (-3, 0), (5, -18), (15, -55), (25, -80), (float("inf"), -100)],
        "w": 0.12,
    },
    # --- macro cluster (total ≈ 0.22) ---
    "hy_oas": {  # tight = risk-on; widening = risk-off
        "band": [(3, 55), (4, 15), (4.5, 0), (5, -35), (6, -70), (float("inf"), -95)],
        "w": 0.06,
    },
    "funding": {  # cool/neg clean-long; hot = squeeze risk
        "band": [(0, 40), (5, 15), (15, -10), (30, -45), (50, -75), (float("inf"), -95)],
        "w": 0.06,
    },
    "netliq_trend": {
        "band": [(-3, -50), (-1, -25), (0, 0), (2, 30), (float("inf"), 55)],
        "w": 0.05,
    },
    "m2_trend": {
        "band": [(-1, -40), (0, -15), (1, 10), (2, 30), (float("inf"), 50)],
        "w": 0.05,
    },
    "tbl": {  # The Bitcoin Layer AI liquidity supertrend. Expanding liquidity = risk-on
              # (long-supportive, +), contracting = risk-off (short, -). PROVISIONAL band:
              # the live value's exact scale is confirmed once the TBL payload is captured in
              # CI; until then tbl carries 0 macro weight (calibration_config.macro_w omits it),
              # so a mis-scale can't move the panel. Symmetric around 0.
        "band": [(-2, -70), (-1, -35), (-0.25, -10), (0.25, 0), (1, 20), (2, 45), (float("inf"), 70)],
        "w": 0.0,
    },
}


# Macro is pulled OUT of the core conviction (it adds noise per Micah) and reported as a
# separate score. TBL liquidity will join this group later.
MACRO_KEYS = {"m2_trend", "netliq_trend", "hy_oas", "funding", "tbl"}

# CORE weights — concentrated on the TOP-CALLERS (mnav / mvrv_z / mstr_btc_trend / slope_5d
# / sth_mvrv = 0.70 combined) so that when several max out together at a CYCLE top the net
# saturates toward -100, while a lone signal firing (local top) lands ~-40/-60. That's what
# separates cycle extremes from local extremes.
CORE_W = {
    "mnav": 0.17, "mvrv_z": 0.15, "mstr_btc_trend": 0.11, "slope_5d": 0.10, "sth_mvrv": 0.10,
    "mri": 0.10, "nupl": 0.08, "sth_sopr": 0.06, "feargreed": 0.07, "rsi": 0.06,
}
# Macro sub-score weights (relative, within the macro panel only).
# tbl default 0 until its live scale is confirmed and calibrate_weights can measure its skill.
MACRO_W = {"hy_oas": 0.35, "netliq_trend": 0.25, "funding": 0.20, "m2_trend": 0.20, "tbl": 0.0}


def export_config() -> dict:
    """The EFFECTIVE scoring config (signed bands + dynamic weights + zone thresholds) so the
    frontend can recompute the conviction + drivers for ANY historical date (the scrubber).
    inf upper-bounds serialize to null (= +Infinity on the JS side)."""
    specs = _effective_specs()
    cal = _load_calibration() or {}
    bands = {}
    for k, v in specs.items():
        bands[k] = [[(None if u == float("inf") else u), sc] for (u, sc) in v["band"]]
    return {
        "bands": bands,
        "core_w": cal.get("core_w", CORE_W),
        "macro_w": cal.get("macro_w", MACRO_W),
        "macro_keys": sorted(MACRO_KEYS),
        "zones": {"long_cap": 65, "long_local": 28, "short_local": -28, "short_top": -65},
    }


def _load_calibration() -> Optional[dict]:
    if not _CONFIG_PATH.exists():
        return None
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except Exception:
        return None


def _effective_specs() -> Dict[str, Dict[str, Any]]:
    cal = _load_calibration()
    if not cal:
        return SPECS
    specs = {k: dict(v) for k, v in SPECS.items()}
    for key, ov in (cal.get("indicators") or {}).items():
        if key not in specs:
            specs[key] = {"band": ov.get("band", [(float("inf"), 0)]), "w": ov.get("w", 0.0)}
            continue
        if "w" in ov:
            specs[key]["w"] = ov["w"]
        if "band" in ov:
            specs[key]["band"] = ov["band"]
    return specs


def indicator_score(key: str, value: Optional[float], specs=None) -> Optional[float]:
    """Signed score in [-100,100] for one indicator, or None if unavailable."""
    if value is None:
        return None
    specs = specs or _effective_specs()
    spec = specs.get(key)
    if not spec:
        return None
    return _signed(value, spec["band"])


def compute_meters(raw: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """raw: indicator -> value. Core net conviction (macro excluded) + a SEPARATE macro score."""
    specs = _effective_specs()
    cal = _load_calibration() or {}
    core_w = cal.get("core_w", CORE_W)
    macro_w = cal.get("macro_w", MACRO_W)
    num = den = mnum = mden = 0.0
    contributions, macro_contrib = {}, {}
    for key in specs:
        sc = indicator_score(key, raw.get(key), specs)
        if sc is None:
            continue
        rec = lambda w: {"value": raw.get(key), "score": round(sc, 1), "weight": w, "contrib": round(w * sc, 2)}
        if key in MACRO_KEYS:
            w = macro_w.get(key, 0.0)
            mnum += w * sc; mden += w; macro_contrib[key] = rec(w)
        else:
            w = core_w.get(key, 0.0)
            num += w * sc; den += w; contributions[key] = rec(w)
    net = round(num / den, 1) if den else None
    macro_score = round(mnum / mden, 1) if mden else None
    zone, label, confidence = net_zone(net)
    bull = round(sum(c["contrib"] for c in contributions.values() if c["contrib"] > 0), 1)
    bear = round(sum(c["contrib"] for c in contributions.values() if c["contrib"] < 0), 1)
    return {
        "net_conviction": net, "zone": zone, "label": label, "read": label, "confidence": confidence,
        "macro_score": macro_score, "macro_label": macro_label(macro_score),
        "macro_contributions": macro_contrib,
        "bull_sum": bull, "bear_sum": bear,
        "contributions": contributions, "available": sorted(contributions.keys()),
    }


# 5-way zone thresholds: extremes saturate to the CYCLE labels so absolute tops/bottoms jump out.
def net_zone(net: Optional[float]):
    """(zone, 5-way label, confidence%)."""
    if net is None:
        return "UNKNOWN", "UNKNOWN", None
    a = round(min(100.0, abs(net)))
    if net >= 65:
        return "LONG", "LONG-CAPITULATION", a
    if net >= 28:
        return "LONG", "LONG-LOCAL", a
    if net > -28:
        return "NEUTRAL", "NEUTRAL", round(abs(net))
    if net > -65:
        return "SHORT", "SHORT-LOCAL", a
    return "SHORT", "SHORT-TOP", a


def verdict(net: Optional[float]) -> str:
    return net_zone(net)[1]


def macro_label(s: Optional[float]) -> str:
    if s is None:
        return "—"
    if s >= 30:
        return "Tailwind"
    if s > -30:
        return "Neutral"
    return "Headwind"


def zone_color(zone: str) -> str:
    return {"LONG": "#16c784", "SHORT": "#ea3943", "NEUTRAL": "#f3c623"}.get(zone, "#8a93a6")


# ---- legacy labels kept for any older consumer ----
def regime_label(score):
    z, r, _ = net_zone(score)
    return z


def regime_color(score):
    z, _, _ = net_zone(score)
    return zone_color(z)

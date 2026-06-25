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
    """STEP form (current model): bands = ascending (upper_exclusive, score); last upper = inf.
    Returns the score of the first band whose upper bound exceeds value."""
    for upper, score in bands:
        if value < upper:
            return float(score)
    return float(bands[-1][1])


def _curve(value: float, bands) -> float:
    """CURVE form (v2 model): piecewise-LINEAR interpolation through the SAME band anchors — no
    artificial cliffs, smooth + monotonic. Flat below the first threshold (at its score) and flat
    above the last (at the inf score); the inf score is reached one step-width past the last finite
    threshold so the tail ramps in rather than jumping."""
    fin = [(t, s) for (t, s) in bands if t != float("inf")]
    if not fin:
        return float(bands[-1][1])
    xs = [t for t, _ in fin]
    ys = [s for _, s in fin]
    tail = float(bands[-1][1])
    if len(xs) >= 2 and tail != ys[-1]:           # ramp into the inf-score tail
        xs = xs + [xs[-1] + (xs[-1] - xs[-2])]
        ys = ys + [tail]
    if value <= xs[0]:
        return float(ys[0])
    if value >= xs[-1]:
        return float(ys[-1])
    for i in range(1, len(xs)):
        if value <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            return float(y0 + (value - x0) / (x1 - x0) * (y1 - y0))
    return float(ys[-1])


# mNAV non-linear TOP amplifier (v2 model only). At a CYCLE top mNAV's lone -100 gets diluted
# in the weighted average by the slow BTC-cycle metrics that read only mildly negative — so the
# net "barely" crosses the cycle-top line (per Micah). This boosts mNAV's EFFECTIVE weight
# super-linearly as the premium climbs into the blow-off zone ("exponentially more impact in the
# ~2.5-3.4x range"), so a stretched premium DOMINATES the read instead of being averaged away.
# A value-gated multiplier: 1.0 below v_lo, 1+amp at/above v_hi, convex (gamma>1) ramp between
# so most of the boost lands in the upper zone. TOP-side only (score<0); bottoms are untouched.
MNAV_TOP_GAIN = {"v_lo": 1.8, "v_hi": 3.4, "amp": 3.0, "gamma": 1.7}


def _mnav_top_gain(value) -> float:
    g = MNAV_TOP_GAIN
    if value is None:
        return 1.0
    t = max(0.0, min(1.0, (value - g["v_lo"]) / (g["v_hi"] - g["v_lo"])))
    return 1.0 + g["amp"] * (t ** g["gamma"])


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
    "mri": {  # <12 is the Q-fire THRESHOLD, not max capitulation — true capitulation is the ~1st
              # pctile (MRI ~3-7). So +100 now requires MRI<7 (deep); at the 12 threshold it reads
              # +84 (strong long, not saturated) so it doesn't overstate a borderline reading.
        "band": [(7, 100), (12, 84), (18, 62), (28, 40), (45, 15), (60, -10), (75, -32), (90, -45), (float("inf"), -52)],
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
    # --- positioning + liquidity momentum (moved INTO core per Micah; the old macro bucket —
    #     hy_oas / netliq_trend / m2_trend / TBL-score — is RETIRED. Net liquidity decayed to
    #     noise post-ETF; TBL's liquidity LEVEL lives in its own section, not the conviction.) ---
    "funding": {  # contrarian froth/positioning: deeply negative = capitulation (long), hot
                  # perps = crowded longs / squeeze risk (short). A fast coincident contrarian.
        "band": [(-20, 90), (-5, 55), (0, 40), (5, 15), (15, -10), (30, -45), (50, -75), (float("inf"), -95)],
        "w": 0.08,
    },
    "tbl_indicator": {  # TBL Liquidity Indicator = slope of the liquidity cycle (±0.26). Measured
                        # skill (per swing size): it calls LOCAL TOPS well (AUC ~0.59 as swings get
                        # smaller) but its local-BOTTOM signal is weak/INVERTED (liquidity momentum
                        # lags at price bottoms, since it leads). So the band is LOCAL-CAPPED (never
                        # alone reaches a CYCLE extreme ±65) and ASYMMETRIC: trust the negative/
                        # local-top side (down to -48), dampen the positive/local-bottom side (+35 cap).
        "band": [(-0.13, -48), (-0.06, -34), (-0.02, -14), (0.02, 0), (0.06, 14), (0.13, 28), (float("inf"), 35)],
        "w": 0.10,
    },
}


# The separate macro bucket is RETIRED (per Micah: ditch all macro signals except TBL; funding
# moves into core; TBL's liquidity LEVEL gets its own section). Everything scored is now core.
MACRO_KEYS: set = set()

# CORE weights — top-callers (mnav / mvrv_z / mstr_btc_trend / sth_mvrv) concentrated so several
# maxing together at a CYCLE top saturate the net toward -100 vs a lone local-top signal at
# ~-40/-60. funding (contrarian) + tbl_indicator (liquidity momentum) join core.
# slope_5d is DROPPED from the conviction entirely (per Micah) — it's wrong both directions as a
# timer and adds noise; it survives only as the v8.5 hedge GATE in strategy_state (derived).
CORE_W = {
    "mnav": 0.16, "mvrv_z": 0.14, "mstr_btc_trend": 0.10, "sth_mvrv": 0.09,
    "mri": 0.09, "nupl": 0.07, "sth_sopr": 0.05, "feargreed": 0.06, "rsi": 0.05,
    "funding": 0.08, "tbl_indicator": 0.12,
}
MACRO_W: dict = {}

# ---- v2 model: DIRECTIONAL JUDGMENT weights (NOT AUC-fit). Set from each indicator's MSTR-
# specific relevance + demonstrated reliability at the real cycle turns (conditional forward
# MSTR move), accepting we can't statistically fit 2-3 cycle tops. Paired with CURVE scoring.
#   - mNAV is the heaviest TOP weight: it's the cleanest MSTR-specific over-valuation read
#     (premium to the BTC it holds; 3.4 marked both cycle tops). RSI/STH-SOPR are bottom
#     specialists (oversold/capitulation → reliable bounce, useless at tops). MA200 slope is a
#     gate, near-zero. mstr_btc_trend is MSTR-euphoria, top-only.  (each side sums to ~1.0)
#   slope_5d is DROPPED entirely (per Micah) — see CORE_W note. Weights below no longer sum to
#   exactly 1.0 (slope's old 0.02 removed); harmless since net = Σw·s / Σw is a weighted average.
#   The mNAV TOP side is further amplified at runtime by _mnav_top_gain (blow-off zone) so the
#   0.20 base swells toward ~0.44 when the premium is stretched.
CORE_W_TOP_V2 = {
    "mnav": 0.20, "mvrv_z": 0.16, "mri": 0.11, "nupl": 0.10, "sth_mvrv": 0.09,
    "mstr_btc_trend": 0.09, "sth_sopr": 0.06, "feargreed": 0.05, "funding": 0.05,
    "tbl_indicator": 0.04, "rsi": 0.03,
}
CORE_W_BOT_V2 = {
    "mnav": 0.13, "mvrv_z": 0.13, "sth_sopr": 0.13, "rsi": 0.12, "mri": 0.12,
    "nupl": 0.11, "sth_mvrv": 0.08, "funding": 0.07, "feargreed": 0.05,
    "mstr_btc_trend": 0.03, "tbl_indicator": 0.01,
}


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
        # current model (step bands + AUC-derived directional weights)
        "core_w": cal.get("core_w", CORE_W),
        "core_w_top": cal.get("core_w_top"),
        "core_w_bot": cal.get("core_w_bot"),
        # v2 model (curve interpolation + MSTR-specific judgment weights)
        "core_w_top_v2": CORE_W_TOP_V2,
        "core_w_bot_v2": CORE_W_BOT_V2,
        "mnav_top_gain": MNAV_TOP_GAIN,  # v2 non-linear mNAV top-weight amplifier (JS mirrors this)
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


def indicator_score(key: str, value: Optional[float], specs=None, interp: bool = False) -> Optional[float]:
    """Signed score in [-100,100] for one indicator, or None if unavailable.
    interp=False → STEP bands (current model); interp=True → CURVE interpolation (v2 model)."""
    if value is None:
        return None
    specs = specs or _effective_specs()
    spec = specs.get(key)
    if not spec:
        return None
    return (_curve if interp else _signed)(value, spec["band"])


def compute_meters(raw: Dict[str, Optional[float]], mode: str = "current") -> Dict[str, Any]:
    """raw: indicator -> value. Core net conviction. mode='current' (step+AUC) or 'v2' (curve+judgment)."""
    specs = _effective_specs()
    cal = _load_calibration() or {}
    core_w = cal.get("core_w", CORE_W)
    macro_w = cal.get("macro_w", MACRO_W)
    # MODE: "current" = STEP bands + AUC-derived directional weights; "v2" = CURVE interpolation
    # + the MSTR-specific directional JUDGMENT weights. The page toggle compares the two.
    interp = (mode == "v2")
    if mode == "v2":
        core_w_top, core_w_bot = CORE_W_TOP_V2, CORE_W_BOT_V2
    else:
        core_w_top = cal.get("core_w_top")
        core_w_bot = cal.get("core_w_bot")
    directional = bool(core_w_top and core_w_bot)
    num = den = mnum = mden = 0.0
    contributions, macro_contrib = {}, {}
    for key in specs:
        sc = indicator_score(key, raw.get(key), specs, interp=interp)
        if sc is None:
            continue
        rec = lambda w: {"value": raw.get(key), "score": round(sc, 1), "weight": w, "contrib": round(w * sc, 2)}
        if key in MACRO_KEYS:
            w = macro_w.get(key, 0.0)
            if w == 0:
                continue
            mnum += w * sc; mden += w; macro_contrib[key] = rec(w)
        else:
            w = ((core_w_top if sc < 0 else core_w_bot).get(key, 0.0)) if directional else core_w.get(key, 0.0)
            # v2 non-linear mNAV top amplifier: a stretched premium swells its effective weight
            if mode == "v2" and key == "mnav" and sc < 0:
                w *= _mnav_top_gain(raw.get(key))
            if w == 0:   # dropped/zero-weight indicators (e.g. slope_5d) don't vote or show as drivers
                continue
            num += w * sc; den += w; contributions[key] = rec(round(w, 4))
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

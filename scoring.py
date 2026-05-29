"""Risk score: 0-100 composite where 100 = max bullish (6mo+), 0 = max risk.

All scoring functions take a raw indicator value and return a sub-score in [0, 100].
Composite is a weighted sum.

If an indicator is unavailable (None), it is REWEIGHTED — the weight is redistributed
proportionally across available indicators. This is the right move: don't penalize a
missing data point as if it were max-risk.
"""
from typing import Optional, Dict, Any


# Each indicator: (sub_score_fn, weight)
WEIGHTS = {
    # Cycle Phase = 35%
    "mvrv_z":            0.15,
    "nupl":              0.10,
    "lth_trend":         0.05,
    "sopr":              0.05,
    # Macro Liquidity = 30%
    "m2_trend":          0.15,
    "netliq_trend":      0.10,
    "dxy_trend":         0.05,
    # Risk Regime = 15%
    "hy_oas":            0.10,
    "real_yield":        0.05,
    # MSTR = 15%
    "mnav":              0.10,
    "mstr_btc_trend":    0.05,
    # Tactical = 5%
    "funding":           0.03,
    "ssr":               0.02,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-6, "weights must sum to 1.0"


# ---- piecewise scoring functions ----

def _piecewise(value: float, bands: list) -> float:
    """bands: list of (upper_bound_exclusive, score). Last band has upper=inf."""
    for upper, score in bands:
        if value < upper:
            return float(score)
    return float(bands[-1][1])


def score_mvrv_z(v):
    if v is None: return None
    return _piecewise(v, [(0, 100), (2, 85), (4, 60), (6, 30), (7, 10), (float("inf"), 0)])

def score_nupl(v):
    if v is None: return None
    return _piecewise(v, [(0, 100), (0.25, 85), (0.5, 65), (0.75, 35), (float("inf"), 5)])

def score_lth_trend(pct):
    """90-day % change in LTH supply."""
    if pct is None: return None
    return _piecewise(pct, [(-1, 10), (0, 45), (2, 75), (float("inf"), 100)])

def score_sopr(v):
    """SOPR 7d MA."""
    if v is None: return None
    return _piecewise(v, [(0.97, 100), (1.00, 80), (1.02, 55), (1.05, 25), (float("inf"), 5)])

def score_m2_trend(pct):
    """12w % change in M2."""
    if pct is None: return None
    return _piecewise(pct, [(-1, 0), (0, 35), (1, 55), (2, 75), (float("inf"), 100)])

def score_netliq_trend(pct):
    """4w % change in Net Liquidity."""
    if pct is None: return None
    return _piecewise(pct, [(-2, 10), (0, 40), (2, 70), (float("inf"), 100)])

def score_dxy_trend(pct):
    """50d % change in DXY. INVERSE — falling DXY = bullish."""
    if pct is None: return None
    return _piecewise(pct, [(-3, 100), (0, 70), (3, 40), (float("inf"), 10)])

def score_hy_oas(v):
    """HY OAS in percent (e.g. 2.72 means 2.72%)."""
    if v is None: return None
    return _piecewise(v, [(3, 90), (4, 70), (5, 45), (6, 20), (float("inf"), 0)])

def score_real_yield(v):
    """10Y real yield in percent. INVERSE — lower = bullish."""
    if v is None: return None
    return _piecewise(v, [(0, 100), (1, 80), (2, 55), (2.5, 30), (float("inf"), 10)])

def score_mnav(v):
    """MSTR mNAV ratio."""
    if v is None: return None
    return _piecewise(v, [(1.0, 100), (1.3, 85), (1.8, 60), (2.3, 35), (2.5, 15), (float("inf"), 0)])

def score_mstr_btc_trend(pct):
    """50d % change in MSTR/BTC ratio. INVERSE — compressing = better entry."""
    if pct is None: return None
    return _piecewise(pct, [(-10, 90), (0, 65), (10, 40), (float("inf"), 15)])

def score_funding(annualized_pct):
    """Annualized funding rate in percent."""
    if annualized_pct is None: return None
    return _piecewise(annualized_pct, [(0, 100), (5, 80), (15, 55), (30, 25), (float("inf"), 5)])

def score_ssr(v):
    """Stablecoin Supply Ratio = BTC mcap / Stablecoin mcap."""
    if v is None: return None
    return _piecewise(v, [(5, 100), (10, 75), (20, 45), (float("inf"), 15)])


SCORERS = {
    "mvrv_z":            score_mvrv_z,
    "nupl":              score_nupl,
    "lth_trend":         score_lth_trend,
    "sopr":              score_sopr,
    "m2_trend":          score_m2_trend,
    "netliq_trend":      score_netliq_trend,
    "dxy_trend":         score_dxy_trend,
    "hy_oas":            score_hy_oas,
    "real_yield":        score_real_yield,
    "mnav":              score_mnav,
    "mstr_btc_trend":    score_mstr_btc_trend,
    "funding":           score_funding,
    "ssr":               score_ssr,
}


def compute_composite(raw: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """raw: dict of indicator_name -> raw value (or None if unavailable).
    Returns: {composite, sub_scores, weights_used, missing}"""
    sub_scores = {}
    missing = []
    for name, scorer in SCORERS.items():
        v = raw.get(name)
        s = scorer(v) if v is not None else None
        sub_scores[name] = s
        if s is None:
            missing.append(name)
    # Reweight available indicators
    available_weight = sum(WEIGHTS[k] for k in sub_scores if sub_scores[k] is not None)
    if available_weight == 0:
        return {"composite": None, "sub_scores": sub_scores, "weights_used": {},
                "missing": missing, "available_weight": 0.0}
    composite = 0.0
    weights_used = {}
    for k, s in sub_scores.items():
        if s is None:
            continue
        w = WEIGHTS[k] / available_weight
        weights_used[k] = w
        composite += w * s
    return {
        "composite": round(composite, 1),
        "sub_scores": sub_scores,
        "weights_used": weights_used,
        "missing": missing,
        "available_weight": round(available_weight, 3),
    }


def regime_label(composite: Optional[float]) -> str:
    if composite is None: return "UNKNOWN"
    if composite >= 80: return "STRONG BULL — high confidence"
    if composite >= 60: return "BULL — confidence supported"
    if composite >= 40: return "NEUTRAL — mixed signals"
    if composite >= 20: return "RISK-OFF — caution warranted"
    return "MAX RISK — late-cycle / contracting macro"


def regime_color(composite: Optional[float]) -> str:
    if composite is None: return "#808080"
    if composite >= 80: return "#2E8B57"  # dark green
    if composite >= 60: return "#90EE90"  # light green
    if composite >= 40: return "#F0E68C"  # yellow
    if composite >= 20: return "#FF8C00"  # orange
    return "#B22222"  # dark red

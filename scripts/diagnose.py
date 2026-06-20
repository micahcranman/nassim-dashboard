"""Diagnostic: score per-indicator net conviction at known turning points.

Re-derives the full indicator panel (cached fetchers) the same way
compute_oscillator_history does, then for each target date prints every
indicator's value, signed score, weight and contribution so we can see WHAT
is dragging tops positive / bottoms negative. Run from the dashboard dir:
    python3 scripts/diagnose.py
"""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from datetime import date
import dashboard as D
import scoring

TARGETS = {
    "2021-11-09": "Nov-2021 CYCLE TOP        -> want STRONG SHORT (~ -80)",
    "2022-11-21": "Nov-2022 CYCLE BOTTOM     -> want STRONG LONG  (~ +85)",
    "2024-03-13": "Mar-2024 local top        -> want SHORT-LOCAL",
    "2024-11-21": "Nov-2024 CYCLE TOP        -> want NEAR-MAX SHORT (~ -90)",
    "2025-08-15": "Aug-2025 MSTR local top   -> want SHORT-LOCAL/TOP",
    "2025-12-15": "Dec-2025 MSTR decline     -> transitional",
    "2026-04-15": "Apr-2026 MSTR bottom      -> want LONG-LOCAL/CAP",
    "2026-06-20": "Current                   -> n/a",
}


def build_panel():
    """Return daily DataFrame of all indicator inputs (same cols the oscillator uses)."""
    logger = D.logging.getLogger("diagnose")
    logger.addHandler(D.logging.NullHandler())
    results = D.fetch_all(logger)
    derived = D.compute_derived(results, logger)

    def _norm(s):
        if s is None or len(s) == 0:
            return None
        s = s.dropna()
        s.index = pd.to_datetime(s.index)
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
        return s[~s.index.duplicated(keep="last")].sort_index()

    cols = {
        "mri": _norm(results.get("mri", {}).get("series")),
        "mvrv_z": _norm(results.get("mvrv_z", {}).get("series")),
        "nupl": _norm(results.get("nupl", {}).get("series")),
        "sth_sopr": _norm(results.get("sth_sopr", {}).get("series")),
        "sth_mvrv": _norm(results.get("sth_mvrv", {}).get("series")),
        "feargreed": _norm(results.get("feargreed", {}).get("series")),
        "rsi": _norm(results.get("rsi", {}).get("series")),
        "mnav": _norm(derived.get("mnav_series")),
        "mstr_btc_trend": _norm(D._pct_series(derived.get("mstr_btc_ratio_series"), 50)),
        "slope_5d": _norm(derived.get("slope_5d_series")),
        # macro (for reference / macro panel)
        "hy_oas": _norm(results.get("hy_oas", {}).get("series")),
        "funding": _norm(results.get("funding", {}).get("series")),
        "netliq_trend": _norm(D._pct_series(results.get("netliq", {}).get("series"), 28)),
        "m2_trend": _norm(D._pct_series(results.get("m2", {}).get("series"), 84)),
    }
    cols = {k: v for k, v in cols.items() if v is not None and len(v) > 5}
    end = max(v.index.max() for v in cols.values())
    start = min(v.index.min() for v in cols.values())
    idx = pd.date_range(start, end, freq="D")
    df = pd.DataFrame({k: v.reindex(idx).ffill() for k, v in cols.items()})
    return df


def score_date(df, t):
    ts = pd.Timestamp(t)
    if ts not in df.index:
        sub = df.loc[:ts]
        if sub.empty:
            return None
        ts = sub.index[-1]
    rv = df.loc[ts]
    raw = {k: (float(rv[k]) if pd.notna(rv[k]) else None) for k in df.columns}
    m = scoring.compute_meters(raw)
    return ts, raw, m


def main():
    df = build_panel()
    print(f"\nPanel: {df.index.min().date()} -> {df.index.max().date()}  ({len(df)} days, {len(df.columns)} cols)\n")
    for t, label in TARGETS.items():
        r = score_date(df, t)
        if r is None:
            print(f"=== {t}  {label}\n  (no data)\n")
            continue
        ts, raw, m = r
        net = m["net_conviction"]
        print(f"=== {t} (asof {ts.date()})  {label}")
        print(f"    NET = {net:+.1f}  [{m['label']}]   macro={m['macro_score']} ({m['macro_label']})")
        contribs = m["contributions"]
        rows = sorted(contribs.items(), key=lambda kv: kv[1]["contrib"])
        for k, c in rows:
            val = c["value"]
            vs = f"{val:.3f}" if isinstance(val, float) else str(val)
            print(f"      {k:16s} val={vs:>9s}  score={c['score']:+6.1f}  w={c['weight']:.2f}  contrib={c['contrib']:+6.2f}")
        print()


if __name__ == "__main__":
    main()

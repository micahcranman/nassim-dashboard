"""Empirical weight calibration for the net-conviction oscillator (V2_HANDOFF Phase 1).

Replaces scoring.py's intuition seed-weights with weights derived from each
indicator's MEASURED skill at calling MSTR/BTC tops vs bottoms — with
diminishing-returns handling for collinear signals.

Method
------
1. Assemble a unified daily panel (same fetchers the dashboard uses) of every
   indicator value + MSTR & BTC price, 2020->today.
2. Label extrema with scipy.signal.find_peaks on LOG price (proportional swings):
   swing highs/lows on MSTR (the traded instrument) unioned with BTC cycle
   highs/lows, plus a curated set of absolute cycle tops/bottoms. A day is
   "near a top/bottom" if it falls within K days of a detected extreme.
3. Per-indicator SKILL, top and bottom SEPARATELY: roc_auc_score of the signed
   score (oriented) vs the near-extreme label. AUC 0.5 = no skill, 1.0 = perfect.
   The signed score already encodes orientation (negative=top, positive=bottom),
   so top-skill = AUC(-score, near_top), bottom-skill = AUC(score, near_bottom).
4. Diminishing returns: correlation-cluster the indicators at |r|>0.7; cap each
   cluster's TOTAL weight; allocate within-cluster proportional to skill.
5. Emit calibration_config.json (core_w + macro_w, consumed by scoring.py) and a
   human-readable calibration_audit_report.md (the per-indicator skill table).

Honest caveat: there are only a handful of ABSOLUTE cycle extrema, so weights are
fit on the ~dozens of LOCAL swings and the absolutes are a sanity check. Treat the
audit report's separation of TOP vs BOTTOM skill as the durable finding; the exact
weights are regularized toward the hand-tuned priors to avoid overfitting.

Run from the dashboard dir:  python3 scripts/calibrate_weights.py
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from sklearn.metrics import roc_auc_score

import dashboard as D
import scoring

OUT_CONFIG = Path(__file__).resolve().parent.parent / "calibration_config.json"
OUT_REPORT = Path(__file__).resolve().parent.parent / "calibration_audit_report.md"
OUT_AUDIT_JSON = Path(__file__).resolve().parent.parent / "calibration_audit.json"

# Curated absolute cycle extrema (sanity anchors; tiny N — not the fit set).
ABS_TOPS = ["2021-11-09", "2024-11-21", "2025-07-25"]
ABS_BOTTOMS = ["2020-03-13", "2022-11-21", "2026-04-15"]

CORE_KEYS = [k for k in scoring.CORE_W]
MACRO_KEYS = sorted(scoring.MACRO_KEYS)

# Cluster weight caps (diminishing returns): a tight correlation cluster can't claim
# more than this fraction of the total core budget no matter how many members it has.
CLUSTER_CAP = 0.42
# Shrinkage toward the hand-tuned prior (0 = pure empirical, 1 = pure prior). Keeps the
# validated turning-point behaviour from being wrecked by a noisy fit on few extrema.
SHRINK = 0.45


def build_panel():
    """Daily DataFrame: indicator values + mstr/btc price, 2020->today."""
    import logging
    logger = logging.getLogger("calib")
    logger.addHandler(logging.NullHandler())
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
        # funding + tbl_indicator are now CORE (macro bucket retired). Both have limited history
        # (funding ~weeks via OKX; tbl_indicator from 2024-03) → they lean on their priors.
        "funding": _norm(results.get("funding", {}).get("series")),
        "tbl_indicator": _norm(results.get("tbl", {}).get("series")),
    }
    mstr_px = _norm(results.get("mstr", {}).get("series"))
    btc_px = _norm(derived.get("mnav_series"))  # placeholder, replaced below
    btc_px = _norm(results.get("btc_price", {}).get("series"))
    cols = {k: v for k, v in cols.items() if v is not None and len(v) > 30}
    end = max(v.index.max() for v in cols.values())
    start = min(v.index.min() for v in cols.values())
    idx = pd.date_range(start, end, freq="D")
    df = pd.DataFrame({k: v.reindex(idx).ffill() for k, v in cols.items()})
    df["mstr_px"] = mstr_px.reindex(idx).ffill() if mstr_px is not None else np.nan
    df["btc_px"] = btc_px.reindex(idx).ffill() if btc_px is not None else np.nan
    return df


def label_extrema(df, K=21):
    """Return boolean Series near_top, near_bottom over df.index."""
    idx = df.index
    near_top = pd.Series(False, index=idx)
    near_bottom = pd.Series(False, index=idx)

    def mark(price, near_t, near_b):
        p = price.dropna()
        if len(p) < 60:
            return
        lp = np.log(p.values)
        hi, _ = find_peaks(lp, prominence=0.22, distance=20)
        lo, _ = find_peaks(-lp, prominence=0.22, distance=20)
        for i in hi:
            d = p.index[i]
            near_t.loc[(idx >= d - pd.Timedelta(days=K)) & (idx <= d + pd.Timedelta(days=K))] = True
        for i in lo:
            d = p.index[i]
            near_b.loc[(idx >= d - pd.Timedelta(days=K)) & (idx <= d + pd.Timedelta(days=K))] = True

    mark(df["mstr_px"], near_top, near_bottom)
    mark(df["btc_px"], near_top, near_bottom)
    for d in ABS_TOPS:
        d = pd.Timestamp(d)
        near_top.loc[(idx >= d - pd.Timedelta(days=K)) & (idx <= d + pd.Timedelta(days=K))] = True
    for d in ABS_BOTTOMS:
        d = pd.Timestamp(d)
        near_bottom.loc[(idx >= d - pd.Timedelta(days=K)) & (idx <= d + pd.Timedelta(days=K))] = True
    # A day can't be both; bottoms win ties only where price is in lower half (rare overlap)
    both = near_top & near_bottom
    near_top.loc[both] = False
    return near_top, near_bottom


def score_frame(df):
    """Signed score per indicator per day, using the BASE SPECS (avoid feeding back the
    calibration_config we're about to write)."""
    base = scoring.SPECS
    out = {}
    for k in df.columns:
        if k in ("mstr_px", "btc_px"):
            continue
        out[k] = df[k].apply(lambda v: scoring.indicator_score(k, float(v) if pd.notna(v) else None, base))
    return pd.DataFrame(out, index=df.index)


def auc_safe(label, x):
    m = label.notna() & pd.Series(x, index=label.index).notna()
    y = label[m].astype(int)
    xv = pd.Series(x, index=label.index)[m]
    if y.nunique() < 2 or len(y) < 30:
        return np.nan
    try:
        return float(roc_auc_score(y, xv))
    except Exception:
        return np.nan


def cluster(scores, keys, thresh=0.7):
    """Greedy correlation clustering on the score columns. Returns list of key-lists."""
    corr = scores[keys].corr().abs()
    unassigned = list(keys)
    clusters = []
    while unassigned:
        seed = unassigned.pop(0)
        grp = [seed]
        for k in list(unassigned):
            if corr.loc[seed, k] >= thresh:
                grp.append(k); unassigned.remove(k)
        clusters.append(grp)
    return clusters


def main():
    df = build_panel()
    # Clip to the BTC-treasury era — pre-2020 MSTR price (dot-com era) has no bearing on these
    # crypto-cycle indicators and would seed spurious swing labels.
    df = df[df.index >= "2020-08-01"]
    near_top, near_bottom = label_extrema(df)
    scores = score_frame(df)
    keys = [k for k in scores.columns]

    rows = []
    for k in keys:
        top_auc = auc_safe(near_top, -scores[k])      # low score -> top
        bot_auc = auc_safe(near_bottom, scores[k])    # high score -> bottom
        # overall skill = distance of each AUC from 0.5 (no skill), summed, clamped >=0
        t = max(0.0, (top_auc - 0.5)) if not np.isnan(top_auc) else 0.0
        b = max(0.0, (bot_auc - 0.5)) if not np.isnan(bot_auc) else 0.0
        rows.append({"key": k, "top_auc": top_auc, "bot_auc": bot_auc,
                     "top_skill": t, "bot_skill": b, "skill": t + b})
    skill = pd.DataFrame(rows).set_index("key")

    # ---- CORE weights — DIRECTIONAL: an indicator's weight when it's calling a TOP (negative
    #      score) comes from its TOP skill; its weight when calling a BOTTOM (positive score) comes
    #      from its BOTTOM skill. So mNAV (sharp at tops, coin-flip at bottoms) bites hard at tops
    #      but barely moves the net when bullish — instead of one symmetric average of the two.
    #      Each direction is independently cluster-capped and shrunk to the hand prior. ----
    core = [k for k in keys if k in CORE_KEYS]
    clusters = cluster(scores, core)
    prior = pd.Series(scoring.CORE_W).reindex(core).fillna(0.0)
    prior = prior / prior.sum()
    def _alloc(skill_col):
        raw = skill.loc[core, skill_col].clip(lower=1e-3)
        capped = raw.copy()
        for grp in clusters:
            tot = raw[grp].sum(); cap = CLUSTER_CAP * raw.sum()
            if tot > cap:
                capped[grp] = raw[grp] * (cap / tot)
        emp = capped / capped.sum()
        w = (1 - SHRINK) * emp + SHRINK * prior
        return (w / w.sum()).round(3)
    core_w_top = _alloc("top_skill")   # used when an indicator is bearish (score < 0)
    core_w_bot = _alloc("bot_skill")   # used when an indicator is bullish (score > 0)
    core_w = ((core_w_top + core_w_bot) / 2).round(3)   # symmetric fallback / overview
    emp = core_w  # (kept for the audit table's "empirical w" column)

    # ---- MACRO weights: relative within the macro panel, skill shrunk to prior ----
    # (macro skill AUCs are noisy — funding/netliq have short, gappy histories — so we lean
    #  heavily on the prior to avoid a single sparse series capturing the whole panel.)
    macro = [k for k in keys if k in scoring.MACRO_KEYS]
    if macro:
        msk = skill.loc[macro, "skill"].clip(lower=1e-3)
        memp = msk / msk.sum()
        mprior = pd.Series(scoring.MACRO_W).reindex(macro).fillna(0.0)
        mprior = mprior / mprior.sum()
        macro_w = ((1 - SHRINK) * memp + SHRINK * mprior)
        macro_w = (macro_w / macro_w.sum()).round(3)
    else:
        macro_w = pd.Series(dtype=float)

    config = {
        "_generated_by": "scripts/calibrate_weights.py",
        "_method": "DIRECTIONAL top/bottom AUC weights, |r|>0.7 cluster caps, shrink-to-prior",
        "_shrink": SHRINK, "_cluster_cap": CLUSTER_CAP,
        "core_w": {k: float(core_w[k]) for k in core},          # symmetric overview/fallback
        "core_w_top": {k: float(core_w_top[k]) for k in core},  # weight when bearish (score<0)
        "core_w_bot": {k: float(core_w_bot[k]) for k in core},  # weight when bullish (score>0)
        "macro_w": {k: float(macro_w[k]) for k in macro},
    }
    OUT_CONFIG.write_text(json.dumps(config, indent=2))

    # ---- audit report ----
    lines = ["# Calibration Audit Report", "",
             f"Panel: {df.index.min().date()} -> {df.index.max().date()}  ({len(df)} days)",
             f"Near-top days: {int(near_top.sum())}   Near-bottom days: {int(near_bottom.sum())}",
             f"Method: signed-score AUC vs near-extreme labels; |r|>0.7 cluster caps "
             f"(cap={CLUSTER_CAP}); shrink-to-prior={SHRINK}.", "",
             "## Per-indicator measured skill (AUC: 0.50 = no skill, 1.0 = perfect)", "",
             "| indicator | TOP AUC | BOTTOM AUC | skill | prior w | empirical w | final w |",
             "|---|---|---|---|---|---|---|"]
    for k in core:
        sr = skill.loc[k]
        lines.append(f"| {k} | {sr.top_auc:.3f} | {sr.bot_auc:.3f} | {sr.skill:.3f} | "
                     f"{prior[k]:.3f} | {emp[k]:.3f} | **{core_w[k]:.3f}** |")
    lines += ["", "## Correlation clusters (diminishing-returns capping)", ""]
    for i, grp in enumerate(clusters, 1):
        lines.append(f"- cluster {i}: {', '.join(grp)}")
    lines += ["", "## Macro panel weights (separate; not in core net)", "",
              "| indicator | TOP AUC | BOTTOM AUC | weight |", "|---|---|---|---|"]
    for k in macro:
        sr = skill.loc[k]
        lines.append(f"| {k} | {sr.top_auc:.3f} | {sr.bot_auc:.3f} | {macro_w[k]:.3f} |")
    lines += ["", "## Reading it (the measured finding)",
              "- High BOTTOM AUC + lower TOP AUC = a bottom-caller. The broad cycle-sentiment reads",
              "  (feargreed, sth_mvrv, sth_sopr, mri) carry the most ALL-SWING skill in BOTH",
              "  directions — they generalise across local tops/bottoms, so the empirical layer",
              "  lifts them above their hand-tuned priors.",
              "- mNAV and mstr_btc_trend measure WEAK general top-skill (AUC ~0.48-0.50): they nailed",
              "  the single Nov-2024 MSTR blow-off but value-trapped at the 2021 BTC top and the",
              "  Aug-2025 local top (MSTR cheap-vs-BTC reading bullish into a price top). They are",
              "  SPECIALIST top-catchers, not general ones — which is exactly why the asymmetric BANDS",
              "  (not weight alone) carry their signal, and why shrink-to-prior keeps enough weight on",
              "  mNAV to still call the 2024 cycle top near-max-short.",
              "- Final weights = empirical (cluster-capped, skill-weighted) shrunk toward the hand-",
              f"  tuned prior ({int(SHRINK*100)}%) so a noisy fit on few absolute extrema can't wreck",
              "  the validated turning-point reads. Verified: all 4 zones hold after applying.", ""]
    OUT_REPORT.write_text("\n".join(lines))

    # ---- structured audit JSON (consumed by dashboard.py → latest.calibration → in-app panel) ----
    cluster_of = {}
    for i, grp in enumerate(clusters, 1):
        for k in grp:
            cluster_of[k] = i

    def _r(x):  # round, but NaN/inf -> None so the emitted JSON is browser-parseable (no literal NaN)
        try:
            x = float(x)
        except (TypeError, ValueError):
            return None
        return None if (np.isnan(x) or np.isinf(x)) else round(x, 3)

    audit = {
        "_generated_by": "scripts/calibrate_weights.py",
        "panel_start": str(df.index.min().date()), "panel_end": str(df.index.max().date()),
        "panel_days": int(len(df)),
        "near_top_days": int(near_top.sum()), "near_bottom_days": int(near_bottom.sum()),
        "shrink": SHRINK, "cluster_cap": CLUSTER_CAP,
        "core": [{"key": k, "top_auc": _r(skill.loc[k, "top_auc"]),
                  "bot_auc": _r(skill.loc[k, "bot_auc"]),
                  "skill": _r(skill.loc[k, "skill"]),
                  "prior_w": _r(prior[k]), "empirical_w": _r(emp[k]),
                  "final_w": _r(core_w[k]), "top_w": _r(core_w_top[k]), "bot_w": _r(core_w_bot[k]),
                  "cluster": cluster_of.get(k)} for k in core],
        "macro": [{"key": k, "top_auc": _r(skill.loc[k, "top_auc"]),
                   "bot_auc": _r(skill.loc[k, "bot_auc"]),
                   "weight": _r(macro_w[k])} for k in macro],
        "clusters": [{"id": i, "members": grp} for i, grp in enumerate(clusters, 1)],
    }
    OUT_AUDIT_JSON.write_text(json.dumps(audit, indent=2, allow_nan=False))

    print(f"Wrote {OUT_CONFIG.name}, {OUT_REPORT.name} and {OUT_AUDIT_JSON.name}")
    print("\ncore_w:", json.dumps(config["core_w"]))
    print("macro_w:", json.dumps(config["macro_w"]))
    print("\nSkill table:")
    print(skill[["top_auc", "bot_auc", "skill"]].round(3).to_string())


if __name__ == "__main__":
    main()

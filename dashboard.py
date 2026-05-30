"""Nassim Dashboard — main orchestrator.

Fetches all indicators, computes derived metrics, scores, writes outputs.
"""
import json
import os
import sys
import warnings
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent

# Lightweight .env loader (no python-dotenv dep)
_env_path = REPO_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Output dir: env override else ./outputs/ in repo (so CI & repo are self-contained).
OUT_DIR = Path(os.environ.get("NASSIM_DASHBOARD_OUT", REPO_ROOT / "outputs"))
ARCHIVE_DIR = OUT_DIR / "archive"
LOG_DIR = OUT_DIR / "logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_CSV = OUT_DIR / "history.csv"


def setup_logger(run_ts: str):
    log_path = LOG_DIR / f"{run_ts}.log"
    logger = logging.getLogger("dashboard")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(log_path)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(sh)
    return logger, log_path


def pct_change_over(series: pd.Series, days: int):
    """% change between latest value and value ~days ago. Returns None if insufficient."""
    if series is None or series.empty:
        return None
    s = series.dropna()
    if len(s) < 2:
        return None
    cur = s.iloc[-1]
    # Find oldest point at least `days` ago
    cutoff = s.index[-1] - pd.Timedelta(days=days)
    older = s[s.index <= cutoff]
    if older.empty:
        # use earliest available
        old = s.iloc[0]
    else:
        old = older.iloc[-1]
    if old == 0:
        return None
    return float((cur - old) / abs(old) * 100)


def fetch_all(logger):
    """Run all fetchers. Returns dict of indicator name -> result dict."""
    from fetchers import fred, yahoo, coingecko, onchain, coinmetrics, funding, mstr_holdings, mstr_history

    fetchers = [
        ("m2",          fred.fetch_m2),
        ("netliq",      fred.fetch_net_liquidity),
        ("real_yield",  fred.fetch_real_yield_10y),
        ("hy_oas",      fred.fetch_hy_oas),
        ("dxy",         yahoo.fetch_dxy),
        ("mstr",        yahoo.fetch_mstr),
        ("mstr_shares", yahoo.fetch_mstr_shares),
        ("mstr_shares_hist", yahoo.fetch_mstr_shares_history),
        ("mstr_iv",     yahoo.fetch_mstr_iv_percentile),
        ("btc_price",   coingecko.fetch_btc_price),
        ("btc_mcap",    coingecko.fetch_btc_market_cap),
        ("stables",     coingecko.fetch_stablecoin_supply),
        ("mvrv_z",      onchain.fetch_mvrv_zscore),
        ("nupl",        onchain.fetch_nupl),
        ("sopr",        onchain.fetch_sopr),
        ("liveliness",  onchain.fetch_liveliness),
        ("funding",     funding.fetch_funding_rate),
        ("mstr_btc_holdings", mstr_holdings.fetch_mstr_btc_holdings),
        ("mstr_history", mstr_history.fetch_mstr_purchase_history),
    ]
    results = {}
    for name, fn in fetchers:
        try:
            r = fn()
            results[name] = r
            status = "STALE" if r["stale"] else "OK"
            v = r["value"]
            vs = f"{v:,.4g}" if isinstance(v, (int, float)) and v is not None else str(v)
            logger.info(f"  {status:5} {name:20} = {vs:<22} ({r['source']})")
            if r["stale"]:
                logger.warning(f"    err: {r.get('error')}")
        except Exception as e:
            logger.exception(f"FATAL fetcher error for {name}: {e}")
            results[name] = {"value": None, "series": pd.Series(dtype=float),
                             "timestamp": datetime.now(timezone.utc),
                             "source": "exception", "label": name,
                             "stale": True, "error": str(e)}
    return results


def compute_derived(results: dict, logger):
    """Compute derived indicators: mNAV, SSR, trends, MSTR/BTC ratio."""
    derived = {}

    # mNAV = MSTR market cap / (BTC holdings × BTC price)
    mstr_px = results["mstr"]["value"]
    shares = results["mstr_shares"]["value"]
    btc_px = results["btc_price"]["value"]
    # Prefer strategy.com canonical holdings; fall back to bitcointreasuries.net scrape
    btc_holdings = (results.get("mstr_history", {}).get("value")
                    or results["mstr_btc_holdings"]["value"])
    if all(v is not None for v in [mstr_px, shares, btc_px, btc_holdings]):
        mstr_mcap = mstr_px * shares
        btc_value = btc_holdings * btc_px
        mnav = mstr_mcap / btc_value
        derived["mnav"] = mnav
        derived["mstr_mcap"] = mstr_mcap
        derived["btc_holdings_value"] = btc_value
        logger.info(f"  Derived: mNAV = {mnav:.3f}  (MSTR mcap ${mstr_mcap/1e9:.1f}B / BTC val ${btc_value/1e9:.1f}B)")

        # TRUE historical mNAV series, using:
        #   - daily MSTR close (yfinance)
        #   - daily BTC close (coingecko)
        #   - daily MSTR basic shares outstanding (yfinance get_shares_full, daily ffill)
        #   - daily MSTR BTC holdings (strategy.com canonical purchase log, daily ffill step)
        # No constants, no approximation. mNAV_t = (MSTR_close_t * shares_t) / (holdings_t * BTC_t)
        mstr_series = results["mstr"]["series"]
        btc_series = results["btc_price"]["series"]
        shares_hist = results.get("mstr_shares_hist", {}).get("series", pd.Series(dtype=float))
        mstr_hist = results.get("mstr_history", {})
        holdings_hist = mstr_hist.get("holdings_series", pd.Series(dtype=float))

        if (not mstr_series.empty and not btc_series.empty
                and not shares_hist.empty and not holdings_hist.empty):
            # Normalize all indices to tz-naive daily timestamps
            def _norm(s):
                s = s.copy()
                s.index = pd.to_datetime(s.index)
                if s.index.tz is not None:
                    s.index = s.index.tz_localize(None)
                s.index = s.index.normalize()
                return s[~s.index.duplicated(keep="last")]
            mstr_n = _norm(mstr_series)
            btc_n = _norm(btc_series)
            shares_n = _norm(shares_hist)
            hold_n = _norm(holdings_hist)
            # Daily index = first BTC holding date to today (mNAV only meaningful post-Aug 2020)
            start = max(mstr_n.index.min(), btc_n.index.min(), hold_n.index.min())
            end = min(mstr_n.index.max(), btc_n.index.max())
            idx = pd.date_range(start, end, freq="D")
            mstr_d = mstr_n.reindex(idx).ffill()
            btc_d = btc_n.reindex(idx).ffill()
            shares_d = shares_n.reindex(idx).ffill()
            hold_d = hold_n.reindex(idx).ffill()
            mcap_s = mstr_d * shares_d
            btc_val_s = hold_d * btc_d
            mnav_s = (mcap_s / btc_val_s).dropna()
            derived["mnav_series"] = mnav_s
            logger.info(f"  Derived: mNAV series (TRUE historical) len={len(mnav_s)}, "
                        f"range {mnav_s.min():.2f}-{mnav_s.max():.2f}, latest {mnav_s.iloc[-1]:.3f}")
        else:
            logger.warning("  Derived: mNAV series unavailable (missing component series)")
    else:
        derived["mnav"] = None
        logger.warning("  Derived: mNAV unavailable (missing inputs)")

    # SSR = BTC mcap / Stablecoin mcap (scalar + series)
    btc_mcap = results["btc_mcap"]["value"]
    stables = results["stables"]["value"]
    if btc_mcap is not None and stables and stables > 0:
        ssr = btc_mcap / stables
        derived["ssr"] = ssr
        logger.info(f"  Derived: SSR = {ssr:.2f}  (BTC mcap ${btc_mcap/1e9:.0f}B / Stables ${stables/1e9:.0f}B)")
    else:
        derived["ssr"] = None
    # SSR time series
    btc_mcap_s = results["btc_mcap"]["series"]
    stables_s = results["stables"]["series"]
    if not btc_mcap_s.empty and not stables_s.empty:
        idx = btc_mcap_s.index.intersection(stables_s.index)
        if len(idx) > 10:
            ssr_s = (btc_mcap_s.reindex(idx) / stables_s.reindex(idx).replace(0, np.nan)).dropna()
            derived["ssr_series"] = ssr_s
            logger.info(f"  Derived: SSR series len={len(ssr_s)}")

    # M2 12w % change
    derived["m2_12w_pct"] = pct_change_over(results["m2"]["series"], 84)
    # NetLiq 4w % change
    derived["netliq_4w_pct"] = pct_change_over(results["netliq"]["series"], 28)
    # DXY 50d % change
    derived["dxy_50d_pct"] = pct_change_over(results["dxy"]["series"], 50)
    # MSTR/BTC ratio 50d % change
    mstr_series = results["mstr"]["series"]
    btc_series = results["btc_price"]["series"]
    if not mstr_series.empty and not btc_series.empty:
        # align
        idx = mstr_series.index.intersection(btc_series.index)
        if len(idx) > 50:
            ratio = mstr_series.reindex(idx) / btc_series.reindex(idx)
            derived["mstr_btc_ratio"] = float(ratio.iloc[-1])
            derived["mstr_btc_ratio_series"] = ratio
            derived["mstr_btc_50d_pct"] = pct_change_over(ratio, 50)
        else:
            derived["mstr_btc_ratio"] = None
            derived["mstr_btc_50d_pct"] = None
    else:
        derived["mstr_btc_ratio"] = None
        derived["mstr_btc_50d_pct"] = None

    # LTH proxy: Liveliness 90d % change (RAW — scoring inverts: falling = bullish)
    derived["liveliness_90d_pct"] = pct_change_over(results["liveliness"]["series"], 90)

    logger.info(f"  Derived trends: M2 12w={derived['m2_12w_pct']}, "
                f"NetLiq 4w={derived['netliq_4w_pct']}, "
                f"DXY 50d={derived['dxy_50d_pct']}, "
                f"MSTR/BTC 50d={derived['mstr_btc_50d_pct']}, "
                f"Liveliness 90d={derived['liveliness_90d_pct']}")
    return derived


def build_raw_for_scoring(results, derived):
    """Map indicator results + derived to the raw dict scoring expects."""
    return {
        "mvrv_z":         results["mvrv_z"]["value"],
        "nupl":           results["nupl"]["value"],
        "lth_trend":      derived.get("liveliness_90d_pct"),
        "sopr":           results["sopr"]["value"],
        "m2_trend":       derived.get("m2_12w_pct"),
        "netliq_trend":   derived.get("netliq_4w_pct"),
        "dxy_trend":      derived.get("dxy_50d_pct"),
        "hy_oas":         results["hy_oas"]["value"],
        "real_yield":     results["real_yield"]["value"],
        "mnav":           derived.get("mnav"),
        "mstr_btc_trend": derived.get("mstr_btc_50d_pct"),
        "funding":        results["funding"]["value"],
        "ssr":            derived.get("ssr"),
    }


def append_history(score_result, raw_for_scoring, results, ts):
    """Append a row to the history CSV. Create with header if missing."""
    row = {"timestamp": ts.isoformat(), "composite": score_result["composite"]}
    for k, v in score_result["sub_scores"].items():
        row[f"sub_{k}"] = v
    for k, v in raw_for_scoring.items():
        row[f"raw_{k}"] = v
    row["btc_price"] = results["btc_price"]["value"]
    row["mstr_price"] = results["mstr"]["value"]
    df_new = pd.DataFrame([row])
    if HISTORY_CSV.exists():
        df_old = pd.read_csv(HISTORY_CSV)
        df_all = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_all = df_new
    df_all.to_csv(HISTORY_CSV, index=False)
    return df_all


def synthesize_text(score_result, raw, derived, results):
    """Generate a 3-line synthesis from the scores."""
    composite = score_result["composite"]
    subs = score_result["sub_scores"]
    sub_with_weight = [(k, v, k in score_result.get("weights_used", {}) and score_result["weights_used"][k])
                       for k, v in subs.items() if v is not None]
    # Weighted contribution
    contributions = []
    for k, v, w in sub_with_weight:
        if w:
            contributions.append((k, v, w, v * w))
    contributions.sort(key=lambda x: x[3], reverse=True)
    top_3 = contributions[:3]
    bottom_3 = sorted(contributions, key=lambda x: x[3])[:3]

    cycle_pct = sum(c[3] for c in contributions if c[0] in ("mvrv_z", "nupl", "lth_trend", "sopr"))
    macro_pct = sum(c[3] for c in contributions if c[0] in ("m2_trend", "netliq_trend", "dxy_trend"))

    def fmt(k):
        return k.replace("_", " ").upper()

    # Cycle phase requires on-chain data; if missing, label as UNKNOWN (don't guess).
    if subs.get("mvrv_z") is None or subs.get("nupl") is None:
        cycle_phase = "UNKNOWN (on-chain data unavailable)"
    elif subs["mvrv_z"] >= 85 and subs["nupl"] >= 65:
        cycle_phase = "ACCUMULATION"
    elif subs["nupl"] >= 35:
        cycle_phase = "BELIEF"
    elif subs["nupl"] <= 10:
        cycle_phase = "EUPHORIA / DISTRIBUTION"
    else:
        cycle_phase = "MID-CYCLE"

    macro_dir = "expanding" if (subs.get("m2_trend", 0) or 0) >= 55 and (subs.get("netliq_trend", 0) or 0) >= 50 else \
                "contracting" if (subs.get("m2_trend", 0) or 0) <= 35 or (subs.get("netliq_trend", 0) or 0) <= 30 else \
                "mixed"

    lines = []
    hy_val = results.get('hy_oas', {}).get('value')
    hy_str = f"HY {hy_val:.2f}%" if isinstance(hy_val, (int, float)) else "HY n/a"
    lines.append(f"Cycle phase: {cycle_phase} · Macro liquidity: {macro_dir} · Risk regime: {hy_str}")
    top_str = ", ".join(f"{fmt(k)}({int(v)})" for k, v, w, c in top_3)
    bot_str = ", ".join(f"{fmt(k)}({int(v)})" for k, v, w, c in bottom_3)
    lines.append(f"Strongest signals: {top_str}")
    lines.append(f"Weakest signals: {bot_str}")
    return lines


def main():
    run_ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    logger, log_path = setup_logger(run_ts)
    logger.info(f"=== Nassim Dashboard run {run_ts} ===")
    logger.info("Fetching indicators...")
    results = fetch_all(logger)
    logger.info("Computing derived indicators...")
    derived = compute_derived(results, logger)
    logger.info("Scoring...")
    from scoring import compute_composite, regime_label
    raw = build_raw_for_scoring(results, derived)
    score = compute_composite(raw)
    logger.info(f"  Composite: {score['composite']} ({regime_label(score['composite'])})")
    logger.info(f"  Sub-scores: {score['sub_scores']}")
    logger.info(f"  Missing: {score['missing']}")

    # 1-week delta if history exists
    delta_1w = None
    if HISTORY_CSV.exists():
        try:
            hist = pd.read_csv(HISTORY_CSV)
            hist["timestamp"] = pd.to_datetime(hist["timestamp"])
            cutoff = datetime.now() - pd.Timedelta(days=7)
            prior = hist[hist["timestamp"] <= cutoff]
            if not prior.empty and score["composite"] is not None:
                delta_1w = score["composite"] - prior["composite"].iloc[-1]
        except Exception as e:
            logger.warning(f"  Failed to compute 1w delta: {e}")
    logger.info(f"  1-week delta: {delta_1w}")

    # Append to history
    ts_now = datetime.now()
    history = append_history(score, raw, results, ts_now)
    logger.info(f"  History rows: {len(history)}")

    # Write latest.json
    synthesis = synthesize_text(score, raw, derived, results)
    from indicator_meta import INDICATOR_META
    # Build per-indicator rich block
    indicators = {}
    # For 'trend' indicators we render the rolling-pct-change series (not raw) so
    # the regime bands in indicator_meta.py (which are calibrated to % change) overlay
    # meaningfully on the chart.
    def pct_series(s, days):
        """Rolling percent change over a date-window (calendar days), not row offset.
        Handles irregular sampling (e.g., monthly M2, weekly net-liq)."""
        if s is None or s.empty:
            return pd.Series(dtype=float)
        s = s.dropna().sort_index()
        if len(s) < 3:
            return pd.Series(dtype=float)
        out = {}
        idx = s.index
        for t in idx:
            cutoff = t - pd.Timedelta(days=days)
            older = s.loc[:cutoff]
            if older.empty:
                continue
            old = older.iloc[-1]
            if old == 0 or pd.isna(old):
                continue
            out[t] = (s.loc[t] - old) / abs(old) * 100.0
        return pd.Series(out)

    series_sources = {
        "mvrv_z":         ("raw",   results["mvrv_z"]["series"]),
        "nupl":           ("raw",   results["nupl"]["series"]),
        "sopr":           ("raw",   results["sopr"]["series"]),
        "lth_trend":      ("pct",   pct_series(results["liveliness"]["series"], 90)),
        "m2_trend":       ("pct",   pct_series(results["m2"]["series"], 84)),   # 12 weeks
        "netliq_trend":   ("pct",   pct_series(results["netliq"]["series"], 28)),
        "dxy_trend":      ("pct",   pct_series(results["dxy"]["series"], 50)),
        "hy_oas":         ("raw",   results["hy_oas"]["series"]),
        "real_yield":     ("raw",   results["real_yield"]["series"]),
        "mnav":           ("raw",   derived.get("mnav_series")),
        "mstr_btc_trend": ("pct",   pct_series(derived.get("mstr_btc_ratio_series"), 50)),
        "funding":        ("raw",   results["funding"]["series"]),
        "ssr":            ("raw",   derived.get("ssr_series")),
    }
    raw_value_for_card = {
        "mvrv_z":         results["mvrv_z"]["value"],
        "nupl":           results["nupl"]["value"],
        "sopr":           results["sopr"]["value"],
        "lth_trend":      derived.get("liveliness_90d_pct"),
        "m2_trend":       derived.get("m2_12w_pct"),
        "netliq_trend":   derived.get("netliq_4w_pct"),
        "dxy_trend":      derived.get("dxy_50d_pct"),
        "hy_oas":         results["hy_oas"]["value"],
        "real_yield":     results["real_yield"]["value"],
        "mnav":           derived.get("mnav"),
        "mstr_btc_trend": derived.get("mstr_btc_50d_pct"),
        "funding":        results["funding"]["value"],
        "ssr":            derived.get("ssr"),
    }
    for key, meta in INDICATOR_META.items():
        _, series = series_sources.get(key, ("none", None))
        series_data = []
        if series is not None and len(series) > 0:
            # Keep up to ~6 years to support 5Y range selector and All view
            s = series.dropna().tail(365 * 6)
            for idx, v in s.items():
                try:
                    d = idx.strftime("%Y-%m-%d")
                except Exception:
                    d = str(idx)
                series_data.append({"d": d, "v": round(float(v), 6)})
        indicators[key] = {
            **meta,
            "value":      raw_value_for_card.get(key),
            "sub_score": score["sub_scores"].get(key),
            "series":    series_data,
        }

    # BTC overlay series for cross-asset correlation context on every chart.
    btc_overlay = []
    btc_s = results["btc_price"]["series"]
    if btc_s is not None and not btc_s.empty:
        # Try to extend BTC history beyond CoinGecko's 365-day window via Yahoo (BTC-USD).
        try:
            import yfinance as _yf
            yh = _yf.Ticker("BTC-USD").history(period="max", auto_adjust=False)
            if not yh.empty:
                yh_s = yh["Close"].dropna()
                yh_s.index = yh_s.index.tz_localize(None) if yh_s.index.tz is not None else yh_s.index
                # Combine: prefer CoinGecko where available, backfill with Yahoo
                combined = yh_s.copy()
                for idx, v in btc_s.items():
                    combined.loc[idx] = v
                btc_s = combined.sort_index()
                logger.info(f"  BTC overlay: extended history via Yahoo to {len(btc_s)} pts")
        except Exception as e:
            logger.warning(f"  BTC overlay Yahoo extension failed (non-fatal): {e}")
        for idx, v in btc_s.tail(365 * 6).items():
            try:
                d = idx.strftime("%Y-%m-%d")
            except Exception:
                d = str(idx)
            btc_overlay.append({"d": d, "v": round(float(v), 2)})

    latest = {
        "timestamp": ts_now.isoformat(),
        "btc_overlay": btc_overlay,
        "composite": score["composite"],
        "regime_label": regime_label(score["composite"]),
        "delta_1w": delta_1w,
        "sub_scores": score["sub_scores"],
        "raw_values": raw,
        "missing": score["missing"],
        "weights_used": score["weights_used"],
        "synthesis": synthesis,
        "indicators": indicators,
        "snapshot": {
            "btc_price": results["btc_price"]["value"],
            "mstr_price": results["mstr"]["value"],
            "mnav": derived.get("mnav"),
            "mstr_btc_holdings": (results.get("mstr_history", {}).get("value")
                                  or results["mstr_btc_holdings"]["value"]),
            "mstr_btc_holdings_stale": (results.get("mstr_history", {}).get("stale", True)
                                        if results.get("mstr_history", {}).get("value")
                                        else results["mstr_btc_holdings"]["stale"]),
            "mstr_btc_holdings_source": (results.get("mstr_history", {}).get("source")
                                         if results.get("mstr_history", {}).get("value")
                                         else results["mstr_btc_holdings"]["source"]),
            "mstr_iv_atm": results["mstr_iv"]["value"],
        },
    }
    latest_json_path = OUT_DIR / "latest.json"
    with open(latest_json_path, "w") as f:
        json.dump(latest, f, indent=2, default=str)
    logger.info(f"  Wrote {latest_json_path}")

    # Build viz
    from viz import render_dashboard
    png_path = ARCHIVE_DIR / f"{run_ts}.png"
    latest_png = OUT_DIR / "latest.png"
    render_dashboard(
        png_path=png_path,
        results=results,
        derived=derived,
        score=score,
        delta_1w=delta_1w,
        synthesis=synthesis,
        history=history,
    )
    # Copy to latest.png
    import shutil
    shutil.copyfile(png_path, latest_png)
    logger.info(f"  Wrote {png_path}")
    logger.info(f"  Wrote {latest_png}")

    print(f"\n=== Result ===")
    print(f"Composite: {score['composite']} ({regime_label(score['composite'])})")
    print(f"1w delta: {delta_1w}")
    print(f"Dashboard: {png_path}")
    print(f"JSON: {latest_json_path}")
    print(f"History: {HISTORY_CSV} ({len(history)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

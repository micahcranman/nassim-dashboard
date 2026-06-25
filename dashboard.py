"""Nassim Dashboard — main orchestrator.

Fetches all indicators, computes derived metrics, scores, writes outputs.
"""
import json
import os
import sys
import warnings
import logging
from datetime import datetime, timezone, date
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


def _cohort_posture(sth_mvrv, sth_sopr):
    """Characterize the short-term-holder ('tourist') cohort from STH-MVRV + STH-SOPR."""
    if sth_mvrv is None:
        return "Unknown"
    sopr = sth_sopr if sth_sopr is not None else 1.0
    if sth_mvrv < 1.0 and sopr < 1.0:
        return "Tourists gone — capitulation"
    if sth_mvrv < 1.15:
        return "Tourists thinning out"
    if sth_mvrv > 1.6 and sopr > 1.05:
        return "Tourists pouring in — euphoria"
    if sth_mvrv > 1.4:
        return "Tourists arriving"
    return "Mixed / mid-cycle"


def _with_fallback(primary, fallback, logger=None, name=""):
    """Return a fetcher that tries `primary` first and falls back to `fallback` on any
    error/None. Used to make Bitcoin Magazine Pro the AUTHORITATIVE primary for the
    cycle-value indicators while keeping the old (flaky) sources as a safety net."""
    def _f():
        try:
            r = primary()
            if r and r.get("value") is not None and not r.get("error"):
                return r
        except Exception as e:
            r = {"error": str(e)}
        try:
            fb = fallback()
        except Exception as e:
            return {"value": None, "series": pd.Series(dtype=float),
                    "timestamp": datetime.now(timezone.utc), "source": "fallback-exception",
                    "label": name, "stale": True, "error": str(e)}
        fb = dict(fb)
        fb["source"] = (fb.get("source", "") + " [BMP-primary failed]").strip()
        if logger:
            logger.warning(f"  {name}: BMP primary unavailable ({r.get('error')}) → fallback {fb.get('source')}")
        return fb
    return _f


def fetch_all(logger):
    """Run all fetchers. Returns dict of indicator name -> result dict."""
    from fetchers import (fred, yahoo, coingecko, onchain, funding,
                          mstr_holdings, mstr_history, checkonchain, feargreed, bmp, rsi, tbl)

    fetchers = [
        ("m2",          fred.fetch_m2),
        ("netliq",      fred.fetch_net_liquidity),
        ("hy_oas",      fred.fetch_hy_oas),
        ("mstr",        yahoo.fetch_mstr),
        ("mstr_shares", yahoo.fetch_mstr_shares),
        ("mstr_shares_hist", yahoo.fetch_mstr_shares_history),
        ("mstr_iv",     yahoo.fetch_mstr_iv_percentile),
        ("btc_price",   coingecko.fetch_btc_price),
        ("btc_mcap",    coingecko.fetch_btc_market_cap),
        # cycle / on-chain — Bitcoin Magazine Pro is the AUTHORITATIVE primary (clean CSV
        # API, full history back to 2010); BGeometrics/alternative.me kept as fallback.
        ("mri",         checkonchain.fetch_mri),
        ("mvrv_z",      _with_fallback(bmp.fetch_mvrv_zscore, onchain.fetch_mvrv_zscore, logger, "mvrv_z")),
        ("nupl",        _with_fallback(bmp.fetch_nupl, onchain.fetch_nupl, logger, "nupl")),
        ("sth_sopr",    onchain.fetch_sth_sopr),
        ("sth_mvrv",    _with_fallback(bmp.fetch_sth_mvrv, onchain.fetch_sth_mvrv, logger, "sth_mvrv")),
        ("feargreed",   _with_fallback(bmp.fetch_fear_greed, feargreed.fetch_fear_greed, logger, "feargreed")),
        ("rsi",         rsi.fetch_btc_rsi),
        ("funding",     funding.fetch_funding_rate),
        ("tbl",         tbl.fetch_tbl_liquidity),  # macro panel; best-effort (Playwright/CI)
        # MSTR holdings (for mNAV)
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
    """Compute derived indicators: mNAV (diluted-shares), trends, MSTR/BTC ratio, and the
    v8.5 strategy-state signals (MA200 slope_5d, days-since-MRI<12, cohort posture)."""
    derived = {}

    # --- mNAV = MSTR market cap / (BTC holdings × BTC price) ---
    # Shares: prefer strategy.com assumed-DILUTED shares (the standard mNAV convention,
    # what Saylor publishes); fall back to yfinance basic shares with a confidence flag.
    mstr_px = results["mstr"]["value"]
    diluted = results.get("mstr_history", {}).get("shares_value")
    basic = results["mstr_shares"]["value"]
    if diluted:
        shares, shares_src, shares_conf = diluted, "strategy.com (diluted)", "high"
    else:
        shares, shares_src, shares_conf = basic, "yfinance (basic)", "low — understates dilution"
    btc_px = results["btc_price"]["value"]
    # Holdings: strategy.com canonical; fall back to bitcointreasuries.net scrape.
    # NOTE: holdings only change when MSTR actually buys BTC, so a within-TTL cache is NOT
    # low-confidence — only an outright fetch error or the hardcoded scrape fallback is.
    holdings_rec = results.get("mstr_history", {})
    if holdings_rec.get("value"):
        btc_holdings = holdings_rec["value"]
        holdings_stale = bool(holdings_rec.get("error"))
    else:
        btc_holdings = results["mstr_btc_holdings"]["value"]
        holdings_stale = bool(results["mstr_btc_holdings"]["stale"])
    derived["mnav_shares_source"] = shares_src
    derived["mnav_shares_confidence"] = shares_conf
    derived["mnav_holdings_stale"] = holdings_stale
    if all(v is not None for v in [mstr_px, shares, btc_px, btc_holdings]):
        mstr_mcap = mstr_px * shares
        btc_value = btc_holdings * btc_px
        mnav = mstr_mcap / btc_value
        derived["mnav"] = mnav
        derived["mnav_confidence"] = "low" if (shares_conf.startswith("low") or holdings_stale) else "high"
        logger.info(f"  Derived: mNAV = {mnav:.3f}  (shares {shares_src}, holdings stale={holdings_stale})")

        # mNAV cross-check / divergence flag. BMP cannot serve a published mNAV (404 + absent
        # from /metrics — see fetchers/bmp.mstr_mnav_available), EODHD fundamentals 403, and
        # bitcointreasuries is an unstable SvelteKit scrape — so there is no free published-mNAV
        # API to diff against. The available authoritative cross-check is the share-count
        # convention: recompute mNAV on yfinance BASIC shares and flag when it diverges >5% from
        # the diluted-convention figure (a large gap = dilution materially moves the read, i.e. a
        # stale/under-counted share figure would be visible rather than silent).
        derived["mnav_xcheck"] = None
        if basic and shares and btc_px and btc_holdings:
            mnav_basic = (mstr_px * basic) / (btc_holdings * btc_px)
            div = abs(mnav - mnav_basic) / mnav if mnav else None
            derived["mnav_xcheck"] = {
                "diluted": round(mnav, 4), "basic_shares": round(mnav_basic, 4),
                "divergence_pct": (round(div * 100, 2) if div is not None else None),
                "flag": bool(div is not None and div > 0.05),
                "published_source": None,  # no free published-mNAV API; see note above
                "note": "diluted vs basic-shares convention (no external published mNAV available)",
            }
            if derived["mnav_xcheck"]["flag"]:
                logger.warning(f"  mNAV cross-check: diluted {mnav:.3f} vs basic {mnav_basic:.3f} "
                               f"→ {derived['mnav_xcheck']['divergence_pct']}% divergence (>5%)")

        # TRUE historical mNAV series, using:
        #   - daily MSTR close (yfinance)
        #   - daily BTC close (coingecko)
        #   - daily MSTR basic shares outstanding (yfinance get_shares_full, daily ffill)
        #   - daily MSTR BTC holdings (strategy.com canonical purchase log, daily ffill step)
        # No constants, no approximation. mNAV_t = (MSTR_close_t * shares_t) / (holdings_t * BTC_t)
        mstr_series = results["mstr"]["series"]
        btc_series = results["btc_price"]["series"]
        # Extend BTC back to 2020 via Yahoo (CoinGecko only gives 365d) so the mNAV series
        # covers the Nov-2024 cycle top, not just the last ~1.5y. Prefer CoinGecko where it
        # overlaps (fresher), backfill the rest with Yahoo BTC-USD.
        try:
            import yfinance as _yf
            _yh = _yf.Ticker("BTC-USD").history(period="max", auto_adjust=False)["Close"].dropna()
            _yh.index = _yh.index.tz_localize(None) if _yh.index.tz is not None else _yh.index
            _combined = _yh.copy()
            for _i, _v in btc_series.items():
                _combined.loc[pd.Timestamp(_i).tz_localize(None) if getattr(pd.Timestamp(_i), "tz", None) else _i] = _v
            btc_series = _combined.sort_index()
            logger.info(f"  mNAV: extended BTC history to {len(btc_series)} pts via Yahoo")
        except Exception as _e:
            logger.warning(f"  mNAV BTC extension failed (non-fatal): {_e}")
        # Shares history: COMBINE two sources so the mNAV series reaches back to 2020.
        #   - strategy.com assumed-diluted shares — accurate convention, but only disclosed
        #     from ~2025 (pre-2025 purchase records carry no shares figure).
        #   - yfinance get_shares_full BASIC shares — back to 2020-01, the only historical
        #     source. Slightly understates dilution but anchors the 2020-2024 cycle (incl.
        #     the Nov-2024 top) which is otherwise missing entirely.
        # Diluted WINS where it exists; basic backfills everything before it.
        mstr_hist = results.get("mstr_history", {})
        diluted_hist = mstr_hist.get("shares_series", pd.Series(dtype=float))
        basic_hist = results.get("mstr_shares_hist", {}).get("series", pd.Series(dtype=float))

        def _norm_sh(s):
            if s is None or len(s) == 0:
                return pd.Series(dtype=float)
            s = s.copy()
            s.index = pd.to_datetime(s.index)
            if s.index.tz is not None:
                s.index = s.index.tz_localize(None)
            s.index = s.index.normalize()
            return s[~s.index.duplicated(keep="last")].dropna()

        diluted_n = _norm_sh(diluted_hist)
        basic_n = _norm_sh(basic_hist)
        # combine_first: diluted where present, basic elsewhere (union of dates; daily ffill below)
        shares_hist = diluted_n.combine_first(basic_n) if not diluted_n.empty else basic_n
        if not diluted_n.empty and not basic_n.empty:
            logger.info(f"  mNAV: shares combined — diluted from {diluted_n.index.min().date()} "
                        f"({len(diluted_n)} pts) over basic from {basic_n.index.min().date()} "
                        f"({len(basic_n)} pts) → {len(shares_hist)} total")
        # NOTE: shares_hist is already split-consistent with the (split-adjusted) yfinance close —
        # the mNAV lands at ≈3.4 at both the 2021 and 2024 cycle tops, matching Strategy's reported
        # premium. (Do NOT re-apply a split factor here; that double-adjusts pre-split dates 10x.)
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
            # Clip to the real TREASURY-COMPANY era. Before ~Jan 2021 MSTR still carried material
            # non-BTC enterprise value (a software company that had only just started buying BTC —
            # EV was ~4-5x its tiny BTC NAV), so "mNAV" then is NOT the BTC-premium metric it is
            # now; that pre-treasury data poisons the top/bottom calibration. Post-Jan-2021 the
            # premium tracks tops cleanly (≈3.4 at both the 2021 and 2024 cycle tops).
            mnav_s = mnav_s[mnav_s.index >= "2021-01-01"]
            derived["mnav_series"] = mnav_s
            logger.info(f"  Derived: mNAV series (TRUE historical) len={len(mnav_s)}, "
                        f"range {mnav_s.min():.2f}-{mnav_s.max():.2f}, latest {mnav_s.iloc[-1]:.3f}")
        else:
            logger.warning("  Derived: mNAV series unavailable (missing component series)")
    else:
        derived["mnav"] = None
        derived["mnav_confidence"] = "unavailable"
        logger.warning("  Derived: mNAV unavailable (missing inputs)")

    # --- Macro trends ---
    derived["m2_12w_pct"] = pct_change_over(results["m2"]["series"], 84)
    derived["netliq_4w_pct"] = pct_change_over(results["netliq"]["series"], 28)

    # --- MSTR/BTC ratio + 50d trend (kept as its own indicator) ---
    mstr_series = results["mstr"]["series"]
    btc_series = results["btc_price"]["series"]
    if not mstr_series.empty and not btc_series.empty:
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

    # --- v8.5 strategy-state signals (the mechanical call) ---
    # MSTR MA200 5-day slope — the hedge gate: <0 admits PUT/SHORT.
    derived["slope_5d"] = None
    derived["ma200"] = None
    derived["slope_5d_series"] = pd.Series(dtype=float)
    ms = mstr_series.dropna().sort_index() if not mstr_series.empty else pd.Series(dtype=float)
    if len(ms) >= 206:
        ma200 = ms.rolling(200).mean()
        # 5-trading-day % slope of MA200 (the structural / hedge-gate signal), full series
        slope_series = ((ma200 - ma200.shift(5)) / ma200.shift(5) * 100.0).dropna()
        derived["slope_5d_series"] = slope_series
        if len(slope_series):
            derived["ma200"] = float(ma200.dropna().iloc[-1])
            derived["slope_5d"] = float(slope_series.iloc[-1])
    derived["hedge_gate_open"] = (derived["slope_5d"] is not None and derived["slope_5d"] < 0)

    # MRI Q-fire gate
    mri_val = results.get("mri", {}).get("value")
    derived["mri"] = mri_val
    derived["mri_below_12"] = (mri_val is not None and mri_val < 12)
    mri_s = results.get("mri", {}).get("series", pd.Series(dtype=float))
    derived["days_since_mri12"] = None
    if mri_s is not None and not mri_s.empty:
        below = mri_s[mri_s < 12]
        if len(below):
            derived["days_since_mri12"] = (pd.Timestamp(date.today()) - pd.Timestamp(below.index[-1])).days

    # IV percentile (t2a PUT keyed on IV ≥ 10th pct)
    derived["iv_pct"] = results.get("mstr_iv", {}).get("value")

    # Cohort posture (tourists in / out) from STH-MVRV + STH-SOPR
    sm = results.get("sth_mvrv", {}).get("value")
    ss = results.get("sth_sopr", {}).get("value")
    derived["sth_mvrv"] = sm
    derived["sth_sopr"] = ss
    derived["cohort_posture"] = _cohort_posture(sm, ss)

    logger.info(f"  Strategy-state: MRI={mri_val} (<12={derived['mri_below_12']}), "
                f"slope_5d={derived['slope_5d']}, hedge_gate={'OPEN' if derived['hedge_gate_open'] else 'closed'}, "
                f"IV%={derived['iv_pct']}, cohort={derived['cohort_posture']!r}")
    return derived


def _pct_series(s, days):
    """Rolling percent change over a calendar-day window (handles irregular sampling)."""
    if s is None or len(s) == 0:
        return pd.Series(dtype=float)
    s = s.dropna().sort_index()
    if len(s) < 3:
        return pd.Series(dtype=float)
    out = {}
    for t in s.index:
        older = s.loc[:t - pd.Timedelta(days=days)]
        if older.empty:
            continue
        old = older.iloc[-1]
        if old == 0 or pd.isna(old):
            continue
        out[t] = (s.loc[t] - old) / abs(old) * 100.0
    return pd.Series(out)


# Indicator -> (display series). pct-trend indicators render their rolling % change.
def _tile_series(results, derived):
    return {
        "mri":            results["mri"]["series"],
        "mvrv_z":         results["mvrv_z"]["series"],
        "nupl":           results["nupl"]["series"],
        "sth_sopr":       results["sth_sopr"]["series"],
        "sth_mvrv":       results["sth_mvrv"]["series"],
        "feargreed":      results["feargreed"]["series"],
        "rsi":            results["rsi"]["series"],
        "mnav":           derived.get("mnav_series"),
        "mstr_btc_trend": _pct_series(derived.get("mstr_btc_ratio_series"), 50),
        "slope_5d":       derived.get("slope_5d_series"),
        "funding":        results["funding"]["series"],
        "tbl_indicator":  results.get("tbl", {}).get("series", pd.Series(dtype=float)),
    }


def build_raw_for_meters(results, derived):
    """indicator -> value for the meters engine."""
    return {
        "mri":            derived.get("mri"),
        "mvrv_z":         results["mvrv_z"]["value"],
        "nupl":           results["nupl"]["value"],
        "sth_sopr":       derived.get("sth_sopr"),
        "sth_mvrv":       derived.get("sth_mvrv"),
        "feargreed":      results["feargreed"]["value"],
        "rsi":            results["rsi"]["value"],
        "mnav":           derived.get("mnav"),
        "funding":        results["funding"]["value"],
        "tbl_indicator":  results.get("tbl", {}).get("value"),
        "mstr_btc_trend": derived.get("mstr_btc_50d_pct"),
        "slope_5d":       derived.get("slope_5d"),
    }


def build_strategy_state(derived):
    """v8.5 mechanical state — the system of record."""
    mri = derived.get("mri")
    slope = derived.get("slope_5d")
    hedge_open = bool(derived.get("hedge_gate_open"))
    days_since = derived.get("days_since_mri12")
    armed = bool(derived.get("mri_below_12") and (days_since is None or days_since >= 30))
    if derived.get("mri_below_12"):
        action = "MRI < 12 — Q-FIRE ARMED" if armed else f"MRI < 12 but {days_since}d since last (need 30d)"
    elif mri is not None:
        action = f"MRI {mri:.1f} — Q-fire arms below 12"
    else:
        action = "MRI unavailable"
    if hedge_open:
        action += " · hedge gate OPEN (PUT/SHORT admitted)"
    return {
        "mri": mri, "mri_threshold": 12, "mri_below_12": bool(derived.get("mri_below_12")),
        "days_since_mri12": days_since, "qfire_armed": armed,
        "slope_5d": slope, "hedge_gate_open": hedge_open,
        "hedge_gate_label": "OPEN" if hedge_open else "CLOSED",
        "iv_pct": derived.get("iv_pct"), "mnav": derived.get("mnav"),
        "mnav_confidence": derived.get("mnav_confidence"),
        "cohort_posture": derived.get("cohort_posture"),
        "next_action": action,
    }


def compute_oscillator_history(results, derived, scoring, mode="current"):
    """Backfill the net-conviction oscillator over ~5y from the daily indicator series,
    so the centerpiece chart has real history (not one point). Returns (list, last-day meters).
    mode='current' (step+AUC) or 'v2' (curve+judgment) — for the A/B page toggle."""
    def _norm(s):
        if s is None or len(s) == 0:
            return None
        s = s.dropna()
        s.index = pd.to_datetime(s.index)
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
        # normalize to calendar day + keep the LAST reading of each day, so intraday series
        # (funding, 8h) score the same value the emitted tile series exposes to the JS scrubber.
        s.index = s.index.normalize()
        s = s.sort_index()
        return s[~s.index.duplicated(keep="last")]

    cols = {
        "mri": _norm(results.get("mri", {}).get("series")),
        "mvrv_z": _norm(results.get("mvrv_z", {}).get("series")),
        "nupl": _norm(results.get("nupl", {}).get("series")),
        "sth_sopr": _norm(results.get("sth_sopr", {}).get("series")),
        "sth_mvrv": _norm(results.get("sth_mvrv", {}).get("series")),
        "feargreed": _norm(results.get("feargreed", {}).get("series")),
        "rsi": _norm(results.get("rsi", {}).get("series")),
        "mnav": _norm(derived.get("mnav_series")),
        "mstr_btc_trend": _norm(_pct_series(derived.get("mstr_btc_ratio_series"), 50)),
        "slope_5d": _norm(derived.get("slope_5d_series")),
        "funding": _norm(results.get("funding", {}).get("series")),
        "tbl_indicator": _norm(results.get("tbl", {}).get("series")),
    }
    cols = {k: v for k, v in cols.items() if v is not None and len(v) > 30}
    if not cols:
        return []
    end = max(v.index.max() for v in cols.values())
    # Anchor the backfill to the MSTR-mNAV TREASURY ERA start (2021-01-01), NOT a rolling 5y
    # window. The old 5y cap (today-1826d ≈ mid-2021) silently chopped off the FEB-2021 mNAV
    # blow-off (premium peaked ~3.41x on 2021-02-09 — the real MSTR cycle top), so the chart
    # never showed it and the model never scored it. Pre-2021 stays excluded (EV-distorted, and
    # mnav_series is clipped there anyway). Indicator tile series already reach ≥2021-01-01, so
    # the JS scrubber can recompute any pinned era date. (era floor avoids unbounded growth vs
    # min-of-all-series, which would drag in pre-treasury 2014-era BTC history.)
    ERA_START = pd.Timestamp("2021-01-01")
    start = max(min(v.index.min() for v in cols.values()), ERA_START)
    idx = pd.date_range(start, end, freq="D")
    df = pd.DataFrame({k: v.reindex(idx).ffill() for k, v in cols.items()})
    nets = []
    for _, rv in df.iterrows():
        raw = {k: (float(rv[k]) if pd.notna(rv[k]) else None) for k in cols}
        nets.append(scoring.compute_meters(raw, mode)["net_conviction"])
    net_s = pd.Series(nets, index=idx)
    smooth = net_s.ewm(span=14, min_periods=1).mean()
    out = []
    for i, t in enumerate(idx):
        if nets[i] is None:
            continue
        out.append({"d": t.strftime("%Y-%m-%d"), "net": nets[i],
                    "smooth": round(float(smooth.iloc[i]), 1)})
    # The most-recent ALIGNED day = the authoritative "now" headline, so the big number matches
    # the last point on the chart (and the scrubber) instead of a separately-computed snapshot
    # that could straddle a zone threshold.
    last_raw = {k: (float(df[k].iloc[-1]) if pd.notna(df[k].iloc[-1]) else None) for k in cols}
    last_meters = scoring.compute_meters(last_raw, mode)
    last_meters["as_of"] = idx[-1].strftime("%Y-%m-%d")
    return out, last_meters


def append_history(meters, strat, results, derived, ts):
    """One row per DAY (downsampled). Overwrites the same-day row on re-runs."""
    day = ts.strftime("%Y-%m-%d")
    row = {
        "date": day, "timestamp": ts.isoformat(),
        "net_conviction": meters.get("net_conviction"),
        "bull_sum": meters.get("bull_sum"), "bear_sum": meters.get("bear_sum"),
        "zone": meters.get("zone"), "mri": strat.get("mri"),
        "slope_5d": strat.get("slope_5d"), "mnav": derived.get("mnav"),
        "btc_price": results["btc_price"]["value"], "mstr_price": results["mstr"]["value"],
    }
    if HISTORY_CSV.exists():
        df = pd.read_csv(HISTORY_CSV)
        if "net_conviction" not in df.columns:
            # old-schema history (composite era) — archive and start fresh
            try:
                df.to_csv(HISTORY_CSV.with_suffix(".legacy.csv"), index=False)
            except Exception:
                pass
            df = pd.DataFrame(columns=list(row.keys()))
        if "date" in df.columns:
            df = df[df["date"] != day]
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    df.to_csv(HISTORY_CSV, index=False)
    return df


def _series_to_points(series, decimals=6, years=6):
    out = []
    if series is None or len(series) == 0:
        return out
    s = series.dropna()
    # Collapse any intraday / duplicate-day points to ONE per calendar day (keep last). funding is
    # 8h-granular; emitting 3 points/day made the JS scrubber's valAt (matches on the YYYY-MM-DD
    # string) read a different value than the daily backend pipeline scores → a pinned-date driver
    # bar that disagreed with the headline. One-per-day keeps them in lockstep (and tail() then
    # counts DAYS, not raw points, so the window length is right for intraday series too).
    try:
        s.index = pd.to_datetime(s.index)
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
        s.index = s.index.normalize()
        s = s.sort_index()
        s = s[~s.index.duplicated(keep="last")]
    except Exception:
        pass
    for idx, v in s.tail(365 * years).items():
        try:
            d = idx.strftime("%Y-%m-%d")
        except Exception:
            d = str(idx)
        out.append({"d": d, "v": round(float(v), decimals)})
    return out


def main():
    run_ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    logger, log_path = setup_logger(run_ts)
    logger.info(f"=== Nassim Dashboard run {run_ts} ===")
    logger.info("Fetching indicators...")
    results = fetch_all(logger)
    logger.info("Computing derived indicators...")
    derived = compute_derived(results, logger)

    logger.info("Scoring (signed net-conviction oscillator)...")
    import scoring
    raw = build_raw_for_meters(results, derived)
    # Compute BOTH models so the page can A/B toggle: "current" (step bands + AUC directional
    # weights) and "v2" (curve interpolation + MSTR-specific judgment weights). Each adopts its
    # own most-recent ALIGNED oscillator day as the headline (consistent with its chart).
    def _build(mode):
        m = scoring.compute_meters(raw, mode)
        m["verdict"] = scoring.verdict(m["net_conviction"])
        osc, last = compute_oscillator_history(results, derived, scoring, mode)
        if last and last.get("net_conviction") is not None:
            last["verdict"] = scoring.verdict(last["net_conviction"])
            m = last
        return m, osc
    meters, oscillator = _build("current")
    meters_v2, oscillator_v2 = _build("v2")
    logger.info(f"  Models: current net {meters['net_conviction']} ({meters['label']}) · "
                f"v2 net {meters_v2['net_conviction']} ({meters_v2['label']})")
    strat = build_strategy_state(derived)
    logger.info(f"  Net={meters['net_conviction']} (bull {meters['bull_sum']} / bear {meters['bear_sum']}) "
                f"→ {meters['zone']} = {meters['verdict']} ({meters['read']})")

    ts_now = datetime.now()
    history = append_history(meters, strat, results, derived, ts_now)
    logger.info(f"  History rows (daily): {len(history)}")

    # net delta vs ~7d ago (from history)
    delta_7d = None
    try:
        h = history.copy()
        h["date"] = pd.to_datetime(h["date"])
        prior = h[h["date"] <= (pd.Timestamp(date.today()) - pd.Timedelta(days=7))]
        if not prior.empty and meters["net_conviction"] is not None:
            delta_7d = round(meters["net_conviction"] - float(prior["net_conviction"].iloc[-1]), 1)
    except Exception:
        pass

    logger.info(f"  Oscillator history points: {len(oscillator)}")

    # indicator tiles
    try:
        from indicator_meta import INDICATOR_META
    except Exception:
        INDICATOR_META = {}
    tiles = _tile_series(results, derived)
    contrib = meters["contributions"]
    macro_contrib = meters.get("macro_contributions", {})
    indicators = {}
    for key, series in tiles.items():
        meta = INDICATOR_META.get(key, {"label": key.replace("_", " ").title()})
        # core score lives in contributions; macro indicators carry theirs in macro_contributions
        c = contrib.get(key) or macro_contrib.get(key, {})
        decimals = 2 if key in ("mri", "feargreed") else 4
        indicators[key] = {
            "label": meta.get("label", key),
            "category": meta.get("category", ""),
            "value_fmt": meta.get("value_fmt", ".2f"),
            "value_suffix": meta.get("value_suffix", ""),
            "explanation": meta.get("explanation", ""),
            "use": meta.get("use", ""),
            "regime_bands": meta.get("regime_bands", []),
            "value": raw.get(key),
            "score": c.get("score"),
            # 7yr ≥ the oscillator's era-anchored backfill (now 2021-01-01 → today, ~5.5y and
            # growing), so the JS scrubber recomputes the SAME conviction the oscillator shows
            # for any pinned date — including the FEB-2021 mNAV top. (Was 6yr vs a 5y oscillator;
            # bumped to keep margin as the era window grows past 6y.)
            "series": _series_to_points(series, decimals=decimals, years=7),
        }

    # BTC overlay (extended via Yahoo for long history)
    btc_s = results["btc_price"]["series"]
    if btc_s is not None and not btc_s.empty:
        try:
            import yfinance as _yf
            yh = _yf.Ticker("BTC-USD").history(period="max", auto_adjust=False)
            if not yh.empty:
                yh_s = yh["Close"].dropna()
                yh_s.index = yh_s.index.tz_localize(None) if yh_s.index.tz is not None else yh_s.index
                combined = yh_s.copy()
                for idx, v in btc_s.items():
                    combined.loc[idx] = v
                btc_s = combined.sort_index()
        except Exception as e:
            logger.warning(f"  BTC overlay Yahoo extension failed (non-fatal): {e}")
    # Trim price lines to the MSTR-era (first BTC buy Aug 2020); earlier is noise.
    _ERA = pd.Timestamp("2020-08-01")
    def _era(s):
        if s is None or len(s) == 0:
            return s
        s = s.copy(); s.index = pd.to_datetime(s.index)
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
        return s[s.index >= _ERA]
    btc_overlay = _series_to_points(_era(btc_s), decimals=2)
    mstr_line = _series_to_points(_era(results["mstr"]["series"]), decimals=2)

    # data health (for the age badge)
    health = []
    for name in ["mri", "mvrv_z", "nupl", "sth_sopr", "sth_mvrv", "feargreed", "rsi",
                 "funding", "tbl", "mstr", "btc_price", "mstr_history"]:
        r = results.get(name, {})
        health.append({"name": name, "stale": bool(r.get("stale")),
                       "source": r.get("source", ""), "error": r.get("error")})

    # v8.5 backtest signals (Phase 3 + simulator): committed docs/signals.json from the
    # backtest (scripts/build_signals.py). Enriched object: {markers, trades, equity_curve,
    # backtest}. markers → the MSTR signal chart (Q-fire longs, PUT/SHORT hedges, t1b exits);
    # the rest → latest.simulator for the client-side v8.5 STRATEGY SIMULATOR (replay any
    # start date / starting capital, mark open positions to market at the live price).
    signals, simulator = [], None
    for sp in (REPO_ROOT / "docs" / "signals.json", REPO_ROOT / "signals.json"):
        try:
            if sp.exists():
                obj = json.loads(sp.read_text())
                if isinstance(obj, dict):  # enriched schema
                    signals = obj.get("markers", [])
                    simulator = {"trades": obj.get("trades", []),
                                 "equity_curve": obj.get("equity_curve", []),
                                 "backtest": obj.get("backtest", {})}
                    logger.info(f"  Loaded v8.5 signals from {sp.name}: {len(signals)} markers, "
                                f"{len(simulator['trades'])} trades, "
                                f"{len(simulator['equity_curve'])} equity pts")
                else:  # legacy flat array
                    signals = obj
                    logger.info(f"  Loaded {len(signals)} v8.5 signal markers from {sp.name} (legacy)")
                break
        except Exception as e:
            logger.warning(f"  signals.json load failed ({sp}): {e}")

    # Calibration methodology (Phase 2 panel): measured top/bottom skill per indicator +
    # zone thresholds + each indicator's signed band & current weight, so the in-app
    # CALIBRATION panel can render the whole methodology (the .md won't open for Micah).
    scoring_cfg = scoring.export_config()
    calibration = None
    try:
        audit = json.loads((REPO_ROOT / "calibration_audit.json").read_text())
        # tag each core/macro row with its live band + zone thresholds so the panel is self-contained
        bands = scoring_cfg.get("bands", {})
        for row in audit.get("core", []) + audit.get("macro", []):
            row["band"] = bands.get(row["key"])
        calibration = {
            "audit": audit,
            "zones": scoring_cfg.get("zones"),
            "zone_defs": [
                {"label": "LONG-CAPITULATION", "min": 65, "max": 100, "zone": "LONG",
                 "desc": "cycle bottom — value clusters saturate together"},
                {"label": "LONG-LOCAL", "min": 28, "max": 64, "zone": "LONG",
                 "desc": "local oversold / a lone bottom-caller firing"},
                {"label": "NEUTRAL", "min": -27, "max": 27, "zone": "NEUTRAL",
                 "desc": "mid-cycle, no directional edge"},
                {"label": "SHORT-LOCAL", "min": -64, "max": -28, "zone": "SHORT",
                 "desc": "local top / a lone top-caller firing"},
                {"label": "SHORT-TOP", "min": -100, "max": -65, "zone": "SHORT",
                 "desc": "cycle top — BTC-cycle + MSTR-structural clusters align"},
            ],
            "local_vs_cycle": ("LOCAL vs CYCLE: a lone signal saturating reads as a LOCAL extreme "
                               "(score lands ~±40/60); a CYCLE extreme requires multiple correlated "
                               "callers saturating together so the weighted net pushes past ±65."),
        }
    except Exception as e:
        logger.warning(f"  calibration_audit.json load failed (non-fatal): {e}")

    # TBL Liquidity section (replaces the retired macro panel): the liquidity LEVEL (score 0-100),
    # the Cycle oscillator (±8), the Indicator (±0.3 = slope of the cycle) and its reconstructed
    # buy/sell dots (zero-crossings). The indicator also feeds the conviction (as tbl_indicator);
    # the dots also overlay the MSTR price chart. From TBL's public Supabase history tables.
    tbl_res = results.get("tbl", {})
    tbl_block = {
        "score": tbl_res.get("score"), "indicator": tbl_res.get("value"), "cycle": tbl_res.get("cycle"),
        "stale": bool(tbl_res.get("stale")), "source": tbl_res.get("source"),
        "dots": tbl_res.get("dots", []),
        "score_series": _series_to_points(tbl_res.get("score_series"), decimals=2, years=6),
        "cycle_series": _series_to_points(tbl_res.get("cycle_series"), decimals=3, years=6),
        "indicator_series": _series_to_points(tbl_res.get("series"), decimals=4, years=6),
    }

    latest = {
        "timestamp": ts_now.isoformat(),
        "strategy_state": strat,
        "meters": meters,
        "meters_v2": meters_v2,
        "tbl": tbl_block,
        "signals": signals,
        "simulator": simulator,
        "scoring_config": scoring_cfg,
        "calibration": calibration,
        "net_delta_7d": delta_7d,
        "zones": {"long": scoring.LONG_ZONE, "short": -scoring.SHORT_ZONE},
        "oscillator": oscillator,
        "oscillator_v2": oscillator_v2,
        "indicators": indicators,
        "btc_overlay": btc_overlay,
        "mstr_line": mstr_line,
        "snapshot": {
            "btc_price": results["btc_price"]["value"],
            "mstr_price": results["mstr"]["value"],
            "mnav": derived.get("mnav"),
            "mnav_confidence": derived.get("mnav_confidence"),
            "mnav_shares_source": derived.get("mnav_shares_source"),
            "mnav_convention": "common-equity diluted",  # mktcap(diluted shares)/BTC-NAV — matches
            # bitcointreasuries.net's "diluted mNAV". NOT Strategy's headline EV-mNAV (which adds
            # convert debt + preferred − cash and reads ~0.3-0.4x higher). See mnav_xcheck.
            "mnav_xcheck": derived.get("mnav_xcheck"),
            "mstr_btc_holdings": (results.get("mstr_history", {}).get("value")
                                  or results["mstr_btc_holdings"]["value"]),
            "mstr_btc_holdings_stale": derived.get("mnav_holdings_stale"),
            "mstr_iv_atm": results["mstr_iv"]["value"],
        },
        "data_health": health,
    }
    # Sanitize NaN/inf → null so the browser-facing JSON is always parseable. Python's
    # json.dump emits a literal `NaN`/`Infinity` (invalid JSON) by default, which would make
    # the live site's JSON.parse throw and the whole dashboard render blank. allow_nan=False
    # then guarantees we never silently ship an unparseable file (it raises instead).
    def _clean(o):
        if isinstance(o, float):
            return None if (o != o or o in (float("inf"), float("-inf"))) else o
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_clean(v) for v in o]
        return o
    latest_json_path = OUT_DIR / "latest.json"
    with open(latest_json_path, "w") as f:
        json.dump(_clean(latest), f, indent=2, default=str, allow_nan=False)
    logger.info(f"  Wrote {latest_json_path}")

    print(f"\n=== Result ===")
    print(f"Net conviction: {meters['net_conviction']} → {meters['zone']} ({meters['read']}, conf {meters['confidence']})")
    print(f"Strategy state: {strat['next_action']}")
    print(f"JSON: {latest_json_path}  ({len(oscillator)} oscillator pts)")
    print(f"History: {HISTORY_CSV} ({len(history)} daily rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

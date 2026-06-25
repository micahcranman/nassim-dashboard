"""The Bitcoin Layer (TBL) — liquidity score, cycle, and the buy/sell indicator.

Source: TBL's PUBLIC Supabase REST tables (anon key baked into their JS bundle; RLS-readable).
Three series, all daily:
  - tbl_liquidity_history.score            : 0-100 liquidity LEVEL (the tide), history to 2008
  - tbl_cycle_history.cycle_smooth/_raw    : the TBL Liquidity Cycle oscillator (+/-8)
  - tbl_cycle_history.indicator_slope      : the TBL Liquidity Indicator (+/-0.3) = slope of the
                                             cycle. Its ZERO-CROSSINGS are the green(buy)/red(sell)
                                             "confirmed dots". History from 2024-03-17 (~2.3yr).

(The recent-only tbl_liquidity_scores table — 71 rows, anon-RLS'd to ~3mo — is NOT used here;
the *_history tables expose the full series.)

Roles in the dashboard:
  - indicator_slope  -> the "what now" CONVICTION input (liquidity-momentum; level vs momentum is
    exactly why the score sits >50 for years while this oscillates). Scored in scoring.py as 'tbl_indicator'.
  - score + cycle + dots -> the dedicated TBL Liquidity SECTION (recreates TBL's chart).

Standard contract; `value` = latest indicator_slope (the scored quantity). Extra fields carry the
score, cycle, and reconstructed dots for the section. Last-good fallback; never raises.
Public anon key overridable via TBL_SUPABASE_URL / TBL_SUPABASE_KEY.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

from . import lastgood

_KEY = "tbl"
_LABEL = "TBL Liquidity"
_DEFAULT_URL = "https://gqtjolzuoxvlqpupbsvp.supabase.co"
_DEFAULT_ANON = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdxdGpvbHp1b3h2bHFwdXBic3ZwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDkxMzg1MDEsImV4cCI6MjA2NDcxNDUwMX0"
    ".ArPtf7KT0AgKeKpM7rSVmonwsalPvOdHtqbZrrIx1BY"
)
_TIMEOUT = 30
# only need recent era for the dashboard; cycle/indicator start 2024-03 anyway
_FROM = "2020-01-01"


def _hdr():
    anon = os.environ.get("TBL_SUPABASE_KEY", _DEFAULT_ANON)
    return {"apikey": anon, "Authorization": f"Bearer {anon}", "Accept": "application/json"}


def _base():
    return os.environ.get("TBL_SUPABASE_URL", _DEFAULT_URL).rstrip("/") + "/rest/v1"


def _series(table, col, from_date=_FROM):
    # Supabase hard-caps responses at 1000 rows, so order DESC to always get the most-recent
    # window (then re-sort ascending). 1000 daily rows ≈ 2.7yr, ample for the dashboard.
    rows = requests.get(f"{_base()}/{table}", headers=_hdr(),
                        params={"select": f"date,{col}", "date": f"gte.{from_date}",
                                "order": "date.desc", "limit": "1000"}, timeout=_TIMEOUT).json()
    s = pd.Series({pd.to_datetime(r["date"]).normalize(): r[col]
                   for r in rows if r.get(col) is not None and r.get("date")}).sort_index()
    return pd.to_numeric(s[~s.index.duplicated(keep="last")], errors="coerce").dropna()


def reconstruct_dots(indicator: pd.Series, confirm_days: int = 0) -> list:
    """Buy/sell dots = zero-crossings of indicator_slope. Up-cross -> BUY (green, liquidity
    momentum turning up), down-cross -> SELL (red). Optional confirm: require the new sign to
    persist `confirm_days` before emitting (TBL's 'Confirmed Dots')."""
    if indicator is None or indicator.empty:
        return []
    s = indicator.dropna()
    sign = np.sign(s).replace(0, np.nan).ffill()
    crossed = sign.ne(sign.shift())
    dots = []
    for d in s.index[crossed.fillna(False)]:
        kind = "BUY" if sign.loc[d] > 0 else "SELL"
        if confirm_days > 0:
            window = sign.loc[d:].iloc[:confirm_days + 1]
            if not (window == sign.loc[d]).all():
                continue
        dots.append({"date": d.strftime("%Y-%m-%d"), "type": kind, "slope": round(float(s.loc[d]), 4)})
    return dots


def _pack_stale(err):
    lg = lastgood.load(_KEY)
    base = {"series": pd.Series(dtype=float), "score": None, "score_series": pd.Series(dtype=float),
            "cycle": None, "cycle_series": pd.Series(dtype=float), "dots": [],
            "label": _LABEL, "stale": True, "error": err}
    if lg is not None:
        base.update({"value": float(lg["value"]), "timestamp": lastgood.parse_ts(lg),
                     "source": "thebitcoinlayer (last-good)", "score": lg.get("score")})
        return base
    base.update({"value": None, "timestamp": datetime.now(timezone.utc), "source": "thebitcoinlayer"})
    return base


def fetch_tbl_liquidity() -> dict:
    try:
        cyc = requests.get(f"{_base()}/tbl_cycle_history", headers=_hdr(),
                           params={"select": "date,cycle_smooth,cycle_raw,indicator_slope",
                                   "order": "date.asc", "limit": "20000"}, timeout=_TIMEOUT).json()
        if not isinstance(cyc, list) or not cyc:
            raise RuntimeError("empty tbl_cycle_history")
        idx = pd.to_datetime([r["date"] for r in cyc]).normalize()
        ind = pd.to_numeric(pd.Series([r.get("indicator_slope") for r in cyc], index=idx), errors="coerce").dropna()
        cycle = pd.to_numeric(pd.Series([r.get("cycle_smooth") for r in cyc], index=idx), errors="coerce").dropna()
        try:
            score = _series("tbl_liquidity_history", "score")
        except Exception:
            score = pd.Series(dtype=float)
        if ind.empty:
            raise RuntimeError("no indicator_slope")
        dots = reconstruct_dots(ind)
        ind_latest = float(ind.iloc[-1])
        score_latest = float(score.iloc[-1]) if not score.empty else None
        ts = ind.index[-1].to_pydatetime()
        lastgood.save(_KEY, ind_latest, ts, score=score_latest)
        return {"value": ind_latest, "series": ind, "timestamp": ts,
                "source": "thebitcoinlayer (supabase)", "label": _LABEL, "stale": False, "error": None,
                "score": score_latest, "score_series": score, "cycle": float(cycle.iloc[-1]) if not cycle.empty else None,
                "cycle_series": cycle, "dots": dots}
    except Exception as e:
        return _pack_stale(f"TBL fetch failed: {e}")


if __name__ == "__main__":
    r = fetch_tbl_liquidity()
    print(f"{r['label']}: indicator={r['value']} score={r.get('score')} "
          f"cycle={r.get('cycle')} stale={r['stale']}")
    print(f"  indicator_slope: {len(r['series'])} pts"
          + (f" {r['series'].index[0].date()}→{r['series'].index[-1].date()}" if len(r['series']) else ""))
    print(f"  score series: {len(r['score_series'])} pts, dots: {len(r['dots'])}")
    for d in r["dots"][-6:]:
        print(f"    {d['date']}  {d['type']}  slope={d['slope']:+.4f}")
    if r["error"]:
        print("  note:", r["error"])

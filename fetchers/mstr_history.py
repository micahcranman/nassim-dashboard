"""Official MSTR (Strategy) BTC purchase + share history.

Source: https://www.strategy.com/purchases  (Next.js __NEXT_DATA__ embed)

Pulls every disclosed purchase event with:
  - date_of_purchase
  - btc_holdings (cumulative after this purchase)
  - assumed_diluted_shares_outstanding (when disclosed)
  - basic_shares_outstanding (when disclosed)
  - average_price, total_purchase_price, etc.

Builds two daily step-function series indexed back to the first purchase
(Aug 2020):
  - holdings_series:  forward-fill cumulative BTC after each disclosure
  - shares_series:    forward-fill assumed_diluted shares outstanding

For early dates where assumed_diluted_shares is None (2020-2021 records
predate disclosure of the diluted figure), we fall back to basic_shares.
If both are None for a record, we leave gaps and forward-fill from the
prior known value. This is the same logic Strategy itself uses on the
public chart page.

This is the authoritative data — no approximation. Used to build a true
historical mNAV series in dashboard.py.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import pandas as pd
import requests

URL = "https://www.strategy.com/purchases"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)
_CACHE_PATH = _CACHE_DIR / "mstr_history.json"
_CACHE_TTL_HOURS = 6


def _load_cache():
    if not _CACHE_PATH.exists():
        return None
    age_h = (datetime.now() - datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime)).total_seconds() / 3600
    if age_h > _CACHE_TTL_HOURS:
        return None
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return None


def _save_cache(records):
    try:
        _CACHE_PATH.write_text(json.dumps(records))
    except Exception:
        pass


def _scrape():
    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError("__NEXT_DATA__ not found on strategy.com/purchases")
    data = json.loads(m.group(1))
    arr = data["props"]["pageProps"]["bitcoinData"]
    if not arr:
        raise RuntimeError("empty bitcoinData array")
    # Keep only the fields we need
    slim = []
    for rec in arr:
        slim.append({
            "date": rec.get("date_of_purchase"),
            "btc_holdings": rec.get("btc_holdings"),
            "assumed_diluted_shares": rec.get("assumed_diluted_shares_outstanding"),
            "basic_shares": rec.get("basic_shares_outstanding"),
            "purchase_price": rec.get("purchase_price"),
            "average_price": rec.get("average_price"),
        })
    return slim


def fetch_mstr_purchase_history() -> dict:
    """Return canonical MSTR purchase history.

    Returns:
        {
          "holdings_series": pd.Series[date -> int btc_holdings] (daily step, forward-filled),
          "shares_series":   pd.Series[date -> float shares]     (daily step, forward-filled),
          "events": DataFrame of all purchase events (one row per disclosure),
          "value": current latest holdings (int),
          "shares_value": current latest shares (float),
          "source": "strategy.com/purchases",
          "stale": False / True,
          "timestamp": datetime,
          "label": "MSTR BTC Holdings (canonical)",
          "error": None / str,
        }
    """
    cached = _load_cache()
    used_cache = False
    if cached:
        records = cached
        used_cache = True
    else:
        try:
            records = _scrape()
            _save_cache(records)
        except Exception as e:
            # Last-ditch: use stale cache if any exists
            if _CACHE_PATH.exists():
                try:
                    records = json.loads(_CACHE_PATH.read_text())
                    used_cache = True
                except Exception:
                    return _error_result(str(e))
            else:
                return _error_result(str(e))

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    if df.empty:
        return _error_result("no usable records")

    # Build daily date index from first purchase to today
    start = df["date"].min().normalize()
    today = pd.Timestamp(date.today())
    idx = pd.date_range(start, today, freq="D")

    # Holdings: forward-fill from each purchase event
    hold = df.set_index("date")["btc_holdings"].astype(float)
    hold = hold[~hold.index.duplicated(keep="last")]
    holdings_series = hold.reindex(idx, method="ffill")
    holdings_series.name = "btc_holdings"

    # Shares: prefer assumed_diluted, fall back to basic
    shares = df["assumed_diluted_shares"].fillna(df["basic_shares"]).astype(float)
    shares = pd.Series(shares.values, index=df["date"].values)
    shares = shares[~shares.index.duplicated(keep="last")]
    shares = shares.dropna()  # drop dates with no disclosure
    shares_series = shares.reindex(idx).ffill()
    shares_series.name = "shares_outstanding"

    latest_holdings = float(holdings_series.iloc[-1])
    latest_shares = float(shares_series.iloc[-1]) if shares_series.notna().any() else None

    return {
        "holdings_series": holdings_series,
        "shares_series": shares_series,
        "events": df,
        "value": latest_holdings,
        "shares_value": latest_shares,
        "source": "strategy.com/purchases" + (" [cache]" if used_cache else ""),
        "stale": used_cache,
        "timestamp": datetime.now(timezone.utc),
        "label": "MSTR BTC Holdings (canonical)",
        "error": None,
    }


def _error_result(err: str) -> dict:
    return {
        "holdings_series": pd.Series(dtype=float),
        "shares_series": pd.Series(dtype=float),
        "events": pd.DataFrame(),
        "value": None,
        "shares_value": None,
        "source": "strategy.com/purchases [FAILED]",
        "stale": True,
        "timestamp": datetime.now(timezone.utc),
        "label": "MSTR BTC Holdings (canonical)",
        "error": err,
    }


if __name__ == "__main__":
    r = fetch_mstr_purchase_history()
    print(f"{r['label']}: holdings={r['value']!r}, shares={r['shares_value']!r}, stale={r['stale']}")
    if r["error"]:
        print(f"  ERROR: {r['error']}")
    hs = r["holdings_series"]
    ss = r["shares_series"]
    print(f"  Holdings series: {len(hs)} days, range {hs.index[0].date()} -> {hs.index[-1].date()}")
    print(f"  Shares series:   {ss.notna().sum()} populated of {len(ss)} days")
    print(f"  Events:          {len(r['events'])} purchase disclosures")
    print(f"  First 3 events:")
    print(r["events"].head(3)[["date", "btc_holdings", "assumed_diluted_shares", "basic_shares"]])
    print(f"  Last 3 events:")
    print(r["events"].tail(3)[["date", "btc_holdings", "assumed_diluted_shares", "basic_shares"]])

"""Yahoo Finance fetchers via yfinance."""
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone


def _wrap(ticker: str, label: str, period: str = "1y"):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period, auto_adjust=False)
        if hist.empty:
            raise RuntimeError(f"empty history for {ticker}")
        s = hist["Close"].dropna()
        s.index = s.index.tz_localize(None) if s.index.tz is not None else s.index
        return {
            "value": float(s.iloc[-1]),
            "series": s,
            "timestamp": s.index[-1].to_pydatetime(),
            "source": f"Yahoo:{ticker}",
            "label": label,
            "stale": False,
            "error": None,
        }
    except Exception as e:
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": f"Yahoo:{ticker}", "label": label,
            "stale": True, "error": str(e),
        }


def fetch_dxy():
    return _wrap("DX-Y.NYB", "US Dollar Index (DXY)")


def fetch_mstr():
    # Need full history back to 2020-08 to compute historical mNAV
    return _wrap("MSTR", "MSTR Price", period="max")


def fetch_mstr_shares():
    """MSTR shares outstanding from yfinance info."""
    try:
        t = yf.Ticker("MSTR")
        info = t.info
        shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        if not shares:
            raise RuntimeError("sharesOutstanding not available")
        return {
            "value": float(shares),
            "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": "Yahoo:MSTR.info",
            "label": "MSTR Shares Outstanding",
            "stale": False,
            "error": None,
        }
    except Exception as e:
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": "Yahoo:MSTR.info", "label": "MSTR Shares Outstanding",
            "stale": True, "error": str(e),
        }


def fetch_mstr_shares_history():
    """MSTR daily basic shares outstanding back to 2020, split-adjusted.

    Source: yfinance get_shares_full() returns ACTUAL historical shares
    (not split-adjusted). yfinance price history (auto_adjust=False) is
    nevertheless still split-adjusted on Yahoo's side. To keep mNAV math
    consistent (mcap = price * shares), we multiply pre-split shares by
    the cumulative split ratio of all splits AFTER that date.
    """
    try:
        t = yf.Ticker("MSTR")
        s = t.get_shares_full(start="2020-01-01")
        if s is None or len(s) == 0:
            raise RuntimeError("get_shares_full returned empty")
        # Convert timezone-aware index to date-only
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        s = s.groupby(s.index).last()  # collapse duplicate days
        s = s.astype(float)

        # Apply split adjustment: for each date d, multiply by product of all
        # split ratios with split_date > d.
        splits = t.splits.copy()
        if splits is not None and len(splits) > 0:
            splits.index = pd.to_datetime(splits.index).tz_localize(None).normalize()
            # For each share-date, cumulative ratio of splits AFTER it
            def _ratio_after(date):
                future = splits[splits.index > date]
                if len(future) == 0:
                    return 1.0
                r = 1.0
                for v in future.values:
                    r *= float(v)
                return r
            ratios = pd.Series([_ratio_after(d) for d in s.index], index=s.index)
            s = s * ratios
        s.name = "mstr_shares"
        # Daily forward-fill
        idx = pd.date_range(s.index.min(), pd.Timestamp.today().normalize(), freq="D")
        daily = s.reindex(idx).ffill()
        return {
            "value": float(daily.iloc[-1]),
            "series": daily,
            "timestamp": datetime.now(timezone.utc),
            "source": "yfinance:get_shares_full",
            "label": "MSTR Shares Outstanding (daily)",
            "stale": False,
            "error": None,
        }
    except Exception as e:
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": "yfinance:get_shares_full",
            "label": "MSTR Shares Outstanding (daily)",
            "stale": True, "error": str(e),
        }


def fetch_mstr_iv_percentile():
    """ATM IV from nearest monthly expiry, percentile vs 252d.

    NOTE: yfinance options only gives current snapshot, no history.
    For v1: return current ATM IV without percentile (need to accrue history).
    """
    try:
        t = yf.Ticker("MSTR")
        spot = t.history(period="1d")["Close"].iloc[-1]
        expiries = t.options
        if not expiries:
            raise RuntimeError("no options expiries available")
        # Pick nearest expiry at least 7d out
        from datetime import datetime as dt
        today = dt.now().date()
        chosen = None
        for e in expiries:
            d = dt.strptime(e, "%Y-%m-%d").date()
            if (d - today).days >= 7:
                chosen = e
                break
        if not chosen:
            chosen = expiries[0]
        chain = t.option_chain(chosen)
        calls = chain.calls
        if calls.empty:
            raise RuntimeError("empty call chain")
        # ATM = closest strike to spot
        calls = calls.copy()
        calls["dist"] = (calls["strike"] - spot).abs()
        atm = calls.sort_values("dist").iloc[0]
        iv = float(atm["impliedVolatility"])
        return {
            "value": iv,
            "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": f"Yahoo:MSTR options {chosen}",
            "label": "MSTR ATM IV (current)",
            "stale": False,
            "error": None,
            "note": "Percentile requires accrued history (TBD)",
        }
    except Exception as e:
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": "Yahoo:MSTR options", "label": "MSTR ATM IV",
            "stale": True, "error": str(e),
        }


if __name__ == "__main__":
    for fn in [fetch_dxy, fetch_mstr, fetch_mstr_shares, fetch_mstr_iv_percentile]:
        r = fn()
        print(f"{r['label']}: {r['value']} @ {r['timestamp']} (stale={r['stale']})")
        if r.get("error"):
            print(f"  ERROR: {r['error']}")

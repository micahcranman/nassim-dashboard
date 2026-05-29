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
    return _wrap("MSTR", "MSTR Price")


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

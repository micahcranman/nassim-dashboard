"""BTC RSI-14 — momentum oscillator (Wilder's smoothing) on daily BTC close.

A pure-momentum read to complement the value/cohort cluster: RSI is overbought (>70) at
blow-off tops and oversold (<30) at capitulation, so as a SIGNED score it leans short when
hot and long when cold — a fast, model-free transition signal that the slow on-chain
value metrics lag. Computed from BTC-USD daily close (yfinance, full history), so it has
the same deep backfill the oscillator needs. Standard contract + last-good fallback.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from . import lastgood

_KEY = "rsi"
_PERIOD = 14


def _wilder_rsi(close: pd.Series, period: int = _PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder's smoothing == EMA with alpha = 1/period
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # all-gains window → avg_loss 0 → rs inf → rsi 100
    rsi = rsi.where(avg_loss != 0, 100.0)
    return rsi.dropna()


def fetch_btc_rsi() -> dict:
    label = "BTC RSI-14"
    try:
        import yfinance as yf
        hist = yf.Ticker("BTC-USD").history(period="max", auto_adjust=False)
        close = hist["Close"].dropna()
        if close.index.tz is not None:
            close.index = close.index.tz_localize(None)
        close.index = close.index.normalize()
        close = close[~close.index.duplicated(keep="last")]
        if len(close) < _PERIOD + 5:
            raise RuntimeError(f"insufficient BTC history ({len(close)} pts)")
        s = _wilder_rsi(close)
        if s.empty:
            raise RuntimeError("empty RSI series")
        s.name = _KEY
        latest = float(s.iloc[-1])
        ts_latest = s.index[-1].to_pydatetime()
        lastgood.save(_KEY, latest, ts_latest)
        return {"value": latest, "series": s, "timestamp": ts_latest,
                "source": "yfinance BTC-USD (RSI-14)", "label": label,
                "stale": False, "error": None}
    except Exception as e:
        lg = lastgood.load(_KEY)
        if lg is not None:
            return {"value": float(lg["value"]), "series": pd.Series(dtype=float),
                    "timestamp": lastgood.parse_ts(lg),
                    "source": "yfinance BTC-USD (RSI-14, last-good)", "label": label,
                    "stale": True, "error": str(e)}
        return {"value": None, "series": pd.Series(dtype=float),
                "timestamp": datetime.now(timezone.utc),
                "source": "yfinance BTC-USD (RSI-14)", "label": label,
                "stale": True, "error": str(e)}


if __name__ == "__main__":
    r = fetch_btc_rsi()
    n = len(r["series"])
    span = f"{r['series'].index[0].date()}→{r['series'].index[-1].date()}" if n else "—"
    print(f"{r['label']}: {r['value']:.1f}  stale={r['stale']}  [{n} pts {span}]")
    if r["error"]:
        print(f"  ERROR: {r['error']}")

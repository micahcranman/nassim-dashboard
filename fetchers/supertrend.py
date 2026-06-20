"""Trend verdict — an ATR Supertrend on MSTR price.

This is the headline BUY/SELL/HOLD signal (the TBL-supertrend-style call Micah wants).
It is a TREND follower: it flips SELL when MSTR breaks down structurally (catching the
2025 $366→$107 decline) and BUY on the reversal — the job the value oscillator can't do.
Pairs with the value net-conviction gauge (how oversold) the way v8.5 pairs its slope
hedge gate with the MRI value bottom.

Flips are emitted as dated BUY/SELL markers for the price chart. Later this can ingest
real TBL liquidity instead of (or alongside) price.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import datetime, timezone

try:
    from . import lastgood
except ImportError:
    import lastgood

PERIOD = 20
MULT = 4.0
_ERA = pd.Timestamp("2020-08-01")


def _ohlc():
    import yfinance as yf
    df = yf.Ticker("MSTR").history(period="max", auto_adjust=True)
    if df.empty:
        raise RuntimeError("no MSTR OHLC")
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index
    return df[df.index >= _ERA]


def _supertrend(df, period=PERIOD, mult=MULT):
    h, l, c = df["High"], df["Low"], df["Close"]
    hl2 = (h + l) / 2.0
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    fu = upper.copy().values
    fl = lower.copy().values
    cv = c.values
    for i in range(1, len(df)):
        fu[i] = upper.iloc[i] if (upper.iloc[i] < fu[i - 1] or cv[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower.iloc[i] if (lower.iloc[i] > fl[i - 1] or cv[i - 1] < fl[i - 1]) else fl[i - 1]
    direction = np.ones(len(df), dtype=int)
    st = np.empty(len(df))
    for i in range(len(df)):
        if i == 0:
            direction[i] = 1
            st[i] = fl[i]
            continue
        if cv[i] > fu[i - 1]:
            direction[i] = 1
        elif cv[i] < fl[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        st[i] = fl[i] if direction[i] == 1 else fu[i]
    return pd.Series(st, index=df.index), pd.Series(direction, index=df.index)


def fetch_trend() -> dict:
    label = "MSTR Trend (Supertrend)"
    try:
        df = _ohlc()
        st, direction = _supertrend(df)
        cur = int(direction.iloc[-1])
        verdict = "BUY" if cur == 1 else "SELL"
        # last flip
        flips = []
        for i in range(1, len(direction)):
            if direction.iloc[i] != direction.iloc[i - 1]:
                flips.append({"date": direction.index[i].strftime("%Y-%m-%d"),
                              "price": round(float(df["Close"].iloc[i]), 2),
                              "dir": int(direction.iloc[i])})
        since = flips[-1]["date"] if flips else direction.index[0].strftime("%Y-%m-%d")
        # strength = distance of close from the supertrend line, % (capped 100)
        last_close = float(df["Close"].iloc[-1])
        strength = round(min(100.0, abs(last_close - float(st.iloc[-1])) / last_close * 100.0 / 0.25 * 25), 0)
        line = [{"d": d.strftime("%Y-%m-%d"), "v": round(float(v), 2)}
                for d, v in st.tail(365 * 6).items()]
        lastgood.save("trend", verdict, datetime.now(timezone.utc), direction=cur, since=since)
        return {
            "verdict": verdict, "direction": cur, "since": since,
            "strength": strength, "line": line, "flips": flips,
            "close": last_close, "supertrend": round(float(st.iloc[-1]), 2),
            "source": f"supertrend({PERIOD},{MULT}) on MSTR", "stale": False, "error": None,
            "timestamp": df.index[-1].to_pydatetime(),
        }
    except Exception as e:
        lg = lastgood.load("trend")
        if lg is not None:
            return {"verdict": lg["value"], "direction": lg.get("direction"), "since": lg.get("since"),
                    "strength": None, "line": [], "flips": [], "close": None, "supertrend": None,
                    "source": "supertrend (last-good)", "stale": True, "error": str(e),
                    "timestamp": lastgood.parse_ts(lg)}
        return {"verdict": None, "direction": None, "since": None, "strength": None,
                "line": [], "flips": [], "close": None, "supertrend": None,
                "source": "supertrend", "stale": True, "error": str(e),
                "timestamp": datetime.now(timezone.utc)}


if __name__ == "__main__":
    r = fetch_trend()
    print(f"{r['verdict']} since {r['since']} (strength {r['strength']}, close {r['close']} vs ST {r['supertrend']})")
    print(f"  flips: {len(r['flips'])}, last 6:")
    for f in r["flips"][-6:]:
        print(f"    {f['date']}  {'BUY ' if f['dir']==1 else 'SELL'}  ${f['price']}")

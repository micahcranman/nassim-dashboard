"""CoinGecko public API. Free tier — rate limits apply (~10-30 calls/min)."""
import time
import pandas as pd
import requests
from datetime import datetime, timezone

BASE = "https://api.coingecko.com/api/v3"
HEADERS = {"User-Agent": "nassim-dashboard/1.0", "Accept": "application/json"}


def _get(path: str, params=None, retries=3, delay=2.0):
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=20)
            if r.status_code == 429:
                time.sleep(delay * (i + 1) * 3)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(delay * (i + 1))
    raise RuntimeError(f"coingecko failed: {last_err}")


def fetch_btc_price():
    try:
        # Series for 1y chart
        chart = _get("/coins/bitcoin/market_chart", {"vs_currency": "usd", "days": "365"})
        prices = chart["prices"]
        df = pd.DataFrame(prices, columns=["ts_ms", "price"])
        df["date"] = pd.to_datetime(df["ts_ms"], unit="ms").dt.tz_localize(None).dt.normalize()
        # Dedupe to daily close (last per day)
        df = df.groupby("date")["price"].last()
        return {
            "value": float(df.iloc[-1]),
            "series": df,
            "timestamp": df.index[-1].to_pydatetime(),
            "source": "CoinGecko:bitcoin",
            "label": "BTC Price (USD)",
            "stale": False,
            "error": None,
        }
    except Exception as e:
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": "CoinGecko:bitcoin", "label": "BTC Price (USD)",
            "stale": True, "error": str(e),
        }


def fetch_btc_market_cap():
    try:
        chart = _get("/coins/bitcoin/market_chart", {"vs_currency": "usd", "days": "365"})
        mcaps = chart["market_caps"]
        df = pd.DataFrame(mcaps, columns=["ts_ms", "mcap"])
        df["date"] = pd.to_datetime(df["ts_ms"], unit="ms").dt.tz_localize(None).dt.normalize()
        df = df.groupby("date")["mcap"].last()
        return {
            "value": float(df.iloc[-1]),
            "series": df,
            "timestamp": df.index[-1].to_pydatetime(),
            "source": "CoinGecko:bitcoin/market_caps",
            "label": "BTC Market Cap (USD)",
            "stale": False,
            "error": None,
        }
    except Exception as e:
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": "CoinGecko:bitcoin/market_caps", "label": "BTC Market Cap",
            "stale": True, "error": str(e),
        }


def _stable_mcap(coin: str):
    chart = _get(f"/coins/{coin}/market_chart", {"vs_currency": "usd", "days": "365"})
    mcaps = chart["market_caps"]
    df = pd.DataFrame(mcaps, columns=["ts_ms", "mcap"])
    df["date"] = pd.to_datetime(df["ts_ms"], unit="ms").dt.tz_localize(None).dt.normalize()
    df = df.groupby("date")["mcap"].last()
    return df


def fetch_stablecoin_supply():
    """USDT + USDC + DAI aggregated. Returns total $ market cap."""
    try:
        usdt = _stable_mcap("tether"); time.sleep(2)
        usdc = _stable_mcap("usd-coin"); time.sleep(2)
        try:
            dai = _stable_mcap("dai")
        except Exception:
            dai = pd.Series(0, index=usdt.index)
        idx = usdt.index.union(usdc.index).union(dai.index)
        total = usdt.reindex(idx, method="ffill").fillna(0) + \
                usdc.reindex(idx, method="ffill").fillna(0) + \
                dai.reindex(idx, method="ffill").fillna(0)
        return {
            "value": float(total.iloc[-1]),
            "series": total,
            "timestamp": total.index[-1].to_pydatetime(),
            "source": "CoinGecko (USDT+USDC+DAI)",
            "label": "Stablecoin Total Supply ($)",
            "stale": False,
            "error": None,
        }
    except Exception as e:
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": "CoinGecko stables", "label": "Stablecoin Supply",
            "stale": True, "error": str(e),
        }


if __name__ == "__main__":
    for fn in [fetch_btc_price, fetch_btc_market_cap, fetch_stablecoin_supply]:
        r = fn()
        print(f"{r['label']}: {r['value']} @ {r['timestamp']} (stale={r['stale']})")
        if r.get("error"):
            print(f"  ERROR: {r['error']}")
        time.sleep(2)

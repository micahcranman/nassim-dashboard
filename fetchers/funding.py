"""BTC perpetual funding rates. OKX primary (US-accessible), Bybit fallback."""
import pandas as pd
import requests
from datetime import datetime, timezone

OKX_FUNDING_HISTORY = "https://www.okx.com/api/v5/public/funding-rate-history"
OKX_FUNDING_CURRENT = "https://www.okx.com/api/v5/public/funding-rate"
BYBIT_FUNDING_HISTORY = "https://api.bybit.com/v5/market/funding/history"
HEADERS = {"User-Agent": "nassim-dashboard/1.0"}


def _try_okx():
    """OKX BTC-USDT-SWAP. Funding settles every 8h. Returns history + current."""
    r = requests.get(OKX_FUNDING_HISTORY,
                     params={"instId": "BTC-USDT-SWAP", "limit": 100},
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != "0":
        raise RuntimeError(f"OKX history error: {j}")
    rows = j["data"]
    if not rows:
        raise RuntimeError("OKX returned no funding history")
    df = pd.DataFrame(rows)
    df["fundingTime"] = pd.to_datetime(pd.to_numeric(df["fundingTime"]), unit="ms").dt.tz_localize(None)
    df["fundingRate"] = pd.to_numeric(df["fundingRate"])
    df["annualized_pct"] = df["fundingRate"] * 3 * 365 * 100
    df = df.set_index("fundingTime").sort_index()
    s = df["annualized_pct"]
    # Current snapshot
    r2 = requests.get(OKX_FUNDING_CURRENT,
                      params={"instId": "BTC-USDT-SWAP"},
                      headers=HEADERS, timeout=10)
    r2.raise_for_status()
    j2 = r2.json()
    cur_rate = float(j2["data"][0]["fundingRate"])
    current_annualized = cur_rate * 3 * 365 * 100
    return s, current_annualized, "OKX:BTC-USDT-SWAP"


def _try_bybit():
    r = requests.get(BYBIT_FUNDING_HISTORY,
                     params={"category": "linear", "symbol": "BTCUSDT", "limit": 200},
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    j = r.json()
    rows = j.get("result", {}).get("list", [])
    if not rows:
        raise RuntimeError(f"Bybit returned no rows: {j}")
    df = pd.DataFrame(rows)
    df["fundingRateTimestamp"] = pd.to_datetime(pd.to_numeric(df["fundingRateTimestamp"]), unit="ms").dt.tz_localize(None)
    df["fundingRate"] = pd.to_numeric(df["fundingRate"])
    df["annualized_pct"] = df["fundingRate"] * 3 * 365 * 100
    df = df.set_index("fundingRateTimestamp").sort_index()
    s = df["annualized_pct"]
    return s, float(s.iloc[-1]), "Bybit:BTCUSDT"


def fetch_funding_rate():
    """Returns current funding rate (annualized %) + 30d history."""
    last_err = None
    for fn, name in [(_try_okx, "OKX"), (_try_bybit, "Bybit")]:
        try:
            s, current, src = fn()
            return {
                "value": current,
                "series": s,
                "timestamp": s.index[-1].to_pydatetime(),
                "source": f"{src} (annualized %)",
                "label": "BTC Perp Funding (annualized %)",
                "stale": False,
                "error": None,
            }
        except Exception as e:
            last_err = f"{name}: {e}"
            continue
    return {
        "value": None, "series": pd.Series(dtype=float),
        "timestamp": datetime.now(timezone.utc),
        "source": "OKX/Bybit (both failed)", "label": "BTC Perp Funding",
        "stale": True, "error": str(last_err),
    }


if __name__ == "__main__":
    r = fetch_funding_rate()
    print(f"{r['label']}: {r['value']} @ {r['timestamp']} (stale={r['stale']})")
    if r.get("error"):
        print(f"  ERROR: {r['error']}")

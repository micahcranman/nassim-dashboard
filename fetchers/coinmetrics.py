"""Coin Metrics community API (free tier) for on-chain metrics."""
import pandas as pd
import requests
from datetime import datetime, timezone

BASE = "https://community-api.coinmetrics.io/v4"
HEADERS = {"User-Agent": "nassim-dashboard/1.0", "Accept": "application/json"}


def _fetch_metric(metric: str, asset: str = "btc", days: int = 365):
    """Returns time series. Iterates pages if needed."""
    params = {
        "assets": asset,
        "metrics": metric,
        "frequency": "1d",
        "page_size": 1000,
        "pretty": "false",
    }
    out_rows = []
    next_url = f"{BASE}/timeseries/asset-metrics"
    while next_url:
        r = requests.get(next_url, params=params if next_url.endswith("metrics") else None,
                         headers=HEADERS, timeout=30)
        r.raise_for_status()
        j = r.json()
        for row in j.get("data", []):
            out_rows.append(row)
        next_url = j.get("next_page_url")
        params = None
        if len(out_rows) > 5000:  # safety
            break
    if not out_rows:
        raise RuntimeError(f"no data for {metric}")
    df = pd.DataFrame(out_rows)
    if "time" not in df.columns:
        raise RuntimeError(f"no time col in CM response: {df.columns.tolist()}")
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    df = df.set_index("time").sort_index()
    if metric not in df.columns:
        raise RuntimeError(f"metric {metric} not in columns: {df.columns.tolist()}")
    s = pd.to_numeric(df[metric], errors="coerce").dropna()
    s.name = metric
    # last year
    s = s.tail(days)
    return s


def fetch_lth_supply():
    """Long-term holder supply. CM metric: SplyAct1yr (supply active < 1yr) inverse,
    or SplyActPct1yr. We'll use 'AdrBalUSD1Cnt' as fallback or supply held >1yr.

    Best CM proxy: SplyAct1yr is supply active in last 1yr; LTH = total supply - active 1yr.
    Or use SplyAct1yrPct.
    """
    # CM community tier does not expose LTH supply metrics (403 on SplyAct*).
    # Try paid-only metrics first, but if they fail, return stale with explicit note.
    candidates = ["SplyAct180d", "SplyAct1yr"]  # both 403 on community tier
    last_err = None
    for metric in candidates:
        try:
            s = _fetch_metric(metric)
            supply = _fetch_metric("SplyCur")
            idx = s.index.intersection(supply.index)
            lth = supply.reindex(idx) - s.reindex(idx)
            lth.name = "LTH_supply"
            return {
                "value": float(lth.iloc[-1]),
                "series": lth,
                "timestamp": lth.index[-1].to_pydatetime(),
                "source": f"CoinMetrics:SplyCur-{metric}",
                "label": "LTH Supply (BTC)",
                "stale": False,
                "error": None,
            }
        except Exception as e:
            last_err = e
            continue
    return {
        "value": None, "series": pd.Series(dtype=float),
        "timestamp": datetime.now(timezone.utc),
        "source": "CoinMetrics (community tier insufficient)",
        "label": "LTH Supply (BTC)",
        "stale": True,
        "error": f"community tier 403; need paid CM key or alt source. Last: {last_err}",
    }


if __name__ == "__main__":
    r = fetch_lth_supply()
    print(f"{r['label']}: {r['value']} @ {r['timestamp']} (stale={r['stale']})")
    if r.get("error"):
        print(f"  ERROR: {r['error']}")

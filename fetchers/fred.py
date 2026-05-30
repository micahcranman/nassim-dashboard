"""FRED data fetcher. No auth required for CSV endpoints.

Hardened: retries with exponential backoff + on-disk cache fallback so a
transient FRED outage doesn't drop us to None for hours.
"""
import io
import os
import time
import pandas as pd
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Use cosd= (start date) to avoid 504s on large daily series. 2018 is plenty for
# every indicator we compute (longest lookback is ~5y trend windows).
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2018-01-01"
UA = "nassim-dashboard/1.0"

_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)
_CACHE_TTL_HOURS = 24


def _cache_path(series_id: str) -> Path:
    return _CACHE_DIR / f"fred_{series_id}.csv"


def _save_cache(series_id: str, df: pd.DataFrame) -> None:
    try:
        df.to_csv(_cache_path(series_id), index=False)
    except Exception:
        pass


def _load_cache(series_id: str, max_age_hours: float = _CACHE_TTL_HOURS):
    p = _cache_path(series_id)
    if not p.exists():
        return None
    age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() / 3600
    if age > max_age_hours:
        return None
    try:
        return pd.read_csv(p)
    except Exception:
        return None


def _fetch_series(series_id: str) -> pd.Series:
    url = FRED_CSV.format(series=series_id)
    # Try fresh fetch with 8s timeout + 2 attempts. Fall back to ANY cached copy
    # (no age limit) on failure so a transient FRED outage doesn't drop us to None.
    last_err = None
    df = None
    for attempt in range(2):
        try:
            r = requests.get(url, timeout=5, headers={"User-Agent": UA})
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            _save_cache(series_id, df)
            break
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    if df is None:
        # Last resort: ANY cached copy (no TTL on emergency fallback)
        cached = _load_cache(series_id, max_age_hours=24 * 365)
        if cached is not None:
            df = cached
        else:
            raise last_err if last_err else RuntimeError("FRED fetch failed and no cache")
    # FRED columns: observation_date,SERIES_ID
    date_col = df.columns[0]
    val_col = df.columns[1]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col)
    # FRED uses "." for missing
    s = pd.to_numeric(df[val_col], errors="coerce").dropna()
    s.name = series_id
    return s


def _wrap(series_id: str, label: str):
    try:
        s = _fetch_series(series_id)
        return {
            "value": float(s.iloc[-1]),
            "series": s,
            "timestamp": s.index[-1].to_pydatetime(),
            "source": f"FRED:{series_id}",
            "label": label,
            "stale": False,
            "error": None,
        }
    except Exception as e:
        return {
            "value": None,
            "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": f"FRED:{series_id}",
            "label": label,
            "stale": True,
            "error": str(e),
        }


def fetch_m2():
    return _wrap("M2SL", "US M2 Money Supply")


def fetch_walcl():
    return _wrap("WALCL", "Fed Balance Sheet")


def fetch_tga():
    return _wrap("WTREGEN", "Treasury General Account")


def fetch_rrp():
    return _wrap("RRPONTSYD", "Overnight Reverse Repo")


def fetch_real_yield_10y():
    return _wrap("DFII10", "10Y Real Yield (TIPS)")


def fetch_hy_oas():
    return _wrap("BAMLH0A0HYM2", "HY Credit Spread (OAS)")


def fetch_net_liquidity():
    """Net Liquidity = Fed BS - TGA - RRP. All in $B."""
    try:
        walcl = _fetch_series("WALCL")     # weekly, in $M
        tga = _fetch_series("WTREGEN")      # weekly, in $B
        rrp = _fetch_series("RRPONTSYD")    # daily, in $B
        # Resample to weekly, forward-fill, align
        idx = walcl.index
        tga_w = tga.reindex(idx, method="ffill")
        rrp_w = rrp.reindex(idx, method="ffill")
        # FRED units: WALCL in $M, WTREGEN in $M, RRPONTSYD in $B. Normalize all to $B.
        net = (walcl / 1000.0) - (tga_w / 1000.0) - rrp_w
        net = net.dropna()
        return {
            "value": float(net.iloc[-1]),
            "series": net,
            "timestamp": net.index[-1].to_pydatetime(),
            "source": "FRED computed (WALCL/1000 - WTREGEN - RRPONTSYD)",
            "label": "US Net Liquidity ($B)",
            "stale": False,
            "error": None,
        }
    except Exception as e:
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": "FRED computed", "label": "US Net Liquidity ($B)",
            "stale": True, "error": str(e),
        }


if __name__ == "__main__":
    for fn in [fetch_m2, fetch_real_yield_10y, fetch_hy_oas, fetch_net_liquidity]:
        r = fn()
        print(f"{r['label']}: {r['value']} @ {r['timestamp']} (stale={r['stale']})")
        if r["error"]:
            print(f"  ERROR: {r['error']}")

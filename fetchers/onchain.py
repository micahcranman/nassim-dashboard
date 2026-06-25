"""On-chain BTC indicators from bitcoin-data.com (public API).

Includes disk cache to survive rate limits (10 req/hr on free tier).
Cache TTL: 6 hours. If API fails, fall back to cached values.
"""
import os
import pandas as pd
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from . import lastgood
except ImportError:  # allow `python onchain.py` direct execution
    import lastgood

BASE = "https://api.bgeometrics.com/v1"
HEADERS = {"User-Agent": "nassim-dashboard/1.0", "Accept": "application/json"}

_TOKEN = os.environ.get("BGEO_TOKEN", "")

_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)
_CACHE_TTL = timedelta(hours=6)


def _cache_path(endpoint):
    safe = endpoint.replace("/", "_")
    return _CACHE_DIR / f"{safe}.csv"


def _load_cache(endpoint):
    path = _cache_path(endpoint)
    if not path.exists():
        return None, None
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        s = df.iloc[:, 0]
        return s, age
    except Exception:
        return None, None


def _save_cache(endpoint, series):
    path = _cache_path(endpoint)
    try:
        series.to_frame().to_csv(path)
    except Exception:
        pass


# BGeometrics throttles bursts (separate from the 200/hr cap). Enforce a minimum gap
# between live calls so many sequential endpoint fetches don't trip a 429.
_MIN_GAP_S = 2.2
_last_call = [0.0]


def _throttle():
    import time as _t
    elapsed = _t.monotonic() - _last_call[0]
    if elapsed < _MIN_GAP_S:
        _t.sleep(_MIN_GAP_S - elapsed)
    _last_call[0] = _t.monotonic()


def _fetch(endpoint: str, value_key_candidates=("mvrvZscore", "nupl", "sopr", "liveliness", "value")):
    import time as _t
    params = {"token": _TOKEN} if _TOKEN else {}
    # Retry on 429 (burst throttle) and 5xx with backoff. Hourly cap (200/hr) is generous;
    # the throttle is per-burst, so short spacing clears it.
    last = None
    data = None
    for attempt in range(4):
        try:
            _throttle()
            r = requests.get(f"{BASE}/{endpoint}", headers=HEADERS, params=params, timeout=30)
            if r.status_code in (429, 500, 502, 503, 504):
                last = requests.HTTPError(f"{r.status_code} for {endpoint}")
                _t.sleep(1.0 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            last = e
            _t.sleep(1.0 * (attempt + 1))
    if data is None:
        raise last if last else RuntimeError(f"fetch failed for {endpoint}")
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"empty response for {endpoint}: {data!r}")
    # Find the date key + value key
    sample = data[0]
    date_key = None
    for k in ("d", "date", "t", "time"):
        if k in sample:
            date_key = k
            break
    if date_key is None:
        raise RuntimeError(f"no date key in {sample!r}")
    val_key = None
    for k in value_key_candidates:
        if k in sample:
            val_key = k
            break
    if val_key is None:
        # Try first non-date key
        keys = [k for k in sample if k != date_key]
        if keys:
            val_key = keys[0]
        else:
            raise RuntimeError(f"no value key in {sample!r}")
    df = pd.DataFrame(data)
    df[date_key] = pd.to_datetime(df[date_key])
    df = df.set_index(date_key).sort_index()
    s = pd.to_numeric(df[val_key], errors="coerce").dropna()
    s.name = endpoint
    return s


def _wrap(endpoint, label, value_keys):
    cached, cache_age = _load_cache(endpoint)
    # Use cache if fresh
    if cached is not None and cache_age is not None and cache_age < _CACHE_TTL:
        return {
            "value": float(cached.iloc[-1]),
            "series": cached,
            "timestamp": cached.index[-1].to_pydatetime(),
            "source": f"bitcoin-data.com/{endpoint} (cache, age {cache_age})",
            "label": label,
            "stale": False,
            "error": None,
        }
    try:
        s = _fetch(endpoint, value_keys)
        _save_cache(endpoint, s)
        lastgood.save(endpoint, float(s.iloc[-1]), s.index[-1].to_pydatetime())
        return {
            "value": float(s.iloc[-1]),
            "series": s,
            "timestamp": s.index[-1].to_pydatetime(),
            "source": f"bitcoin-data.com/{endpoint}",
            "label": label,
            "stale": False,
            "error": None,
        }
    except Exception as e:
        # API failed — fall back to stale cache if any
        if cached is not None:
            return {
                "value": float(cached.iloc[-1]),
                "series": cached,
                "timestamp": cached.index[-1].to_pydatetime(),
                "source": f"bitcoin-data.com/{endpoint} (STALE cache, age {cache_age})",
                "label": label,
                "stale": True,
                "error": f"API failed ({e}); using stale cache",
            }
        # Last resort: committed last-good (survives fresh CI runners)
        lg = lastgood.load(endpoint)
        if lg is not None:
            return {
                "value": float(lg["value"]), "series": pd.Series(dtype=float),
                "timestamp": lastgood.parse_ts(lg),
                "source": f"bitcoin-data.com/{endpoint} (last-good)", "label": label,
                "stale": True, "error": str(e),
            }
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": f"bitcoin-data.com/{endpoint}", "label": label,
            "stale": True, "error": str(e),
        }


def fetch_mvrv_zscore():
    return _wrap("mvrv-zscore", "MVRV Z-Score", ("mvrvZscore", "value"))


def fetch_nupl():
    return _wrap("nupl", "NUPL", ("nupl", "value"))


def fetch_sopr():
    r = _wrap("sopr", "SOPR (raw)", ("sopr", "value"))
    if not r["stale"] and not r["series"].empty:
        # compute 7d MA
        s = r["series"]
        sma = s.rolling(7, min_periods=1).mean()
        r["series_raw"] = s
        r["series"] = sma
        r["value"] = float(sma.iloc[-1])
        r["label"] = "SOPR (7d MA)"
    return r


def fetch_liveliness():
    """Liveliness (LTH proxy).

    Liveliness = CDD / cumulative_coin_days_created. Range ~0-1.
    Falling liveliness = LTHs accumulating (bullish).
    Rising liveliness = LTHs distributing (bearish).
    """
    return _wrap("liveliness", "Liveliness (LTH proxy)", ("liveliness", "value"))


# ---- holder-cohort / tourist-detection metrics (BGeometrics) ----

def fetch_sth_sopr():
    """Short-Term Holder SOPR. <1 = STHs (tourists) realizing losses / capitulating;
    >1.05 = STHs euphorically taking profit. Cohort-aware replacement for raw SOPR."""
    return _wrap("sth-sopr", "STH-SOPR", ("sthSopr", "value"))


def fetch_lth_sopr():
    """Long-Term Holder SOPR. Rising >1 = smart money distributing into strength."""
    return _wrap("lth-sopr", "LTH-SOPR", ("lthSopr", "value"))


def fetch_sth_mvrv():
    """Short-Term Holder MVRV. <1 = tourists underwater (bottoms); high = tourists in
    heavy unrealized profit (tops)."""
    return _wrap("sth-mvrv", "STH-MVRV", ("sthMvrv", "value"))


def fetch_lth_mvrv():
    """Long-Term Holder MVRV."""
    return _wrap("lth-mvrv", "LTH-MVRV", ("lthMvrv", "value"))


def fetch_reserve_risk():
    """Reserve Risk — LTH conviction vs price. Low = strong hands accumulating (bottoms)."""
    return _wrap("reserve-risk", "Reserve Risk", ("reserveRisk", "value"))


if __name__ == "__main__":
    for fn in [fetch_mvrv_zscore, fetch_nupl, fetch_sopr, fetch_liveliness,
               fetch_sth_sopr, fetch_lth_sopr, fetch_sth_mvrv, fetch_lth_mvrv,
               fetch_reserve_risk]:
        r = fn()
        print(f"{r['label']}: {r['value']} @ {r['timestamp']} (stale={r['stale']})")
        if r.get("error"):
            print(f"  ERROR: {r['error']}")

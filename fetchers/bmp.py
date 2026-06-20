"""Bitcoin Magazine Pro (BM Pro) — authoritative on-chain cycle metrics.

API: https://api.bitcoinmagazinepro.com
Auth: `Authorization: Bearer <BMP_API_KEY>` (the raw 52-char key from .env, used verbatim
      as the bearer token — NOT base64-decoded, NOT HTTP Basic; probed and confirmed).
List metrics: GET /metrics  (JSON array of slugs).
Metric data:  GET /metrics/{slug}?from_date=&to_date=  → a JSON-encoded STRING whose body
              is CSV (cols vary; always has a `Date` column). Parse with read_csv(StringIO).

WHY BMP is the authoritative source here:
  BMP serves clean, full-history daily series (mvrv-zscore/nupl/sth-mvrv back to 2010,
  fear-and-greed to 2018) over a stable CSV API. That supersedes the flaky BGeometrics
  Advanced API (burst-throttles to 429, needs 2.2s spacing) and the checkonchain Plotly
  scrape as the PRIMARY for the cycle-value indicators, with those kept as fallback.
  Cross-checked 2026-06-20: BMP vs prior sources agree within noise (nupl 0.160 vs 0.159,
  sth_mvrv 0.887 vs 0.87, F&G 23=23, mvrv_z 0.336 vs 0.383) → swapping does not disturb
  the calibrated bands.

mNAV NOTE (the headline ask, RESOLVED as: BMP cannot serve it on this plan):
  BMP's documented `bitcoin-treasury-analytics-strategy` metric returns 404 on this key's
  tier; the /metrics list contains ZERO MSTR / treasury / mNAV / NAV-premium metrics
  (104 metrics, all pure-Bitcoin on-chain/macro). So mNAV stays COMPUTED in
  dashboard.compute_derived (MSTR mcap / BTC NAV, with combined diluted+basic share
  history back to 2020-08 already covering the Nov-2024 cycle top). bitcointreasuries
  remains the holdings fallback. `mstr_mnav_available()` documents this for callers.

Every fetcher returns the standard contract {value, series, stale, source, error} plus a
committed last-good fallback. Responses are disk-cached (12h) so calibration backfills and
repeated dashboard runs don't hammer the API.
"""
from __future__ import annotations

import io
import os
import time
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from . import lastgood

BASE = "https://api.bitcoinmagazinepro.com"
_CACHE_DIR = Path(__file__).resolve().parent.parent / "outputs" / "cache" / "bmp"
_CACHE_TTL_S = 12 * 3600
_TIMEOUT = 40


def _api_key() -> str:
    return os.environ.get("BMP_API_KEY", "").strip()


def _headers() -> dict:
    return {"Authorization": f"Bearer {_api_key()}", "Accept": "application/json"}


def _cache_path(slug: str) -> Path:
    return _CACHE_DIR / f"{slug}.csv"


def _read_cache(slug: str):
    p = _cache_path(slug)
    if not p.exists():
        return None
    try:
        if (time.time() - p.stat().st_mtime) > _CACHE_TTL_S:
            return None
        return pd.read_csv(p)
    except Exception:
        return None


def _write_cache(slug: str, df: pd.DataFrame) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(_cache_path(slug), index=False)
    except Exception:
        pass


def fetch_raw(slug: str, from_date: str | None = None, to_date: str | None = None,
              use_cache: bool = True) -> pd.DataFrame:
    """Fetch one BMP metric as a DataFrame (Date + value columns). Raises on failure.

    The API returns a JSON-encoded string of CSV text. Disk-cached 12h when no date
    range is requested (the common full-history case)."""
    full = from_date is None and to_date is None
    if use_cache and full:
        cached = _read_cache(slug)
        if cached is not None and len(cached):
            return cached
    if not _api_key():
        raise RuntimeError("BMP_API_KEY not set")
    params = {}
    if from_date:
        params["from_date"] = from_date
    if to_date:
        params["to_date"] = to_date
    r = requests.get(f"{BASE}/metrics/{slug}", headers=_headers(), params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    body = r.json()  # JSON-encoded string body containing CSV
    if isinstance(body, str):
        df = pd.read_csv(io.StringIO(body))
    elif isinstance(body, list):
        df = pd.DataFrame(body)
    else:
        raise RuntimeError(f"unexpected BMP body type {type(body).__name__}")
    if "Date" not in df.columns:
        raise RuntimeError(f"BMP {slug}: no Date column (cols={list(df.columns)})")
    if full:
        _write_cache(slug, df)
    return df


def _to_series(df: pd.DataFrame, col: str) -> pd.Series:
    s = pd.Series(df[col].values, index=pd.to_datetime(df["Date"]))
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return pd.to_numeric(s, errors="coerce").dropna()


def _fetch_metric(slug: str, col: str, key: str, label: str,
                  source_note: str = "") -> dict:
    """Generic BMP fetcher → standard contract + last-good fallback."""
    src = f"BM Pro/{slug}"
    if source_note:
        src += f" ({source_note})"
    try:
        df = fetch_raw(slug)
        if col not in df.columns:
            raise RuntimeError(f"column {col!r} missing (have {list(df.columns)})")
        s = _to_series(df, col)
        if s.empty:
            raise RuntimeError("empty series")
        s.name = key
        latest = float(s.iloc[-1])
        ts_latest = s.index[-1].to_pydatetime()
        lastgood.save(key, latest, ts_latest)
        return {"value": latest, "series": s, "timestamp": ts_latest,
                "source": src, "label": label, "stale": False, "error": None}
    except Exception as e:
        lg = lastgood.load(key)
        if lg is not None:
            return {"value": float(lg["value"]), "series": pd.Series(dtype=float),
                    "timestamp": lastgood.parse_ts(lg), "source": f"{src} (last-good)",
                    "label": label, "stale": True, "error": str(e)}
        return {"value": None, "series": pd.Series(dtype=float),
                "timestamp": datetime.now(timezone.utc), "source": src,
                "label": label, "stale": True, "error": str(e)}


# --- Public fetchers (standard contract). These are the PRIMARY cycle-value sources. ---

def fetch_mvrv_zscore() -> dict:
    return _fetch_metric("mvrv-zscore", "ZScore", "mvrv_z", "MVRV Z-Score")


def fetch_nupl() -> dict:
    return _fetch_metric("nupl", "NUPL", "nupl", "Net Unrealized P/L")


def fetch_sth_mvrv() -> dict:
    return _fetch_metric("short-term-holder-mvrv", "sth_mvrv", "sth_mvrv",
                         "Short-Term Holder MVRV")


def fetch_fear_greed() -> dict:
    r = _fetch_metric("fear-and-greed", "value", "feargreed", "Fear & Greed Index")
    # add the classification field the frontend/contract expects
    v = r.get("value")
    if v is not None:
        r["classification"] = _fng_class(v)
    return r


def fetch_reserve_risk() -> dict:
    return _fetch_metric("reserve-risk", "Reserve Risk", "reserve_risk", "Reserve Risk")


def _fng_class(v: float) -> str:
    if v < 25:
        return "Extreme Fear"
    if v < 45:
        return "Fear"
    if v < 55:
        return "Neutral"
    if v < 75:
        return "Greed"
    return "Extreme Greed"


def mstr_mnav_available() -> bool:
    """BMP does NOT expose MSTR mNAV/treasury on this plan tier (probed: 404 + absent from
    /metrics). Kept as an explicit, greppable record so future callers don't re-investigate.
    mNAV is computed in dashboard.compute_derived instead."""
    return False


if __name__ == "__main__":
    # Load .env the same lightweight way dashboard.py does.
    envf = Path(__file__).resolve().parent.parent / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    for fn in (fetch_mvrv_zscore, fetch_nupl, fetch_sth_mvrv, fetch_fear_greed, fetch_reserve_risk):
        r = fn()
        n = len(r["series"])
        span = f"{r['series'].index[0].date()}→{r['series'].index[-1].date()}" if n else "—"
        print(f"{r['label']:24} = {r['value']}  stale={r['stale']}  [{n} pts {span}]  {r['source']}")
        if r["error"]:
            print(f"   ERROR: {r['error']}")
    print(f"mstr_mnav_available() = {mstr_mnav_available()}")

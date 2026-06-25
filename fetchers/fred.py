"""FRED macro fetcher — bulletproofed.

PRIMARY: official FRED JSON API with FRED_API_KEY (120 req/min, reliable).
FALLBACK: keyless fredgraph CSV (what this used before — flaky, kept only as a fallback
so local dev works without a key).
Plus: exponential backoff, on-disk cache, and committed last-good (survives fresh CI
runners) so M2 / Net Liquidity / HY OAS never silently drop to blank.

Net Liquidity = Fed Balance Sheet (WALCL) − TGA − RRP. The historical SERIES comes from
FRED; the freshest CURRENT value is taken from the issuers (Treasury Fiscal Data + NY Fed)
via treasury.py / nyfed.py, which are lower-latency and don't depend on FRED being up.
"""
import io
import os
import time
import pandas as pd
import requests
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import lastgood, treasury, nyfed
except ImportError:  # direct execution
    import lastgood, treasury, nyfed

FRED_JSON = "https://api.stlouisfed.org/fred/series/observations"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2015-01-01"
UA = "nassim-dashboard/1.0"
_API_KEY = os.environ.get("FRED_API_KEY", "").strip()

_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)


def _cache_path(series_id: str) -> Path:
    return _CACHE_DIR / f"fred_{series_id}.csv"


def _save_cache(series_id: str, s: pd.Series) -> None:
    try:
        s.to_frame("v").to_csv(_cache_path(series_id))
    except Exception:
        pass


def _load_cache(series_id: str):
    p = _cache_path(series_id)
    if not p.exists():
        return None
    try:
        return pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0]
    except Exception:
        return None


def _fetch_json(series_id: str) -> pd.Series:
    params = {
        "series_id": series_id, "api_key": _API_KEY, "file_type": "json",
        "observation_start": "2015-01-01",
    }
    last = None
    for attempt in range(4):
        try:
            r = requests.get(FRED_JSON, params=params, headers={"User-Agent": UA}, timeout=15)
            if r.status_code in (429, 500, 502, 503, 504):
                last = requests.HTTPError(f"{r.status_code}")
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            obs = r.json().get("observations", [])
            idx, vals = [], []
            for o in obs:
                v = o.get("value")
                if v in (None, ".", ""):
                    continue
                idx.append(pd.to_datetime(o["date"]))
                vals.append(float(v))
            s = pd.Series(vals, index=idx, name=series_id)
            if s.empty:
                raise RuntimeError("empty observations")
            return s
        except Exception as e:
            last = e
            time.sleep(2 ** attempt)
    raise last if last else RuntimeError("FRED JSON failed")


def _fetch_csv(series_id: str) -> pd.Series:
    last = None
    for attempt in range(3):
        try:
            # NOTE: FRED's keyless fredgraph endpoint blackholes requests that send a
            # custom User-Agent (read-timeout). The default requests UA returns 200 fast.
            r = requests.get(FRED_CSV.format(series=series_id), timeout=8)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            df[df.columns[0]] = pd.to_datetime(df[df.columns[0]])
            df = df.set_index(df.columns[0])
            s = pd.to_numeric(df[df.columns[0]], errors="coerce").dropna()
            s.name = series_id
            if s.empty:
                raise RuntimeError("empty CSV")
            return s
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last if last else RuntimeError("FRED CSV failed")


def _fetch_series(series_id: str) -> pd.Series:
    """Keyed JSON primary, keyless CSV fallback, then disk cache (any age)."""
    err = None
    if _API_KEY:
        try:
            s = _fetch_json(series_id)
            _save_cache(series_id, s)
            return s
        except Exception as e:
            err = e
    try:
        s = _fetch_csv(series_id)
        _save_cache(series_id, s)
        return s
    except Exception as e:
        err = e
    cached = _load_cache(series_id)
    if cached is not None and not cached.empty:
        return cached
    raise err if err else RuntimeError(f"FRED fetch failed for {series_id}")


def _wrap(series_id: str, label: str):
    try:
        s = _fetch_series(series_id)
        val = float(s.iloc[-1])
        ts = s.index[-1].to_pydatetime()
        lastgood.save(f"fred_{series_id}", val, ts)
        return {"value": val, "series": s, "timestamp": ts,
                "source": f"FRED:{series_id}", "label": label, "stale": False, "error": None}
    except Exception as e:
        lg = lastgood.load(f"fred_{series_id}")
        if lg is not None:
            return {"value": float(lg["value"]), "series": pd.Series(dtype=float),
                    "timestamp": lastgood.parse_ts(lg), "source": f"FRED:{series_id} (last-good)",
                    "label": label, "stale": True, "error": str(e)}
        return {"value": None, "series": pd.Series(dtype=float),
                "timestamp": datetime.now(timezone.utc), "source": f"FRED:{series_id}",
                "label": label, "stale": True, "error": str(e)}


def fetch_m2():
    return _wrap("M2SL", "US M2 Money Supply")


def fetch_nominal_gdp():
    """Nominal GDP (current-$, SAAR, quarterly) — the real-economy 'consumed' leg of the
    money-gap (M2 YoY% − nominal-GDP YoY%). NOT GDPC1 (that's real/inflation-adjusted)."""
    return _wrap("GDP", "US Nominal GDP ($B SAAR)")


def fetch_federal_deficit():
    """Federal surplus(+)/deficit(−), monthly NSA ($M) — the fiscal-absorption leg.
    Roll to a trailing-12-month sum and normalize by GDP downstream."""
    return _wrap("MTSDS133FMS", "Federal Surplus/Deficit ($M, monthly)")


def fetch_real_yield_10y():
    return _wrap("DFII10", "10Y Real Yield (TIPS)")


def fetch_hy_oas():
    return _wrap("BAMLH0A0HYM2", "HY Credit Spread (OAS)")


def fetch_net_liquidity():
    """Net Liquidity = WALCL − TGA − RRP in $B.

    Series from FRED; current value refreshed from issuers (Treasury TGA + NY Fed RRP)
    and cross-checked. Falls back gracefully at each layer.
    """
    label = "US Net Liquidity ($B)"
    try:
        walcl = _fetch_series("WALCL") / 1000.0          # $M → $B
        tga_fred = _fetch_series("WTREGEN") / 1000.0     # $M → $B
        rrp_fred = _fetch_series("RRPONTSYD")            # already $B
        idx = walcl.index
        tga_w = tga_fred.reindex(idx, method="ffill")
        rrp_w = rrp_fred.reindex(idx, method="ffill")
        net = (walcl - tga_w - rrp_w).dropna()
        if net.empty:
            raise RuntimeError("empty net-liq series")

        # Freshest current value from issuers (independent of FRED freshness)
        cur_walcl = float(walcl.iloc[-1])
        tga_iss = treasury.fetch_tga()
        rrp_iss = nyfed.fetch_rrp()
        cur_tga = tga_iss["value"] if tga_iss["value"] is not None else float(tga_w.iloc[-1])
        cur_rrp = rrp_iss["value"] if rrp_iss["value"] is not None else float(rrp_w.iloc[-1])
        cur_net = cur_walcl - cur_tga - cur_rrp

        # Cross-check TGA: issuer vs FRED (flag large divergence, don't fail)
        xcheck = None
        try:
            if tga_iss["value"] is not None:
                d = abs(tga_iss["value"] - float(tga_w.iloc[-1]))
                if d > 50:  # >$50B apart → worth noting
                    xcheck = f"TGA issuer {tga_iss['value']:.0f} vs FRED {float(tga_w.iloc[-1]):.0f}"
        except Exception:
            pass

        # Use the fresher issuer-based current value as the headline; keep FRED series for history
        series = net.copy()
        series.iloc[-1] = cur_net
        val = cur_net
        ts = max(net.index[-1].to_pydatetime(),
                 tga_iss.get("timestamp") or net.index[-1].to_pydatetime())
        lastgood.save("net_liquidity", val, datetime.now(timezone.utc))
        src = "FRED series + issuer current (Treasury/NYFed)"
        return {"value": val, "series": series, "timestamp": ts, "source": src,
                "label": label, "stale": False, "error": xcheck,
                "components": {"walcl": cur_walcl, "tga": cur_tga, "rrp": cur_rrp}}
    except Exception as e:
        lg = lastgood.load("net_liquidity")
        if lg is not None:
            return {"value": float(lg["value"]), "series": pd.Series(dtype=float),
                    "timestamp": lastgood.parse_ts(lg), "source": "net-liq (last-good)",
                    "label": label, "stale": True, "error": str(e)}
        return {"value": None, "series": pd.Series(dtype=float),
                "timestamp": datetime.now(timezone.utc), "source": "FRED computed",
                "label": label, "stale": True, "error": str(e)}


if __name__ == "__main__":
    for fn in [fetch_m2, fetch_real_yield_10y, fetch_hy_oas, fetch_net_liquidity]:
        r = fn()
        print(f"{r['label']}: {r['value']} @ {r['timestamp']} (stale={r['stale']}) {r['source']}")
        if r.get("components"):
            print(f"   components: {r['components']}")
        if r["error"]:
            print(f"  note: {r['error']}")

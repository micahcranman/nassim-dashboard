"""Checkonchain Mean Reversion Index (MRI) — the same series v8.5's `<12` Q-fire gate reads.

The chart is a static Plotly HTML with the full daily series embedded as JSON. We extract
the trace named "Index" (the MRI), decoding Plotly's base64 typed-array form. This mirrors
`scripts/checkonchain_mri_fetch.py` exactly so the dashboard's MRI equals the strategy's by
construction — do NOT substitute BGeometrics `mri` (a different calculation).
"""
from __future__ import annotations

import base64
import math
import re
import struct
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import pandas as pd
import requests

try:
    from . import lastgood
except ImportError:
    import lastgood

URL = ("https://charts.checkonchain.com/btconchain/pricing/"
       "meanreversion_index/meanreversion_index_light.html")
HEADERS = {"User-Agent": "Mozilla/5.0 (Nassim/MRI-fetcher)"}
_KEY = "mri"

# Committed cache (under outputs/, persisted by CI). MRI updates daily, so skip the
# ~4MB HTML download when the cache already holds today's/yesterday's point. Data-date
# freshness — NOT mtime — because git checkout resets mtimes on fresh runners.
_CACHE = Path(__file__).resolve().parent.parent / "outputs" / "cache" / "mri_series.csv"


def _load_cache_series():
    if not _CACHE.exists():
        return None
    try:
        s = pd.read_csv(_CACHE, index_col=0, parse_dates=True).iloc[:, 0]
        return s if len(s) else None
    except Exception:
        return None


def _save_cache_series(s: pd.Series):
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        s.tail(365 * 7).to_frame("mri").to_csv(_CACHE)
    except Exception:
        pass

MIN_PLAUSIBLE, MAX_PLAUSIBLE = 0.0, 300.0

_DTYPE_MAP = {
    "f4": ("f", 4), "f8": ("d", 8),
    "i1": ("b", 1), "i2": ("h", 2), "i4": ("i", 4), "i8": ("q", 8),
    "u1": ("B", 1), "u2": ("H", 2), "u4": ("I", 4), "u8": ("Q", 8),
}


def _extract_traces(html: str) -> list:
    m = re.search(r"Plotly\.newPlot\(\s*\"[^\"]+\"\s*,\s*\[", html)
    if not m:
        raise RuntimeError("Plotly.newPlot not found")
    start = m.end() - 1
    depth = 0
    in_str = escape = False
    data_str = None
    for i in range(start, len(html)):
        c = html[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                data_str = html[start:i + 1]
                break
    if data_str is None:
        raise RuntimeError("unmatched bracket scanning data array")
    import json
    data_str = re.sub(r"\bNaN\b", "null", data_str)
    data_str = re.sub(r"\b-?Infinity\b", "null", data_str)
    return json.loads(data_str)


def _decode_bdata(spec: dict) -> list:
    dtype = spec.get("dtype")
    bdata = spec.get("bdata")
    if dtype not in _DTYPE_MAP or not isinstance(bdata, str):
        raise RuntimeError(f"unsupported bdata dtype={dtype!r}")
    fmt, size = _DTYPE_MAP[dtype]
    raw = base64.b64decode(bdata)
    n = len(raw) // size
    return list(struct.unpack(f"<{n}{fmt}", raw))


def _axis(v):
    if isinstance(v, list):
        return v
    if isinstance(v, dict) and "bdata" in v:
        return _decode_bdata(v)
    return None


def _select_index_trace(traces: list):
    """Pick the trace named 'Index' (the MRI). Fallback: any plausible 0–300 series."""
    cands = []
    for tr in traces:
        name = (tr.get("name") or "").strip()
        x = _axis(tr.get("x"))
        y = _axis(tr.get("y"))
        if not x or not y or len(x) != len(y) or len(y) < 100:
            continue
        recent = [v for v in y[-365:] if isinstance(v, (int, float)) and not math.isnan(v)]
        if not recent or max(recent) > MAX_PLAUSIBLE or min(recent) < MIN_PLAUSIBLE:
            continue
        cands.append((name, x, y))
    if not cands:
        raise RuntimeError("no plausible MRI trace")
    preferred = [c for c in cands if c[0] == "Index"]
    name, x, y = (preferred[0] if preferred else cands[0])
    return name, x, y


def fetch_mri() -> dict:
    """Mean Reversion Index — latest value + full daily series. Threshold: <12 = Q-fire zone."""
    label = "Mean Reversion Index (MRI)"
    # Cache hit: cached series already has today's or yesterday's point → skip 4MB download.
    cached = _load_cache_series()
    if cached is not None:
        latest_date = cached.index[-1].date()
        if latest_date >= (date.today() - timedelta(days=1)):
            latest = float(cached.iloc[-1])
            ts = cached.index[-1].to_pydatetime()
            lastgood.save(_KEY, latest, ts)
            return {
                "value": latest, "series": cached, "timestamp": ts,
                "source": "checkonchain/meanreversion_index (cache)", "label": label,
                "stale": False, "error": None, "trace_drift": False,
            }
    try:
        html = requests.get(URL, headers=HEADERS, timeout=40).text
        traces = _extract_traces(html)
        name, xs, ys = _select_index_trace(traces)
        if name != "Index":
            # flag drift but proceed with the best plausible series
            pass
        pairs = {}
        for d, v in zip(xs, ys):
            if not isinstance(v, (int, float)) or math.isnan(v) or not d:
                continue
            try:
                ts = pd.to_datetime(str(d).split("T")[0])
            except Exception:
                continue
            pairs[ts.normalize()] = float(v)
        if not pairs:
            raise RuntimeError("no usable MRI points")
        s = pd.Series(pairs).sort_index()
        s.name = "mri"
        latest = float(s.iloc[-1])
        if not (MIN_PLAUSIBLE <= latest <= MAX_PLAUSIBLE):
            raise RuntimeError(f"MRI out of range: {latest}")
        ts = s.index[-1].to_pydatetime()
        drift = (name != "Index")
        _save_cache_series(s)
        lastgood.save(_KEY, latest, ts)
        return {
            "value": latest, "series": s, "timestamp": ts,
            "source": "checkonchain/meanreversion_index" + (" [TRACE-DRIFT]" if drift else ""),
            "label": label, "stale": False,
            "error": ("trace name not 'Index' (was %r) — verify" % name) if drift else None,
            "trace_drift": drift,
        }
    except Exception as e:
        lg = lastgood.load(_KEY)
        if lg is not None:
            return {
                "value": float(lg["value"]), "series": pd.Series(dtype=float),
                "timestamp": lastgood.parse_ts(lg), "source": "checkonchain (last-good)",
                "label": label, "stale": True, "error": str(e), "trace_drift": False,
            }
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc), "source": "checkonchain",
            "label": label, "stale": True, "error": str(e), "trace_drift": False,
        }


if __name__ == "__main__":
    r = fetch_mri()
    print(f"{r['label']}: {r['value']} @ {r['timestamp']} stale={r['stale']} drift={r.get('trace_drift')}")
    if len(r["series"]):
        s = r["series"]
        print(f"  series {len(s)} pts {s.index[0].date()}→{s.index[-1].date()}; last5={[round(v,2) for v in s.tail(5)]}")
    if r["error"]:
        print(f"  note: {r['error']}")

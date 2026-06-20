"""Crypto Fear & Greed Index from alternative.me (free, no key, CORS-enabled).

Endpoint: https://api.alternative.me/fng/?limit=0  (limit=0 = full history, ~2600 days)
Each record: {value: "23", value_classification: "Extreme Fear", timestamp: "<unix>"}

Returns the standard fetcher contract plus `classification`. Falls back to committed
last-good on failure. Also fetched live client-side by the frontend for instant refresh.
"""
from __future__ import annotations

import pandas as pd
import requests
from datetime import datetime, timezone

from . import lastgood

URL = "https://api.alternative.me/fng/"
HEADERS = {"User-Agent": "nassim-dashboard/1.0", "Accept": "application/json"}
_KEY = "feargreed"


def _classify(v: float) -> str:
    if v < 25:
        return "Extreme Fear"
    if v < 45:
        return "Fear"
    if v < 55:
        return "Neutral"
    if v < 75:
        return "Greed"
    return "Extreme Greed"


def fetch_fear_greed() -> dict:
    label = "Fear & Greed Index"
    try:
        r = requests.get(URL, params={"limit": 0, "format": "json"}, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            raise RuntimeError("empty F&G data")
        # API returns newest-first; build an ascending daily series
        rows = []
        for rec in data:
            try:
                ts = pd.to_datetime(int(rec["timestamp"]), unit="s")
                rows.append((ts.normalize(), float(rec["value"])))
            except Exception:
                continue
        s = pd.Series(dict(rows)).sort_index()
        s.name = "fear_greed"
        latest = float(s.iloc[-1])
        classification = data[0].get("value_classification") or _classify(latest)
        ts_latest = s.index[-1].to_pydatetime()
        lastgood.save(_KEY, latest, ts_latest, classification=classification)
        return {
            "value": latest,
            "series": s,
            "timestamp": ts_latest,
            "source": "alternative.me/fng",
            "label": label,
            "classification": classification,
            "stale": False,
            "error": None,
        }
    except Exception as e:
        lg = lastgood.load(_KEY)
        if lg is not None:
            return {
                "value": float(lg["value"]),
                "series": pd.Series(dtype=float),
                "timestamp": lastgood.parse_ts(lg),
                "source": "alternative.me/fng (last-good)",
                "label": label,
                "classification": lg.get("classification") or _classify(float(lg["value"])),
                "stale": True,
                "error": str(e),
            }
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc), "source": "alternative.me/fng",
            "label": label, "classification": None, "stale": True, "error": str(e),
        }


if __name__ == "__main__":
    r = fetch_fear_greed()
    print(f"{r['label']}: {r['value']} ({r['classification']}) @ {r['timestamp']} stale={r['stale']}")
    print(f"  series: {len(r['series'])} pts" + (f", {r['series'].index[0].date()}→{r['series'].index[-1].date()}" if len(r['series']) else ""))
    if r["error"]:
        print(f"  ERROR: {r['error']}")

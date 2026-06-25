"""Overnight Reverse Repo (RRP) from the NY Fed Markets API.

Direct from the desk that runs the ON RRP facility — keyless JSON, daily.
Freshest current RRP value + short cross-check series; FRED RRPONTSYD supplies the
long historical series for Net Liquidity.

Endpoint: /api/rp/reverserepo/all/results/lastTwoWeeks.json
Each op: {operationType, operationDate, term, totalAmtAccepted, ...}
totalAmtAccepted is in USD; we report $B.
"""
from __future__ import annotations

import pandas as pd
import requests
from datetime import datetime, timezone

from . import lastgood

URL = "https://markets.newyorkfed.org/api/rp/reverserepo/all/results/lastTwoWeeks.json"
HEADERS = {"User-Agent": "nassim-dashboard/1.0", "Accept": "application/json"}
_KEY = "rrp"


def _is_overnight_rrp(op: dict) -> bool:
    otype = (op.get("operationType") or "").lower()
    term = (op.get("term") or "").lower()
    note = (op.get("note") or "").lower()
    if "reverse" not in otype:
        return False
    return ("overnight" in term) or ("overnight" in note) or (term == "")


def fetch_rrp() -> dict:
    """ON RRP accepted amount in $B (value) + short daily series in $B."""
    label = "Overnight Reverse Repo ($B)"
    try:
        r = requests.get(URL, headers=HEADERS, timeout=25)
        r.raise_for_status()
        ops = r.json().get("repo", {}).get("operations", [])
        rows = {}
        for op in ops:
            if not _is_overnight_rrp(op):
                continue
            amt = op.get("totalAmtAccepted")
            d = op.get("operationDate")
            if amt in (None, "") or not d:
                continue
            try:
                rows[pd.to_datetime(d).normalize()] = float(amt) / 1e9  # USD → $B
            except Exception:
                continue
        if not rows:
            raise RuntimeError("no overnight RRP operations found")
        s = pd.Series(rows).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        s.name = "rrp_b"
        latest = float(s.iloc[-1])
        ts = s.index[-1].to_pydatetime()
        lastgood.save(_KEY, latest, ts)
        return {
            "value": latest, "series": s, "timestamp": ts,
            "source": "newyorkfed/reverserepo", "label": label,
            "stale": False, "error": None,
        }
    except Exception as e:
        lg = lastgood.load(_KEY)
        if lg is not None:
            return {
                "value": float(lg["value"]), "series": pd.Series(dtype=float),
                "timestamp": lastgood.parse_ts(lg), "source": "newyorkfed (last-good)",
                "label": label, "stale": True, "error": str(e),
            }
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc), "source": "newyorkfed",
            "label": label, "stale": True, "error": str(e),
        }


if __name__ == "__main__":
    r = fetch_rrp()
    print(f"{r['label']}: {r['value']} @ {r['timestamp']} stale={r['stale']}")
    if len(r["series"]):
        print(f"  series {len(r['series'])} pts {r['series'].index[0].date()}→{r['series'].index[-1].date()}")
    if r["error"]:
        print(f"  ERROR: {r['error']}")

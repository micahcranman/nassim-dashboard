"""Treasury General Account (TGA) from the US Treasury Fiscal Data API.

Direct from the issuer — keyless JSON, daily, lower latency than FRED's WTREGEN.
Used as the freshest current TGA value + cross-check for Net Liquidity; FRED supplies
the long historical series.

Dataset: Daily Treasury Statement → operating_cash_balance
Row of interest: account_type == "Treasury General Account (TGA) Closing Balance"
Value field: close_today_bal (or open_today_bal when close is null), in millions USD.
"""
from __future__ import annotations

import pandas as pd
import requests
from datetime import datetime, timezone, date, timedelta

from . import lastgood

BASE = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
        "/v1/accounting/dts/operating_cash_balance")
HEADERS = {"User-Agent": "nassim-dashboard/1.0", "Accept": "application/json"}
_TGA_CLOSING = "Treasury General Account (TGA) Closing Balance"
_KEY = "tga"


def _row_value(rec):
    for f in ("close_today_bal", "open_today_bal"):
        v = rec.get(f)
        if v not in (None, "", "null"):
            try:
                return float(v)
            except Exception:
                pass
    return None


def fetch_tga() -> dict:
    """TGA closing balance in $B (value) + daily series in $B."""
    label = "Treasury General Account ($B)"
    try:
        # Filter client-side: the account_type string contains parens/spaces that break
        # the server-side filter param. Pull recent rows desc and keep the closing-balance ones.
        params = {
            "fields": "record_date,account_type,close_today_bal,open_today_bal",
            "sort": "-record_date",
            "page[size]": "600",
        }
        data = None
        last_err = None
        for attempt in range(3):
            try:
                r = requests.get(BASE, params=params, headers=HEADERS, timeout=25)
                r.raise_for_status()
                data = r.json().get("data", [])
                break
            except Exception as ex:
                last_err = ex
                import time as _t; _t.sleep(1.5 * (attempt + 1))
        if not data:
            raise last_err or RuntimeError("empty TGA data")
        rows = {}
        for rec in data:
            if _TGA_CLOSING not in (rec.get("account_type") or ""):
                continue
            v = _row_value(rec)
            if v is None:
                continue
            rows[pd.to_datetime(rec["record_date"]).normalize()] = v / 1000.0  # millions → $B
        if not rows:
            raise RuntimeError("no usable TGA closing-balance rows")
        s = pd.Series(rows).sort_index()
        s.name = "tga_b"
        latest = float(s.iloc[-1])
        ts = s.index[-1].to_pydatetime()
        lastgood.save(_KEY, latest, ts)
        return {
            "value": latest, "series": s, "timestamp": ts,
            "source": "treasury.fiscaldata/operating_cash_balance",
            "label": label, "stale": False, "error": None,
        }
    except Exception as e:
        lg = lastgood.load(_KEY)
        if lg is not None:
            return {
                "value": float(lg["value"]), "series": pd.Series(dtype=float),
                "timestamp": lastgood.parse_ts(lg),
                "source": "treasury (last-good)", "label": label,
                "stale": True, "error": str(e),
            }
        return {
            "value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc), "source": "treasury",
            "label": label, "stale": True, "error": str(e),
        }


if __name__ == "__main__":
    r = fetch_tga()
    print(f"{r['label']}: {r['value']} @ {r['timestamp']} stale={r['stale']}")
    if len(r["series"]):
        print(f"  series {len(r['series'])} pts {r['series'].index[0].date()}→{r['series'].index[-1].date()}")
    if r["error"]:
        print(f"  ERROR: {r['error']}")

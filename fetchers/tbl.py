"""The Bitcoin Layer (TBL) — AI liquidity supertrend, for the Macro/Liquidity panel.

Source: research.thebitcoinlayer.com/overview?tab=ai&chart=supertrend  (login-gated).
Strategy: headless Playwright login with TBL_EMAIL / TBL_PASSWORD, then read the
supertrend chart's data. The page is a SvelteKit/Next app; the chart is hydrated from an
XHR/JSON endpoint — once we capture that endpoint+cookie we can later replay it with plain
requests (cheaper, less fragile). This first pass sniffs network responses during login.

CONTRACT: standard {value, series, stale, source, error} + last-good fallback. This source
is FRAGILE and BEST-EFFORT by design — on any failure (no creds, no Playwright, login
change, selector drift) it returns last-good stale rather than raising, so it can never
break the dashboard build. It feeds the SEPARATE macro/liquidity panel, never the core net.

Local note: Playwright + its chromium are typically only present in CI (see build.yml:
`playwright install chromium`). Locally this returns stale/None, which is expected.
The `value` is the supertrend's signed liquidity reading (expanding>0 → long-supportive,
contracting<0 → short-supportive); exact scaling is normalized once the live payload shape
is confirmed against the rendered chart.
"""
from __future__ import annotations

import os
import json
from datetime import datetime, timezone

import pandas as pd

from . import lastgood

_KEY = "tbl"
LOGIN_URL = "https://research.thebitcoinlayer.com/login"
CHART_URL = "https://research.thebitcoinlayer.com/overview?tab=ai&chart=supertrend"
_LABEL = "TBL Liquidity (supertrend)"


def _stale(err: str) -> dict:
    lg = lastgood.load(_KEY)
    if lg is not None:
        return {"value": float(lg["value"]), "series": pd.Series(dtype=float),
                "timestamp": lastgood.parse_ts(lg), "source": "thebitcoinlayer (last-good)",
                "label": _LABEL, "stale": True, "error": err}
    return {"value": None, "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc), "source": "thebitcoinlayer",
            "label": _LABEL, "stale": True, "error": err}


def _parse_series(payload) -> pd.Series:
    """Best-effort extraction of a {date->value} liquidity series from a captured JSON
    payload. TBL's exact schema is confirmed live in CI; we probe the common shapes
    (list of {date/time/t, value/v/y} or columnar {dates:[], values:[]})."""
    rows = {}
    def add(d, v):
        try:
            rows[pd.to_datetime(d).normalize()] = float(v)
        except Exception:
            pass
    if isinstance(payload, dict):
        # columnar
        dates = payload.get("dates") or payload.get("x") or payload.get("labels")
        vals = payload.get("values") or payload.get("y") or payload.get("data")
        if isinstance(dates, list) and isinstance(vals, list) and len(dates) == len(vals):
            for d, v in zip(dates, vals):
                add(d, v if not isinstance(v, dict) else v.get("value"))
        # nested series
        for key in ("series", "supertrend", "result", "data"):
            sub = payload.get(key)
            if isinstance(sub, list):
                payload = sub
                break
    if isinstance(payload, list):
        for rec in payload:
            if isinstance(rec, dict):
                d = rec.get("date") or rec.get("time") or rec.get("t") or rec.get("x")
                v = rec.get("value") or rec.get("v") or rec.get("y") or rec.get("close")
                if d is not None and v is not None:
                    add(d, v)
            elif isinstance(rec, (list, tuple)) and len(rec) >= 2:
                add(rec[0], rec[1])
    s = pd.Series(rows).sort_index()
    return s.dropna()


def fetch_tbl_liquidity() -> dict:
    email = os.environ.get("TBL_EMAIL", "").strip()
    password = os.environ.get("TBL_PASSWORD", "").strip()
    if not email or not password:
        return _stale("TBL_EMAIL/TBL_PASSWORD not set")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return _stale(f"playwright unavailable: {e}")

    captured = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()

            def on_response(resp):
                try:
                    ct = resp.headers.get("content-type", "")
                    if "application/json" in ct and any(
                            k in resp.url.lower() for k in ("supertrend", "liquidity", "overview", "ai", "chart", "metric")):
                        captured.append((resp.url, resp.json()))
                except Exception:
                    pass

            page.on("response", on_response)

            # --- login ---
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            for sel in ('input[type="email"]', 'input[name="email"]', '#email'):
                if page.query_selector(sel):
                    page.fill(sel, email); break
            for sel in ('input[type="password"]', 'input[name="password"]', '#password'):
                if page.query_selector(sel):
                    page.fill(sel, password); break
            for sel in ('button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Log in")'):
                if page.query_selector(sel):
                    page.click(sel); break
            page.wait_for_load_state("networkidle", timeout=45000)

            # --- chart page (triggers the supertrend XHR) ---
            page.goto(CHART_URL, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(3500)
            browser.close()
    except Exception as e:
        return _stale(f"playwright run failed: {e}")

    # pick the captured payload that yields the longest series
    best = pd.Series(dtype=float)
    best_url = ""
    for url, payload in captured:
        s = _parse_series(payload)
        if len(s) > len(best):
            best, best_url = s, url
    if best.empty:
        return _stale("no supertrend series captured (selectors/endpoint may have changed)")

    latest = float(best.iloc[-1])
    ts_latest = best.index[-1].to_pydatetime()
    lastgood.save(_KEY, latest, ts_latest)
    return {"value": latest, "series": best, "timestamp": ts_latest,
            "source": f"thebitcoinlayer ({best_url.split('?')[0].rsplit('/',1)[-1] or 'supertrend'})",
            "label": _LABEL, "stale": False, "error": None}


if __name__ == "__main__":
    envf = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(envf):
        for line in open(envf):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    r = fetch_tbl_liquidity()
    print(f"{r['label']}: {r['value']} stale={r['stale']} src={r['source']}")
    if r["error"]:
        print(f"  note: {r['error']}")

"""MSTR BTC holdings. Tries saylortracker.com scrape; falls back to hardcoded with timestamp."""
import re
import requests
from datetime import datetime, timezone
import pandas as pd

# Fallback baseline: last known public figure
FALLBACK_HOLDINGS = 597_325
FALLBACK_DATE = "2026-05-12"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; nassim-dashboard/1.0)"}


def fetch_mstr_btc_holdings():
    candidates = [
        "https://saylortracker.com/",
        "https://www.saylortracker.com/",
    ]
    for url in candidates:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            html = r.text
            # Look for patterns like "597,325 BTC" or "BTC Holdings: 597,325"
            matches = re.findall(r"([0-9]{3}(?:,[0-9]{3})+)\s*(?:BTC|bitcoin)", html, re.IGNORECASE)
            if matches:
                holdings = max(int(m.replace(",", "")) for m in matches)
                if holdings >= 100_000:  # sanity floor
                    return {
                        "value": float(holdings),
                        "series": pd.Series(dtype=float),
                        "timestamp": datetime.now(timezone.utc),
                        "source": f"saylortracker.com scrape",
                        "label": "MSTR BTC Holdings",
                        "stale": False,
                        "error": None,
                    }
        except Exception:
            continue
    # Fallback
    return {
        "value": float(FALLBACK_HOLDINGS),
        "series": pd.Series(dtype=float),
        "timestamp": datetime.fromisoformat(FALLBACK_DATE),
        "source": f"hardcoded fallback ({FALLBACK_DATE})",
        "label": "MSTR BTC Holdings",
        "stale": True,
        "error": "scrape failed; using hardcoded fallback",
    }


if __name__ == "__main__":
    r = fetch_mstr_btc_holdings()
    print(f"{r['label']}: {r['value']:,.0f} @ {r['timestamp']} (stale={r['stale']})")
    if r.get("error"):
        print(f"  NOTE: {r['error']}")

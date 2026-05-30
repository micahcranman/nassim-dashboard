"""MSTR BTC holdings.

Primary source: bitcointreasuries.net — they embed structured data in their
page HTML including ticker:"MSTR" + btc_balance:NNNNNN.

Fallback: hardcoded last-known value with timestamp.
"""
import re
import requests
from datetime import datetime, timezone
import pandas as pd

# Hardcoded fallback baseline — last known public figure (Saylor disclosure)
FALLBACK_HOLDINGS = 597_325
FALLBACK_DATE = "2026-05-12"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _try_bitcointreasuries():
    """Parse bitcointreasuries.net for MSTR btc_balance.

    Structured JS object embedded in page HTML contains records like:
      ticker:{symbol:"MSTR",...},...btc_balance:NNNNNN,...

    The gap between the MSTR ticker marker and btc_balance contains nested
    objects (industries, tags). We use a generous window of 600 chars and
    require btc_balance to appear within it, then sanity-check the number.
    """
    r = requests.get("https://bitcointreasuries.net", headers=HEADERS, timeout=30)
    r.raise_for_status()
    text = r.text
    # Find every occurrence of MSTR ticker symbol
    candidates = []
    for m in re.finditer(r'symbol:"MSTR"', text):
        # Look in the 600 chars after this for btc_balance
        window = text[m.end():m.end() + 800]
        bm = re.search(r'btc_balance:(\d+)', window)
        if bm:
            n = int(bm.group(1))
            if 100_000 <= n <= 5_000_000:
                candidates.append(n)
    if not candidates:
        raise RuntimeError("MSTR btc_balance not found in bitcointreasuries.net HTML")
    # Take the largest plausible (in case of multiple records for related entities)
    holdings = max(candidates)
    return holdings, "bitcointreasuries.net"


def fetch_mstr_btc_holdings():
    try:
        holdings, source = _try_bitcointreasuries()
        return {
            "value": float(holdings),
            "series": pd.Series(dtype=float),
            "timestamp": datetime.now(timezone.utc),
            "source": source,
            "label": "MSTR BTC Holdings",
            "stale": False,
            "error": None,
        }
    except Exception as e:
        return {
            "value": float(FALLBACK_HOLDINGS),
            "series": pd.Series(dtype=float),
            "timestamp": datetime.fromisoformat(FALLBACK_DATE),
            "source": f"hardcoded fallback ({FALLBACK_DATE})",
            "label": "MSTR BTC Holdings",
            "stale": True,
            "error": f"scrape failed ({e}); using hardcoded fallback",
        }


if __name__ == "__main__":
    r = fetch_mstr_btc_holdings()
    print(f"{r['label']}: {r['value']:,.0f} @ {r['timestamp']} (stale={r['stale']})")
    if r.get("error"):
        print(f"  NOTE: {r['error']}")

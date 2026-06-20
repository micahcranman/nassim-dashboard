"""Committed last-good value store.

The real reliability gap in CI: each GitHub Actions run is a fresh runner with an
empty `.cache/`, so the existing "fall back to stale cache" logic never fires across
runs. This store lives under `outputs/lastgood/` which CI commits, so the last
successful scalar survives between runs and a source outage shows yesterday's number
(flagged stale) instead of a blank.

Scalar + timestamp only — full series for charts come from the committed history;
a single failed run can tolerate an empty series but must never show a blank value.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / "outputs" / "lastgood"


def save(key: str, value, timestamp=None, **extra) -> None:
    """Persist the last successful value for `key`. No-op if value is None."""
    if value is None:
        return
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        ts = timestamp or datetime.now(timezone.utc)
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        rec = {"value": value, "timestamp": ts_str}
        rec.update({k: v for k, v in extra.items() if v is not None})
        (_DIR / f"{key}.json").write_text(json.dumps(rec))
    except Exception:
        pass


def load(key: str):
    """Return the stored {value, timestamp, ...} dict for `key`, or None."""
    p = _DIR / f"{key}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def parse_ts(rec) -> datetime:
    """Best-effort parse of a stored timestamp back to a datetime."""
    try:
        return datetime.fromisoformat(rec["timestamp"])
    except Exception:
        return datetime.now(timezone.utc)

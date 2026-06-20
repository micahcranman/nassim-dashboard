"""build_signals.py — enrich the v8.5 backtest trade dump into docs/signals.json.

Reads the locked v8.5 backtest's trade log + daily equity curve and joins, per trade,
the signals/gates that were live at the entry date (MRI, MRI<12, MSTR MA200 5-day slope,
realized-vol percentile as the IV-percentile proxy, days-since-Q-fire). Emits an enriched
docs/signals.json (+ repo-root copy) consumed by the dashboard's v8.5 STRATEGY SIMULATOR.

Inputs (regenerate the dumps with the locked env vars first — see V2_HANDOFF.md):
    V8_TRADE_DUMP_PATH=/tmp/v8_5_trades.jsonl   (trade event log)
    V8_EQ_DUMP_PATH=/tmp/v8_5_equity.csv        (authoritative daily NAV — used for replay scaling)

The equity curve is the system of record for the simulator's scaling math: NAV is exact
per day, so replaying from any start date / starting capital is a single linear rescale
(scale = capital / NAV_at_start). We never reconstruct equity from the ambiguous per-event
`value` fields (those are position-level notionals, not always account NAV).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent          # scripts/dashboard/
RESEARCH = REPO.parent / "mstr_research"
DATA = REPO.parent.parent / "data"                      # workspace-investing/data (full-history)

TRADE_DUMP = Path(os.environ.get("V8_TRADE_DUMP_PATH", "/tmp/v8_5_trades.jsonl"))
EQ_DUMP = Path(os.environ.get("V8_EQ_DUMP_PATH", "/tmp/v8_5_equity.csv"))
MRI_CSV = DATA / "checkonchain_mri.csv"
MSTR_CSV = REPO.parent / "mstr_daily_history.csv"       # hybrid (2018-03-19+), what the backtest reads

# Position taxonomy (v8.5 vocab): t2a = PUT, t2b = SHORT. ENV = BTC Z-envelope short.
ENTRY_TYPES = {"BULL_ENTRY", "ENV_ENTRY", "MSTR_SHORT_ENTRY", "MSTR_PUT_ENTRY", "V8_TIER1B_Q7"}
EXIT_TYPES = {"BULL_EXIT", "ENV_EXIT", "MSTR_SHORT_EXIT", "MSTR_PUT_EXIT",
              "V8_TIER1B_EXIT", "V8_TIER1B_MERGE", "T1B_TERMINAL_CLOSE"}
FAMILY = {  # entry-type -> (family key, position label, direction)
    "BULL_ENTRY":       ("BULL", "t1-BULL long",  "long"),
    "V8_TIER1B_Q7":     ("T1B",  "t1b Q-fire long", "long"),
    "MSTR_PUT_ENTRY":   ("PUT",  "t2a PUT hedge",  "short"),
    "MSTR_SHORT_ENTRY": ("SHORT", "t2b SHORT hedge", "short"),
    "ENV_ENTRY":        ("ENV",  "ENV BTC short",  "short"),
}
EXIT_FAMILY = {
    "BULL_EXIT": "BULL", "ENV_EXIT": "ENV", "MSTR_SHORT_EXIT": "SHORT",
    "MSTR_PUT_EXIT": "PUT", "V8_TIER1B_EXIT": "T1B", "V8_TIER1B_MERGE": "T1B",
    "T1B_TERMINAL_CLOSE": "T1B",
}
# Chart markers keep the 4 types the frontend SIGMETA already knows.
MARKER_MAP = {
    "V8_TIER1B_Q7": "V8_TIER1B_TRANCHE",
    "V8_TIER1B_EXIT": "V8_TIER1B_EXIT",
    "MSTR_PUT_ENTRY": "MSTR_PUT_ENTRY",
    "MSTR_SHORT_ENTRY": "MSTR_SHORT_ENTRY",
}


def _load_trades():
    rows = []
    for line in TRADE_DUMP.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _gate_panels():
    """Build asof-lookup series for the entry gates from canonical sources."""
    panels = {}
    # MRI (checkonchain Index trace, the v8.5 <12 Q-fire gate)
    if MRI_CSV.exists():
        m = pd.read_csv(MRI_CSV)
        m["Date"] = pd.to_datetime(m["Date"])
        panels["mri"] = m.set_index("Date")["MRI"].sort_index()
    # MSTR MA200 5-day slope (%) — the hedge gate that admits PUT/SHORT — and a 252d
    # realized-vol percentile (the IV-percentile proxy the t2a PUT keys on, ivlb=252).
    if MSTR_CSV.exists():
        px = pd.read_csv(MSTR_CSV)
        px["Date"] = pd.to_datetime(px["Date"])
        s = px.set_index("Date")["Close"].sort_index()
        ma200 = s.rolling(200).mean()
        panels["slope_5d"] = ((ma200 - ma200.shift(5)) / ma200.shift(5) * 100.0)
        ret = np.log(s / s.shift(1))
        rvol = ret.rolling(20).std() * np.sqrt(252)            # annualized 20d realized vol
        panels["rvol_pct"] = rvol.rolling(252, min_periods=60).apply(
            lambda w: (w[-1] >= w).mean() * 100.0, raw=True)    # percentile rank within trailing year
    return panels


def _asof(series, date):
    if series is None or series.empty:
        return None
    s = series[series.index <= date]
    if s.empty:
        return None
    v = s.iloc[-1]
    return None if pd.isna(v) else round(float(v), 4)


def main():
    if not TRADE_DUMP.exists():
        print(f"ERROR: trade dump not found at {TRADE_DUMP}. Re-run the v8.5 backtest first "
              f"(see V2_HANDOFF.md Phase 3).", file=sys.stderr)
        return 1
    events = _load_trades()
    panels = _gate_panels()

    # daily equity curve (authoritative NAV) → weekly downsample + always keep trade-date anchors
    equity_curve, eq_index = [], None
    if EQ_DUMP.exists():
        eq = pd.read_csv(EQ_DUMP)
        eq["date"] = pd.to_datetime(eq["date"])
        eq = eq.set_index("date")["total"].sort_index()
        eq_index = eq
        keep = set(eq.index[::7])                       # weekly
        keep |= {pd.to_datetime(e["date"]) for e in events if "date" in e}  # + trade dates
        sub = eq[eq.index.isin(keep)].sort_index()
        equity_curve = [{"d": d.strftime("%Y-%m-%d"), "v": round(float(v), 2)}
                        for d, v in sub.items()]

    qfire_dates = sorted(pd.to_datetime(e["date"]) for e in events if e["type"] == "V8_TIER1B_Q7")

    def gates_at(date_str, ev):
        d = pd.to_datetime(date_str)
        mri = _asof(panels.get("mri"), d)
        prior_q = [q for q in qfire_dates if q <= d]
        g = {
            "mri": mri,
            "mri_below_12": (mri is not None and mri < 12),
            "slope_5d": _asof(panels.get("slope_5d"), d),
            "rvol_pct": _asof(panels.get("rvol_pct"), d),
            "days_since_qfire": ((d - prior_q[-1]).days if prior_q else None),
        }
        # Q-fire dumps carry the exact entry-bar internals (extension/RSI/Mayer)
        for k in ("ext", "rsi", "mayer"):
            if k in ev and ev[k] is not None:
                g[k] = round(float(ev[k]), 4)
        return g

    # FIFO-pair entries with exits per family
    open_q = {k: [] for k in ("BULL", "T1B", "PUT", "SHORT", "ENV")}
    trades, tid = [], 0
    for ev in events:
        t = ev["type"]
        if t in ENTRY_TYPES:
            fam, label, direction = FAMILY[t]
            tid += 1
            open_q[fam].append({
                "id": tid, "type": label, "family": fam, "direction": direction,
                "raw_entry_type": t,
                "entry_date": ev["date"], "entry_price": round(float(ev["price"]), 4),
                "size_usd": round(float(ev.get("value") or 0.0), 2),
                "gates": gates_at(ev["date"], ev),
            })
        elif t in EXIT_TYPES:
            fam = EXIT_FAMILY[t]
            if not open_q[fam]:
                continue
            tr = open_q[fam].pop(0)
            tr["exit_date"] = ev["date"]
            tr["exit_price"] = round(float(ev["price"]), 4)
            tr["exit_reason"] = ev.get("reason") or ev.get("exit_code") or t
            tr["exit_code"] = ev.get("exit_code") or t
            tr["days"] = ev.get("days")
            if tr["days"] is None:  # not all exit events carry it (e.g. t1b liquidations/merges)
                tr["days"] = (pd.to_datetime(ev["date"]) - pd.to_datetime(tr["entry_date"])).days
            # P&L: prefer the dump's own realized figures; otherwise derive honestly.
            pnl = ev.get("pnl")
            pnl_pct = ev.get("pnl_pct")
            if pnl is None and t == "BULL_EXIT" and tr["size_usd"]:
                pnl = round(float(ev.get("value", 0.0)) - tr["size_usd"], 2)  # all-in: NAV delta
            if pnl is None and pnl_pct is not None and tr["size_usd"]:
                pnl = round(tr["size_usd"] * float(pnl_pct) / 100.0, 2)
            if pnl_pct is None:
                if tr["direction"] == "long":
                    pnl_pct = round((tr["exit_price"] / tr["entry_price"] - 1) * 100, 4)
                else:
                    pnl_pct = round((1 - tr["exit_price"] / tr["entry_price"]) * 100, 4)
            tr["pnl"] = round(float(pnl), 2) if pnl is not None else None
            tr["pnl_pct"] = round(float(pnl_pct), 4) if pnl_pct is not None else None
            tr["open"] = False
            trades.append(tr)
    # anything still open → mark-to-market client-side at current price
    for fam, lst in open_q.items():
        for tr in lst:
            tr.update({"exit_date": None, "exit_price": None, "exit_reason": None,
                       "exit_code": None, "days": None, "pnl": None, "pnl_pct": None,
                       "open": True})
            trades.append(tr)
    trades.sort(key=lambda x: x["entry_date"])

    # chart markers (back-compat with the existing signal chart)
    markers = []
    for ev in events:
        if ev["type"] in MARKER_MAP:
            mp = MARKER_MAP[ev["type"]]
            markers.append({"type": mp, "date": ev["date"], "price": round(float(ev["price"]), 2),
                            "pnl": (round(float(ev["pnl"]), 2) if ev.get("pnl") is not None else None)})

    out = {
        "_generated_by": "scripts/build_signals.py",
        "backtest": {
            "version": "v8.5", "filter": "mstr_ma200_slope_5d",
            "initial_capital": 100000.0,
            "final_equity": (round(float(eq_index.iloc[-1]), 2) if eq_index is not None else None),
            "start_date": (eq_index.index[0].strftime("%Y-%m-%d") if eq_index is not None else None),
            "end_date": (eq_index.index[-1].strftime("%Y-%m-%d") if eq_index is not None else None),
            "sharpe": 1.4701, "mdd_pct": 36.2203, "cagr_pct": 294.67,
            "iv_percentile_lookback": 252, "iv_percentile_floor": 0.10,
            "note": "rvol_pct = 252-day realized-vol percentile (the IV-percentile proxy the t2a PUT gate keys on).",
        },
        "markers": markers,
        "trades": trades,
        "equity_curve": equity_curve,
    }
    for p in (REPO / "docs" / "signals.json", REPO / "signals.json"):
        p.write_text(json.dumps(out, indent=2))
    closed = [t for t in trades if not t["open"]]
    print(f"Wrote signals.json: {len(markers)} markers, {len(trades)} trades "
          f"({len(closed)} closed, {len(trades)-len(closed)} open), "
          f"{len(equity_curve)} equity points.")
    print(f"  final equity ${out['backtest']['final_equity']:,.0f} from "
          f"${out['backtest']['initial_capital']:,.0f}")
    for t in trades:
        g = t["gates"]
        ex = t["exit_date"] or "OPEN"
        pnl = f"${t['pnl']:,.0f}" if t["pnl"] is not None else "—"
        print(f"  {t['entry_date']} {t['type']:18} → {ex:10} pnl {pnl:>16} "
              f"| MRI {g['mri']} slope5d {g['slope_5d']} rvol%{g['rvol_pct']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

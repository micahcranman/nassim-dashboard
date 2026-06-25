"""
intel_lib.py — shared library for the MSTR/BTC Narrative-Intelligence Report pipeline.

Pieces (all pure-Python, no LLM):
  * report_periods()  -> the Mon/Thu cadence + coverage windows
  * load_corpus_window() -> that period's actual analyst posts (the only narrative input)
  * signal_snapshot() -> the dashboard's point-in-time system state for the period
  * describe_signal() -> plain-language, CODENAME-FREE system read (what the writer is told)
  * build_packet() -> assembles {period, signal, corpus} for one report

Design contract (from the project handoff — do NOT violate):
  - The report writer sees ONLY: the plain-language signal + the sanitized trust
    profiles + that week's actual posts. NEVER the scorecards (they contain outcomes).
  - The signal description carries no internal codenames (no "Q-fire", "t1b",
    "slope_5d", "MRI"); it speaks in plain trader English.
  - Strictly point-in-time: a report for date D knows nothing published after its
    coverage window.
"""

import os
import re
import json
import glob
import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
REPO = HERE.parent                                  # scripts/dashboard
CORPUS_ROOT = Path(os.environ.get("INTEL_CORPUS_ROOT",
                                  "/Users/micahs-mac-mini/newsletter-intelligence"))
LATEST_JSON = REPO / "docs" / "latest.json"
PROFILES_MD = HERE / "profiles.md"
BUILD_DIR = HERE / "build"
DOCS_INTEL = REPO / "docs" / "intel"

# The six SCORED forecasters (folder -> display name). These six and only these six
# are the graded roster the sanitized profiles cover.
ROSTER = [
    ("james-check",      "James Check"),
    ("lynn-alden",       "Lyn Alden"),
    ("capital-wars",     "Michael Howell"),
    ("the-bitcoin-layer","The Bitcoin Layer"),
    ("macro-ops",        "Macro Ops"),
    ("willy-woo",        "Willy Woo"),
]
FOLDER_BY_NAME = {name: folder for folder, name in ROSTER}

MAX_POST_CHARS = 7000   # truncate any single post body fed to the writer

# ---------------------------------------------------------------------------
# Cadence
# ---------------------------------------------------------------------------

def report_periods(anchor: datetime.date, n: int):
    """The n most-recent report periods at/at-or-before `anchor`.

    Cadence: a MONDAY report covers the prior Thursday..Sunday; a THURSDAY report
    covers that week's Monday..Wednesday. Returns newest-first list of dicts:
      {report_date, kind ('Mon'|'Thu'), cover_start, cover_end, slug, label}
    """
    out = []
    d = anchor
    while len(out) < n:
        wd = d.weekday()        # Mon=0 .. Sun=6
        if wd == 3:             # Thursday -> Mon..Wed (same week)
            start = d - datetime.timedelta(days=3)
            end = d - datetime.timedelta(days=1)
            out.append(_period(d, "Thu", start, end))
        elif wd == 0:           # Monday -> Thu..Sun (prior week)
            start = d - datetime.timedelta(days=4)
            end = d - datetime.timedelta(days=1)
            out.append(_period(d, "Mon", start, end))
        d -= datetime.timedelta(days=1)
    return out


def _period(report_date, kind, start, end):
    return {
        "report_date": report_date.isoformat(),
        "kind": kind,
        "cover_start": start.isoformat(),
        "cover_end": end.isoformat(),
        "slug": report_date.isoformat(),
        "label": f"{_fmt(start)} – {_fmt(end)}, {end.year}",
        "title": f"Market Note — week of {report_date.strftime('%B %-d, %Y')}",
    }


def _fmt(d):
    return d.strftime("%b %-d")

# ---------------------------------------------------------------------------
# Corpus ingestion
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)


def _parse_front_matter(raw: str):
    m = _FM_RE.match(raw)
    if not m:
        return {}, raw
    head, body = m.group(1), m.group(2)
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def _clean_body(body: str) -> str:
    """Strip image markdown / CDN links / repeated whitespace so the writer reads prose."""
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)             # images
    body = re.sub(r"\[\s*\n*\s*\[Chart\][^\]]*\]\([^)]*\)\s*\]\([^)]*\)", "", body)
    body = re.sub(r"\[\s*\]\([^)]*\)", "", body)                  # empty links
    body = re.sub(r"https?://substackcdn\.com[^\s)]*", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def load_corpus_window(start_iso: str, end_iso: str):
    """All in-window posts for the six scored analysts. Returns {display_name: [post,...]}.
    A post = {analyst, title, date, url, is_paid, word_count, text}. Strictly date-filtered
    by the filename's YYYY-MM-DD prefix (the publication date)."""
    start = datetime.date.fromisoformat(start_iso)
    end = datetime.date.fromisoformat(end_iso)
    result = {}
    for folder, name in ROSTER:
        posts = []
        d = CORPUS_ROOT / folder
        if d.is_dir():
            for fp in sorted(d.glob("*.md")):
                m = re.match(r"(\d{4}-\d{2}-\d{2})", fp.name)
                if not m:
                    continue
                fdate = datetime.date.fromisoformat(m.group(1))
                if not (start <= fdate <= end):
                    continue
                raw = fp.read_text(errors="ignore")
                meta, body = _parse_front_matter(raw)
                body = _clean_body(body)
                truncated = len(body) > MAX_POST_CHARS
                posts.append({
                    "analyst": name,
                    "date": meta.get("date", m.group(1)),
                    "title": meta.get("title", fp.stem),
                    "url": meta.get("url", ""),
                    "is_paid": meta.get("is_paid", "") in ("true", "True"),
                    "word_count": meta.get("word_count", ""),
                    "text": body[:MAX_POST_CHARS] + ("\n…[truncated]" if truncated else ""),
                    "file": fp.name,
                })
        result[name] = posts
    return result

# ---------------------------------------------------------------------------
# Signal snapshot (point-in-time dashboard state)
# ---------------------------------------------------------------------------

def _series_map(latest, ind_key):
    s = (latest.get("indicators", {}).get(ind_key, {}) or {}).get("series", []) or []
    return {p["d"]: p.get("v") for p in s if isinstance(p, dict) and "d" in p}


def _as_of(series: dict, date_iso: str):
    """Most recent value at or before date_iso (last available trading day)."""
    keys = sorted(k for k in series if k <= date_iso)
    return (series[keys[-1]], keys[-1]) if keys else (None, None)


def signal_snapshot(period, latest=None):
    """Numeric system state as-of the report date, plus a window trajectory.
    Reads docs/latest.json daily series (the same data the live console shows)."""
    if latest is None:
        latest = json.loads(LATEST_JSON.read_text())
    rd = period["report_date"]
    cs, ce = period["cover_start"], period["cover_end"]

    series = {k: _series_map(latest, k) for k in
              ("mri", "slope_5d", "mnav", "mstr_btc_trend")}
    btc = {p["d"]: p["v"] for p in latest.get("btc_overlay", [])}
    mstr = {p["d"]: p["v"] for p in latest.get("mstr_line", [])}
    osc = {p["d"]: p for p in latest.get("oscillator_v2", latest.get("oscillator", []))}

    def aso(name, src):
        v, on = _as_of(src, rd)
        return {"value": v, "as_of": on}

    snap = {
        "btc": aso("btc", btc),
        "mstr": aso("mstr", mstr),
        "mri": aso("mri", series["mri"]),
        "slope_5d": aso("slope", series["slope_5d"]),
        "mnav": aso("mnav", series["mnav"]),
    }
    # window trajectory for charts: every day in [cover_start-21d, report_date]
    win_start = (datetime.date.fromisoformat(cs) - datetime.timedelta(days=35)).isoformat()
    traj = []
    alldates = sorted(set(btc) | set(series["mri"]) | set(series["slope_5d"]))
    for dt in alldates:
        if win_start <= dt <= rd:
            traj.append({
                "d": dt,
                "btc": btc.get(dt),
                "mstr": mstr.get(dt),
                "mri": series["mri"].get(dt),
                "slope": series["slope_5d"].get(dt),
                "mnav": series["mnav"].get(dt),
                "in_window": cs <= dt <= ce,
            })
    snap["trajectory"] = traj

    # derived booleans / labels
    mri_v = snap["mri"]["value"]
    slope_v = snap["slope_5d"]["value"]
    mnav_v = snap["mnav"]["value"]
    snap["derived"] = {
        "mri_zone": _mri_zone(mri_v),
        "hedge_gate_open": (slope_v is not None and slope_v < 0),
        "trend_label": _slope_label(slope_v),
        "mnav_label": _mnav_label(mnav_v),
        "qfire_zone": (mri_v is not None and mri_v < 12),
    }
    # window MRI trajectory direction
    mris = [t["mri"] for t in traj if t["in_window"] and t["mri"] is not None]
    if len(mris) >= 2:
        snap["derived"]["mri_window_dir"] = "falling toward capitulation" if mris[-1] < mris[0] - 0.4 \
            else "lifting off the lows" if mris[-1] > mris[0] + 0.4 else "roughly flat"
    else:
        snap["derived"]["mri_window_dir"] = "flat"
    return snap


def _mri_zone(v):
    if v is None: return "unknown"
    if v < 12: return "capitulation extreme (deep-value buy zone)"
    if v < 30: return "accumulation zone"
    if v < 60: return "mid-range"
    if v < 100: return "extended"
    return "overheated"


def _slope_label(v):
    if v is None: return "unknown"
    if v <= -1: return "downtrend — defensive positioning permitted"
    if v < 0: return "rolling over"
    if v < 1: return "turning up"
    return "uptrend"


def _mnav_label(v):
    if v is None: return "unknown"
    if v < 0.9: return f"deep discount (~{v:.2f}× — stock below the value of the Bitcoin it holds)"
    if v < 1.0: return f"discount (~{v:.2f}×)"
    if v < 1.5: return f"slight premium (~{v:.2f}×)"
    return f"premium (~{v:.2f}×)"

# ---------------------------------------------------------------------------
# Plain-language signal description (CODENAME-FREE — this is what the writer reads)
# ---------------------------------------------------------------------------

def describe_signal(period, snap):
    """Compose the codename-free 'where the system stands' paragraph + a one-line posture.
    Mirrors the voice of the validated point-in-time samples."""
    d = snap["derived"]
    btc = snap["btc"]["value"]; mstr = snap["mstr"]["value"]; mnav = snap["mnav"]["value"]
    mri = snap["mri"]["value"]

    # which side is live
    hedge = d["hedge_gate_open"]
    qfire = d["qfire_zone"]
    near_q = (mri is not None and mri < 16)

    parts = []
    px = []
    if btc: px.append(f"Bitcoin near ${btc:,.0f}")
    if mstr: px.append(f"MicroStrategy near ${mstr:,.0f}")
    if px:
        parts.append(", ".join(px) + ".")

    # trend / hedge side
    if hedge:
        parts.append("The medium-term trend that governs our hedge is firmly negative, so the "
                     "long-term regime is bearish and defensive positions (shorts / puts) are "
                     "permitted — we are past 'watch for a top' and into an open hedge.")
    else:
        parts.append("The medium-term trend that governs our hedge has not rolled over, so no "
                     "defensive positions are admitted yet.")

    # bottom / capitulation side
    if qfire:
        parts.append("At the same time, the on-chain mean-reversion gauge has dropped into its "
                     "historic capitulation extreme — the deep-value buy zone that has marked "
                     "major lows. So the system is conflicted: a contrarian buy is arming against "
                     "a still-bearish trend. (The buy is an armed setup, not yet a confirmed "
                     "trigger — it needs to hold there, not just touch it.)")
    elif near_q:
        parts.append(f"The on-chain mean-reversion gauge is {d['mri_window_dir']} and sits just "
                     "above its capitulation extreme — close to, but not yet in, the deep-value "
                     "buy zone. No confirmed dip-buy signal, but it is the thing to watch.")
    else:
        parts.append("The on-chain mean-reversion gauge is well above its capitulation extreme — "
                     "no dip-buy signal, on-chain stress is not yet oversold.")

    if mnav is not None and mnav < 1.0:
        parts.append(f"MicroStrategy trades at a {d['mnav_label']} — a behavioural regime change "
                     "(below 1.0× the company's own policy inverts toward buying back stock rather "
                     "than issuing it for Bitcoin).")

    # one-line posture
    if qfire and hedge:
        posture = ("CONFLICTED — bearish trend (hedge open) colliding with a capitulation-extreme "
                   "buy setup. The question for the voices: is this a buyable bottom forming, or "
                   "more downside coming?")
        focus = "BOTTOM"
    elif hedge and near_q:
        posture = ("DEFENSIVE, with a bottom-watch building — trend bearish and hedge open, on-chain "
                   "stress approaching the buy extreme.")
        focus = "BOTTOM"
    elif hedge:
        posture = "DEFENSIVE — bearish trend, hedge open, no buy signal yet."
        focus = "TOP"
    else:
        posture = "NEUTRAL — no clean buy, no clean sell."
        focus = "BOTH"

    return {
        "paragraph": " ".join(parts),
        "posture": posture,
        "focus_side": focus,   # which side the voices most need to confirm this period
    }

# ---------------------------------------------------------------------------
# Packet assembly
# ---------------------------------------------------------------------------

def build_packet(period, latest=None):
    snap = signal_snapshot(period, latest)
    desc = describe_signal(period, snap)
    corpus = load_corpus_window(period["cover_start"], period["cover_end"])
    n_posts = sum(len(v) for v in corpus.values())
    silent = [name for name, posts in corpus.items() if not posts]
    return {
        "period": period,
        "signal": snap,
        "signal_plain": desc,
        "corpus": corpus,
        "n_posts": n_posts,
        "silent": silent,
        "profiles": PROFILES_MD.read_text(),
        "generated_at": None,   # stamped by caller
    }


if __name__ == "__main__":
    import sys
    anchor = datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 \
        else datetime.date.today()
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    periods = report_periods(anchor, n)
    BUILD_DIR.mkdir(exist_ok=True)
    latest = json.loads(LATEST_JSON.read_text())
    for p in periods:
        pkt = build_packet(p, latest)
        out = BUILD_DIR / f"packet-{p['slug']}.json"
        out.write_text(json.dumps(pkt, indent=2))
        print(f"{p['report_date']} ({p['kind']}) covers {p['cover_start']}..{p['cover_end']} "
              f"| {pkt['n_posts']} posts | silent: {', '.join(pkt['silent']) or 'none'} "
              f"| posture: {pkt['signal_plain']['posture'][:48]}…")
        print(f"    -> {out.name}")

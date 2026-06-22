# Nassim Dashboard v2 — Session Handoff (2026-06-22)

Strategy-aware confidence console for the **MSTR/BTC v8.5** directionally-neutral strategy.
This supersedes `V2_HANDOFF.md` (which was the mid-build "remaining work" list). The build is
now **functionally complete and preview-verified**; what's left is operator-gated (secrets,
deploy, a couple of confirmations). Read this top-to-bottom before continuing.

---

## TL;DR status
- **Repo:** `/Users/micahs-mac-mini/.openclaw/workspace-investing/scripts/dashboard/` — its own git repo, remote `github.com/micahcranman/nassim-dashboard.git`. Live (old v1) at https://micahcranman.github.io/nassim-dashboard/.
- **Branch:** `feat/dashboard-v2`. Latest commit **`81a2b40`** ("v2: v8.5 simulator + calibration methodology panel + mNAV cross-check"). Working tree clean. **NOTHING has been pushed/deployed** — the live site is still old v1.
- **Memory:** `~/.claude/projects/-Users-micahs-mac-mini/memory/project_nassim_dashboard_v2.md` carries a **"BUILD COMPLETE (2026-06-20)"** marker with full history.
- **Current reading** (from the last build at 2026-06-20, so the *data* is stale — see "Open items"): net **+65.9 → LONG-CAPITULATION**, macro **+18.2** (Tailwind). Calibration verified across all 4 zones.
- An hourly scheduled task drove the autonomous completion; it now no-ops. **I've disabled it** (it's done its job).

## How to run / preview (do this first)
```bash
cd /Users/micahs-mac-mini/.openclaw/workspace-investing/scripts/dashboard
python3 dashboard.py                 # fetches everything, writes outputs/latest.json (~60-90s)
cp outputs/latest.json docs/latest.json
cd docs && python3 -m http.server 8770    # open http://127.0.0.1:8770
```
`.env` (gitignored) already holds `BGEO_TOKEN`, `EODHD_API_TOKEN`, `BMP_API_KEY`. Background bash
resets cwd to home — always `cd` explicitly. Python 3.9 local; CI uses 3.11.

---

## What the dashboard does (architecture)

**1. Data layer — `fetchers/*.py`** (each returns `{value, series, stale, source, error}` + committed
last-good under `outputs/lastgood/`). The reliability story is the spine of the whole thing:
- **Bitcoin Magazine Pro is the AUTHORITATIVE primary** for the cycle-value indicators (clean CSV API,
  full history). `dashboard.py::_with_fallback()` tries BMP first for `mvrv_z, nupl, sth_mvrv, feargreed`
  and falls back to BGeometrics/alternative.me. `fetchers/bmp.py`. Key in `.env` as `BMP_API_KEY`.
- **MRI** (the v8.5 Q-fire gate) — `fetchers/checkonchain.py`, the "Index" Plotly trace, matches the
  strategy's `data/checkonchain_mri.csv` and the `<12` threshold. Do NOT swap to BGeometrics `mris`.
- **Macro** — `fetchers/fred.py` (keyed JSON API; keyless CSV fallback needs the DEFAULT user-agent or
  FRED blackholes it), with **Treasury** (`treasury.py`) + **NY Fed** (`nyfed.py`) as issuer-grade TGA/RRP
  for Net Liquidity.
- **RSI** — `fetchers/rsi.py` (BTC RSI-14). **TBL Liquidity** — `fetchers/tbl.py` (Playwright; best-effort).
  **Cohort** (STH-SOPR/STH-MVRV), **funding**, **F&G** — on-chain/sentiment.
- **mNAV** — `compute_derived()` uses strategy.com diluted shares; BTC extended via Yahoo. (See gotcha below.)

**2. Scoring — `scoring.py`** (the heart). Each indicator → ONE **signed** score in [-100,+100]
(+ = bottom/long, − = top/short), centered at 0. Net = weighted avg of CORE indicators.
- **5 labels** via `net_zone()`: ≥+65 **LONG-CAPITULATION**, +28..+64 **LONG-LOCAL**, ±27 **NEUTRAL**,
  −28..−64 **SHORT-LOCAL**, ≤−65 **SHORT-TOP**. (Cycle extremes saturate; locals are milder.)
- **Macro is separated** out of the core net into its own `macro_score` (Tailwind/Neutral/Headwind) — Micah's call (macro = noise for top/bottom timing). `MACRO_KEYS`, `MACRO_W`.
- **Weights:** `CORE_W` (top-callers concentrated: mnav/mvrv_z/mstr_btc_trend/slope_5d/sth_mvrv) and `MACRO_W`. `calibration_config.json` (from `scripts/calibrate_weights.py`) overrides bands/weights empirically.
- `scoring.export_config()` ships the bands+weights+thresholds into `latest.json` so the **frontend
  recomputes any historical date client-side** (powers the scrubber).

**3. v8.5 strategy-state** — the mechanical call (system of record), shown as chips: MRI vs 12, hedge
gate (slope_5d sign), IV %ile, mNAV, days-since-MRI<12, cohort posture. Cloud-RED is deprecated.

**4. Frontend — `docs/index.html`** (single file, glass/neon, Plotly, responsive). Sections:
- **Hero**: net conviction + 5-label verdict + flipped-axis oscillator (LONG/green at bottom, SHORT/red
  at top) with MSTR price overlaid (right log axis).
- **Historical SCRUBBER**: click the oscillator to pin any date → hero + Conviction Drivers recompute
  client-side (`metersForDate()` using `scoring_config`); pinned marker + "Reset to live". Driver rows
  show **dynamic effective weights**.
- **v8.5 Strategy State** chips. **v8.5 Backtest-Signals chart** (`drawSignalChart`) — real trade markers.
- **v8.5 Simulator** (`drawSim`, `simStart` inputs) — start date + capital → equity/P&L + open positions.
- **Conviction Drivers** (signed diverging bars + weights). **Macro/Liquidity** panel. **Calibration
  methodology** panel. **Indicator tiles** (tap → modal w/ chart + explanation).

## Calibration — verified correct (the thing Micah cared most about)
Validated via the scrubber against real turning points:
- Nov-2024 cycle top → **SHORT-TOP (−66.8)** · Nov-2022 bottom → **LONG-CAPITULATION (+73.6)**
- Mar-2024 local top → **SHORT-LOCAL** · mid-cycle (Aug-2023) → **NEUTRAL** · today → **LONG-CAPITULATION**
Audit: `scripts/calibrate_weights.py` → `calibration_config.json` + `calibration_audit_report.md`
(the `.md` wouldn't open for Micah → it's now also rendered in-app in the Calibration panel).

---

## OPEN / INCOMPLETE — what a fresh session should pick up

**Operator-gated (Micah must do; can't be done autonomously):**
1. **Secrets for CI** — add GitHub Actions repo secrets: `FRED_API_KEY` (free, create at
   fredaccount.stlouisfed.org — app description was provided), `BGEO_TOKEN`, `EODHD_API_TOKEN`,
   `BMP_API_KEY`, `TBL_EMAIL`, `TBL_PASSWORD`. The CI workflow (`.github/workflows/build.yml`,
   cron `*/30`) expects them.
2. **Rotate the TBL password** — it was shared in chat; treat current as setup-only.
3. **Deploy decision** — nothing is pushed. To go live: review the diff, push `feat/dashboard-v2`,
   merge to the Pages branch, confirm GitHub Pages serves `docs/`. The 30-min CI then keeps it fresh.

**Verify / likely-needs-attention:**
4. **Data is stale** — `latest.json` is from 2026-06-20 (the build froze it; the task no-ops and there's
   no live refresh until CI runs). Re-run `python3 dashboard.py` to refresh, and confirm every source is
   fresh-or-last-good (no blanks).
5. **TBL live-scale unconfirmed** — `tbl` carries **0 weight** in `MACRO_W` until its real value scale is
   captured in CI (Playwright login). It shows in the macro panel but doesn't move the score yet. Confirm
   the TBL payload/auth in CI, then give it a real band + weight.
6. **Simulator data contract** — `docs/signals.json` was restructured (now an object, ~5 keys) while
   `latest.json`'s embedded `signals` is still the basic 13-item list `[{type,date,price,pnl}]`. **Verify
   the simulator reads the enriched trades** (entry/exit, size, pnl%, position type, fired signals) and
   that open-position mark-to-market + the trade-list modals all populate. This is the piece most worth a
   hands-on check.
7. **mNAV accuracy** — currently strategy.com diluted shares + computed mNAV, cross-checked vs BMP. The
   historical shares gap (pre-2025) was the original blocker; confirm the BMP-sourced mNAV covers
   2020-present cleanly and the cross-check divergence flag (>5%) is sane.

**Nice-to-have / not started:** none critical. The original V2_HANDOFF.md phase list is done.

---

## Gotchas & locked decisions (don't relitigate / don't rediscover)
- **FRED keyless CSV blackholes a custom User-Agent** → use the default UA; keyed JSON API is primary.
- **BGeometrics burst-throttles (429)** despite a 200/hr cap → `onchain.py` enforces ≥2.2s spacing.
- **MRI must be the checkonchain "Index" trace** (matches the v8.5 `<12` gate). Not BGeometrics `mris`.
- **mNAV gap was historical DILUTED SHARES**, not BTC price — strategy.com only has them from ~2025; BMP
  + Yahoo-extended BTC fixed the history so Nov-2024 reads SHORT-TOP.
- **The scrubber recomputes from `scoring_config`** emitted into `latest.json` — keep that in sync if you
  change bands/weights, or the historical recompute drifts from the backend.
- **Triple-CSV / hybrid-data trap** for the v8.5 backtest (`scripts/mstr_research/v8_4_t2a_filter_2026_06_18.py`):
  three copies of `mstr_daily_history.csv`; the script reads `./scripts/`; use the hybrid form (start
  2018-03-19). See the v8.5 spec `~/.openclaw/workspace-investing/memory/reference/mstr-strategy-v8_5.md`.
- **Design decisions (locked):** signed single-score model; 5 labels; macro separated; the abandoned
  trend/supertrend buy-sell signal was REMOVED (don't re-add — `fetchers/supertrend.py` is dormant);
  flipped oscillator axis; click-to-pin scrubber; v8.5 mechanical state = system of record, meters = overlay.

## Key files
- `dashboard.py` (orchestrator), `scoring.py` (signed engine + export_config), `indicator_meta.py`
- `fetchers/`: `bmp.py` (authoritative), `checkonchain.py` (MRI), `fred.py`/`treasury.py`/`nyfed.py` (macro),
  `onchain.py` (cohort fallback), `rsi.py`, `tbl.py`, `feargreed.py`, `mstr_history.py`, `lastgood.py`
- `scripts/calibrate_weights.py` → `calibration_config.json` + `calibration_audit_report.md`
- `docs/index.html` (frontend), `docs/latest.json` (data), `docs/signals.json` (v8.5 trades)
- `.github/workflows/build.yml` (CI), `tests/test_scoring.py`
- Memory: `project_nassim_dashboard_v2.md`. Old mid-build list: `V2_HANDOFF.md` (superseded by this file).

## Strategy context
v8.5 (`~/.openclaw/workspace-investing/memory/reference/mstr-strategy-v8_5.md`): long Q-fire when
checkonchain MRI < 12 (≥30d gap); hedge (PUT/SHORT) when MSTR MA200 5-day slope < 0; t2a PUT also keyed
on MSTR IV percentile. The dashboard surfaces this state and overlays a confidence read on top.

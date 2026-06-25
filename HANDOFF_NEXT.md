# Nassim Dashboard v2 — Session Handoff (as of 2026-06-25)

Read this + the auto-memory `project_nassim_dashboard_v2.md` (full running log) before starting.
This file = **current state + how to operate + the open loops, prioritized.**

## Where things are / how to operate
- **Repo:** `/Users/micahs-mac-mini/.openclaw/workspace-investing/scripts/dashboard/` — branch **`feat/dashboard-v2`**, **NOT pushed / not deployed**. Always `cd` explicitly (background bash resets cwd).
- **Python:** use the venv `.venv/bin/python` (3.9). Build: `.venv/bin/python dashboard.py` → then **`cp outputs/latest.json docs/latest.json`** (the frontend reads docs/).
- **Preview:** Claude Preview MCP server **"nassim-dashboard"** on :8765 (`.claude/launch.json`), or `python -m http.server 8770` in `docs/`. NOTE: the Preview screenshot tool's scroll-sync is flaky with Plotly — verify via DOM `preview_eval` (it's reliable); a fresh `location.reload()` clears the resize-artifact horizontal overflow on mobile.
- **Recalibrate (current model only):** `.venv/bin/python scripts/calibrate_weights.py`. **Validate turning points:** `.venv/bin/python scripts/diagnose.py`. **Tests:** `.venv/bin/python -m pytest tests/` (15 should pass).
- **Always** after editing latest.json logic: confirm browser-safe — `json.loads(..., parse_constant=raise)` must not throw (Python's json writes literal `NaN` which kills the live site; dashboard.py `_clean()` + `allow_nan=False` guard this).

## WHAT WE'RE CURRENTLY ON — the v2 A/B model toggle
There's a **MODEL toggle** in the hero (under the range buttons): **"Current"** vs **"v2 · curves + MSTR weights"**. It recomputes the headline, oscillator, drivers, tiles, scrubber, and popover live; a note shows both nets. **Default = Current** (nothing changes until Micah flips it). Micah is A/B-comparing to decide whether **v2 becomes the default.**

- **Current model** = STEP bands (`scoring._signed`) + AUC-derived **directional** weights (`calibration_config.json` `core_w_top`/`core_w_bot`).
- **v2 model** = CURVE interpolation (`scoring._curve`, JS mirror `_curveJS` — they MUST stay in sync) through the *same* band anchors + hand-set **judgment** weights `scoring.CORE_W_TOP_V2`/`CORE_W_BOT_V2` (each sums 1.0).
- Backend computes BOTH: `dashboard.main` → `meters`/`oscillator` (current) + `meters_v2`/`oscillator_v2`; `scoring.export_config()` carries `core_w_top_v2`/`core_w_bot_v2`. Frontend `MODE` global + `isV2()`/`modeMeters()`/`modeOsc()`/`scoreJS()` drive everything.

### WHY (the methodology shift Micah drove — don't lose this)
Micah **rejected AUC** as the weighting basis ("don't care about it; I care about usability + how well these correlate with reality"). The replacement evidence = **conditional forward MSTR move** (when an indicator hits an extreme, what did MSTR do next), computed in `/tmp/usability.py` (treasury era). Findings that shaped v2:
- **RSI**: elite at bottoms (oversold → +21%, 70% up), *useless* at tops → proves directional weights are needed.
- **mNAV / MSTR-BTC-trend**: *early* risk-gauges (go extreme months before the top, so 3mo-fwd reads positive) — they mark the danger *zone*, the fast on-chain metrics (MRI/SOPR/MVRV) supply the *timing*.
- **MA200 slope**: wrong both directions (+17%/−6%) → it's a regime GATE, not a conviction signal.
- **Only mNAV, MSTR/BTC-trend, MA-slope are MSTR-SPECIFIC**; the rest (MVRV-Z/NUPL/MRI/STH-*/F&G/RSI/funding) are BTC-cycle signals MSTR inherits with leverage. The MSTR-specific trio is what flags an MSTR top that diverges from a soft BTC read.
- **v2 weights (top/bot):** mNAV 0.20/0.13 (heaviest top — MSTR over/under-valuation, 3.4 at both cycle tops), MVRV-Z 0.16/0.13, MRI 0.11/0.12, NUPL 0.10/0.11, STH-SOPR 0.06/0.13, RSI 0.03/0.12, STH-MVRV 0.09/0.08, MSTR-BTC 0.09/0.03, F&G 0.05/0.05, funding 0.05/0.07, TBL 0.04/0.01, slope 0.02/0.02.

## OPEN LOOPS (prioritized)
1. **v2 default decision** — Micah A/B compares; if v2 wins, set `MODE` default to "v2" (or keep the toggle, default v2). The thing to feel for: does conviction lean harder short when mNAV was stretched, and does the curve kill jumpiness without dulling turns?
2. **If v2 wins:** repoint the in-app **Calibration Methodology panel** (`drawCalibration` in index.html) from AUC → the **conditional-forward-move** usability stat; consider retiring/repurposing `calibrate_weights.py`'s AUC machinery (it's now only the "current" model's source).
3. **MA200 slope final fate** — demote to gate-only (pull from the conviction net, keep it as the hedge-gate state already in Strategy State) vs keep token weight. Data says gate. Micah's call.
4. **DCA-out markers (confirmed present, not visualized).** v8.5 HAS the quadratic Rule I scale-OUT (`sp = min(ext²·0.03, 0.30)`) — always ON, NOT gated — in `scripts/mstr_research/v8_4_t2a_filter_2026_06_18.py` (the DCA-out `else`-branch ~line 1437). It's NOT emitted to the trade dump, so it can't be charted. To show it: add a dump line (type e.g. `DCA_OUT`) in that Rule I block, re-run the backtest with the locked Phase-3 env vars + `V8_TRADE_DUMP_PATH`, then `scripts/build_signals.py` (extend `MARKER_MAP`/`drawSignalChart` for the new type). (The *linear scale-IN* buy ladder is a SEPARATE system, OFF via `V8_DISABLE_TRANCHE_LADDER=1`.)
5. **mNAV cycle-top-skill term** — optional: add a term rewarding skill at the curated cycle tops to lift mNAV's top weight further (v2 already does this by judgment). Risks overfitting ~3 dates.
6. **Cleanup:** m2/netliq/hy_oas fetchers still run in `fetch_all` (compute_derived references them) but are unused by scoring — can prune.

## KEY FACTS the next session MUST NOT re-break
- **mNAV** is clipped to **≥2021-01-01** (treasury era — pre-2021 had non-BTC enterprise value, poisoned the calibration). Reads **3.41 at both the 2021 & 2024 cycle tops**, discount (<1) at bottoms, live ~0.71. **Do NOT re-apply a split factor** — the share history is already split-consistent; a ×10 over-corrects to 34.
- **Directional weights**: an indicator's weight when **bearish (score<0)** comes from its TOP weight; when **bullish (score≥0)** from its BOTTOM weight. Both models do this.
- **Headline = the latest aligned oscillator day** (`meters` adopts `compute_oscillator_history`'s `osc_last`, has `as_of`) so the big number = the chart's last point = the scrubber. Don't revert to a separate live snapshot.
- **`_curve` (Py) and `_curveJS` (JS) must stay identical.** Same for `_signed`/`_signedJS`. Tiles/scrubber/popover use `scoreJS` (mode-aware).
- **Macro is retired** (no hy_oas/netliq/m2/TBL-score in conviction); funding + tbl_indicator are CORE. TBL section + buy/sell dots come from `fetchers/tbl.py` (public Supabase `tbl_cycle_history`/`tbl_liquidity_history`; indicator_slope zero-crossings = dots).
- Calibration panel collapses by default; `drawCalibration` guards `aucBar(null)`.

## OPS still pending (Micah's side)
- GitHub Actions secrets: `FRED_API_KEY`, `BGEO_TOKEN`, `EODHD_API_TOKEN`, `BMP_API_KEY` (**no TBL creds needed** — TBL is a public endpoint). FRED key is in local `.env`.
- Review → merge `feat/dashboard-v2` → push → Pages deploy (CI is `*/30` in `.github/workflows/build.yml`).

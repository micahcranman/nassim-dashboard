# Nassim Dashboard — Session Handoff (as of 2026-06-25)

Read this + the auto-memory `project_nassim_dashboard_v2.md` (full running log) before starting.

## 🚀 STATUS: DEPLOYED LIVE
- **Live:** https://micahcranman.github.io/nassim-dashboard/ (GitHub Pages = **legacy**, source `main`/`docs`).
- **Branch state:** `feat/dashboard-v2` merged into **`main`** and **pushed** (deploy commit `819d9f6`). Pages auto-builds on every push to main. Keep developing on `feat/dashboard-v2`, merge to main to ship.
- **Default model is now v2** (`let MODE="v2"` in index.html). The old "Current" model is relabeled **"v1"** in the toggle (internal mode key stays `"current"`).

## How to operate
- **Repo:** `/Users/micahs-mac-mini/.openclaw/workspace-investing/scripts/dashboard/`. Always `cd` explicitly (bash cwd resets between calls).
- **Python:** venv `.venv/bin/python` (3.9). Build: `.venv/bin/python dashboard.py` → then **`cp outputs/latest.json docs/latest.json`** (frontend reads docs/).
- **Preview:** Claude Preview MCP "nassim-dashboard" :8765. Plotly scroll-sync screenshots are flaky → verify via DOM `preview_eval` (reliable).
- **Validate turning points:** `.venv/bin/python scripts/diagnose.py` (prints v1/"current" nets; TARGETS now include the Feb-2021 mNAV top). **Tests:** `.venv/bin/python -m pytest tests/` (**20 pass**).
- **JSON safety:** dashboard.py `_clean()` + `allow_nan=False` guard against NaN literals that would blank the live site. Don't remove.

## What shipped this session (the v2 calibration + UI batch)
- **Non-linear mNAV TOP-amplifier (v2 only):** `scoring._mnav_top_gain` (MNAV_TOP_GAIN v_lo 1.8 / v_hi 3.4 / amp 3.0 / gamma 1.7) swells mNAV's effective weight on the SHORT side as the premium stretches (0.20→~0.80 at 3.4) so cycle tops cross decisively. **Mirrored in JS `mnavTopGainJS` — MUST stay in sync** (params flow via `scoring_config.mnav_top_gain`). Top-side only (score<0); bottoms untouched.
- **slope_5d DROPPED from the conviction entirely** (both models). Removed from CORE_W / CORE_W_TOP_V2 / CORE_W_BOT_V2 / calibration_config.json; `compute_meters` skips zero-weight indicators. slope survives as the v8.5 hedge GATE in strategy_state + an informational tile.
- **Feb-2021 mNAV-top fix:** `compute_oscillator_history` now anchors at **ERA_START 2021-01-01** (was a rolling 5y window that cut off the Feb-2021 blow-off — the real MSTR cycle top). Indicator tile series bumped 6yr→7yr so the scrubber covers the era. v2 nets: **Feb-2021 −90.7, Nov-2024 −76.7** (both SHORT-TOP); Nov-2021 BTC-top is only mild (mNAV ~1.2 there — different event).
- **mNAV is COMMON-EQUITY DILUTED**, computed (strategy.com is bot-walled). Live ~0.66 matches bitcointreasuries diluted. NOT Strategy's headline **EV-mNAV** (~1.0, adds convert debt + preferred − cash). UI labels it + tooltip; `snapshot.mnav_convention`.
- **UI:** Strategy State click-to-pin reconstructs per date (IV% = live-only); signal-chart P&L scales to the simulator capital (`simScale`); tooltips = exact dates + cent prices; Conviction Drivers moved under Strategy State; smoothed conviction line now bold sky-blue (#38bdf8), live line receded.
- **Adversarial-review fixes:** funding (8h) collapsed to one pt/calendar day so the scrubber == the daily backend; slope tile/modal score consistent; +5 v2/amplifier/slope unit tests.

## OPEN LOOPS (prioritized)
1. **Micah ops — GitHub Actions secrets** (FRED_API_KEY, BGEO_TOKEN, EODHD_API_TOKEN, BMP_API_KEY; FRED key is in local `.env`; **no TBL creds needed** — public). Until added, the `*/30` CI rebuild degrades those sources to last-good (today's committed cache) but the live site stays up; mNAV/price/funding/TBL recompute keyless.
2. **EV-mNAV (Micah's call, follow-up):** to match Strategy's published headline (~1.0x) add a historical convert-debt + preferred + cash pipeline and compute EV-mNAV alongside (or instead of) the diluted figure. Cross-check source = bitcointreasuries.net (WebFetch-accessible; shows basic/diluted/EV).
3. **CI cleanup:** `build.yml` has a redundant Actions deploy job (configure-pages/upload-pages-artifact/deploy-pages) while Pages source is **legacy** — the legacy build is what deploys, the Actions job may error harmlessly. Either switch Pages to "GitHub Actions" source or drop the Actions deploy steps.
4. **DCA-out markers (confirmed present, not visualized).** v8.5 HAS the quadratic Rule I scale-OUT (`sp = min(ext²·0.03, 0.30)`) — always ON — in `scripts/mstr_research/v8_4_t2a_filter_2026_06_18.py` (~line 1437). NOT emitted to the trade dump → can't be charted. To show it: add a `DCA_OUT` dump line in that Rule I block, re-run the backtest with the locked Phase-3 env vars + `V8_TRADE_DUMP_PATH`, then `scripts/build_signals.py` (extend `TR_STYLE`/`drawSignalChart`). (The linear scale-IN ladder is a SEPARATE system, OFF via `V8_DISABLE_TRANCHE_LADDER=1`.)
5. **Calibration panel (v2):** repoint the in-app Calibration Methodology panel from AUC → the conditional-forward-move usability stat now that v2 is default; the AUC machinery in `calibrate_weights.py` now only feeds the "v1"/current model.
6. **Cleanup:** m2/netliq/hy_oas fetchers still run in `fetch_all` (compute_derived references them) but are unused by scoring — can prune.

## KEY FACTS the next session MUST NOT re-break
- **mNAV** clipped to **≥2021-01-01** (pre-2021 = EV-distorted). Reads **3.41 at Feb-2021 (2021-02-09) and Nov-2024 (2024-11-20)** cycle tops; ~1.2 at the Nov-2021 BTC top (MSTR premium unwound by then); discount (<1) at bottoms, live ~0.66. Do NOT re-apply a split factor.
- **`_curve`/`_curveJS`, `_signed`/`_signedJS`, `_mnav_top_gain`/`mnavTopGainJS` must stay identical** across Python↔JS. Tiles/scrubber/popover use `scoreJS` (mode-aware).
- **Directional weights:** an indicator's weight when bearish (score<0) comes from its TOP weight; bullish (≥0) from its BOTTOM weight. Both models.
- **Headline = the latest aligned oscillator day** (`meters` adopts `compute_oscillator_history`'s `osc_last`, has `as_of`) so the big number = the chart's last point = the scrubber.
- **Macro is retired** (no hy_oas/netliq/m2/TBL-score in conviction); funding + tbl_indicator are CORE. TBL section + dots from `fetchers/tbl.py` (public Supabase).
- **Emitted series are one-point-per-calendar-day** (`_series_to_points` dedupes) so the JS scrubber matches the daily backend — don't reintroduce intraday points.

# Nassim Dashboard v2 — Remaining Work Handoff

**For:** Nassim / Knox (OpenClaw agents)
**Branch:** `feat/dashboard-v2` (in this repo, remote `nassim-dashboard.git`). Do NOT push to `main` or deploy until Micah approves.
**Status:** Phases 0 (data), 2 (scoring), 4 (frontend) are DONE and tested live. This file covers what's left: empirical weight calibration, v8.5 signal markers, TBL Liquidity, and CI/deploy.

Read `~/.openclaw/workspace-investing/memory/reference/mstr-strategy-v8_5.md` for the strategy and `MEMORY.md` (auto-memory `project_nassim_dashboard_v2`) for full context before starting.

## What already works (don't re-do)
- Data: `fetchers/{fred,treasury,nyfed,onchain,checkonchain,feargreed,mstr_history,yahoo,coingecko,funding,lastgood}.py`. Run `python3 dashboard.py` → writes `outputs/latest.json` + `outputs/history.csv`. Every source has last-good fallback.
- Scoring: `scoring.py` — dual long/short meters + net oscillator. Uses **seed weights**; it auto-loads `calibration_config.json` if that file exists (Phase 1 produces it).
- Frontend: `docs/index.html` (glass/neon). Reads `docs/latest.json`. The price chart ALREADY renders v8.5 markers if `latest.json` contains a `signals` array (Phase 3 must add it) — schema: `[{type, date, price}]` with type in `V8_TIER1B_TRANCHE|MSTR_PUT_ENTRY|MSTR_SHORT_ENTRY|V8_TIER1B_EXIT`.

## Gotchas already discovered (respect these)
- **FRED keyless CSV blackholes a custom User-Agent** (read-timeout). `fred.py` uses the keyed JSON API when `FRED_API_KEY` is set, else keyless CSV with the default UA. Set the `FRED_API_KEY` GitHub secret.
- **BGeometrics burst-throttles** (`429`) despite a 200/hr cap → `onchain.py` enforces a 2.2s gap between calls. Keep that.
- **MRI must come from the checkonchain "Index" trace** (see `checkonchain.py` / `scripts/checkonchain_mri_fetch.py`) so it matches v8.5's `<12` gate. Do NOT use BGeometrics `mri` (different calc).
- **mNAV uses strategy.com `assumed_diluted_shares`** (not yfinance basic). A within-TTL cache is NOT low-confidence — only an error/hardcoded fallback is.
- **Triple-CSV data trap** for the backtest: `mstr_daily_history.csv` exists in 3 places (`./`, `./scripts/`, `./data/`). The backtest reads `./scripts/`. Sync all three after any refresh. Use the HYBRID data form (start 2018-03-19) — a full-history yfinance pull breaks the 2023 BULL_ENTRY. See the v8.5 spec "Data dependencies".

---

## Phase 1 — Empirical weight calibration  (`scripts/calibrate_weights.py`, NEW)

Goal: replace `scoring.py`'s seed weights with weights tuned from each indicator's MEASURED skill at calling tops vs bottoms (separately), with diminishing-returns handling. Output a committed `calibration_config.json` that `scoring.py` already knows how to load.

Reuse: `scripts/mstr_research/confidence_analysis.py` (Wilson CIs, walk-forward) and `lag_analysis_d1.py` (turning-point dates, lead-lag).

Steps:
1. **Assemble** a unified daily DataFrame: BTC + MSTR price (`scripts/btc_daily_history.csv`, `scripts/mstr_daily_history.csv`), MRI (`data/checkonchain_mri.csv`), and the on-chain/sentiment indicators (pull full history from the dashboard fetchers or BGeometrics: mvrv_z, nupl, sth_sopr, sth_mvrv, feargreed; mnav series from `dashboard.compute_derived`). Forward-fill; handle differing start dates.
2. **Label extrema:** local swing highs/lows via `scipy.signal.find_peaks(price, prominence=…, distance=20)` (~150–200 points); curated absolute cycle tops/bottoms (~7) from `lag_analysis_d1.py`. Build forward-return labels ("within K days of a top/bottom", try K=14,30).
3. **Per-indicator skill, top vs bottom SEPARATELY:** `sklearn.metrics.roc_auc_score` of the indicator value vs the near-extreme label (primary), plus lead-time and mean forward-N-day return conditional on the indicator being in its extreme zone. (Install `scikit-learn` — add to requirements.txt.)
4. **Diminishing returns:** correlation-cluster the indicators (cluster at |r|>0.7 — MVRV-Z/NUPL are ~0.92); cap each cluster's TOTAL weight; allocate within-cluster ∝ AUC.
5. **Translate:** AUC → `wlong`/`wshort` per indicator; decile hit-rates → per-indicator `long`/`short` piecewise bands (the conviction curve — high score only in each signal's historically-reliable zone). Emit in the SAME shape `scoring.py` expects: `{"indicators": {"mri": {"wlong":…, "wshort":…, "long":[[12,100],…], "short":[…]}, …}}`.
6. **Validate/regularize:** walk-forward folds (train 2018–22, val 2023–24, OOS 2024–26); ridge shrinkage if val AUC decays >5%. **Honest caveat:** ~7 absolute extrema is tiny → calibrate on the ~150 LOCAL swings, validate on absolutes.
7. **Emit:** `calibration_config.json` (consumed by scoring) + `calibration_audit_report.md` (per-indicator measured skill table — this is the auditable artifact; show it to Micah).

Verify: `python3 scripts/calibrate_weights.py` runs; re-run `python3 dashboard.py` and confirm `latest.json` meters shift toward the calibrated weights; review the audit report (MRI/MVRV should show strong BOTTOM skill, weak TOP skill).

---

## Phase 3 — v8.5 signal markers  (`docs/signals.json` + live recompute in `dashboard.py`)

Two parts:

**A. Historical signals (one-time, regenerate on strategy re-lock):**
```bash
cd scripts/mstr_research
# (ensure hybrid data + triple-CSV synced first — see gotchas)
V8_MRI_THRESH=12 V8_Q_ALLOC_PCT=1.00 V8_TRANCHE_DISABLE=0 V8_DISABLE_TRANCHE_LADDER=1 \
V8_Q_MULTIFIRE=1 V8_Q_MIN_GAP=30 V8_Q_MAX_FIRES=99 V8_Q_GATE_T2A_OPEN=1 \
V8_USE_MRI=1 V8_T2A_LIQUIDATES_T1B=1 V8_T2A_FILTER=mstr_ma200_slope_5d \
V8_TRADE_DUMP_PATH=/tmp/v8_5_trades.jsonl python3 v8_4_t2a_filter_2026_06_18.py
```
Convert `/tmp/v8_5_trades.jsonl` → `docs/signals.json` as `[{type,date,price,pnl}]` (filter to the marker types above). Commit it. The frontend reads `DATA.signals` and plots them.

**B. Live/forward signals (in `dashboard.py`, no full backtest):** recompute the lightweight gates each run from data already pulled and append any NEW triggered events to `signals.json`:
- `slope_5d` (already computed in `compute_derived`),
- `MRI < 12` with ≥30-day gap,
- IV percentile via the `est_iv` formula (see `scripts/mstr_research/hybrid_mstr_btc.py::est_iv` + the 252-day rolling percentile in the v8.4 script).
Wire `signals` into the `latest` dict in `dashboard.py::main()` (load `docs/signals.json`, append new, write back, include in `latest.json`).

---

## TBL Liquidity  (`fetchers/tbl.py`, NEW — fragile, best-effort)

Source: `research.thebitcoinlayer.com/overview?tab=ai&chart=supertrend` (login-gated). In CI use Playwright headless login with secrets `TBL_EMAIL`/`TBL_PASSWORD`:
1. `pip install playwright && playwright install chromium` (add to requirements + CI).
2. Headless login; open DevTools/network to find the supertrend chart's XHR/JSON endpoint; if it's a clean API, replay with `requests` + the session cookie on later runs (more robust than scraping the rendered chart).
3. Return the standard contract `{value, series, stale, source, error}` + `lastgood`. On any failure, return last-good stale — accept fragility.
4. Register in `dashboard.py::fetch_all` as `("tbl", tbl.fetch_tbl_liquidity)`, add a scorer in `scoring.py` (expanding liquidity → long, contracting → short), a tile in `_tile_series` + `indicator_meta`. **Rotate the TBL password after wiring** (it was shared in chat).

---

## Phase 5 — CI + deploy + tests

**`.github/workflows/build.yml`:**
- Change cron `30 12 * * 1` → `*/30 * * * *` (30-min). Keep `workflow_dispatch`.
- Install Playwright: `pip install -r requirements.txt && playwright install --with-deps chromium`.
- Pass secrets as env: `FRED_API_KEY`, `BGEO_TOKEN`, `TBL_EMAIL`, `TBL_PASSWORD`, `EODHD_API_TOKEN`.
- Commit `docs/latest.json`, `docs/signals.json`, `outputs/lastgood/`, `outputs/cache/` (so last-good + caches persist across fresh runners).
- Drop the Matplotlib PNG step (retired) or make it non-blocking.
- Keep the existing Pages deploy job.

**Secrets to add (GitHub → repo Settings → Secrets → Actions):** `FRED_API_KEY` (Micah is creating it), `TBL_EMAIL`, `TBL_PASSWORD`, `EODHD_API_TOKEN`. `BGEO_TOKEN` already exists.

**Tests (`tests/`):** the old tests target the removed `compute_composite`. Replace with tests for `scoring.compute_meters` (dual meters + net + zone), missing-data reweighting, `net_zone` thresholds, and calibration-config loading. Run `pytest tests/`.

**`requirements.txt`:** add `scipy`, `scikit-learn`, `playwright`.

## Final verification (end-to-end)
1. `python3 dashboard.py` → no blanks in `latest.json` (all sources fresh or last-good).
2. `python3 scripts/calibrate_weights.py` → review `calibration_audit_report.md`.
3. Historical oscillator long-zone entries should line up with backtest Q-fire dates; short-zone with PUT/SHORT dates.
4. `pytest tests/` green.
5. Serve `docs/` (`python3 -m http.server 8770`) → check oscillator+zones, gate badges, signal markers, tiles, live refresh, mobile.
6. `workflow_dispatch` CI run → commits artifacts, Pages updates, data-age stays fresh on the 30-min schedule.

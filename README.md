# Nassim Confidence Dashboard

Diagnostic confidence calibrator for the v7.8d MSTR strategy. Produces a 0–100 risk score (100 = max bullish 6mo+ horizon; 0 = max risk) from a weighted composite of cycle-phase, macro liquidity, risk regime, MSTR-specific, and tactical indicators.

**This is not a signal generator.** It is a diagnostic to inform allocation-level sizing decisions when the underlying strategy signal fires. Do not use it to override the strategy's mechanical entry/exit logic.

## Live site

Auto-deployed via GitHub Actions on Mondays 12:30 UTC (7:30 AM CT) and on `workflow_dispatch`.

→ <https://micahcranman.github.io/nassim-dashboard/>

## Scoring

| Category | Weight | Indicators |
|---|---|---|
| Cycle Phase (BTC on-chain) | 35% | MVRV-Z (15%), NUPL (10%), LTH supply trend (5%), SOPR 7d MA (5%) |
| Macro Liquidity | 30% | US M2 12w trend (15%), Net Liquidity 4w trend (10%), DXY 50d inverse (5%) |
| Risk Regime | 15% | HY OAS (10%), 10Y real yield inverse (5%) |
| MSTR-Specific | 15% | mNAV (10%), MSTR/BTC 50d trend (5%) |
| Tactical | 5% | Funding rate (3%), SSR (2%) |

Indicators that fail to fetch are excluded; remaining weights are reproportional. The composite is `Σ (sub_score_i × renormalized_weight_i)`.

## Data sources

| Indicator | Source | Notes |
|---|---|---|
| US M2, Net Liquidity, 10Y real yield, HY OAS | FRED (`fredgraph.csv`) | No auth |
| DXY, MSTR price, MSTR shares, MSTR IV | Yahoo Finance via `yfinance` | |
| BTC price, BTC mcap, stablecoin caps | CoinGecko `/coins/*/market_chart` | Free tier, rate-limited |
| MVRV-Z, NUPL, SOPR | bitcoin-data.com `/api/v1/*` | Free tier 10 req/hr; 6h disk cache |
| LTH supply | TBD (CoinMetrics community tier insufficient) | v2 |
| BTC perp funding | OKX `/funding-rate-history`, Bybit fallback | |
| MSTR BTC holdings | saylortracker.com scrape, hardcoded fallback | |
| mNAV, SSR, MSTR/BTC ratio | Computed | |

## Local dev

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest tests/        # scoring math tests; should be 69/69
python dashboard.py  # produces outputs/{latest.png, latest.json, history.csv}
```

## Caveats

- Score is backward-looking. No indicator predicts the future.
- Weights are hand-calibrated, not regression-optimized. N=3–4 BTC cycles for calibration.
- ETF era is shifting MVRV/NUPL absolute thresholds. Periodic recalibration needed.
- Does NOT capture geopolitical / black-swan risk. That's the qualitative override layer.
- Score changes <5pts are noise. >15pts week-over-week is signal.

# Quarterly refresh routine — `docs/ai_capex.json` (NLAFA AI-absorption leg)

The "Net Liquidity to Assets" panel reads `docs/ai_capex.json` for the AI-buildout leg: the
**circularity-adjusted net external cash drain** to AI/data-center capex. It is modeled (shown as
a range) and changes on the quarterly earnings clock, so it is refreshed by this routine, NOT by
the 30-min dashboard cron.

## When
Run **quarterly at ~T+35 days** after each calendar quarter-end (covers the late-Jan/Apr/Jul/Oct
earnings cluster), then re-run weekly until all target 10-Qs are filed. Off-cycle pulls mid-Jun
and mid-Dec for Oracle (FY ends May 31).

## How to schedule (Micah's choice)
- **OpenClaw / Nassim cron (recommended):** add a quarterly job that runs this routine and
  `git -C scripts/dashboard commit/push docs/ai_capex.json`. Leverages existing local infra with
  repo access.
- **GitHub-native:** a scheduled GitHub Action (quarterly cron) that calls Claude via the
  Anthropic API to run this routine and commit. Self-contained in the repo; needs an
  `ANTHROPIC_API_KEY` secret.

## The 5-step methodology (what the agent does each run)
1. **Gross from FLOWS, not commitments.** Sum capex from cash-flow statements (10-Q/10-K) via SEC
   EDGAR XBRL (keyless, `data.sec.gov/api/xbrl/companyfacts/CIK{10-digit}.json`, User-Agent header)
   for MSFT(0000789019), GOOGL(0001652044), AMZN(0001018724), META(0001326801), ORCL(0001341439),
   CoreWeave(0001769628), Nebius(0001513845). **Auto-discover the capex tag per CIK** (most use
   `PaymentsToAcquirePropertyPlantAndEquipment`; **AMZN uses `PaymentsToAcquireProductiveAssets`**).
   Normalize off-calendar fiscal years (Oracle, MSFT) using reported fiscal-quarter durations.
   EXCLUDE all multi-year commitment headlines ($1.4T OpenAI, $300B Stargate) — those are backlog,
   not annual cash (conflating them is the ~10x error in popular coverage). Cross-check the
   aggregate against Epoch AI's CC-BY CSV (epoch.ai/data-insights/hyperscaler-capex-vs-cash-flow).
2. **Add off-balance-sheet / debt-financed real assets** (fix undercount): neocloud GPU debt +
   finance leases (`ProceedsFromIssuanceOfLongTermDebt`, finance-lease ROU additions); hand-add
   known SPVs (Meta–Blue Owl Hyperion ~$27B) and private-lab self-build, flagged as estimates.
3. **Deduplicate circular pass-through + strip vendor financing** (fix overcount): END-NODE rule —
   count each dollar once, where the physical PP&E is booked; do NOT add compute-purchase
   commitments on top of the capex they fund. Subtract vendor-financing round-trips (Nvidia/AMD
   equity → customer → vendor GPU revenue). Drop take-or-pay backstops (contingent). Maintain the
   `deal_ledger` in ai_capex.json with deployed estimates, not headlines.
4. **Split funding source:** capex ÷ operating cash flow per company → internal (recycled) vs
   NEW EXTERNAL (bond issuance + off-B/S SPV + new equity + externally-funded lab burn). Anchor
   the debt share with BIS Bulletin 120 (2025: ~$120B bonds + ~$120B off-B/S = ~$240B new debt).
5. **Net external drain** = (gross + off-B/S) − circularity, then isolate the new-external share.
   **That is the panel leg** (internally-funded capex doesn't compete for the marginal liquidity
   that bids financial assets). Always publish a RANGE + confidence; never a bare point.

## Output: overwrite `docs/ai_capex.json` with
`as_of`, `quarter`, `gross_annual_capex_usd_b{central,low,high}`, `circular_double_count_usd_b{}`,
`debt_funded_share_pct{}`, `net_external_cash_drain_usd_b{central,low,high}` (the panel leg),
`all_resource_absorption_usd_b{}`, `by_company_capex_quarter_usd_b{}`, `deal_ledger[]`,
`debt_anchor`, `sources[]`, `flags[]`, `confidence`.

## Guardrails
Store the discovered XBRL tag per CIK (detect drift); never add commitment headlines to the flows
sum; flag when any company's capex exceeds internal cash (the crossover signal, ~Q3-2026); the
private-lab increment is the widest error band — keep it flagged secondary.

_Seeded 2026-06-25 from the ai-capex-groundtruth research pass. See `project_nassim_dashboard_v2`._

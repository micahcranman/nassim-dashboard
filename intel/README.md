# Narrative-Intelligence Reports — pipeline

A twice-weekly read of the trusted MSTR/BTC analysts, set against the Strategy² v8.5 system.
It does **not** generate signals — it tells you whether the voices we trust raise or lower
**conviction** in what the dashboard already says, weighting each voice only on the side it has
earned (defensive top-warnings vs buy-the-dip calls). Strictly point-in-time: a note knows
nothing published after its coverage window.

Live: **https://micahcranman.github.io/nassim-dashboard/intel/**

## Cadence

- **Monday** report covers the prior **Thursday → Sunday**.
- **Thursday** report covers that week's **Monday → Wednesday**.

## How it works (the contract — do not break)

Each report is written by a fresh, context-free model that sees **only** three things:

1. the system's state in **plain English** (no codenames — never "MRI", "Q-fire", "slope_5d"),
   composed deterministically from `docs/latest.json`;
2. the **sanitized trust profiles** (`profiles.md`) — what each voice is good/bad at, with **no
   past calls or outcomes**;
3. that window's **actual posts**, read straight from the corpus folders.

It never sees the scorecards (they contain outcomes → lookahead). A second, independent agent
adversarially checks every draft for lookahead, fabrication, codename leakage, and mis-weighting,
then writes the corrected final. This mirrors the validated backtest in
`~/.openclaw/workspace-investing/memory/notes/2026-06-25-weekly-reports-backtest.md`.

The one locked nuance: at a **capitulation extreme**, widespread expert fear/silence is read as
*confirmation* of the contrarian buy, not conflict. The only voice whose bottom calls add buy-side
conviction is **The Bitcoin Layer** (and only while the trend hasn't fully broken).

## Files

| file | role |
|---|---|
| `intel_lib.py` | periods (cadence), corpus ingest, point-in-time signal snapshot, plain-language description |
| `profiles.md` | sanitized trust profiles (the only character input the writer gets) |
| `intel_prompt.py` | write + verify prompts and the structured-output schema (single source of truth) |
| `emit_prompts.py` | renders prompts to `build/` so headless + workflow read identical text |
| `generate.py` | headless generation via `claude -p` (write → adversarial verify) |
| `render.py` | HTML report pages + index + Plotly charts + email bodies → `docs/intel/` |
| `send_email.py` | deliver a report via `gog gmail send` (idempotent; tracks `build/sent.json`) |
| `run_intel.py` | **end-to-end runner** — the single entry point for cron / OpenClaw |

Outputs deploy to `docs/intel/` (GitHub Pages serves `main:/docs` directly — a push goes live in
~1 min). `docs/intel/data/<slug>.json` holds the merged structured data for future in-dashboard
integration.

## Run it

```bash
cd ~/.openclaw/workspace-investing/scripts/dashboard/intel

# the current period, generate + render + deploy + email yourself:
python3 run_intel.py --deploy --email

# backfill the last 5 periods and deploy:
python3 run_intel.py --backfill 5 --deploy

# just re-render the site from existing reports (no model calls):
python3 run_intel.py --render-only --deploy
```

Dependencies (all already on the Mac mini): `claude` CLI (auth'd), `gog` (Gmail), `git`, Python 3.
The corpus lives at `~/newsletter-intelligence/` and is refreshed by Nole's scraper —
**a report is only as fresh as the corpus**, so the scraper must run before the report.
`docs/latest.json` (the signal source) is refreshed every 30 min by the dashboard's GitHub Action;
a deploy-mode run should `git pull` first to pick up the freshest signal (the runner leaves that to
the scheduler — see below).

## Scheduling (choose one — NOT auto-enabled)

This emails you and pushes to a public repo on a schedule, so it's left for you to switch on.

**Option A — launchd (Mac-native), the simple path.** A ready plist is at
`intel/com.strategy2.intel.plist`. It runs Mon & Thu at 07:15 CT. Enable:

```bash
cp ~/.openclaw/workspace-investing/scripts/dashboard/intel/com.strategy2.intel.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.strategy2.intel.plist     # kill switch: launchctl unload
```

Edit the plist first to add a `git pull` step (or run the dashboard build) if you want the freshest
signal, and confirm the scraper runs earlier that morning.

**Option B — OpenClaw (Nassim), the smarter path (recommended).** Hand the runner to Nassim as a
cron so it lives next to the corpus scraper and the dashboard build it depends on, with escalation
on failure. Nassim's cron would, Mon & Thu after the scraper completes:
`cd …/intel && git pull --autostash && python3 run_intel.py --deploy --email`.
This keeps the corpus → signal → report → deploy chain ordered and observable in one agent.

## Known limitations / next

- **Profiles are full-sample** (mild forward-looking bias on early dates) — the rigorous fix is
  as-of-date profiles. Fine for live forward reports; matters only for backtests. See the project
  memory.
- **Willy Woo** corpus ends 2021 and **Pollinate** is unscraped → effectively always silent now.
- **Lyn Alden** posts ~biweekly, so she's silent in most single-window reports — expected.
- Eventually fold this into the main dashboard as a tab (the `data/<slug>.json` files are ready for
  that); for now it's a standalone sub-folder sharing the design.

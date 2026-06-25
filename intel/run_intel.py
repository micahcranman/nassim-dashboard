#!/usr/bin/env python3
"""
run_intel.py — end-to-end narrative-intel pipeline. Single entry point for cron / OpenClaw.

Pipeline:  period(s) -> ingest packet -> emit prompts -> generate (headless claude -p,
           write + adversarial verify) -> render HTML + email bodies -> [deploy] -> [email]

Typical recurring invocation (run on Mon & Thu — see README / launchd plist):
    python3 run_intel.py --deploy --email

Backfill the last N periods (what produced the initial 5):
    python3 run_intel.py --backfill 5 --render-only        # if finals already exist
    python3 run_intel.py --backfill 5 --deploy             # regenerate + deploy

Flags:
  --anchor YYYY-MM-DD   anchor date (default: today)
  --backfill N          process the N most-recent periods (default: 1 = current period)
  --date YYYY-MM-DD     process exactly one report date (overrides --backfill)
  --no-verify           skip the adversarial verify pass (faster, lower quality)
  --render-only         skip generation; just (re)render + index from existing finals
  --deploy              git add docs/intel + intel/ source, commit, push (-> GitHub Pages)
  --email               email each freshly-generated report (idempotent via sent.json)
  --email-all           email every processed report even if generated earlier
  --to ADDR             override recipient
"""
import os
import sys
import json
import argparse
import datetime
import subprocess
from pathlib import Path

import intel_lib as L
from emit_prompts import emit
import render as R


def _periods(args):
    if args.date:
        d = datetime.date.fromisoformat(args.date)
        # snap to the cadence: if it's a Mon/Thu use it, else find the matching kind window
        return L.report_periods(d, 1)
    anchor = datetime.date.fromisoformat(args.anchor) if args.anchor else datetime.date.today()
    return L.report_periods(anchor, args.backfill)


def _git(*a):
    return subprocess.run(["git", "-C", str(L.REPO), *a], capture_output=True, text=True)


def deploy():
    """Commit ONLY the intel files (never the prior session's unrelated working changes)."""
    paths = ["docs/intel", "intel"]
    _git("add", "--", *paths)
    st = _git("status", "--porcelain", "--", *paths).stdout.strip()
    if not st:
        print("  [deploy] nothing to commit"); return
    msg = f"intel: narrative-intel reports {datetime.datetime.now():%Y-%m-%d %H:%M}"
    c = _git("commit", "-m", msg, "--", *paths)
    if c.returncode != 0:
        print("  [deploy] commit failed:", c.stderr[:300]); return
    p = _git("push")
    if p.returncode != 0:
        print("  [deploy] push failed:", p.stderr[:300]); return
    print("  [deploy] pushed -> GitHub Pages will serve in ~1 min")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchor"); ap.add_argument("--date")
    ap.add_argument("--backfill", type=int, default=1)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--deploy", action="store_true")
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--email-all", action="store_true")
    ap.add_argument("--to")
    args = ap.parse_args()
    os.chdir(Path(__file__).resolve().parent)
    L.BUILD_DIR.mkdir(exist_ok=True)

    periods = _periods(args)
    latest = json.loads(L.LATEST_JSON.read_text())
    print(f"Processing {len(periods)} period(s): {', '.join(p['slug'] for p in periods)}")

    fresh = []
    if not args.render_only:
        from generate import generate_report
        for p in periods:
            pkt = L.build_packet(p, latest)
            (L.BUILD_DIR / f"packet-{p['slug']}.json").write_text(json.dumps(pkt, indent=2))
            emit(p["slug"])
            print(f"  generating {p['slug']} ({p['n_posts']} posts, silent: {', '.join(p['silent']) or 'none'}) …")
            rep = generate_report(p["slug"], verify=not args.no_verify)
            print(f"    -> {rep.get('conviction_delta')} | bear={rep['bear_overlay']['verdict']} | qfire={rep['qfire']['verdict']}")
            fresh.append(p["slug"])

    # render everything that has a final
    R.main()

    if args.email or args.email_all:
        from send_email import send_report
        to = args.to or os.environ.get("INTEL_EMAIL_TO", "micahcranman@gmail.com")
        targets = [p["slug"] for p in periods] if args.email_all else fresh
        for slug in targets:
            try:
                send_report(slug, to=to, force=args.email_all)
            except Exception as e:
                print(f"  [email] {slug} failed: {e}")

    if args.deploy:
        deploy()
    print("Done.")


if __name__ == "__main__":
    main()

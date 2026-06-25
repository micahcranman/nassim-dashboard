"""
send_email.py — deliver a rendered report to an inbox via the `gog gmail` CLI.

HTML is passed as a subprocess argument (list form, no shell) so there is no escaping risk.
Tracks sent slugs in build/sent.json so a re-run / cron does not double-send.
"""
import os
import json
import subprocess
import datetime
from pathlib import Path

from intel_lib import BUILD_DIR, DOCS_INTEL

DEFAULT_TO = os.environ.get("INTEL_EMAIL_TO", "micahcranman@gmail.com")
SENT_LOG = BUILD_DIR / "sent.json"


def _sent():
    return json.loads(SENT_LOG.read_text()) if SENT_LOG.exists() else {}


def _mark(slug):
    s = _sent(); s[slug] = datetime.datetime.now().isoformat(timespec="seconds")
    SENT_LOG.write_text(json.dumps(s, indent=2))


def send_report(slug: str, to: str = DEFAULT_TO, force: bool = False) -> bool:
    if not force and slug in _sent():
        print(f"  [skip] {slug} already emailed ({_sent()[slug]})")
        return False
    email_html = DOCS_INTEL / "email" / f"{slug}.html"
    if not email_html.exists():
        raise FileNotFoundError(f"missing email body {email_html} — run render.py first")
    data = json.loads((DOCS_INTEL / "data" / f"{slug}.json").read_text())
    rep, period = data["report"], data["period"]
    delta = {"MORE": "↑ more", "SAME": "→ same", "LESS": "↓ less"}.get(rep.get("conviction_delta"), "")
    subject = (f"Strategy² Intel · {period['title'].replace('Market Note — ','')} "
               f"· {delta} conviction")
    plain = (f"{rep.get('system_state','')}\n\n"
             f"Hedge/top side: {rep['bear_overlay']['verdict']}. "
             f"Buy/bottom side: {rep['qfire']['verdict']}.\n\n"
             f"{rep.get('bottom_line','')}\n\n"
             f"Full report: https://micahcranman.github.io/nassim-dashboard/intel/{slug}.html")
    cmd = ["gog", "gmail", "send", "--to", to, "--subject", subject,
           "--body", plain, "--body-html", email_html.read_text(), "--no-input"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"gog gmail send failed: {proc.stderr[:400] or proc.stdout[:400]}")
    _mark(slug)
    print(f"  [sent] {slug} -> {to}")
    return True


if __name__ == "__main__":
    import sys
    os.chdir(Path(__file__).resolve().parent)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    to = DEFAULT_TO
    for a in sys.argv:
        if a.startswith("--to="):
            to = a.split("=", 1)[1]
    for slug in args:
        send_report(slug, to=to, force=force)

"""
generate.py — headless report generation via the Claude CLI (`claude -p`).

This is the unattended path used by run_intel.py (cron / OpenClaw). It mirrors the
two-stage backfill Workflow: write -> adversarial verify. Same prompts (intel_prompt.py),
so output is identical whether produced interactively or headless.

Requires: `claude` on PATH (Claude Code CLI). Model defaults to Opus.
"""
import os
import re
import json
import subprocess
from pathlib import Path

from intel_lib import BUILD_DIR
from intel_prompt import build_write_prompt, build_verify_prompt

MODEL = os.environ.get("INTEL_MODEL", "claude-opus-4-8")

JSON_ONLY = ("\n\n# OUTPUT FORMAT (STRICT)\n"
             "Return ONLY a single minified-or-pretty JSON object — no prose, no markdown "
             "fences, nothing before or after it. Keys exactly: system_state, regime, "
             "focus_side, analysts (array of {name, published, side, lean, stance_change, "
             "conviction, summary, quote, url}), bear_overlay {verdict, strength, note}, "
             "qfire {verdict, strength, note}, conviction_delta, bottom_line, narrative_md.")


def _claude(prompt: str, model: str = MODEL, timeout: int = 600) -> str:
    """Run `claude -p` headless; return the assistant's final text."""
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", model],
        input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed ({proc.returncode}): {proc.stderr[:500]}")
    try:
        wrap = json.loads(proc.stdout)
        return wrap.get("result", proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout


def _extract_json(text: str) -> dict:
    """Pull the first balanced top-level JSON object out of a model response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text); text = re.sub(r"\n?```$", "", text)
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in model output")
    depth, instr, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if instr:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': instr = False
        else:
            if c == '"': instr = True
            elif c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON in model output")


def generate_report(slug: str, verify: bool = True, model: str = MODEL) -> dict:
    pkt = json.loads((BUILD_DIR / f"packet-{slug}.json").read_text())
    # write
    draft = _extract_json(_claude(build_write_prompt(pkt) + JSON_ONLY, model))
    final = draft
    # adversarial verify + correct
    if verify:
        try:
            final = _extract_json(_claude(build_verify_prompt(pkt, draft) + JSON_ONLY, model))
        except Exception as e:
            print(f"  [warn] verify failed for {slug}, keeping draft: {e}")
            final = draft
    (BUILD_DIR / f"final-{slug}.json").write_text(json.dumps(final, indent=2))
    return final


if __name__ == "__main__":
    import sys
    os.chdir(Path(__file__).resolve().parent)
    for slug in sys.argv[1:]:
        print("generating", slug, "…")
        r = generate_report(slug)
        print(f"  {slug}: {r.get('conviction_delta')} | bear={r['bear_overlay']['verdict']} "
              f"| qfire={r['qfire']['verdict']}")

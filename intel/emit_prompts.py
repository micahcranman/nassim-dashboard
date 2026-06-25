"""
emit_prompts.py — render the write-prompt (and verify source block) to text files in build/,
so both the backfill Workflow agents and the headless `claude -p` runner read identical prompts.

Usage: python3 intel/emit_prompts.py        # all packets currently in build/
"""
import json
import glob
from pathlib import Path

from intel_prompt import build_write_prompt, _posts_block
from intel_lib import BUILD_DIR


def emit(slug):
    pkt = json.loads((BUILD_DIR / f"packet-{slug}.json").read_text())
    (BUILD_DIR / f"prompt-write-{slug}.txt").write_text(build_write_prompt(pkt))
    p = pkt["period"]
    verify_src = f"""# Coverage window: {p['cover_start']} → {p['cover_end']} (you know NOTHING after this)

# System state the writer was given (these facts are ALLOWED in the note):
{pkt['signal_plain']['paragraph']}
Posture: {pkt['signal_plain']['posture']}

# Source posts the writer had (the ONLY narrative material that may be cited):
{_posts_block(pkt['corpus'])}
"""
    (BUILD_DIR / f"verify-src-{slug}.txt").write_text(verify_src)
    return slug


if __name__ == "__main__":
    import os
    os.chdir(Path(__file__).resolve().parent)
    slugs = sorted(Path(p).stem.replace("packet-", "")
                   for p in glob.glob(str(BUILD_DIR / "packet-*.json")))
    for s in slugs:
        emit(s)
        print("emitted prompts for", s)

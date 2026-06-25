"""
intel_prompt.py — assembles the report-writer prompt + the structured-output schema.

Identical prompt is used by:
  * the backfill Workflow (agents in this Claude Code session), and
  * run_intel.py -> `claude -p` (headless, for the recurring live pipeline).

The writer sees ONLY: plain-language signal + sanitized profiles + that week's posts.
"""

import json


# The structured object every report agent must return (drives the dashboard visuals).
REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["system_state", "regime", "focus_side", "analysts",
                 "bear_overlay", "qfire", "conviction_delta", "bottom_line", "narrative_md"],
    "properties": {
        "system_state": {"type": "string", "description": "One plain-language line: where the system stands this period (no codenames)."},
        "regime": {"type": "string", "enum": ["BULL", "BEAR", "NEUTRAL"]},
        "focus_side": {"type": "string", "enum": ["TOP", "BOTTOM", "BOTH"],
                       "description": "Which side the voices most need to confirm this period."},
        "analysts": {
            "type": "array",
            "description": "One entry per scored voice (all six, even if silent).",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "published", "side", "lean", "stance_change", "conviction", "summary", "quote", "url"],
                "properties": {
                    "name": {"type": "string"},
                    "published": {"type": "boolean"},
                    "side": {"type": "string", "enum": ["TOP", "BOTTOM", "NEUTRAL", "NA"],
                             "description": "TOP = a defensive/top warning; BOTTOM = a buy-weakness call; NEUTRAL/NA otherwise."},
                    "lean": {"type": "string", "enum": ["confirms", "contradicts", "neutral", "silent"],
                             "description": "Does this voice confirm or contradict the system's posture this period?"},
                    "stance_change": {"type": "boolean", "description": "True only if a genuine fresh change of view (not a restatement)."},
                    "conviction": {"type": "integer", "minimum": 0, "maximum": 5},
                    "summary": {"type": "string", "description": "One sentence on what they actually said this period."},
                    "quote": {"type": "string", "description": "A short verbatim quote from their in-window post, or '' if silent."},
                    "url": {"type": "string"}
                }
            }
        },
        "bear_overlay": {
            "type": "object", "additionalProperties": False,
            "required": ["verdict", "strength", "note"],
            "properties": {
                "verdict": {"type": "string", "enum": ["CORROBORATE", "CONFLICT", "SILENT"]},
                "strength": {"type": "integer", "minimum": 0, "maximum": 3},
                "note": {"type": "string"}
            }
        },
        "qfire": {
            "type": "object", "additionalProperties": False,
            "required": ["verdict", "strength", "note"],
            "properties": {
                "verdict": {"type": "string", "enum": ["CORROBORATE", "CONFLICT", "SILENT"]},
                "strength": {"type": "integer", "minimum": 0, "maximum": 3},
                "note": {"type": "string"}
            }
        },
        "conviction_delta": {"type": "string", "enum": ["MORE", "SAME", "LESS"],
                             "description": "Does the narrative this period add MORE conviction in the system's posture, leave it the SAME, or argue for LESS?"},
        "bottom_line": {"type": "string", "description": "1-2 sentence takeaway."},
        "narrative_md": {"type": "string", "description": "The full human-readable note in markdown (see length/voice guidance)."}
    }
}


def _posts_block(corpus):
    lines = []
    for name, posts in corpus.items():
        if not posts:
            lines.append(f"\n### {name}\n(no posts in window — silent)")
            continue
        lines.append(f"\n### {name} — {len(posts)} post(s) in window")
        for p in posts:
            paid = " [PAYWALLED TEASER — may be partial]" if p["is_paid"] else ""
            lines.append(f"\n**{p['date']} · {p['title']}**{paid}\n{p['url']}\n\n{p['text']}")
    return "\n".join(lines)


HOW_TO_WEIGH = """\
## How to read the trusted voices against the system

You are NOT generating a trade signal. The dashboard already produced the system posture
above. Your job is to say whether the analysts we trust **raise or lower conviction** in
that posture, and how much to trust them on this specific question.

Two sides, and every voice is good at only one of them:
- A **TOP call** is a warning of downside / a reason to hedge. It speaks to the *defensive*
  side of the system (the open hedge / bearish trend).
- A **BOTTOM call** is a reason to buy weakness. It speaks to the *contrarian-buy* side
  (the capitulation / deep-value setup).

Rules for weighting (apply the sanitized profiles — they tell you who is good at which side):
1. **Genuine change beats restatement.** A voice newly *changing* its stance carries real
   information. A voice merely restating a long-standing view carries almost none — discount it.
2. **Weight each voice only on its good side.** Lean on a top-specialist's defensive warnings;
   lean on the one bottom-caller's (The Bitcoin Layer's) liquidity-pivot buy calls *while the
   broader trend hasn't fully broken*. Fade calls on a voice's weak side.
3. **The contrarian-at-an-extreme rule (important when the system is at capitulation or at a
   confirmed top):** when the quant gauge is already pinned at an extreme, broad agreement of
   the *crowd against* the setup is itself weak CONFIRMATION, not conflict.
   - At a **capitulation extreme** (deep-value buy zone): if the trusted voices are mostly
     fearful / bearish / silent, that fear is the bottom — the crowd can't buy the low. Read
     widespread expert fear at a capitulation as *confirming* the buy setup, not conflicting
     with it. Do NOT wait for human bottom-corroboration; its absence is normal and expected.
     The exception that genuinely *adds* buy-side conviction is The Bitcoin Layer making a real
     liquidity-pivot bottom call — and only while the trend hasn't decisively broken.
   - At a **confirmed top**: a perma-bull restating "still early / not overheated" is the crowd
     failing to call the top — weak confirmation of the defensive posture.
4. **Silence is information sometimes, noise other times.** A structural bull going quiet tells
   you nothing. A voice you trust on this side going quiet at a key moment is a genuine gap —
   note it honestly.
5. **Macro voices give direction, not timing** (often months early/late). On-chain voices give
   the earlier, sharper turn read. Don't treat a macro lean as a same-week trigger.
"""

VOICE = """\
## Output — voice and shape of `narrative_md`

Write a punchy, plain-English market note a sharp trader would actually read. Structure:
  - **Where the system stands** — one short paragraph restating the posture above in plain
    words (NO internal codenames — never write "Q-fire", "MRI", "slope_5d", "t1b", "t2a";
    say "the on-chain capitulation gauge", "the hedge slope", etc.).
  - **What the trusted voices actually said** — one tight bullet per voice that published,
    naming what they said, whether it's a genuine change or a restatement, and how much weight
    it earns *given their profile*. Be specific; quote a few words where it lands.
  - **Do the voices confirm the system?** — a short synthesis: who lines up, who doesn't, and
    why, weighted by side and trust.
  - **Bottom line** — does this period give MORE / the SAME / LESS conviction in the system's
    posture, and what to watch next (a level, a voice, an event).
  - End with a one-line **coverage note** listing who was silent.

Rules: 300–600 words. Have opinions. Vary sentence length. No hedging stacks. Do not invent
quotes or facts — everything must trace to the posts provided. Never reference anything that
happened after the coverage window — you do not know the future.
"""


def build_write_prompt(packet):
    p = packet["period"]
    sig = packet["signal_plain"]
    return f"""\
You are writing one **point-in-time market-intelligence note** for a MicroStrategy / Bitcoin
trading system. Today is the report date below; you know NOTHING that happened after the
coverage window. This is strictly point-in-time.

# Report
- Report date: {p['report_date']} ({p['kind']})
- Coverage window: {p['cover_start']} → {p['cover_end']}

# Where the system stands (plain language — this is the dashboard's read, treat as given)
{sig['paragraph']}

**System posture:** {sig['posture']}
**The side the voices most need to confirm this period:** {sig['focus_side']}

# Sanitized trust profiles (how good each voice is, by call type — no past outcomes)
{packet['profiles']}

{HOW_TO_WEIGH}

# The trusted voices' ACTUAL posts this window (your ONLY narrative input)
{_posts_block(packet['corpus'])}

{VOICE}

# Also return the structured fields (they drive the dashboard visuals)
Fill every field of the schema. For `analysts`, include an entry for ALL SIX voices
(James Check, Lyn Alden, Michael Howell, The Bitcoin Layer, Macro Ops, Willy Woo) — mark the
silent ones published=false, lean="silent". `bear_overlay` summarizes the TOP-side confluence;
`qfire` summarizes the BOTTOM-side confluence (remember the contrarian-at-extreme rule when
the system is at capitulation). `conviction_delta` is MORE/SAME/LESS conviction in the posture.
Return ONLY the structured object."""


def build_verify_prompt(packet, draft_json):
    p = packet["period"]
    return f"""\
You are an adversarial QA reviewer for a point-in-time market note. Below is a DRAFT report
object and the EXACT source material the writer was given. Check the draft hard for four faults:

1. **Lookahead / hindsight** — does the narrative or any field reference ANY event, price, or
   outcome that happened after the coverage window {p['cover_start']} → {p['cover_end']}? It must not.
2. **Fabrication** — is every quote and factual claim traceable to the provided posts? Flag any
   quote not found in the source, any analyst attributed something they didn't say, any invented
   number. (The signal/system numbers in 'Where the system stands' are given facts — those are fine.)
3. **Codename leakage** — does `narrative_md` contain internal jargon that must NOT appear
   ("Q-fire", "MRI", "slope_5d", "t1b", "t2a", "t2b", "composite", "v8.5")? Plain-English
   equivalents are required.
4. **Mis-weighting** — does it lean on a voice's WEAK side, treat a restatement as a fresh
   signal, or (critically) read broad expert fear at a capitulation as CONFLICTING with the buy
   setup rather than confirming it? Flag profile-inconsistent weighting.

Then return a CORRECTED version of the SAME object (same schema, all fields) with every fault
fixed — keep everything that was already correct, only fix faults. If the draft was clean,
return it essentially unchanged. In `narrative_md`, preserve the writer's voice; only repair faults.

Add nothing that isn't supported by the sources. Do not soften a correct, well-grounded read.

# Coverage window: {p['cover_start']} → {p['cover_end']} (know nothing after this)

# Source posts the writer had:
{_posts_block(packet['corpus'])}

# System state the writer was given (these facts are allowed):
{packet['signal_plain']['paragraph']}
Posture: {packet['signal_plain']['posture']}

# DRAFT object to review and correct:
{json.dumps(draft_json, indent=2)}

Return ONLY the corrected structured object."""

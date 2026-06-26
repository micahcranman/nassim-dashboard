"""
intel_prompt.py — assembles the report-writer prompt + the structured-output schema.

Identical prompt is used by:
  * the backfill Workflow (agents in this Claude Code session), and
  * run_intel.py -> `claude -p` (headless, for the recurring live pipeline).

The writer sees ONLY: plain-language signal + sanitized profiles + that week's posts.
"""

import json


# The structured object every report agent returns. Deliberately small — the report IS the
# prose. `summary` + `conviction` are only used for the one-line teaser on the index page.
REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["narrative_md", "summary", "conviction"],
    "properties": {
        "narrative_md": {"type": "string",
                         "description": "The full human-readable note in markdown (see structure + voice guidance). This is the deliverable."},
        "summary": {"type": "string",
                    "description": "ONE plain sentence for the index list — the single most useful takeaway of this note."},
        "conviction": {"type": "string", "enum": ["MORE", "SAME", "LESS"],
                       "description": "Does this week's reading give MORE / the SAME / LESS conviction in the system's current posture?"},
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
## Output — `narrative_md` (this is the whole deliverable; make it clean and human)

Write a plain-English note a smart person reads top-to-bottom and immediately understands.
NO jargon, NO codenames (never "Q-fire", "MRI", "slope_5d", "t1b/t2a", "composite", "v8.5"),
NO labels like "TOP-side / BOTTOM-side", NO scores, dots, or tables. Just clear prose.

Follow THIS exact structure (it is the house format — match it closely):

**The system this week:** one short paragraph, plain words, restating the posture you were given
(trend, hedge, whether there's a buy or sell, on-chain stress). End it with the one question the
voices need to answer this week.

**What the trusted voices actually said:** then ONE short paragraph per voice that published.
Start each with the analyst's name in bold, followed by a brief plain-English descriptor of how
much to trust them in parentheses — drawn from their profile, e.g. "(our best all-rounder)",
"(liquidity tide — good on direction, weak on timing)", "(our richest on-chain read; lean on his
defensive warnings, fade his bottom calls)", "(good fire alarm, poor all-clear; fade their
dip-buying)", "(our bottom-caller; ignore their top warnings)", "(structural bull — only his rare
bearish turns matter)" — then an em-dash and the prose: what they said, whether it's a genuine
change of view or just restating an old one, and the net read. Quote a few of their own words where
it lands. Keep each voice to a tight paragraph. For a silent voice, a single line ("**Willy Woo** —
Quiet. No posts in the window.").

**Does the narrative confirm the system?** one paragraph of synthesis: who lines up with the
system, who doesn't, and why — leaning on the voices that are actually good at this week's question.

**Bottom line:** one paragraph — does this week give MORE, the SAME, or LESS conviction in the
system's posture, and the one or two concrete things to watch next (a price level, a voice, an event).

Rules: ~350–650 words. Have opinions; vary sentence length; no hedging stacks. Do not invent quotes
or facts — everything traces to the posts provided. Never reference anything after the coverage
window. Do NOT put the date title inside narrative_md (the page adds it).
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

# Return the object
Return `narrative_md` (the full note above), `summary` (one plain sentence for the index list),
and `conviction` (MORE / SAME / LESS conviction in the system's posture this week).
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
3. **Jargon / codename leakage** — does `narrative_md` contain internal jargon that must NOT
   appear ("Q-fire", "MRI", "slope_5d", "t1b/t2a/t2b", "composite", "v8.5") OR clunky labels
   like "TOP-side"/"BOTTOM-side"/scores/dots? Require plain-English. The note must read cleanly.
4. **Mis-weighting** — does it lean on a voice's WEAK side, treat a restatement as a fresh
   signal, or (critically) read broad expert fear at a capitulation as CONFLICTING with the buy
   setup rather than confirming it? Flag profile-inconsistent weighting.
5. **Readability** — is it clean human prose matching the house structure (The system this week
   / What the trusted voices actually said, one paragraph per voice / Does the narrative confirm
   the system? / Bottom line)? If it's cluttered or hard to follow, smooth it.

Then return a CORRECTED version of the SAME object (narrative_md, summary, conviction) with every
fault fixed — keep what was already correct, only fix faults and improve clarity. Preserve the
writer's voice. Add nothing unsupported by the sources; do not soften a correct, well-grounded read.

# Coverage window: {p['cover_start']} → {p['cover_end']} (know nothing after this)

# Source posts the writer had:
{_posts_block(packet['corpus'])}

# System state the writer was given (these facts are allowed):
{packet['signal_plain']['paragraph']}
Posture: {packet['signal_plain']['posture']}

# DRAFT object to review and correct:
{json.dumps(draft_json, indent=2)}

Return ONLY the corrected structured object."""

"""
render.py — turn generated reports into the live dashboard sub-folder.

Deliberately simple: each report is the clean narrative note, nothing else. The only
interactive touch is that analyst NAMES in the prose are hover-able — hovering shows a short
description of how good that voice is and how to treat their calls (from profiles.md).

Outputs into docs/intel/ (GitHub Pages serves docs/ from main):
  index.html              -> https://micahcranman.github.io/nassim-dashboard/intel/
  <slug>.html             -> one clean page per report
  data/<slug>.json        -> {period, summary, conviction, narrative_md} for reuse
  email/<slug>.html       -> inline-styled email body (same clean prose)
"""
import os
import re
import json
import html
import glob
import datetime
from pathlib import Path

from intel_lib import BUILD_DIR, DOCS_INTEL, PROFILES_MD

DASH_URL = "https://micahcranman.github.io/nassim-dashboard/"
INTEL_URL = DASH_URL + "intel/"

C = dict(bg="#070b14", ink="#eaf0ff", muted="#8c98b8", faint="#586187",
         long="#16c784", short="#ea3943", neutral="#f3c623", accent="#4aa8ff", accent2="#7c5cff")

# ---------------------------------------------------------------------------
# analyst profiles -> hover popovers
# ---------------------------------------------------------------------------

def load_profiles():
    """Parse profiles.md into {canonical_name: html_popover_body}, plus name aliases."""
    txt = PROFILES_MD.read_text()
    profs = {}
    for m in re.finditer(r"\*\*(.+?)\*\*\s*—\s*(.+?)\n(.*?)(?=\n\*\*|\n---|\Z)", txt, re.S):
        name, tag, body = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        body = re.sub(r"\s+", " ", body)
        profs[name] = {"tag": tag, "body": body}
    return profs


# names to make hover-able in the prose (longest first; only safe proper-noun short forms)
def _alias_map(profs):
    aliases = {
        "James Check": "James Check", "Lyn Alden": "Lyn Alden", "Lyn": "Lyn Alden",
        "Michael Howell": "Michael Howell", "Howell": "Michael Howell",
        "The Bitcoin Layer": "The Bitcoin Layer", "TBL": "The Bitcoin Layer",
        "Macro Ops": "Macro Ops", "Willy Woo": "Willy Woo", "Woo": "Willy Woo",
    }
    return {a: c for a, c in aliases.items() if c in profs}


def _popover_html(canonical, prof):
    tag = html.escape(prof["tag"].rstrip("."))
    body = html.escape(prof["body"])
    return (f'<span class="who-pop"><b>{html.escape(canonical)}</b>'
            f'<span class="who-tag">{tag}</span>{body}</span>')


def wrap_analyst_names(html_str, profs):
    """Wrap analyst-name occurrences (in text only, not inside tags) with a hover popover."""
    aliases = _alias_map(profs)
    names = sorted(aliases, key=len, reverse=True)
    pat = re.compile(r"(?<![\w>])(" + "|".join(re.escape(n) for n in names) + r")(?![\w<])")
    pops = {c: _popover_html(c, profs[c]) for c in set(aliases.values())}

    def repl(m):
        alias = m.group(1)
        canon = aliases[alias]
        return f'<span class="who" tabindex="0">{alias}{pops[canon]}</span>'

    # only operate on text segments, never inside HTML tags
    parts = re.split(r"(<[^>]+>)", html_str)
    for i in range(0, len(parts), 2):       # even indices are text
        parts[i] = pat.sub(repl, parts[i])
    return "".join(parts)


# ---------------------------------------------------------------------------
# tiny markdown -> html
# ---------------------------------------------------------------------------

def md_to_html(md: str) -> str:
    md = md.replace("\r\n", "\n")
    out, lines, i = [], md.split("\n"), 0

    def inline(s):
        s = html.escape(s, quote=False)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
        return s

    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1; continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            out.append(f"<h3>{inline(m.group(2))}</h3>"); i += 1; continue
        m = re.match(r"^[-*]\s+(.*)$", ln)
        if m:
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                items.append(f"<li>{inline(re.sub(r'^[-*][ ]+','',lines[i].rstrip()))}</li>"); i += 1
            out.append("<ul>" + "".join(items) + "</ul>"); continue
        buf = [ln]
        while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^(#{1,4}\s|[-*]\s)", lines[i + 1]):
            i += 1; buf.append(lines[i].rstrip())
        out.append(f"<p>{inline(' '.join(buf))}</p>"); i += 1
    return "\n".join(out)


# ---------------------------------------------------------------------------
# page chrome
# ---------------------------------------------------------------------------

CSS = f"""
:root{{--bg:#070b14;--glass:rgba(20,28,48,0.55);--glass-brd:rgba(120,150,220,0.16);
--ink:#eaf0ff;--muted:#8c98b8;--faint:#586187;--long:#16c784;--short:#ea3943;
--neutral:#f3c623;--accent:#4aa8ff;--accent2:#7c5cff;
--sans:'Inter',system-ui,sans-serif;}}
*{{box-sizing:border-box}}
html,body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased}}
body{{background:radial-gradient(1100px 640px at 15% -10%,rgba(74,168,255,.07),transparent 60%),
radial-gradient(900px 560px at 100% 0%,rgba(124,92,255,.06),transparent 55%),var(--bg);min-height:100vh}}
.wrap{{max-width:720px;margin:0 auto;padding:20px 20px 90px}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}
.top{{display:flex;align-items:center;gap:12px;margin-bottom:30px}}
.brand{{display:flex;align-items:center;gap:9px;font-weight:800;letter-spacing:.3px;font-size:15px}}
.brand .dot{{width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 12px var(--accent)}}
.brand small{{font-weight:600;color:var(--muted);letter-spacing:2px;font-size:10.5px}}
.spacer{{flex:1}}
.back{{font:600 12px var(--sans);color:var(--muted);border:1px solid var(--glass-brd);padding:7px 12px;border-radius:9px;background:rgba(255,255,255,.03)}}

.eyebrow{{font:600 12px var(--sans);color:var(--faint);letter-spacing:.4px;text-transform:none;margin-bottom:4px}}
h1.title{{font-size:30px;font-weight:800;letter-spacing:-.5px;margin:0 0 6px}}
.convtag{{display:inline-block;font:700 11px var(--sans);letter-spacing:.4px;padding:4px 11px;border-radius:20px;margin-top:6px}}

/* the article */
.note{{font-size:16.5px;line-height:1.72;color:#dde4f7;margin-top:26px}}
.note p{{margin:0 0 17px}}
.note h3{{font-size:13px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);
margin:30px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--glass-brd)}}
.note strong{{color:#fff;font-weight:700}}
.note ul{{margin:0 0 17px;padding-left:20px}} .note li{{margin:8px 0}}
.note em{{color:#cdd6ef}}

/* hover popover on analyst names */
.who{{position:relative;color:#fff;font-weight:700;border-bottom:1px dotted rgba(74,168,255,.6);cursor:help;outline:none}}
.who-pop{{visibility:hidden;opacity:0;position:absolute;left:0;top:calc(100% + 9px);z-index:50;
width:330px;max-width:78vw;padding:14px 16px;border-radius:13px;
background:rgba(10,15,28,.985);border:1px solid var(--glass-brd);
box-shadow:0 16px 48px rgba(0,0,0,.6);backdrop-filter:blur(8px);
font:400 13.5px var(--sans);line-height:1.58;color:var(--muted);letter-spacing:0;
transition:opacity .14s ease;pointer-events:none}}
.who-pop::before{{content:"";position:absolute;left:18px;top:-6px;width:11px;height:11px;
background:rgba(10,15,28,.985);border-left:1px solid var(--glass-brd);border-top:1px solid var(--glass-brd);transform:rotate(45deg)}}
.who-pop b{{display:block;color:var(--ink);font-size:14.5px;font-weight:700;margin-bottom:1px}}
.who-pop .who-tag{{display:block;color:var(--accent);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px}}
.who:hover .who-pop,.who:focus .who-pop,.who:focus-within .who-pop{{visibility:visible;opacity:1}}
@media (max-width:560px){{.who-pop{{left:auto;right:0}}.who-pop::before{{left:auto;right:18px}}}}

.foot{{color:var(--faint);font-size:12px;margin-top:40px;line-height:1.65;border-top:1px solid var(--glass-brd);padding-top:18px}}

/* index */
.lead{{color:var(--muted);font-size:15px;line-height:1.7;margin:6px 0 30px}}
.rlist{{display:flex;flex-direction:column;gap:2px}}
.rrow{{display:block;color:inherit;padding:18px 4px;border-bottom:1px solid rgba(120,150,220,.10);transition:background .12s}}
.rrow:hover{{background:rgba(74,168,255,.05);text-decoration:none}}
.rrow .rd{{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}}
.rrow .rdate{{font:700 18px var(--sans)}}
.rrow .rcov{{font:500 12.5px var(--sans);color:var(--faint)}}
.rrow .rsum{{color:var(--muted);font-size:14.5px;line-height:1.55;margin-top:7px}}
.rrow .rconv{{font:700 10.5px var(--sans);letter-spacing:.3px;padding:3px 9px;border-radius:20px;white-space:nowrap}}
"""

CONV = {  # (label, text color, bg)
    "MORE": ("More conviction", C["long"]),
    "SAME": ("Same conviction", C["neutral"]),
    "LESS": ("Less conviction", C["short"]),
}


def _conv_tag(conv, big=False):
    label, col = CONV.get(conv, ("", C["faint"]))
    if not label:
        return ""
    cls = "convtag" if big else "rconv"
    return f'<span class="{cls}" style="color:{col};background:{col}1c;border:1px solid {col}44">{label}</span>'


HEAD = """<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{css}</style></head><body><div class="wrap">"""


def _topbar():
    return ('<div class="top"><div class="brand"><span class="dot"></span>Strategy²&nbsp;'
            '<small>NARRATIVE INTEL</small></div><div class="spacer"></div>'
            f'<a class="back" href="{DASH_URL}">← v8.5 Console</a></div>')


def _week_title(period):
    s = datetime.date.fromisoformat(period["cover_start"])
    return f"Week of {s.strftime('%B %-d, %Y')}"


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------

def render_report(slug, profs):
    pkt = json.loads((BUILD_DIR / f"packet-{slug}.json").read_text())
    rep = json.loads((BUILD_DIR / f"final-{slug}.json").read_text())
    period = pkt["period"]
    note = wrap_analyst_names(md_to_html(rep.get("narrative_md", "")), profs)
    cov = f"{datetime.date.fromisoformat(period['cover_start']).strftime('%b %-d')} – {datetime.date.fromisoformat(period['cover_end']).strftime('%b %-d, %Y')}"

    body = f"""{_topbar()}
<div class="eyebrow">Covers {cov}</div>
<h1 class="title">{_week_title(period)}</h1>
{_conv_tag(rep.get('conviction'), big=True)}
<article class="note">{note}</article>
<div class="foot">
  A point-in-time read of the trusted voices against the Strategy² v8.5 system — it calibrates
  conviction, it doesn't generate signals, and it never uses hindsight. Hover any analyst's name
  to see how much to trust them and how to read their calls.<br>
  Generated {rep.get('_generated_at','')} · <a href="{INTEL_URL}">all reports</a> · <a href="{DASH_URL}">v8.5 console</a>
</div>"""
    page = HEAD.format(title=f"{_week_title(period)} · Strategy² Intel", css=CSS) + body + "</div></body></html>"
    (DOCS_INTEL / f"{slug}.html").write_text(page)

    (DOCS_INTEL / "data" / f"{slug}.json").write_text(json.dumps({
        "period": period, "conviction": rep.get("conviction"),
        "summary": rep.get("summary", ""), "narrative_md": rep.get("narrative_md", ""),
    }, indent=2))
    return rep, period


def render_index(cards):
    rows = []
    for rep, period in cards:
        cov = f"{datetime.date.fromisoformat(period['cover_start']).strftime('%b %-d')} – {datetime.date.fromisoformat(period['cover_end']).strftime('%b %-d')}"
        rows.append(f"""<a class="rrow" href="{period['slug']}.html">
  <div class="rd"><span class="rdate">{_week_title(period)}</span>
    <span class="rcov">{cov}</span>
    <span class="spacer"></span>{_conv_tag(rep.get('conviction'))}</div>
  <div class="rsum">{html.escape(rep.get('summary',''))}</div>
</a>""")
    lead = ("A twice-weekly read of the analysts we trust, set against the Strategy² v8.5 system. "
            "It doesn't call trades — it tells you whether the voices we trust make the dashboard's "
            "current stance more or less convincing this week, and which voices to weight. "
            "Mondays cover Thursday–Sunday; Thursdays cover Monday–Wednesday.")
    body = f"""{_topbar()}
<div class="eyebrow">conviction layer · MSTR / BTC</div>
<h1 class="title">Narrative Intelligence</h1>
<div class="lead">{lead}</div>
<div class="rlist">{''.join(rows)}</div>
<div class="foot">Hover any analyst's name in a report to see how to read their calls. · <a href="{DASH_URL}">v8.5 console</a></div>"""
    page = HEAD.format(title="Narrative Intelligence · Strategy²", css=CSS) + body + "</div></body></html>"
    (DOCS_INTEL / "index.html").write_text(page)


def render_email(slug, profs):
    data = json.loads((DOCS_INTEL / "data" / f"{slug}.json").read_text())
    period, rep = data["period"], data
    # email: clean prose, inline styles, no JS / no hover (link out instead)
    note = md_to_html(rep.get("narrative_md", ""))
    note = (note.replace("<h3>", '<h3 style="font-size:12px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:#8c98b8;margin:26px 0 10px;border-bottom:1px solid rgba(120,150,220,.2);padding-bottom:6px">')
                .replace("<p>", '<p style="margin:0 0 15px">')
                .replace("<strong>", '<strong style="color:#fff">'))
    label, col = CONV.get(rep.get("conviction"), ("", C["faint"]))
    url = f"{INTEL_URL}{slug}.html"
    cov = f"{datetime.date.fromisoformat(period['cover_start']).strftime('%b %-d')} – {datetime.date.fromisoformat(period['cover_end']).strftime('%b %-d, %Y')}"
    doc = f"""<div style="background:#070b14;color:#dde4f7;font-family:-apple-system,Segoe UI,Inter,sans-serif;margin:0;padding:0">
<div style="max-width:600px;margin:0 auto;padding:26px 22px">
  <div style="font-weight:800;color:#eaf0ff;font-size:14px">Strategy² <span style="color:#8c98b8;font-weight:600;font-size:10.5px;letter-spacing:2px">NARRATIVE INTEL</span></div>
  <div style="color:#586187;font-size:12px;margin-top:16px">Covers {cov}</div>
  <h1 style="font-size:25px;margin:3px 0 8px;color:#fff;font-weight:800">{_week_title(period)}</h1>
  {'<span style="display:inline-block;font-size:11px;font-weight:700;color:'+col+';background:'+col+'1c;border:1px solid '+col+'44;border-radius:20px;padding:4px 11px">'+label+'</span>' if label else ''}
  <div style="font-size:15.5px;line-height:1.72;color:#dde4f7;margin-top:22px">{note}</div>
  <p style="margin:26px 0 6px"><a href="{url}" style="background:linear-gradient(180deg,#4aa8ff,#2b6fd0);color:#fff;text-decoration:none;padding:11px 20px;border-radius:10px;font-weight:600;font-size:14px;display:inline-block">Open on the dashboard ↗</a></p>
  <p style="color:#586187;font-size:11px;line-height:1.6;margin-top:22px">A point-in-time read of the trusted voices against the Strategy² v8.5 system. Calibrates conviction; no signals; no hindsight. On the dashboard you can hover any analyst's name to see how to read their calls.</p>
</div></div>"""
    out = DOCS_INTEL / "email"; out.mkdir(exist_ok=True)
    (out / f"{slug}.html").write_text(doc)
    return out / f"{slug}.html"


def main():
    os.chdir(Path(__file__).resolve().parent)
    DOCS_INTEL.mkdir(parents=True, exist_ok=True)
    (DOCS_INTEL / "data").mkdir(exist_ok=True)
    profs = load_profiles()
    slugs = sorted((Path(p).stem.replace("final-", "")
                    for p in glob.glob(str(BUILD_DIR / "final-*.json"))), reverse=True)
    if not slugs:
        print("No final-*.json reports in build/. Run generation first."); return
    cards = []
    for slug in slugs:
        fp = BUILD_DIR / f"final-{slug}.json"
        rep = json.loads(fp.read_text())
        rep.setdefault("_generated_at", datetime.datetime.now().strftime("%Y-%m-%d %H:%M CT"))
        fp.write_text(json.dumps(rep, indent=2))
        rep, period = render_report(slug, profs)
        render_email(slug, profs)
        cards.append((rep, period)); print("rendered", slug)
    render_index(cards)
    print(f"index.html + {len(cards)} reports -> {DOCS_INTEL}")


if __name__ == "__main__":
    main()

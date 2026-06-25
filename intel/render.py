"""
render.py — turn generated reports (+ their packets) into the live dashboard sub-folder.

Outputs into docs/intel/ (GitHub Pages serves docs/ from main):
  index.html              -> https://micahcranman.github.io/nassim-dashboard/intel/
  <slug>.html             -> one page per report
  data/<slug>.json        -> merged structured data (report + signal) for reuse
  email/<slug>.html       -> inline-styled email body

Design matches the Strategy² v8.5 console (docs/index.html): dark glass, Inter + JetBrains
Mono, Plotly via CDN, the same color tokens.
"""
import os
import re
import json
import html
import glob
import datetime
from pathlib import Path

from intel_lib import BUILD_DIR, DOCS_INTEL, REPO

DASH_URL = "https://micahcranman.github.io/nassim-dashboard/"
INTEL_URL = DASH_URL + "intel/"

# ---- color tokens (mirror docs/index.html) --------------------------------
C = dict(bg="#070b14", ink="#eaf0ff", muted="#8c98b8", faint="#586187",
         long="#16c784", short="#ea3943", neutral="#f3c623", accent="#4aa8ff", accent2="#7c5cff")

DELTA_COLOR = {"MORE": C["long"], "SAME": C["neutral"], "LESS": C["short"]}
DELTA_LABEL = {"MORE": "MORE CONVICTION", "SAME": "SAME CONVICTION", "LESS": "LESS CONVICTION"}
VERDICT_COLOR = {"CORROBORATE": C["long"], "CONFLICT": C["short"], "SILENT": C["faint"]}
LEAN_COLOR = {"confirms": C["long"], "contradicts": C["short"], "neutral": C["neutral"], "silent": C["faint"]}
LEAN_LABEL = {"confirms": "confirms", "contradicts": "contradicts", "neutral": "neutral", "silent": "silent"}
SIDE_LABEL = {"TOP": "TOP-side", "BOTTOM": "BOTTOM-side", "NEUTRAL": "neutral", "NA": "—"}

ROSTER_ORDER = ["James Check", "Lyn Alden", "Michael Howell",
                "The Bitcoin Layer", "Macro Ops", "Willy Woo"]
ANALYST_TAG = {"James Check": "on-chain", "Lyn Alden": "macro / liquidity",
               "Michael Howell": "global liquidity", "The Bitcoin Layer": "macro · bottom-caller",
               "Macro Ops": "tactical macro", "Willy Woo": "on-chain"}

# ---------------------------------------------------------------------------
# tiny markdown -> html (bold, italic, headings, bullets, links, paragraphs)
# ---------------------------------------------------------------------------

def md_to_html(md: str) -> str:
    md = md.replace("\r\n", "\n")
    out = []
    lines = md.split("\n")
    i = 0
    in_ul = False

    def inline(s):
        s = html.escape(s, quote=False)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                   r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
        return s

    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            if in_ul:
                out.append("</ul>"); in_ul = False
            i += 1; continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            if in_ul: out.append("</ul>"); in_ul = False
            lvl = len(m.group(1)); out.append(f"<h{lvl+1}>{inline(m.group(2))}</h{lvl+1}>")
            i += 1; continue
        m = re.match(r"^[-*]\s+(.*)$", ln)
        if m:
            if not in_ul: out.append("<ul>"); in_ul = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            i += 1; continue
        # paragraph (gather until blank)
        if in_ul: out.append("</ul>"); in_ul = False
        buf = [ln]
        while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^(#{1,4}\s|[-*]\s)", lines[i + 1]):
            i += 1; buf.append(lines[i].rstrip())
        out.append(f"<p>{inline(' '.join(buf))}</p>")
        i += 1
    if in_ul: out.append("</ul>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# shared HTML head / chrome
# ---------------------------------------------------------------------------

CSS = """
:root{--bg:#070b14;--glass:rgba(20,28,48,0.55);--glass-brd:rgba(120,150,220,0.16);
--ink:#eaf0ff;--muted:#8c98b8;--faint:#586187;--long:#16c784;--short:#ea3943;
--neutral:#f3c623;--accent:#4aa8ff;--accent2:#7c5cff;
--mono:'JetBrains Mono',ui-monospace,monospace;--sans:'Inter',system-ui,sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased}
body{background:radial-gradient(1200px 700px at 12% -8%,rgba(74,168,255,.10),transparent 60%),
radial-gradient(1000px 600px at 100% 0%,rgba(124,92,255,.10),transparent 55%),
radial-gradient(900px 700px at 50% 120%,rgba(22,199,132,.06),transparent 60%),var(--bg);min-height:100vh}
.wrap{max-width:1080px;margin:0 auto;padding:18px 16px 80px}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.top{display:flex;align-items:center;gap:14px;margin-bottom:18px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;letter-spacing:.3px}
.brand .dot{width:10px;height:10px;border-radius:50%;background:var(--accent);box-shadow:0 0 14px var(--accent)}
.brand small{font-weight:600;color:var(--muted);letter-spacing:2px;font-size:11px}
.spacer{flex:1}
.back{font:600 12px var(--sans);color:var(--muted);border:1px solid var(--glass-brd);
padding:7px 13px;border-radius:10px;background:rgba(255,255,255,.03)}
.card{background:var(--glass);border:1px solid var(--glass-brd);border-radius:18px;
backdrop-filter:blur(16px) saturate(140%);-webkit-backdrop-filter:blur(16px) saturate(140%);
box-shadow:0 10px 40px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.04)}
.cat{font-size:9.5px;text-transform:uppercase;letter-spacing:1px;color:var(--faint)}
.badge{font:700 10px var(--mono);padding:3px 8px;border-radius:6px;letter-spacing:.5px;display:inline-block}
.pill{font:700 11px var(--mono);padding:4px 10px;border-radius:8px;letter-spacing:.4px;display:inline-flex;gap:6px;align-items:center}

/* hero */
.hero{padding:24px;overflow:hidden}
.hero .meta{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:flex-start}
.hero .when{font:700 13px var(--mono);color:var(--muted)}
.hero h1{font-size:25px;margin:6px 0 2px;font-weight:800;letter-spacing:-.4px}
.verdict{display:flex;align-items:center;gap:16px;margin:16px 0 4px;flex-wrap:wrap}
.vbadge{font:800 22px var(--mono);letter-spacing:1px;padding:11px 20px;border-radius:13px;text-transform:uppercase}
.posture{color:var(--muted);font-size:13.5px;line-height:1.5;margin-top:8px;max-width:760px}
.conf{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}
.confcard{padding:13px 16px;border-radius:13px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);min-width:230px;flex:1}
.confcard .k{font-size:10.5px;text-transform:uppercase;letter-spacing:1.1px;color:var(--muted);font-weight:600;display:flex;justify-content:space-between;gap:8px}
.confcard .vv{font:800 17px var(--mono);margin-top:6px;display:flex;align-items:center;gap:9px}
.dots{display:inline-flex;gap:3px}
.dots i{width:7px;height:7px;border-radius:50%;background:rgba(255,255,255,.16)}
.confcard .nt{font-size:12px;color:var(--muted);margin-top:7px;line-height:1.45}

/* snapshot chips */
.sec{display:flex;align-items:center;gap:10px;margin:26px 2px 12px;font-weight:700;font-size:15px;flex-wrap:wrap}
.sec .hint{font-weight:500;font-size:12px;color:var(--muted)}
.chips{display:flex;gap:10px;flex-wrap:wrap}
.chip{padding:11px 14px;border-radius:13px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);min-width:130px}
.chip .k{font-size:10px;text-transform:uppercase;letter-spacing:1.1px;color:var(--muted);font-weight:600}
.chip .v{font:700 19px var(--mono);margin-top:4px}
.chip .s{font-size:11px;color:var(--faint);margin-top:3px}

/* chart */
.chart{padding:14px 10px 8px}
.chart .plot{width:100%;height:360px}
.clegend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:2px 8px 4px}
.clegend i{display:inline-block;width:10px;height:3px;border-radius:2px;margin-right:6px;vertical-align:3px}

/* voices */
.voices{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:13px}
.voice{padding:15px 16px;border-radius:14px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07)}
.voice.silent{opacity:.5}
.voice .vh{display:flex;justify-content:space-between;align-items:center;gap:8px}
.voice .nm{font-weight:700;font-size:14.5px}
.voice .tg{font-size:10.5px;color:var(--faint);margin-top:1px}
.voice .row2{display:flex;gap:7px;align-items:center;margin:9px 0 2px;flex-wrap:wrap}
.voice .summ{font-size:12.5px;color:var(--ink);line-height:1.5;margin-top:8px}
.voice .quote{font-size:12px;color:var(--muted);font-style:italic;border-left:2px solid var(--glass-brd);padding-left:10px;margin-top:9px;line-height:1.45}
.voice .src{font-size:11px;margin-top:9px}
.cdots{display:inline-flex;gap:3px;align-items:center}
.cdots i{width:6px;height:6px;border-radius:50%}

/* narrative */
.narr{padding:8px 26px 22px;font-size:14.5px;line-height:1.72;color:#dfe6fb}
.narr h2{font-size:17px;margin:22px 0 8px;color:var(--ink)}
.narr h3{font-size:15px;margin:18px 0 6px;color:var(--ink)}
.narr p{margin:11px 0}
.narr ul{margin:10px 0;padding-left:20px}
.narr li{margin:7px 0}
.narr strong{color:#fff}
.callout{margin:18px 0 2px;padding:15px 18px;border-radius:13px;
background:linear-gradient(90deg,rgba(74,168,255,.12),rgba(124,92,255,.07));border:1px solid rgba(74,168,255,.2)}
.callout .k{font-size:10.5px;text-transform:uppercase;letter-spacing:1.1px;color:var(--accent);font-weight:700}
.callout .v{font-size:15px;line-height:1.6;margin-top:6px;color:#eef2ff}
.foot{color:var(--faint);font-size:11.5px;margin-top:26px;line-height:1.6}

/* index list */
.lead{color:var(--muted);font-size:14px;line-height:1.65;max-width:780px;margin:2px 2px 22px}
.rlist{display:flex;flex-direction:column;gap:13px}
.rcard{padding:18px 20px;border-radius:15px;display:block;color:inherit;transition:transform .13s,border-color .2s,box-shadow .2s}
.rcard:hover{transform:translateY(-2px);border-color:rgba(120,150,220,.34);box-shadow:0 12px 36px rgba(0,0,0,.3);text-decoration:none}
.rcard .rh{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.rcard .rdate{font:700 16px var(--sans)}
.rcard .rcov{font:600 12px var(--mono);color:var(--muted)}
.rcard .rb{font-size:13px;color:var(--muted);line-height:1.55;margin-top:10px}
.rcard .rchips{display:flex;gap:8px;flex-wrap:wrap;margin-top:11px}
"""

HEAD = """<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<title>{title}</title>
{plotly}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>{css}</style></head><body><div class="wrap">"""

PLOTLY = '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>'


def _topbar(subtitle, with_back=True):
    back = f'<a class="back" href="{DASH_URL}">← v8.5 Console</a>' if with_back else ""
    return f"""<div class="top">
  <div class="brand"><span class="dot"></span>Strategy²&nbsp;<small>{subtitle}</small></div>
  <div class="spacer"></div>{back}
</div>"""


def _dots(n, color):
    return '<span class="dots">' + "".join(
        f'<i style="background:{color}"></i>' if k < n else '<i></i>' for k in range(3)) + "</span>"


def _cdots(n, color):
    return '<span class="cdots">' + "".join(
        f'<i style="background:{color}"></i>' if k < n else '<i style="background:rgba(255,255,255,.16)"></i>'
        for k in range(5)) + "</span>"


def _fmt_num(v, kind):
    if v is None:
        return "—"
    if kind == "usd0":
        return f"${v:,.0f}"
    if kind == "usd2":
        return f"${v:,.2f}"
    if kind == "x":
        return f"{v:.2f}×"
    return f"{v:.1f}"


# ---------------------------------------------------------------------------
# report page
# ---------------------------------------------------------------------------

def render_report(slug):
    pkt = json.loads((BUILD_DIR / f"packet-{slug}.json").read_text())
    rep = json.loads((BUILD_DIR / f"final-{slug}.json").read_text())
    period = pkt["period"]
    sig = pkt["signal"]; der = sig["derived"]
    delta = rep.get("conviction_delta", "SAME")
    dcol = DELTA_COLOR.get(delta, C["neutral"])

    # ---- hero
    bear, qf = rep["bear_overlay"], rep["qfire"]
    conf_cards = []
    for title, obj, side_hint in [("Bear-overlay (defensive / top side)", bear, "Does the chorus back the hedge?"),
                                  ("Bottom-watch (contrarian buy side)", qf, "Does the chorus back the dip-buy?")]:
        vc = VERDICT_COLOR.get(obj["verdict"], C["faint"])
        conf_cards.append(f"""<div class="confcard">
  <div class="k"><span>{title}</span>{_dots(obj['strength'], vc)}</div>
  <div class="vv" style="color:{vc}">{obj['verdict']}</div>
  <div class="nt">{html.escape(obj['note'])}</div></div>""")

    # ---- snapshot chips
    chips = [
        ("Bitcoin", _fmt_num(sig["btc"]["value"], "usd0"), ""),
        ("MicroStrategy", _fmt_num(sig["mstr"]["value"], "usd2"), ""),
        ("On-chain stress", _fmt_num(sig["mri"]["value"], "num"), der["mri_zone"].split(" (")[0]),
        ("Hedge trend", "OPEN" if der["hedge_gate_open"] else "shut", der["trend_label"].split(" — ")[0]),
        ("mNAV", _fmt_num(sig["mnav"]["value"], "x"), der["mnav_label"].split(" (")[0].split(" —")[0]),
    ]
    chip_html = "".join(
        f'<div class="chip"><div class="k">{k}</div><div class="v">{v}</div>'
        f'<div class="s">{html.escape(s)}</div></div>' for k, v, s in chips)

    # ---- voices
    by_name = {a["name"]: a for a in rep.get("analysts", [])}
    vcards = []
    for name in ROSTER_ORDER:
        a = by_name.get(name, {"name": name, "published": False, "side": "NA",
                               "lean": "silent", "conviction": 0, "summary": "", "quote": "", "url": "", "stance_change": False})
        silent = not a.get("published")
        lcol = LEAN_COLOR.get(a.get("lean", "silent"), C["faint"])
        side = a.get("side", "NA")
        side_badge = f'<span class="badge" style="background:rgba(255,255,255,.05);color:var(--muted);border:1px solid var(--glass-brd)">{SIDE_LABEL.get(side, side)}</span>' if not silent else ""
        change = '<span class="badge" style="background:rgba(74,168,255,.14);color:var(--accent);border:1px solid rgba(74,168,255,.3)">fresh change</span>' if a.get("stance_change") and not silent else ""
        lean_badge = f'<span class="pill" style="background:rgba(0,0,0,.18);color:{lcol};border:1px solid {lcol}55">{LEAN_LABEL.get(a.get("lean","silent"))}</span>'
        conv = _cdots(a.get("conviction", 0), lcol) if not silent else ""
        summ = f'<div class="summ">{html.escape(a.get("summary",""))}</div>' if a.get("summary") else ""
        quote = f'<div class="quote">“{html.escape(a.get("quote",""))}”</div>' if a.get("quote") else ""
        src = f'<div class="src"><a href="{html.escape(a.get("url",""))}" target="_blank" rel="noopener">source ↗</a></div>' if a.get("url") else ""
        if silent:
            summ = '<div class="summ" style="color:var(--faint)">No post in the coverage window.</div>'
        vcards.append(f"""<div class="voice{' silent' if silent else ''}">
  <div class="vh"><div><div class="nm">{name}</div><div class="tg">{ANALYST_TAG.get(name,'')}</div></div>
    <div style="text-align:right">{lean_badge}</div></div>
  <div class="row2">{side_badge}{change}{conv}</div>
  {summ}{quote}{src}</div>""")

    # ---- chart data
    traj = sig["trajectory"]
    chart_json = json.dumps({
        "dates": [t["d"] for t in traj],
        "btc": [t["btc"] for t in traj],
        "mri": [t["mri"] for t in traj],
        "mnav": [t["mnav"] for t in traj],
        "win_start": period["cover_start"], "win_end": period["cover_end"],
        "report_date": period["report_date"],
    })

    narrative = md_to_html(rep.get("narrative_md", ""))
    regime = rep.get("regime", "—")
    regime_col = {"BULL": C["long"], "BEAR": C["short"], "NEUTRAL": C["neutral"]}.get(regime, C["faint"])

    body = f"""{_topbar('NARRATIVE INTEL')}
<div class="card hero">
  <div class="meta">
    <div>
      <div class="when">{period['kind'].upper()} REPORT · {period['cover_start']} → {period['cover_end']}</div>
      <h1>{html.escape(period['title'])}</h1>
    </div>
    <span class="pill" style="background:{regime_col}22;color:{regime_col};border:1px solid {regime_col}55;font-size:12px">{regime} REGIME</span>
  </div>
  <div class="verdict">
    <span class="vbadge" style="background:{dcol}1f;color:{dcol};border:1px solid {dcol}66">{DELTA_LABEL.get(delta, delta)}</span>
    <span style="color:var(--muted);font-size:13px;max-width:520px">{html.escape(rep.get('bottom_line',''))}</span>
  </div>
  <div class="posture">{html.escape(rep.get('system_state',''))}</div>
  <div class="conf">{''.join(conf_cards)}</div>
</div>

<div class="sec">System snapshot <span class="hint">· what the dashboard showed when this note was written</span></div>
<div class="chips">{chip_html}</div>

<div class="sec">Price &amp; on-chain stress <span class="hint">· shaded band = this report's coverage window</span></div>
<div class="card chart">
  <div class="clegend"><span><i style="background:{C['accent']}"></i>Bitcoin price</span>
    <span><i style="background:{C['neutral']}"></i>On-chain stress gauge</span>
    <span><i style="background:{C['short']};height:2px"></i>capitulation line</span></div>
  <div id="plot" class="plot"></div>
</div>

<div class="sec">The trusted voices <span class="hint">· weighted by what each is good at — defensive warnings vs buy-the-dip calls</span></div>
<div class="voices">{''.join(vcards)}</div>

<div class="sec">The note</div>
<div class="card"><div class="narr">{narrative}
  <div class="callout"><div class="k">Bottom line</div><div class="v">{html.escape(rep.get('bottom_line',''))}</div></div>
</div></div>

<div class="foot">
  Point-in-time narrative-intelligence note. The system posture is produced by the Strategy² v8.5 dashboard;
  this note only calibrates conviction in it by reading the trusted voices' actual posts inside the coverage
  window — it never uses hindsight. Voices weighted by side-specific skill; the one bottom-caller is
  The Bitcoin Layer, and at a capitulation widespread expert fear is read as confirmation, not conflict.<br>
  Generated {rep.get('_generated_at','')} · <a href="{INTEL_URL}">all reports</a> · <a href="{DASH_URL}">v8.5 console</a>
</div>

<script>
const D = {chart_json};
(function(){{
  const shade0 = D.win_start, shade1 = D.win_end;
  const btcVals = D.btc.filter(v=>v!=null);
  const ylo = Math.min.apply(null,btcVals)*0.985, yhi = Math.max.apply(null,btcVals)*1.012;
  const t_btc = {{x:D.dates,y:D.btc,name:'Bitcoin',type:'scatter',mode:'lines',
    line:{{color:'{C['accent']}',width:3,shape:'spline',smoothing:0.6}},yaxis:'y',
    fill:'tozeroy',fillcolor:'rgba(74,168,255,0.13)',
    hovertemplate:'%{{x}}<br>BTC $%{{y:,.0f}}<extra></extra>'}};
  const t_mri = {{x:D.dates,y:D.mri,name:'On-chain stress',type:'scatter',mode:'lines+markers',
    line:{{color:'{C['neutral']}',width:2.2,dash:'dot'}},marker:{{size:4,color:'{C['neutral']}'}},
    yaxis:'y2',connectgaps:true,hovertemplate:'%{{x}}<br>stress %{{y:.1f}}<extra></extra>'}};
  const layout = {{
    paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(255,255,255,0.018)',
    font:{{color:'{C['muted']}',family:'JetBrains Mono, monospace',size:11}},
    margin:{{l:60,r:54,t:10,b:34}},showlegend:false,
    xaxis:{{gridcolor:'rgba(255,255,255,.05)',zeroline:false}},
    yaxis:{{title:'BTC',gridcolor:'rgba(255,255,255,.06)',zeroline:false,tickprefix:'$',tickformat:',.0f',range:[ylo,yhi]}},
    yaxis2:{{title:'stress',overlaying:'y',side:'right',gridcolor:'rgba(0,0,0,0)',zeroline:false,range:[0,Math.max(40,Math.max.apply(null,D.mri.filter(v=>v!=null))+6)]}},
    shapes:[
      {{type:'rect',xref:'x',yref:'paper',x0:shade0,x1:shade1,y0:0,y1:1,
        fillcolor:'rgba(124,92,255,.16)',line:{{color:'rgba(124,92,255,.45)',width:1,dash:'dot'}},layer:'below'}},
      {{type:'line',xref:'paper',yref:'y2',x0:0,x1:1,y0:12,y1:12,
        line:{{color:'{C['short']}',width:1.4,dash:'dash'}}}}
    ],
    annotations:[
      {{xref:'paper',yref:'y2',x:0.012,y:12,yanchor:'bottom',text:'capitulation buy zone (≤12)',
        showarrow:false,font:{{color:'{C['short']}',size:9.5}}}},
      {{xref:'x',yref:'paper',x:shade1,y:1,yanchor:'bottom',xanchor:'right',text:'coverage window',
        showarrow:false,font:{{color:'{C['accent2']}',size:9.5}}}}
    ]
  }};
  Plotly.newPlot('plot',[t_btc,t_mri],layout,{{displayModeBar:false,responsive:true}});
}})();
</script>"""
    page = HEAD.format(title=f"{period['title']} · Strategy² Intel", plotly=PLOTLY, css=CSS) + body + "</div></body></html>"
    (DOCS_INTEL / f"{slug}.html").write_text(page)

    # merged data for reuse / future dashboard integration
    (DOCS_INTEL / "data" / f"{slug}.json").write_text(json.dumps({
        "period": period, "signal": sig, "signal_plain": pkt["signal_plain"], "report": rep,
    }, indent=2))
    return rep, period


# ---------------------------------------------------------------------------
# index page
# ---------------------------------------------------------------------------

def render_index(cards):
    rows = []
    for rep, period in cards:
        delta = rep.get("conviction_delta", "SAME"); dcol = DELTA_COLOR.get(delta, C["neutral"])
        regime = rep.get("regime", "—"); rcol = {"BULL": C["long"], "BEAR": C["short"], "NEUTRAL": C["neutral"]}.get(regime, C["faint"])
        bear, qf = rep["bear_overlay"], rep["qfire"]
        bc, qc = VERDICT_COLOR.get(bear["verdict"], C["faint"]), VERDICT_COLOR.get(qf["verdict"], C["faint"])
        rows.append(f"""<a class="card rcard" href="{period['slug']}.html">
  <div class="rh">
    <div><div class="rdate">{html.escape(period['title'].replace('Market Note — ',''))}</div>
      <div class="rcov">{period['kind'].upper()} · {period['cover_start']} → {period['cover_end']}</div></div>
    <span class="pill" style="background:{dcol}1f;color:{dcol};border:1px solid {dcol}66">{DELTA_LABEL.get(delta,delta)}</span>
  </div>
  <div class="rb">{html.escape(rep.get('bottom_line',''))}</div>
  <div class="rchips">
    <span class="pill" style="background:{rcol}18;color:{rcol};border:1px solid {rcol}44">{regime}</span>
    <span class="pill" style="background:rgba(255,255,255,.04);color:{bc};border:1px solid {bc}44">Hedge: {bear['verdict']}</span>
    <span class="pill" style="background:rgba(255,255,255,.04);color:{qc};border:1px solid {qc}44">Buy-watch: {qf['verdict']}</span>
  </div>
</a>""")

    lead = ("A twice-weekly read of the analysts we actually trust, set against the Strategy² v8.5 "
            "system. It does not generate signals — it tells you whether the trusted voices raise or "
            "lower conviction in what the dashboard is already saying, weighting each voice only on the "
            "side it has earned (defensive top-warnings vs buy-the-dip calls). Mondays cover the prior "
            "Thursday–Sunday; Thursdays cover Monday–Wednesday. Strictly point-in-time — each note knows "
            "nothing published after its window.")
    body = f"""{_topbar('NARRATIVE INTEL')}
<div class="card hero" style="padding:22px 24px">
  <h1 style="margin:0 0 4px">Narrative Intelligence</h1>
  <div class="cat">conviction layer · MSTR / BTC · v8.5</div>
  <div class="lead" style="margin-top:14px">{lead}</div>
</div>
<div class="sec">Recent reports <span class="hint">· newest first</span></div>
<div class="rlist">{''.join(rows)}</div>
<div class="foot">Generated by the narrative-intel pipeline · <a href="{DASH_URL}">v8.5 console</a></div>"""
    page = HEAD.format(title="Narrative Intelligence · Strategy²", plotly="", css=CSS) + body + "</div></body></html>"
    (DOCS_INTEL / "index.html").write_text(page)


# ---------------------------------------------------------------------------
# email body (inline-styled, no JS)
# ---------------------------------------------------------------------------

def render_email(slug):
    rep = json.loads((DOCS_INTEL / "data" / f"{slug}.json").read_text())["report"]
    pkt = json.loads((BUILD_DIR / f"packet-{slug}.json").read_text())
    period = pkt["period"]
    delta = rep.get("conviction_delta", "SAME"); dcol = DELTA_COLOR.get(delta, C["neutral"])
    bear, qf = rep["bear_overlay"], rep["qfire"]
    url = f"{INTEL_URL}{slug}.html"

    def vrow(a):
        if not a.get("published"):
            return f'<tr><td style="padding:6px 0;color:#586187">{a["name"]}</td><td style="padding:6px 0;color:#586187">silent</td></tr>'
        lcol = LEAN_COLOR.get(a.get("lean", "neutral"), C["muted"])
        return (f'<tr><td style="padding:6px 10px 6px 0;color:#eaf0ff;font-weight:600;vertical-align:top;white-space:nowrap">{a["name"]} '
                f'<span style="color:{lcol};font-size:12px">· {a.get("lean")}</span></td>'
                f'<td style="padding:6px 0;color:#b8c2da;font-size:13px">{html.escape(a.get("summary",""))}</td></tr>')

    voices = "".join(vrow(a) for a in sorted(rep.get("analysts", []),
                     key=lambda x: ROSTER_ORDER.index(x["name"]) if x["name"] in ROSTER_ORDER else 9))
    narrative = md_to_html(rep.get("narrative_md", ""))

    html_doc = f"""<div style="background:#070b14;color:#eaf0ff;font-family:-apple-system,Segoe UI,Inter,sans-serif;padding:0;margin:0">
<div style="max-width:640px;margin:0 auto;padding:24px 22px">
  <div style="font-weight:800;letter-spacing:.3px;color:#eaf0ff;font-size:15px">Strategy² <span style="color:#8c98b8;font-weight:600;font-size:11px;letter-spacing:2px">NARRATIVE INTEL</span></div>
  <div style="color:#8c98b8;font:600 12px ui-monospace,monospace;margin-top:14px">{period['kind'].upper()} REPORT · {period['cover_start']} → {period['cover_end']}</div>
  <h1 style="font-size:21px;margin:4px 0 14px;color:#fff">{html.escape(period['title'])}</h1>
  <div style="display:inline-block;background:{dcol}1f;color:{dcol};border:1px solid {dcol}66;border-radius:10px;padding:9px 16px;font:800 16px ui-monospace,monospace;letter-spacing:1px">{DELTA_LABEL.get(delta, delta)}</div>
  <p style="color:#b8c2da;font-size:14px;line-height:1.6;margin:14px 0">{html.escape(rep.get('system_state',''))}</p>
  <table style="width:100%;border-collapse:collapse;margin:14px 0">
    <tr><td style="padding:10px 12px;background:rgba(255,255,255,.04);border-radius:10px;border:1px solid rgba(120,150,220,.16)">
      <span style="color:#8c98b8;font-size:11px;text-transform:uppercase;letter-spacing:1px">Hedge / top side</span><br>
      <b style="color:{VERDICT_COLOR.get(bear['verdict'],C['faint'])};font-size:15px">{bear['verdict']}</b>
      <span style="color:#8c98b8;font-size:12px"> — {html.escape(bear['note'])}</span></td></tr>
    <tr><td style="height:8px"></td></tr>
    <tr><td style="padding:10px 12px;background:rgba(255,255,255,.04);border-radius:10px;border:1px solid rgba(120,150,220,.16)">
      <span style="color:#8c98b8;font-size:11px;text-transform:uppercase;letter-spacing:1px">Buy-the-dip / bottom side</span><br>
      <b style="color:{VERDICT_COLOR.get(qf['verdict'],C['faint'])};font-size:15px">{qf['verdict']}</b>
      <span style="color:#8c98b8;font-size:12px"> — {html.escape(qf['note'])}</span></td></tr>
  </table>
  <h3 style="font-size:13px;color:#8c98b8;text-transform:uppercase;letter-spacing:1px;margin:18px 0 6px">The voices</h3>
  <table style="width:100%;border-collapse:collapse">{voices}</table>
  <div style="margin:20px 0;border-top:1px solid rgba(120,150,220,.16)"></div>
  <div style="font-size:14px;line-height:1.7;color:#dfe6fb">{narrative}</div>
  <div style="margin:18px 0;padding:14px 16px;background:rgba(74,168,255,.10);border:1px solid rgba(74,168,255,.2);border-radius:11px">
    <span style="color:#4aa8ff;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700">Bottom line</span><br>
    <span style="font-size:14px;color:#eef2ff;line-height:1.6">{html.escape(rep.get('bottom_line',''))}</span></div>
  <p style="margin:18px 0"><a href="{url}" style="background:linear-gradient(180deg,#4aa8ff,#2b6fd0);color:#fff;text-decoration:none;padding:11px 20px;border-radius:11px;font-weight:600;font-size:14px;display:inline-block">View the interactive report ↗</a></p>
  <p style="color:#586187;font-size:11px;line-height:1.6;margin-top:20px">Point-in-time narrative layer over the Strategy² v8.5 system. Calibrates conviction; does not generate signals. No hindsight used.</p>
</div></div>"""
    out = DOCS_INTEL / "email"
    out.mkdir(exist_ok=True)
    (out / f"{slug}.html").write_text(html_doc)
    return out / f"{slug}.html"


# ---------------------------------------------------------------------------
def main():
    os.chdir(Path(__file__).resolve().parent)
    DOCS_INTEL.mkdir(parents=True, exist_ok=True)
    (DOCS_INTEL / "data").mkdir(exist_ok=True)
    slugs = sorted((Path(p).stem.replace("final-", "")
                    for p in glob.glob(str(BUILD_DIR / "final-*.json"))), reverse=True)
    if not slugs:
        print("No final-*.json reports found in build/. Run generation first.")
        return
    cards = []
    for slug in slugs:
        # stamp generation time if absent
        fp = BUILD_DIR / f"final-{slug}.json"
        rep = json.loads(fp.read_text())
        rep.setdefault("_generated_at", datetime.datetime.now().strftime("%Y-%m-%d %H:%M CT"))
        fp.write_text(json.dumps(rep, indent=2))
        rep, period = render_report(slug)
        render_email(slug)
        cards.append((rep, period))
        print("rendered", slug)
    render_index(cards)
    print(f"index.html + {len(cards)} reports -> {DOCS_INTEL}")


if __name__ == "__main__":
    main()

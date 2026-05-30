"""Dashboard visualization. Matplotlib, dark theme, single PNG."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd
from datetime import datetime

from scoring import (
    score_mvrv_z, score_nupl, score_lth_trend, score_sopr,
    score_m2_trend, score_netliq_trend, score_dxy_trend,
    score_hy_oas, score_real_yield,
    score_mnav, score_mstr_btc_trend,
    score_funding, score_ssr,
    regime_color, regime_label,
)

# Dark palette
BG = "#0F1419"
PANEL_BG = "#1A1F2E"
TEXT = "#E0E0E0"
MUTED = "#7A8090"
ACCENT = "#4FC3F7"
GREEN = "#66BB6A"
RED = "#EF5350"
YELLOW = "#FFCA28"

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": PANEL_BG,
    "axes.edgecolor": MUTED,
    "axes.labelcolor": TEXT,
    "axes.titlecolor": TEXT,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "text.color": TEXT,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.family": "sans-serif",
    "font.size": 9,
})


def score_color(s):
    if s is None: return MUTED
    if s >= 80: return "#2E8B57"
    if s >= 60: return "#90EE90"
    if s >= 40: return "#F0E68C"
    if s >= 20: return "#FF8C00"
    return "#B22222"


def fmt_val(v, prec=2, suffix=""):
    if v is None: return "N/A"
    if isinstance(v, (int, float)):
        if abs(v) >= 1e9:
            return f"${v/1e9:.{prec}f}B{suffix}"
        if abs(v) >= 1e6:
            return f"${v/1e6:.{prec}f}M{suffix}"
        if abs(v) >= 1000:
            return f"{v:,.0f}{suffix}"
        return f"{v:.{prec}f}{suffix}"
    return str(v)


def draw_card(ax, title, value, sub_score, sub_label="", series=None,
              regime_bands=None, value_fmt=None, footnote=""):
    """Generic card with title, big value, sub-score chip, and mini chart."""
    ax.clear()
    ax.set_facecolor(PANEL_BG)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Title bar
    ax.text(0.03, 0.92, title, fontsize=10, color=TEXT, fontweight="bold", transform=ax.transAxes)
    if value is None:
        val_str = "N/A"
    else:
        try:
            val_str = value_fmt(value) if value_fmt else fmt_val(value)
        except Exception:
            val_str = "N/A"
    val_color = TEXT if value is not None else MUTED
    ax.text(0.03, 0.74, val_str, fontsize=18, color=val_color, fontweight="bold", transform=ax.transAxes)

    # Sub-score chip top-right
    if sub_score is not None:
        chip_color = score_color(sub_score)
        chip = FancyBboxPatch((0.78, 0.82), 0.18, 0.13,
                              boxstyle="round,pad=0.01",
                              facecolor=chip_color, edgecolor="none",
                              transform=ax.transAxes)
        ax.add_patch(chip)
        ax.text(0.87, 0.88, f"{int(sub_score)}",
                fontsize=14, color="#0F1419", fontweight="bold",
                ha="center", va="center", transform=ax.transAxes)
        if sub_label:
            ax.text(0.87, 0.78, sub_label, fontsize=7, color=MUTED,
                    ha="center", transform=ax.transAxes)

    # Mini chart in lower half
    if series is not None and not series.empty:
        chart_ax = ax.inset_axes([0.05, 0.08, 0.9, 0.45], transform=ax.transAxes)
        s = series.dropna()
        if len(s) > 365:
            s = s.iloc[-365:]
        chart_ax.plot(s.index, s.values, color=ACCENT, linewidth=1.5)
        chart_ax.fill_between(s.index, s.values, s.min(), alpha=0.15, color=ACCENT)
        chart_ax.set_facecolor(PANEL_BG)
        for spine in chart_ax.spines.values():
            spine.set_visible(False)
        chart_ax.tick_params(axis='both', colors=MUTED, labelsize=6)
        chart_ax.set_xticks([s.index[0], s.index[-1]])
        chart_ax.set_xticklabels([s.index[0].strftime("%b"), s.index[-1].strftime("%b")])

        # Regime band shading
        if regime_bands:
            ymin, ymax = chart_ax.get_ylim()
            for low, high, color in regime_bands:
                lo = max(low, ymin) if low is not None else ymin
                hi = min(high, ymax) if high is not None else ymax
                if hi > lo:
                    chart_ax.axhspan(lo, hi, color=color, alpha=0.12, zorder=0)

    if footnote:
        ax.text(0.03, 0.02, footnote, fontsize=7, color=MUTED, transform=ax.transAxes, style="italic")


def draw_score_gauge(ax, composite, delta_1w, history):
    """Big score panel: number + delta + sparkline."""
    ax.clear()
    ax.set_facecolor(PANEL_BG)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    color = regime_color(composite)
    label = regime_label(composite)

    # Big score number
    ax.text(0.5, 0.70, f"{composite if composite is not None else 'N/A'}",
            fontsize=64, color=color, fontweight="bold",
            ha="center", va="center", transform=ax.transAxes)
    ax.text(0.5, 0.40, "RISK SCORE  (0–100)", fontsize=9, color=MUTED,
            ha="center", transform=ax.transAxes)
    ax.text(0.5, 0.30, label, fontsize=10, color=color, fontweight="bold",
            ha="center", transform=ax.transAxes)

    # Delta
    if delta_1w is not None:
        sign = "+" if delta_1w >= 0 else ""
        dcolor = GREEN if delta_1w >= 0 else RED
        ax.text(0.5, 0.18, f"Δ 1w: {sign}{delta_1w:.1f}", fontsize=10, color=dcolor,
                ha="center", transform=ax.transAxes)
    else:
        ax.text(0.5, 0.18, "Δ 1w: first run", fontsize=9, color=MUTED,
                ha="center", transform=ax.transAxes)

    # Sparkline of last 12 scores
    if history is not None and len(history) > 1:
        h = history.tail(12)
        spark_ax = ax.inset_axes([0.10, 0.02, 0.80, 0.13], transform=ax.transAxes)
        spark_ax.plot(range(len(h)), h["composite"].values, color=color, linewidth=2, marker="o", markersize=3)
        spark_ax.set_facecolor(PANEL_BG)
        spark_ax.set_xticks([]); spark_ax.set_yticks([])
        for spine in spark_ax.spines.values():
            spine.set_visible(False)


def draw_header(ax, results, derived, run_ts):
    ax.clear()
    ax.set_facecolor(BG)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.text(0.005, 0.78, "NASSIM CONFIDENCE DASHBOARD",
            fontsize=18, color=TEXT, fontweight="bold", transform=ax.transAxes)
    ax.text(0.005, 0.45, "v7.8d strategy confidence calibrator · diagnostic only",
            fontsize=9, color=MUTED, transform=ax.transAxes, style="italic")
    ax.text(0.005, 0.18, f"Run: {run_ts}",
            fontsize=8, color=MUTED, transform=ax.transAxes)

    # Snapshot stats: BTC, MSTR, mNAV, MSTR BTC holdings
    btc = results["btc_price"]["value"]
    mstr = results["mstr"]["value"]
    mnav = derived.get("mnav")
    holdings = results["mstr_btc_holdings"]["value"]
    holdings_stale = results["mstr_btc_holdings"]["stale"]
    iv = results["mstr_iv"]["value"]

    snaps = [
        ("BTC", f"${btc:,.0f}" if btc else "N/A"),
        ("MSTR", f"${mstr:,.2f}" if mstr else "N/A"),
        ("mNAV", f"{mnav:.2f}x" if mnav else "N/A"),
        ("MSTR BTC", f"{holdings:,.0f}{'*' if holdings_stale else ''}" if holdings else "N/A"),
        ("ATM IV", f"{iv*100:.0f}%" if iv else "N/A"),
    ]
    x0 = 0.40
    dx = 0.12
    for i, (label, val) in enumerate(snaps):
        x = x0 + i*dx
        ax.text(x, 0.62, label, fontsize=8, color=MUTED, transform=ax.transAxes, ha="center")
        ax.text(x, 0.25, val, fontsize=13, color=TEXT, fontweight="bold",
                transform=ax.transAxes, ha="center")


def draw_footer(ax, synthesis_lines, caveats):
    ax.clear()
    ax.set_facecolor(BG)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    # Synthesis box
    box = FancyBboxPatch((0.005, 0.40), 0.99, 0.55,
                         boxstyle="round,pad=0.01",
                         facecolor=PANEL_BG, edgecolor=MUTED, linewidth=0.5,
                         transform=ax.transAxes)
    ax.add_patch(box)
    ax.text(0.012, 0.86, "SYNTHESIS", fontsize=9, color=ACCENT, fontweight="bold", transform=ax.transAxes)
    for i, line in enumerate(synthesis_lines[:3]):
        ax.text(0.012, 0.70 - i*0.13, line, fontsize=10, color=TEXT, transform=ax.transAxes)

    ax.text(0.005, 0.32, "Caveats:", fontsize=7, color=MUTED, fontweight="bold", transform=ax.transAxes)
    for i, c in enumerate(caveats[:4]):
        ax.text(0.005, 0.22 - i*0.06, f"  • {c}", fontsize=6.5, color=MUTED, transform=ax.transAxes)


def render_dashboard(png_path, results, derived, score, delta_1w, synthesis, history):
    fig = plt.figure(figsize=(24, 14), facecolor=BG)

    # Layout: 6 rows × 5 cols grid
    # row 0: header (across)
    # row 1: score gauge (col 0-1) + Cycle phase cards (col 2-4)
    # row 2: Cycle cards continued (col 0-3) + Macro card 1 (col 4)
    # row 3: Macro cards
    # row 4: Risk + MSTR + Tactical
    # row 5: footer (across)

    gs = fig.add_gridspec(20, 24, hspace=0.6, wspace=0.4,
                          left=0.015, right=0.985, top=0.97, bottom=0.02)

    # Header row 0-1
    ax_header = fig.add_subplot(gs[0:2, :])
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M %Z")
    draw_header(ax_header, results, derived, run_ts)

    # Score gauge: rows 2-7, cols 0-5
    ax_score = fig.add_subplot(gs[2:8, 0:5])
    draw_score_gauge(ax_score, score["composite"], delta_1w, history)

    # Cycle phase: 4 cards (rows 2-7, cols 5-24)
    # MVRV-Z
    ax = fig.add_subplot(gs[2:5, 5:11])
    draw_card(ax, "MVRV Z-Score", results["mvrv_z"]["value"],
              score["sub_scores"]["mvrv_z"],
              series=results["mvrv_z"]["series"], value_fmt=lambda v: f"{v:.2f}")
    # NUPL
    ax = fig.add_subplot(gs[2:5, 11:17])
    draw_card(ax, "NUPL", results["nupl"]["value"],
              score["sub_scores"]["nupl"],
              series=results["nupl"]["series"], value_fmt=lambda v: f"{v:.3f}")
    # SOPR
    ax = fig.add_subplot(gs[2:5, 17:24])
    draw_card(ax, "SOPR (7d MA)", results["sopr"]["value"],
              score["sub_scores"]["sopr"],
              series=results["sopr"]["series"], value_fmt=lambda v: f"{v:.4f}")
    # LTH supply trend
    ax = fig.add_subplot(gs[5:8, 5:11])
    lth_val = derived.get("lth_90d_pct")
    draw_card(ax, "LTH Supply (90d Δ%)", lth_val,
              score["sub_scores"]["lth_trend"],
              series=results["lth"]["series"],
              value_fmt=lambda v: f"{v:+.2f}%" if v is not None else "N/A",
              footnote=("source unavailable on free tier" if lth_val is None else ""))
    # M2 trend
    ax = fig.add_subplot(gs[5:8, 11:17])
    draw_card(ax, "US M2 (12w Δ%)", derived.get("m2_12w_pct"),
              score["sub_scores"]["m2_trend"],
              series=results["m2"]["series"],
              value_fmt=lambda v: f"{v:+.2f}%" if v is not None else "N/A",
              footnote=f"latest: ${results['m2']['value']/1000:.1f}T @ {results['m2']['timestamp'].strftime('%Y-%m')}")
    # Net Liquidity trend
    ax = fig.add_subplot(gs[5:8, 17:24])
    draw_card(ax, "Net Liquidity (4w Δ%)", derived.get("netliq_4w_pct"),
              score["sub_scores"]["netliq_trend"],
              series=results["netliq"]["series"],
              value_fmt=lambda v: f"{v:+.2f}%" if v is not None else "N/A",
              footnote=f"latest: ${results['netliq']['value']/1000:.2f}T")

    # Row 8-13: Macro continued + Risk + MSTR + Tactical
    # DXY
    ax = fig.add_subplot(gs[8:11, 0:6])
    draw_card(ax, "DXY (50d Δ%, inverse)", derived.get("dxy_50d_pct"),
              score["sub_scores"]["dxy_trend"],
              series=results["dxy"]["series"],
              value_fmt=lambda v: f"{v:+.2f}%" if v is not None else "N/A",
              footnote=f"current: {results['dxy']['value']:.2f}")
    # HY OAS
    ax = fig.add_subplot(gs[8:11, 6:12])
    draw_card(ax, "HY OAS Spread", results["hy_oas"]["value"],
              score["sub_scores"]["hy_oas"],
              series=results["hy_oas"]["series"],
              value_fmt=lambda v: f"{v:.2f}%")
    # 10Y Real Yield
    ax = fig.add_subplot(gs[8:11, 12:18])
    draw_card(ax, "10Y Real Yield (TIPS)", results["real_yield"]["value"],
              score["sub_scores"]["real_yield"],
              series=results["real_yield"]["series"],
              value_fmt=lambda v: f"{v:.2f}%")
    # mNAV
    ax = fig.add_subplot(gs[8:11, 18:24])
    draw_card(ax, "MSTR mNAV", derived.get("mnav"),
              score["sub_scores"]["mnav"],
              series=None,
              value_fmt=lambda v: f"{v:.2f}x",
              footnote=f"current: {derived.get('mnav'):.2f}x · holdings flag=*{'live' if not results['mstr_btc_holdings']['stale'] else 'fallback'}")

    # Row 11-13: MSTR/BTC + Funding + SSR
    ax = fig.add_subplot(gs[11:14, 0:8])
    mbtc_series = derived.get("mstr_btc_ratio_series", pd.Series(dtype=float))
    mbtc_pct = derived.get("mstr_btc_50d_pct")
    if mbtc_pct is not None and mbtc_pct > 0:
        direction = f"MSTR outperforming BTC by {mbtc_pct:.1f}% over 50d → mNAV expanding (worse entry)"
    elif mbtc_pct is not None:
        direction = f"MSTR compressing vs BTC by {abs(mbtc_pct):.1f}% over 50d → mNAV compressing (better entry)"
    else:
        direction = ""
    draw_card(ax, "MSTR / BTC 50d Trend  (inverse: falling = bullish)",
              mbtc_pct,
              score["sub_scores"]["mstr_btc_trend"],
              series=mbtc_series,
              value_fmt=lambda v: f"{v:+.2f}%" if v is not None else "N/A",
              footnote=direction)
    # Funding
    ax = fig.add_subplot(gs[11:14, 8:16])
    draw_card(ax, "BTC Perp Funding (ann %)", results["funding"]["value"],
              score["sub_scores"]["funding"],
              series=results["funding"]["series"],
              value_fmt=lambda v: f"{v:+.2f}%")
    # SSR
    ax = fig.add_subplot(gs[11:14, 16:24])
    ssr_series = None
    if results["btc_mcap"]["series"].size and results["stables"]["series"].size:
        idx = results["btc_mcap"]["series"].index.intersection(results["stables"]["series"].index)
        if len(idx) > 0:
            ssr_series = (results["btc_mcap"]["series"].reindex(idx) /
                          results["stables"]["series"].reindex(idx).replace(0, np.nan)).dropna()
    draw_card(ax, "Stablecoin Supply Ratio (SSR)", derived.get("ssr"),
              score["sub_scores"]["ssr"],
              series=ssr_series,
              value_fmt=lambda v: f"{v:.2f}")

    # Footer (rows 14-19)
    ax_footer = fig.add_subplot(gs[14:20, :])
    caveats = [
        "Score is backward-looking. No indicator predicts the future.",
        "Weights hand-calibrated, not regression-optimized. N=3–4 BTC cycles for calibration.",
        "Does NOT capture geopolitical / black-swan risk — that's the qualitative override layer.",
        "Score changes <5pts are noise. >15pts week-over-week is signal.",
    ]
    draw_footer(ax_footer, synthesis, caveats)

    fig.savefig(png_path, dpi=110, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return png_path

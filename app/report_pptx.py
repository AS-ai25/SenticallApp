"""PowerPoint export of the analytics dashboard + AI insights."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

from . import config  # noqa: E402
from .analytics import SENTIMENT_ORDER  # noqa: E402
from .schemas import ReportInsights  # noqa: E402

COLORS = {"Positive": "#3ec46d", "Neutral": "#f2a93b", "Negative": "#e5484d"}
BG, AX, TXT = "#15171b", "#1d2026", "#e6e8ec"


def _style(ax, title: str):
    ax.set_facecolor(AX)
    ax.set_title(title, color=TXT, pad=10)
    ax.tick_params(colors=TXT)
    for sp in ax.spines.values():
        sp.set_color("#3a3f49")
    ax.yaxis.label.set_color(TXT)
    ax.xaxis.label.set_color(TXT)


def _bar(group: dict, path: Path):
    cats = group["categories"]
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    fig.patch.set_facecolor(BG)
    width = 0.25
    for i, s in enumerate(SENTIMENT_ORDER):
        xs = [p + i * width for p in range(len(cats))]
        vals = group["series"][s]
        bars = ax.bar(xs, vals, width=width, color=COLORS[s], label=s)
        for b, c in zip(bars, cats):
            suffix = group["letters"].get(c, {}).get(s, "")
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1,
                    f"{b.get_height():.0f}%{(' ' + suffix) if suffix else ''}",
                    ha="center", va="bottom", fontsize=7, color=TXT,
                    fontweight="bold" if suffix else "normal")
    ax.set_xticks([p + width for p in range(len(cats))])
    ax.set_xticklabels(cats, color=TXT, fontsize=8)
    ax.set_ylim(0, 110)
    ax.set_ylabel("Percent (%)")
    _style(ax, f"Sentiment by {group['label']}")
    ax.legend(facecolor=AX, edgecolor="#3a3f49", labelcolor=TXT, fontsize=7)
    fig.tight_layout()
    fig.savefig(path, facecolor=BG, dpi=150)
    plt.close(fig)


def _line(t: dict, title: str, path: Path):
    fig, ax = plt.subplots(figsize=(6.5, 2.4))
    fig.patch.set_facecolor(BG)
    for s in SENTIMENT_ORDER:
        ys = [v if v is not None else float("nan") for v in t["series"][s]]
        ax.plot(t["categories"], ys, marker="o", markersize=3, linewidth=1.5, color=COLORS[s], label=s)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Percent (%)")
    ax.tick_params(axis="x", labelsize=7)
    _style(ax, title)
    ax.legend(facecolor=AX, edgecolor="#3a3f49", labelcolor=TXT, fontsize=7)
    fig.tight_layout()
    fig.savefig(path, facecolor=BG, dpi=150)
    plt.close(fig)


def _pie(overall: dict, path: Path):
    fig, ax = plt.subplots(figsize=(4, 4))
    fig.patch.set_facecolor(BG)
    vals = [overall.get(s, 0) for s in SENTIMENT_ORDER]
    wedges, texts, autotexts = ax.pie(vals, labels=SENTIMENT_ORDER, autopct="%1.0f%%",
                                      colors=[COLORS[s] for s in SENTIMENT_ORDER],
                                      startangle=90, wedgeprops=dict(width=0.5))
    for t in texts + autotexts:
        t.set_color(TXT)
        t.set_fontsize(9)
    ax.set_title("Overall Sentiment", color=TXT)
    fig.tight_layout()
    fig.savefig(path, facecolor=BG, dpi=150)
    plt.close(fig)


def _chunks(items: List[str], n: int = 4):
    return [items[i:i + n] for i in range(0, len(items), n)]


def _bullets_slides(prs, title: str, items: List[str]):
    for idx, chunk in enumerate(_chunks(items)):
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = f"{title} ({idx + 1})" if len(items) > 4 else title
        tf = slide.placeholders[1].text_frame
        tf.clear()
        for line in chunk:
            p = tf.add_paragraph()
            p.text = line
            p.font.size = Pt(16)


def build_pptx(dash: dict, insights: ReportInsights | None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = config.EXPORT_DIR / f"Senticall_Report_{stamp}.pptx"
    tmp = config.EXPORT_DIR / f"_charts_{stamp}"
    tmp.mkdir(exist_ok=True)

    pie = tmp / "pie.png"
    _pie(dash["overall_sentiment"], pie)
    bars = []
    for col in ("gender", "ageGroup", "incomeGroup2", "education"):
        p = tmp / f"bar_{col}.png"
        _bar(dash["by_group"][col], p)
        bars.append(p)
    lines = []
    for key, title in (("month", "Sentiment by Month"), ("day_of_week", "Sentiment by Day of Week"), ("hour", "Sentiment by Hour")):
        p = tmp / f"line_{key}.png"
        _line(dash["by_time"][key], title, p)
        lines.append(p)

    prs = Presentation()
    W = Inches(10)

    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Senticall - Customer Service Intelligence"
    k = dash["kpis"]
    s.placeholders[1].text = (
        f"{k['total_calls']} calls analysed | {k['negative_pct']}% negative | "
        f"avg priority {k['avg_priority']} | {k['safety_alerts']} safety alerts\n"
        f"Generated {datetime.now():%d %b %Y %H:%M}"
    )

    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Overall Customer Sentiment"
    s.shapes.add_picture(str(pie), (W - Inches(4.5)) / 2, Inches(1.5), width=Inches(4.5), height=Inches(4.5))

    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Sentiment by Demographics"
    bw, bh = Inches(4.4), Inches(2.7)
    for i, img in enumerate(bars):
        left = Inches(0.6) + (i % 2) * (bw + Inches(0.1))
        top = Inches(1.4) + (i // 2) * (bh + Inches(0.1))
        s.shapes.add_picture(str(img), left, top, width=bw, height=bh)

    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Sentiment Over Time"
    for i, img in enumerate(lines):
        s.shapes.add_picture(str(img), (W - Inches(6.5)) / 2, Inches(1.4 + i * 2.0), width=Inches(6.5), height=Inches(1.9))

    if insights:
        summary_lines = [x.strip() + "." for x in insights.executive_summary.replace(". ", ".|").split("|") if x.strip()]
        summary_lines = [x.replace("..", ".") for x in summary_lines]
        _bullets_slides(prs, "Executive Summary", summary_lines)
        _bullets_slides(prs, "Key Findings", insights.key_findings)
        _bullets_slides(prs, "Staffing Recommendations", insights.staffing_recommendations)
        _bullets_slides(prs, "Demographic Support Insights", insights.demographic_support_insights)
        _bullets_slides(prs, "Technical Friction Areas", insights.technical_friction_areas)
        _bullets_slides(prs, "Operational Priorities", insights.operational_priorities)
        plan_lines = [x.strip() + "." for x in insights.executive_action_plan.replace(". ", ".|").split("|") if x.strip()]
        plan_lines = [x.replace("..", ".") for x in plan_lines]
        _bullets_slides(prs, "Executive Action Plan", plan_lines)

    prs.save(out)
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    return out

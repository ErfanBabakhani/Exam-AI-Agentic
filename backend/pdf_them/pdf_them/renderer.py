from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

PAGE_W, PAGE_H = A4

# -----------------------------------------------------------------------------
# Theme
# -----------------------------------------------------------------------------
THEME = {
    "ink": "#111827",
    "muted": "#64748B",
    "paper": "#F8FAFC",
    "card": "#FFFFFF",
    "border": "#E2E8F0",
    "primary": "#6D5DFB",
    "primary_dark": "#312E81",
    "cyan": "#22D3EE",
    "pink": "#EC4899",
    "green": "#10B981",
    "amber": "#F59E0B",
    "red": "#EF4444",
    "blue_soft": "#EEF2FF",
    "green_soft": "#ECFDF5",
    "amber_soft": "#FFFBEB",
    "red_soft": "#FEF2F2",
    "cyan_soft": "#ECFEFF",
}


def C(name: str) -> colors.Color:
    return HexColor(THEME[name])


@dataclass
class FontPack:
    regular: str = "Helvetica"
    bold: str = "Helvetica-Bold"
    mono: str = "Courier"


def _register_fonts() -> FontPack:
    """Register a unicode-friendly font if present; fallback to Helvetica.

    We do not ship or expose font files. This simply uses common system fonts if
    they exist on the deployment machine.
    """
    candidates = [
        ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("NotoSans", "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "NotoSans-Bold", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
        ("LiberationSans", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf", "LiberationSans-Bold", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    ]
    for reg_name, reg_path, bold_name, bold_path in candidates:
        if os.path.exists(reg_path) and os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont(reg_name, reg_path))
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
                return FontPack(reg_name, bold_name, "Courier")
            except Exception:
                pass
    return FontPack()


FONTS = _register_fonts()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    replacements = {
        "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u2019": "'", "\u2018": "'",
        "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00a0": " ",
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    # Repair common mojibake seen in copied PDF text.
    s = s.replace("â", "-").replace("â", "≈").replace("â«", "∫").replace("â", "∈")
    s = s.replace("˛‚", "θ")
    # Clean repeated words from generated rationales.
    s = re.sub(r"\bshows\s+shows\b", "shows", s, flags=re.I)
    s = re.sub(r"\bpage\s+(\d+)\s+shows\s+page\s+\1\s+shows\b", r"page \1 shows", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _escape(text: Any) -> str:
    s = _safe_text(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # Split common exported separators but keep concise paragraphs intact.
        parts = [p.strip() for p in re.split(r"\s*\|\s*|\n+", value) if p.strip()]
        return parts if parts else [value]
    if isinstance(value, (list, tuple, set)):
        out: List[str] = []
        for item in value:
            if isinstance(item, Mapping):
                page = item.get("page") or item.get("page_number")
                ev = item.get("evidence") or item.get("text") or item.get("summary") or item
                prefix = f"Page {page}: " if page not in (None, "") else ""
                out.append(prefix + _safe_text(ev))
            else:
                out.append(_safe_text(item))
        return [x for x in out if x]
    return [_safe_text(value)]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            m = re.search(r"-?\d+(?:\.\d+)?", value)
            return float(m.group(0)) if m else default
        return float(value)
    except Exception:
        return default


def _pct(score: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    return max(0.0, min(1.0, score / maximum))


def _score_color(score: float, maximum: float) -> colors.Color:
    p = _pct(score, maximum)
    if p >= 0.85:
        return C("green")
    if p >= 0.6:
        return C("amber")
    return C("red")


def _score_soft_color(score: float, maximum: float) -> colors.Color:
    p = _pct(score, maximum)
    if p >= 0.85:
        return C("green_soft")
    if p >= 0.6:
        return C("amber_soft")
    return C("red_soft")


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.strip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def draw_linear_gradient(canv, x: float, y: float, w: float, h: float, left: str, right: str, steps: int = 90) -> None:
    r1, g1, b1 = _hex_to_rgb(left)
    r2, g2, b2 = _hex_to_rgb(right)
    step_w = w / steps
    for i in range(steps):
        t = i / max(1, steps - 1)
        col = colors.Color(_lerp(r1, r2, t) / 255, _lerp(g1, g2, t) / 255, _lerp(b1, b2, t) / 255)
        canv.setFillColor(col)
        canv.setStrokeColor(col)
        canv.rect(x + i * step_w, y, step_w + 0.8, h, stroke=0, fill=1)


def draw_round_rect(canv, x, y, w, h, fill, stroke=None, radius=12, width=0.6):
    canv.saveState()
    canv.setFillColor(fill)
    if stroke:
        canv.setStrokeColor(stroke)
        canv.setLineWidth(width)
        canv.roundRect(x, y, w, h, radius, stroke=1, fill=1)
    else:
        canv.roundRect(x, y, w, h, radius, stroke=0, fill=1)
    canv.restoreState()


# -----------------------------------------------------------------------------
# Flowables
# -----------------------------------------------------------------------------
class CoverFlowable(Flowable):
    def __init__(self, report: Mapping[str, Any], width: float, height: float = 190):
        super().__init__()
        self.report = report
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        x, y, w, h = 0, 0, self.width, self.height
        draw_round_rect(c, x, y, w, h, C("primary_dark"), radius=24)
        draw_linear_gradient(c, x, y, w, h, "#312E81", "#EC4899", steps=120)
        # overlay depth
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.06))
        c.circle(x + w * 0.83, y + h * 0.64, 86, stroke=0, fill=1)
        c.circle(x + w * 0.16, y + h * 0.12, 110, stroke=0, fill=1)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.11))
        c.roundRect(x + 20, y + h - 64, 116, 30, 14, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONTS.bold, 10)
        c.drawString(x + 38, y + h - 54, _safe_text(self.report.get("brand", "Zanista AI")))

        title = _safe_text(self.report.get("title", "AI Grading Report"))
        subtitle = _safe_text(self.report.get("subtitle", "Evaluation summary and rubric-linked feedback"))
        c.setFillColor(colors.white)
        c.setFont(FONTS.bold, 28)
        c.drawString(x + 24, y + 92, title[:45])
        c.setFont(FONTS.regular, 11)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.82))
        c.drawString(x + 25, y + 72, subtitle[:82])

        # score donut
        runs = list(self.report.get("runs", []) or [])
        total = sum(_num(r.get("score", r.get("total_score", 0))) for r in runs)
        max_total = sum(_num(r.get("max_score", r.get("max_total", 10)), 10) for r in runs) or 1
        p = _pct(total, max_total)
        cx, cy, r = x + w - 76, y + 83, 43
        c.setStrokeColor(colors.Color(1, 1, 1, alpha=0.25))
        c.setLineWidth(8)
        c.circle(cx, cy, r, stroke=1, fill=0)
        c.setStrokeColor(colors.white)
        c.setLineWidth(8)
        start = 90
        c.arc(cx-r, cy-r, cx+r, cy+r, start, start - 360 * p)
        c.setFillColor(colors.white)
        c.setFont(FONTS.bold, 20)
        score_txt = f"{round(total, 1):g}"
        c.drawCentredString(cx, cy + 2, score_txt)
        c.setFont(FONTS.regular, 8)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.78))
        c.drawCentredString(cx, cy - 13, f"of {round(max_total, 1):g}")

        gen = _safe_text(self.report.get("generated_at", ""))
        c.setFont(FONTS.regular, 8.5)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.72))
        c.drawString(x + 25, y + 24, f"Generated: {gen}" if gen else "Generated report")


class StatCards(Flowable):
    def __init__(self, stats: Sequence[Tuple[str, str, str]], width: float):
        super().__init__()
        self.stats = list(stats)
        self.width = width
        self.height = 62

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        n = len(self.stats)
        gap = 10
        card_w = (self.width - gap * (n - 1)) / n
        for i, (label, value, color_name) in enumerate(self.stats):
            x = i * (card_w + gap)
            y = 0
            draw_round_rect(c, x + 1.5, y - 1.5, card_w, self.height, colors.Color(0, 0, 0, alpha=0.05), radius=14)
            draw_round_rect(c, x, y, card_w, self.height, colors.white, C("border"), radius=14)
            c.setFillColor(C(color_name))
            c.roundRect(x + 14, y + self.height - 22, 30, 7, 3, stroke=0, fill=1)
            c.setFillColor(C("ink"))
            c.setFont(FONTS.bold, 17)
            c.drawString(x + 14, y + 22, value)
            c.setFillColor(C("muted"))
            c.setFont(FONTS.regular, 8.5)
            c.drawString(x + 14, y + 9, label.upper())


class RunHeaderCard(Flowable):
    def __init__(self, run: Mapping[str, Any], width: float):
        super().__init__()
        self.run = run
        self.width = width
        self.height = 108

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        x, y, w, h = 0, 0, self.width, self.height
        score = _num(self.run.get("score", self.run.get("total_score", 0)))
        max_score = _num(self.run.get("max_score", self.run.get("max_total", 10)), 10)
        draw_round_rect(c, x + 1.4, y - 1.4, w, h, colors.Color(0, 0, 0, alpha=0.04), radius=18)
        draw_round_rect(c, x, y, w, h, colors.white, C("border"), radius=18)
        # accent strip
        draw_linear_gradient(c, x, y + h - 7, w, 7, "#6D5DFB", "#22D3EE", 80)
        c.setFillColor(C("ink"))
        c.setFont(FONTS.bold, 15)
        student = _safe_text(self.run.get("student_file", self.run.get("student", "Student answer")))
        c.drawString(x + 18, y + h - 30, student[:55])
        c.setFillColor(C("muted"))
        c.setFont(FONTS.regular, 8.8)
        exam = _safe_text(self.run.get("exam_file", self.run.get("exam", "")))
        status = _safe_text(self.run.get("status", ""))
        duration = _safe_text(self.run.get("duration", ""))
        c.drawString(x + 18, y + h - 47, f"Exam: {exam[:45]}  •  Status: {status}  •  Duration: {duration}")
        created = _safe_text(self.run.get("created", ""))
        completed = _safe_text(self.run.get("completed", ""))
        c.drawString(x + 18, y + h - 63, f"Created: {created}  •  Completed: {completed}")
        message = _safe_text(self.run.get("message", ""))
        if message:
            c.drawString(x + 18, y + h - 79, f"Message: {message[:78]}")
        # score pill
        pill_w, pill_h = 100, 42
        px, py = x + w - pill_w - 18, y + 25
        draw_round_rect(c, px, py, pill_w, pill_h, _score_soft_color(score, max_score), None, radius=18)
        c.setFillColor(_score_color(score, max_score))
        c.setFont(FONTS.bold, 18)
        c.drawCentredString(px + pill_w/2, py + 19, f"{score:g}/{max_score:g}")
        c.setFont(FONTS.regular, 7.5)
        c.drawCentredString(px + pill_w/2, py + 7, "SCORE")


class SectionLabel(Flowable):
    def __init__(self, title: str, color_name: str, width: float):
        super().__init__()
        self.title = title
        self.color_name = color_name
        self.width = width
        self.height = 22

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        col = C(self.color_name)
        c.setFillColor(col)
        c.roundRect(0, 4, 7, 7, 3.5, stroke=0, fill=1)
        c.setFillColor(C("ink"))
        c.setFont(FONTS.bold, 9.5)
        c.drawString(13, 3, self.title.upper())


class QuestionTitle(Flowable):
    def __init__(self, q: Mapping[str, Any], width: float):
        super().__init__()
        self.q = q
        self.width = width
        self.height = 42

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        score = _num(self.q.get("score", self.q.get("awarded_marks", 0)))
        max_score = _num(self.q.get("max_score", self.q.get("max_marks", 5)), 5)
        n = _safe_text(self.q.get("number", self.q.get("question_number", "?")))
        c.setFillColor(C("ink"))
        c.setFont(FONTS.bold, 16)
        c.drawString(0, 15, f"Question {n}")
        # score pill
        col = _score_color(score, max_score)
        c.setFillColor(_score_soft_color(score, max_score))
        c.roundRect(self.width - 78, 9, 78, 24, 12, stroke=0, fill=1)
        c.setFillColor(col)
        c.setFont(FONTS.bold, 11)
        c.drawCentredString(self.width - 39, 16, f"{score:g}/{max_score:g}")


class Divider(Flowable):
    def __init__(self, width: float, color_name: str = "border"):
        super().__init__()
        self.width = width
        self.height = 10
        self.color_name = color_name

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        self.canv.setStrokeColor(C(self.color_name))
        self.canv.setLineWidth(0.7)
        self.canv.line(0, 5, self.width, 5)


# -----------------------------------------------------------------------------
# Styles and story builders
# -----------------------------------------------------------------------------
def styles() -> Mapping[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName=FONTS.regular, fontSize=9.2, leading=13.2,
            textColor=C("ink"), spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontName=FONTS.regular, fontSize=8.2, leading=11.5,
            textColor=C("muted"), spaceAfter=2,
        ),
        "muted": ParagraphStyle(
            "muted", parent=base["BodyText"], fontName=FONTS.regular, fontSize=8.5, leading=11.8,
            textColor=C("muted"),
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName=FONTS.bold, fontSize=15, leading=18,
            textColor=C("ink"), spaceBefore=4, spaceAfter=8,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["BodyText"], fontName=FONTS.regular, fontSize=8.7, leading=12,
            leftIndent=10, firstLineIndent=-6, bulletIndent=0, textColor=C("ink"), spaceAfter=2,
        ),
        "evidence": ParagraphStyle(
            "evidence", parent=base["BodyText"], fontName=FONTS.regular, fontSize=8.2, leading=11.3,
            textColor=C("muted"), leftIndent=0, spaceAfter=3,
        ),
    }


def para(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_escape(text), style)


def bullets(items: Sequence[str], style: ParagraphStyle, max_items: Optional[int] = None) -> List[Paragraph]:
    flow: List[Paragraph] = []
    data = list(items)[:max_items] if max_items else list(items)
    for item in data:
        if not _safe_text(item):
            continue
        flow.append(Paragraph("• " + _escape(item), style))
    return flow


def section_block(title: str, color_name: str, content: Sequence[Any], width: float) -> List[Any]:
    if not content:
        return []
    return [Spacer(1, 4), SectionLabel(title, color_name, width), *content]


def _question_to_flowables(q: Mapping[str, Any], width: float, st: Mapping[str, ParagraphStyle]) -> List[Any]:
    score = _num(q.get("score", q.get("awarded_marks", 0)))
    max_score = _num(q.get("max_score", q.get("max_marks", 5)), 5)
    correct = _as_list(q.get("correct", q.get("correct_elements")))
    missing = _as_list(q.get("missing", q.get("missing_or_incorrect_elements")))
    improve = _as_list(q.get("improve", q.get("improvement_suggestions")))
    visible = _as_list(q.get("visible_evidence"))
    evidence_used = _as_list(q.get("evidence_used", q.get("evidence_summaries")))
    rationale = _safe_text(q.get("rationale", q.get("score_rationale", "")))

    # Clean full-score missing filler.
    if score >= max_score and (not missing or any("no substantive" in x.lower() for x in missing)):
        missing = []

    content: List[Any] = [QuestionTitle(q, width), Spacer(1, 2)]
    if rationale:
        content += [SectionLabel("Rationale", "primary", width), para(rationale, st["body"])]
    content += section_block("What was correct", "green", bullets(correct, st["bullet"], 5), width)
    content += section_block("Missing or incorrect", "red", bullets(missing, st["bullet"], 5), width)
    content += section_block("How to improve", "amber", bullets(improve, st["bullet"], 4), width)
    content += section_block("Visible evidence", "cyan", bullets(visible, st["evidence"], 4), width)
    content += section_block("Evidence used", "primary", bullets(evidence_used, st["evidence"], 4), width)
    return [Card(content, width=width, accent=_score_color(score, max_score))]


class Card(Flowable):
    """Container that draws a rounded white card around an inner flowable list."""
    def __init__(self, flowables: Sequence[Any], width: float, accent: Optional[colors.Color] = None, padding: float = 14):
        super().__init__()
        self.flowables = list(flowables)
        self.width = width
        self.padding = padding
        self.accent = accent or C("primary")
        self._table: Optional[Table] = None
        self._height = 0

    def wrap(self, availWidth, availHeight):
        inner_w = self.width - 2 * self.padding
        self._table = Table([[self.flowables]], colWidths=[inner_w])
        self._table.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), self.padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), self.padding),
            ("TOPPADDING", (0, 0), (-1, -1), self.padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), self.padding),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        _, h = self._table.wrapOn(self.canv, inner_w, availHeight)
        self._height = h
        return self.width, h

    def draw(self):
        c = self.canv
        h = self._height
        draw_round_rect(c, 1.2, -1.2, self.width, h, colors.Color(0, 0, 0, alpha=0.035), radius=16)
        draw_round_rect(c, 0, 0, self.width, h, colors.white, C("border"), radius=16)
        c.setFillColor(self.accent)
        c.roundRect(0, 0, 5, h, 2.5, stroke=0, fill=1)
        if self._table:
            self._table.drawOn(c, 0, 0)


# -----------------------------------------------------------------------------
# Pages
# -----------------------------------------------------------------------------
def _on_page(canv, doc):
    canv.saveState()
    # background
    canv.setFillColor(C("paper"))
    canv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    # top tiny gradient line
    draw_linear_gradient(canv, 0, PAGE_H - 5, PAGE_W, 5, "#6D5DFB", "#22D3EE", 90)
    # footer
    canv.setFont(FONTS.regular, 7.5)
    canv.setFillColor(C("muted"))
    canv.drawString(34, 18, "Zanista AI • Grading Export")
    canv.drawRightString(PAGE_W - 34, 18, f"Page {doc.page}")
    canv.restoreState()


def _summary_stats(report: Mapping[str, Any]) -> List[Tuple[str, str, str]]:
    runs = list(report.get("runs", []) or [])
    total_runs = len(runs)
    total_score = sum(_num(r.get("score", r.get("total_score", 0))) for r in runs)
    total_max = sum(_num(r.get("max_score", r.get("max_total", 10)), 10) for r in runs) or 1
    q_count = sum(len(r.get("questions", []) or []) for r in runs)
    avg = total_score / total_max * 100 if total_max else 0
    duration_sum = 0.0
    for r in runs:
        duration_sum += _num(r.get("duration", 0), 0)
    return [
        ("Runs", str(total_runs), "primary"),
        ("Questions", str(q_count), "cyan"),
        ("Average", f"{avg:.0f}%", "green" if avg >= 85 else "amber" if avg >= 60 else "red"),
        ("Total time", f"{duration_sum:.0f}s", "pink"),
    ]


def _overview_table(runs: Sequence[Mapping[str, Any]], width: float, st: Mapping[str, ParagraphStyle]) -> Table:
    data = [[para("Student", st["small"]), para("Status", st["small"]), para("Score", st["small"]), para("Duration", st["small"])]]
    for r in runs:
        data.append([
            para(r.get("student_file", "-"), st["body"]),
            para(r.get("status", "-"), st["body"]),
            para(f"{_num(r.get('score', 0)):g}/{_num(r.get('max_score', 10), 10):g}", st["body"]),
            para(r.get("duration", "-"), st["body"]),
        ])
    col_widths = [width * 0.42, width * 0.2, width * 0.18, width * 0.2]
    table = Table(data, colWidths=col_widths, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), C("blue_soft")),
        ("TEXTCOLOR", (0, 0), (-1, 0), C("muted")),
        ("FONTNAME", (0, 0), (-1, 0), FONTS.bold),
        ("GRID", (0, 0), (-1, -1), 0.35, C("border")),
        ("BOX", (0, 0), (-1, -1), 0.6, C("border")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i in range(1, len(data)):
        style.append(("BACKGROUND", (0, i), (-1, i), colors.white if i % 2 else HexColor("#FBFDFF")))
    table.setStyle(TableStyle(style))
    return table


def build_story(report: Mapping[str, Any]) -> List[Any]:
    st = styles()
    margin_x = 34
    usable_w = PAGE_W - margin_x * 2
    story: List[Any] = []
    runs = list(report.get("runs", []) or [])

    story.append(CoverFlowable(report, usable_w))
    story.append(Spacer(1, 14))
    story.append(StatCards(_summary_stats(report), usable_w))
    story.append(Spacer(1, 16))
    story.append(para("Overview", st["h2"]))
    story.append(_overview_table(runs, usable_w, st))
    story.append(Spacer(1, 18))

    for idx, run in enumerate(runs):
        if idx > 0:
            story.append(PageBreak())
        story.append(RunHeaderCard(run, usable_w))
        story.append(Spacer(1, 12))
        for q in run.get("questions", []) or []:
            story.extend(_question_to_flowables(q, usable_w, st))
            story.append(Spacer(1, 12))
    return story


def render_grading_report_pdf(report_data: Mapping[str, Any], output_path: str | os.PathLike[str]) -> str:
    """Render a polished grading export PDF.

    Args:
        report_data: Report dictionary following the contract in template_contract.md.
        output_path: Destination PDF path.

    Returns:
        The output path as a string.
    """
    output_path = str(output_path)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=34,
        rightMargin=34,
        topMargin=28,
        bottomMargin=34,
        pageCompression=0,
        title=_safe_text(report_data.get("title", "AI Grading Report")),
        author=_safe_text(report_data.get("brand", "Zanista AI")),
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal", showBoundary=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_on_page)])
    doc.build(build_story(report_data))
    return output_path

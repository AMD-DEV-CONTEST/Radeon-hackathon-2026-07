#!/usr/bin/env python3
"""Fallback specification PDF renderer used when Playwright is unavailable."""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
    NextPageTemplate,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "SPECIFICATION.md"
OUTPUT = ROOT / "submission" / "NuclidePath_Project_Specification.pdf"
DASHBOARD = ROOT / "docs" / "assets" / "dashboard.png"

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
pdfmetrics.registerFont(TTFont("DejaVu", FONT))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_BOLD))
pdfmetrics.registerFont(TTFont("DejaVuMono", FONT_MONO))


def inline(text: str) -> str:
    value = html.escape(text, quote=False)
    value = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<link href="\2" color="#1259a5">\1</link>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"\x60([^\x60]+)\x60", r'<font name="DejaVuMono">\1</font>', value)
    value = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", value)
    return value


styles = getSampleStyleSheet()
BODY = ParagraphStyle(
    "Body", parent=styles["BodyText"], fontName="DejaVu", fontSize=9.2,
    leading=13.2, spaceAfter=4.5, textColor=colors.HexColor("#1b2026"),
)
H1 = ParagraphStyle(
    "H1", parent=BODY, fontName="DejaVu-Bold", fontSize=18, leading=22,
    spaceBefore=11, spaceAfter=8, textColor=colors.HexColor("#c64f00"),
)
H2 = ParagraphStyle(
    "H2", parent=BODY, fontName="DejaVu-Bold", fontSize=13, leading=17,
    spaceBefore=8, spaceAfter=5, textColor=colors.HexColor("#28323d"),
)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=12, firstLineIndent=-7, bulletIndent=0)
CODE = ParagraphStyle(
    "Code", parent=BODY, fontName="DejaVuMono", fontSize=7.4, leading=9.6,
    leftIndent=8, rightIndent=8, backColor=colors.HexColor("#f1f3f5"),
    borderColor=colors.HexColor("#d4d9df"), borderWidth=0.5, borderPadding=5,
)
COVER_KICKER = ParagraphStyle(
    "CoverKicker", parent=BODY, fontName="DejaVu-Bold", fontSize=9,
    leading=11, textColor=colors.HexColor("#ff8a45"),
)
COVER_TITLE = ParagraphStyle(
    "CoverTitle", parent=BODY, fontName="DejaVu-Bold", fontSize=33,
    leading=38, textColor=colors.white, spaceAfter=5,
)
COVER_SUB = ParagraphStyle(
    "CoverSub", parent=BODY, fontName="DejaVu", fontSize=15,
    leading=19, textColor=colors.HexColor("#c5cbd2"), spaceAfter=13,
)
COVER_SMALL = ParagraphStyle(
    "CoverSmall", parent=BODY, fontName="DejaVu", fontSize=8.5,
    leading=11, textColor=colors.HexColor("#b9c3cd"),
)
COVER_STAT = ParagraphStyle(
    "CoverStat", parent=BODY, fontName="DejaVu-Bold", fontSize=12,
    leading=14, textColor=colors.HexColor("#ff8a45"), alignment=1,
)
COVER_LABEL = ParagraphStyle(
    "CoverLabel", parent=BODY, fontName="DejaVu", fontSize=7.5,
    leading=9, textColor=colors.HexColor("#d3d9df"), alignment=1,
)


def table_from(lines: list[str]):
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append([Paragraph(inline(cell), BODY) for cell in cells])
    if not rows:
        return None
    width = 178 * mm
    n = max(len(row) for row in rows)
    widths = [width / n] * n
    normalized = [row + [""] * (n - len(row)) for row in rows]
    table = Table(normalized, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef3")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#18232d")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c4ccd4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def body_story() -> list:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    story = []
    i = 0
    in_code = False
    code_lines = []
    while i < len(lines):
        line = lines[i]
        if line.startswith("\x60\x60\x60"):
            if in_code:
                story.append(Preformatted("\n".join(code_lines), CODE))
                story.append(Spacer(1, 3))
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        if line.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            table = table_from(block)
            if table:
                story.extend([Spacer(1, 3), table, Spacer(1, 7)])
            continue
        if not line.strip():
            story.append(Spacer(1, 2))
            i += 1
            continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), H1))
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), H1))
        elif line.startswith("### "):
            story.append(Paragraph(inline(line[4:]), H2))
        elif line.startswith("- "):
            story.append(Paragraph(inline(line[2:]), BULLET, bulletText="•"))
        elif re.match(r"^\d+\.\s+", line):
            story.append(Paragraph(inline(re.sub(r"^\d+\.\s+", "", line)), BULLET, bulletText="•"))
        elif re.match(r"^---+$", line.strip()):
            story.append(Spacer(1, 5))
        else:
            story.append(Paragraph(inline(line), BODY))
        i += 1
    return story


def first_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#0b0f14"))
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#ff6b1a"))
    canvas.rect(16 * mm, 20 * mm, 42 * mm, 2 * mm, fill=1, stroke=0)
    canvas.restoreState()


def later_pages(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#d6dce2"))
    canvas.line(16 * mm, 14 * mm, A4[0] - 16 * mm, 14 * mm)
    canvas.setFont("DejaVu", 7)
    canvas.setFillColor(colors.HexColor("#66727e"))
    canvas.drawString(16 * mm, 8 * mm, "NuclidePath · current project specification · 2026-08-04")
    canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, str(doc.page))
    canvas.restoreState()


def cover_story() -> list:
    story = [
        Spacer(1, 20 * mm),
        Paragraph("AMD AI DEVMASTER HACKATHON 2026 · TRACK 2", COVER_KICKER),
        Spacer(1, 5 * mm),
        Paragraph("NuclidePath", COVER_TITLE),
        Paragraph("Private agents. Deterministic physics.", COVER_SUB),
        Paragraph("A fully local, physics-first AI workflow for traceable Cs-137 groundwater screening.", COVER_SMALL),
        Spacer(1, 8 * mm),
    ]
    if DASHBOARD.exists():
        image = Image(str(DASHBOARD), width=178 * mm, height=98 * mm)
        image.hAlign = "CENTER"
        story.append(image)
    story.extend([
        Spacer(1, 9 * mm),
        Table([
            [Paragraph("5/5", COVER_STAT), Paragraph("231", COVER_STAT), Paragraph("377/15", COVER_STAT), Paragraph("0", COVER_STAT)],
            [Paragraph("Track 2 capabilities", COVER_LABEL), Paragraph("AMD core snapshot", COVER_LABEL), Paragraph("latest CI gate", COVER_LABEL), Paragraph("cloud calls", COVER_LABEL)],
        ], colWidths=[44.5 * mm] * 4, style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#17212b")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#334352")),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#334352")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])),
        Spacer(1, 8 * mm),
        Paragraph("<b>Team:</b> Physics-First AI &nbsp;·&nbsp; <b>Author:</b> Stefano Rigante", COVER_SMALL),
        Paragraph("The optional PHREEQC multicomponent bridge is documented in the current source but is not shown in this core visual package; it remains PROCESS-QUALIFIED ONLY.", COVER_SMALL),
        PageBreak(),
    ])
    return story


def main():
    doc = BaseDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=17 * mm, bottomMargin=19 * mm,
        title="NuclidePath Project Specification",
        author="Physics-First AI",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=frame, onPage=first_page),
        PageTemplate(id="body", frames=frame, onPage=later_pages),
    ])
    story = cover_story() + body_story()
    story.insert(len(cover_story()) - 1, NextPageTemplate("body"))
    doc.build(story)


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
"""Render the English YIJIAN Project Specification Markdown as a polished PDF."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak


INK = colors.HexColor("#18332E")
JADE = colors.HexColor("#2F6B5F")
PALE = colors.HexColor("#EDF4F1")
GOLD = colors.HexColor("#C89B52")
MUTED = colors.HexColor("#5D6B67")


def inline(text: str) -> str:
    value = html.escape(text.strip())
    value = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"\[([^]]+)\]\([^)]+\)", r"<u>\1</u>", value)
    return value


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("Title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=25, leading=30, textColor=INK, alignment=TA_CENTER, spaceAfter=9 * mm),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=INK, spaceBefore=6 * mm, spaceAfter=2.5 * mm, keepWithNext=True),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=JADE, spaceBefore=4 * mm, spaceAfter=2 * mm, keepWithNext=True),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.4, leading=14.2, textColor=INK, spaceAfter=2.4 * mm),
        "bullet": ParagraphStyle("Bullet", parent=base["BodyText"], fontName="Helvetica", fontSize=9.2, leading=13.5, leftIndent=6 * mm, firstLineIndent=-3.5 * mm, textColor=INK, spaceAfter=1.3 * mm),
        "code": ParagraphStyle("Code", parent=base["Code"], fontName="Courier", fontSize=7.6, leading=10.5, leftIndent=4 * mm, rightIndent=4 * mm, borderColor=colors.HexColor("#CDDAD5"), borderWidth=.5, borderPadding=3 * mm, backColor=PALE, spaceBefore=2 * mm, spaceAfter=3 * mm),
        "small": ParagraphStyle("Small", parent=base["BodyText"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED),
    }


def header_footer(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(INK)
    canvas.rect(0, height - 13 * mm, width, 13 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.drawString(18 * mm, height - 8.2 * mm, "YIJIAN - TRACK 2")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(width - 18 * mm, height - 8.2 * mm, "Evidence-Grounded Go Review Agent")
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.2)
    canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(18 * mm, 8.5 * mm, "Ali Moqi | AMD Radeon PRO W7900 / ROCm")
    canvas.drawRightString(width - 18 * mm, 8.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def parse_markdown(text: str, style: dict):
    lines = text.splitlines()
    story = []
    index = 0
    in_code = False
    code_lines: list[str] = []
    while index < len(lines):
        line = lines[index]
        if line.strip() == "<!-- pagebreak -->":
            story.append(PageBreak())
            index += 1
            continue
        if line.startswith("```") or line.startswith("~~~"):
            if in_code:
                story.append(Paragraph("<br/>".join(html.escape(item) or " " for item in code_lines), style["code"]))
                code_lines = []
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if line.startswith("# "):
            story.append(Spacer(1, 12 * mm))
            story.append(Paragraph(inline(line[2:]), style["title"]))
            story.append(Table([["TRACK 2", "AMD RADEON / ROCm", "EVIDENCE FIRST"]], colWidths=[50 * mm] * 3,
                               style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE), ("TEXTCOLOR", (0, 0), (-1, -1), JADE), ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#CDDAD5")), ("INNERGRID", (0, 0), (-1, -1), .25, colors.HexColor("#CDDAD5")), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)])))
            story.append(Spacer(1, 5 * mm))
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), style["h1"]))
        elif line.startswith("### "):
            story.append(Paragraph(inline(line[4:]), style["h2"]))
        elif re.match(r"^\d+\. \*\*", line) or line.startswith("- "):
            marker, value = ("-", line[2:]) if line.startswith("- ") else (line.split(" ", 1)[0], line.split(" ", 1)[1])
            story.append(Paragraph(f"<font color='#C89B52'><b>{html.escape(marker)}</b></font> &nbsp;{inline(value)}", style["bullet"]))
        elif line.strip():
            story.append(Paragraph(inline(line), style["body"]))
        index += 1
    return story


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(args.output), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=21 * mm, bottomMargin=18 * mm, title="YIJIAN Project Specification",
        author="Ali Moqi", subject="Track 2 competition submission",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates(PageTemplate(id="spec", frames=[frame], onPageEnd=header_footer))
    doc.build(parse_markdown(args.input.read_text(encoding="utf-8"), styles()))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

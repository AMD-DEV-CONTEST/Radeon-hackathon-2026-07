#!/usr/bin/env python3
"""Build the SignalForge project specification PDF from its reviewable Markdown source."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "project-specification.md"
DEFAULT_ARCHITECTURE = ROOT / "docs" / "architecture.png"
DEFAULT_OUTPUT = ROOT / "output" / "pdf" / "SignalForge-Project-Specification.pdf"

NAVY = colors.HexColor("#102c38")
TEAL = colors.HexColor("#3f756e")
AMBER = colors.HexColor("#c97936")
CREAM = colors.HexColor("#f7f3e8")
INK = colors.HexColor("#334b52")
MUTED = colors.HexColor("#6a7d80")
LINE = colors.HexColor("#c8d3ce")


def inline_markup(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(
        r"\[([^]]+)]\((https?://[^)]+)\)",
        r'<link href="\2" color="#2f6f68"><u>\1</u></link>',
        escaped,
    )
    if escaped.startswith("http://") or escaped.startswith("https://"):
        escaped = f'<link href="{escaped}" color="#2f6f68"><u>{escaped}</u></link>'
    return escaped


def draw_page(canvas, doc) -> None:
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(CREAM)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(TEAL)
    canvas.rect(0, height - 6 * mm, width, 6 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 15 * mm, width - 18 * mm, 15 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(18 * mm, 9 * mm, "SignalForge · AMD AI DevMaster Hackathon · Track 2")
    canvas.drawRightString(width - 18 * mm, 9 * mm, f"{doc.page}")
    canvas.restoreState()


def cover_page(canvas, doc) -> None:
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#173f46"))
    canvas.circle(width + 5 * mm, 12 * mm, 90 * mm, fill=1, stroke=0)
    canvas.setFillColor(AMBER)
    canvas.rect(22 * mm, height - 53 * mm, 16 * mm, 4 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Times-Bold", 34)
    canvas.drawString(22 * mm, height - 78 * mm, "SignalForge")
    canvas.setFillColor(colors.HexColor("#dbe9e4"))
    canvas.setFont("Helvetica", 15)
    canvas.drawString(22 * mm, height - 92 * mm, "Private, local-first financial research on AMD Radeon")
    canvas.setFillColor(colors.HexColor("#92b8af"))
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(22 * mm, height - 118 * mm, "PROJECT SPECIFICATION")
    canvas.setFont("Helvetica", 10)
    canvas.drawString(22 * mm, height - 126 * mm, "AMD AI DevMaster Hackathon · Track 2: Agentic AI")

    cards = [
        ("11", "logical roles"),
        ("28", "deterministic tools"),
        ("44/44", "golden semantic gates"),
        ("29.17%", "end-to-end improvement"),
    ]
    x = 22 * mm
    y = height - 178 * mm
    for value, label in cards:
        canvas.setFillColor(colors.HexColor("#1e5057"))
        canvas.roundRect(x, y, 39 * mm, 30 * mm, 3 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 17)
        canvas.drawString(x + 5 * mm, y + 17 * mm, value)
        canvas.setFillColor(colors.HexColor("#bed5cf"))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(x + 5 * mm, y + 8 * mm, label)
        x += 42 * mm

    canvas.setFillColor(colors.HexColor("#dbe9e4"))
    canvas.setFont("Helvetica", 9)
    canvas.drawString(22 * mm, 20 * mm, "Evidence date: 22 July 2026 · github.com/rvbernucci/signalforge")
    canvas.restoreState()


def build_styles():
    base = getSampleStyleSheet()
    return {
        "h2": ParagraphStyle(
            "SFHeading2",
            parent=base["Heading2"],
            fontName="Times-Bold",
            fontSize=22,
            leading=25,
            textColor=NAVY,
            spaceBefore=3 * mm,
            spaceAfter=4 * mm,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "SFHeading3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=TEAL,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "SFBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=13.2,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=2.6 * mm,
        ),
        "bullet": ParagraphStyle(
            "SFBullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=12.5,
            textColor=INK,
            leftIndent=5 * mm,
            firstLineIndent=-3.5 * mm,
            bulletIndent=1.5 * mm,
            spaceAfter=1.4 * mm,
        ),
        "number": ParagraphStyle(
            "SFNumber",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=12.5,
            textColor=INK,
            leftIndent=6 * mm,
            firstLineIndent=-4.5 * mm,
            spaceAfter=1.4 * mm,
        ),
        "code": ParagraphStyle(
            "SFCode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7.8,
            leading=11,
            textColor=NAVY,
            backColor=colors.HexColor("#e8efeb"),
            borderPadding=3 * mm,
            borderRadius=2 * mm,
            spaceBefore=1 * mm,
            spaceAfter=3 * mm,
        ),
        "caption": ParagraphStyle(
            "SFCaption",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=3 * mm,
        ),
    }


def parse_story(source: str, architecture: Path):
    styles = build_styles()
    story = [PageBreak()]
    lines = source.splitlines()
    paragraph: list[str] = []
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            story.append(Paragraph(inline_markup(" ".join(part.strip() for part in paragraph)), styles["body"]))
            paragraph = []

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("# "):
            continue
        if line == "```text":
            flush_paragraph()
            in_code = True
            code_lines = []
            continue
        if line == "```" and in_code:
            story.append(Paragraph("<br/>".join(html.escape(item) for item in code_lines), styles["code"]))
            in_code = False
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line == "<!-- pagebreak -->":
            flush_paragraph()
            story.append(PageBreak())
            continue
        if line == "<!-- architecture -->":
            flush_paragraph()
            image = Image(str(architecture), width=172 * mm, height=107.5 * mm)
            story.append(image)
            story.append(Paragraph("SignalForge separates model interpretation from deterministic financial authority.", styles["caption"]))
            continue
        if line.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[3:]), styles["h2"]))
            continue
        if line.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[4:]), styles["h3"]))
            continue
        if line.startswith("- "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[2:]), styles["bullet"], bulletText="•"))
            continue
        numbered = re.match(r"^(\d+)\.\s+(.*)$", line)
        if numbered:
            flush_paragraph()
            story.append(Paragraph(f"<b>{numbered.group(1)}.</b> {inline_markup(numbered.group(2))}", styles["number"]))
            continue
        if not line.strip():
            flush_paragraph()
            continue
        paragraph.append(line)
    flush_paragraph()
    return story


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--architecture", type=Path, default=DEFAULT_ARCHITECTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.source.is_file() or not args.architecture.is_file():
        raise SystemExit("project specification source or architecture image is missing")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        str(args.output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=20 * mm,
        title="SignalForge Project Specification",
        author="SignalForge",
        subject="AMD AI DevMaster Hackathon Track 2",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="content")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame], onPage=cover_page, autoNextPageTemplate="content"),
        PageTemplate(id="content", frames=[frame], onPage=draw_page),
    ])
    story = parse_story(args.source.read_text(encoding="utf-8"), args.architecture)
    doc.build(story)
    print(args.output)


if __name__ == "__main__":
    main()

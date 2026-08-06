#!/usr/bin/env python3
"""Render docs/PROJECT_PROFILE_EN.md -> deliverables/Project_Profile_EN.pdf (A4, English)."""
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    Preformatted, HRFlowable, KeepTogether,
)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "PROJECT_PROFILE_EN.md"
OUT = ROOT / "deliverables" / "Project_Profile_EN.pdf"

F = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("DV", F + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DV-B", F + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DV-I", F + "DejaVuSerif.ttf"))
pdfmetrics.registerFont(TTFont("DV-M", F + "DejaVuSansMono.ttf"))
pdfmetrics.registerFont(TTFont("DV-MB", F + "DejaVuSansMono-Bold.ttf"))

ACCENT = colors.HexColor("#c9922b")
DARK = colors.HexColor("#1d2117")
GRAY = colors.HexColor("#555555")
CODEBG = colors.HexColor("#f4f1e8")
BORDER = colors.HexColor("#d9d2c2")

H1 = ParagraphStyle("H1", fontName="DV-B", fontSize=17, leading=21, textColor=ACCENT, spaceBefore=0, spaceAfter=8)
H2 = ParagraphStyle("H2", fontName="DV-B", fontSize=13, leading=16, textColor=DARK, spaceBefore=12, spaceAfter=5)
H3 = ParagraphStyle("H3", fontName="DV-B", fontSize=11, leading=14, textColor=DARK, spaceBefore=9, spaceAfter=4)
BODY = ParagraphStyle("Body", fontName="DV", fontSize=9.3, leading=13.2, textColor=colors.HexColor("#222222"), alignment=TA_LEFT, spaceAfter=5)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=14, bulletIndent=4, spaceAfter=3)
CODE = ParagraphStyle("Code", fontName="DV-M", fontSize=7.4, leading=9.4, backColor=CODEBG, borderColor=BORDER, borderWidth=0.5, borderPadding=5, leftIndent=6, rightIndent=6, spaceBefore=4, spaceAfter=6)
CELL = ParagraphStyle("Cell", fontName="DV", fontSize=8, leading=10.5)
CELLB = ParagraphStyle("CellB", fontName="DV-B", fontSize=8, leading=10.5, textColor=colors.white)
NOTE = ParagraphStyle("Note", parent=BODY, fontName="DV-I", textColor=GRAY, leftIndent=10, rightIndent=10)


def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(t: str) -> str:
    t = esc(t)
    t = re.sub(r"`([^`]+)`", r'<font face="DV-M">\1</font>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", t)
    return t


def parse_table(lines, i):
    rows, j = [], i
    while j < len(lines) and lines[j].strip().startswith("|"):
        row = [c.strip() for c in lines[j].strip().strip("|").split("|")]
        if not re.fullmatch(r":?-{2,}:?", row[0].strip() or "---"):
            rows.append(row)
        j += 1
    return rows, j


def build():
    md = SRC.read_text(encoding="utf-8").splitlines()
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="IndieGen Asset Studio — Project Profile (AMD ROCm)",
        author="IndieGen Asset Studio",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")

    def footer(canv, doc_):
        canv.saveState()
        canv.setFont("DV", 7.5)
        canv.setFillColor(GRAY)
        canv.drawString(18 * mm, 9 * mm, "IndieGen Asset Studio — Track 1 · Multimodal Content Creation Tools")
        canv.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Page {doc_.page}")
        canv.restoreState()

    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=footer)])

    story = []
    # cover
    story.append(Spacer(1, 70 * mm))
    story.append(Paragraph("IndieGen Asset Studio", ParagraphStyle("CT", fontName="DV-B", fontSize=30, leading=36, textColor=DARK)))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Track 1 · Multimodal Content Creation Tools", ParagraphStyle("CS", fontName="DV", fontSize=14, leading=18, textColor=ACCENT)))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "A full-chain, multimodal AI asset generation platform for indie game developers — "
        "from one text setting to concept art, depth, PBR materials, music, ambient SFX, "
        "sprite sheets and a 3D character, with native AMD Radeon / ROCm support.",
        ParagraphStyle("CD", fontName="DV", fontSize=10.5, leading=15, textColor=GRAY, rightIndent=30 * mm),
    ))
    story.append(Spacer(1, 70 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=8))
    story.append(Paragraph("Project Profile (PDF) · Supplementary deck · Demo video · Live ROCm benchmark", ParagraphStyle("CF", fontName="DV", fontSize=8.5, textColor=GRAY)))
    story.append(PageBreak := Spacer(1, 0))
    story = story[:-1] + [Spacer(1, 0)]

    i = 0
    first_h1 = True
    while i < len(md):
        line = md[i].rstrip()
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            j = i + 1
            buf = []
            while j < len(md) and not md[j].strip().startswith("```"):
                buf.append(md[j])
                j += 1
            story.append(Preformatted("\n".join(buf), CODE))
            i = j + 1
            continue
        if s.startswith("|"):
            rows, j = parse_table(md, i)
            header = [Paragraph(inline(c), CELLB) for c in rows[0]]
            body = [[Paragraph(inline(c), CELL) for c in r] for r in rows[1:]]
            t = Table([header] + body, repeatRows=1, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#faf8f1")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(KeepTogether([Spacer(1, 2), t, Spacer(1, 6)]))
            i = j
            continue
        if s.startswith("### "):
            story.append(Paragraph(inline(s[4:]), H3))
        elif s.startswith("## "):
            story.append(Paragraph(inline(s[3:]), H2))
        elif s.startswith("# "):
            if first_h1:
                first_h1 = False
            else:
                story.append(Paragraph(inline(s[2:]), H1))
            story.append(HRFlowable(width="100%", thickness=1.1, color=ACCENT, spaceAfter=8))
        elif s.startswith("---"):
            story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER, spaceBefore=4, spaceAfter=8))
        elif s.startswith("> "):
            story.append(Paragraph(inline(s[2:]), NOTE))
        elif re.match(r"^\d+\.\s+", s):
            num = re.match(r"^(\d+)\.\s+(.*)$", s)
            story.append(Paragraph(inline(num.group(2)), BULLET, bulletText=num.group(1) + "."))
        elif s.startswith("- ") or s.startswith("* "):
            story.append(Paragraph(inline(s[2:]), BULLET, bulletText="•"))
        else:
            story.append(Paragraph(inline(s), BODY))
        i += 1

    doc.build(story)
    print("PDF written:", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    build()

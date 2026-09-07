"""Render the release technical report Markdown as a self-contained PDF."""

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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing, Group, Line, Polygon, Rect, String
from reportlab.platypus import (
    LongTable,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "reports" / "RadeonVLA-Reflex-Technical-Report.md"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "RadeonVLA-Reflex-Technical-Report.pdf"
FONT_ROOT = Path("/usr/share/fonts/truetype/dejavu")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _register_fonts() -> None:
    required = {
        "RadeonSans": FONT_ROOT / "DejaVuSans.ttf",
        "RadeonSans-Bold": FONT_ROOT / "DejaVuSans-Bold.ttf",
        "RadeonMono": FONT_ROOT / "DejaVuSansMono.ttf",
    }
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Required PDF fonts are missing: {missing}")
    for name, path in required.items():
        pdfmetrics.registerFont(TTFont(name, str(path)))


def _inline(text: str) -> str:
    text = text.replace("**", "").replace("`", "")
    escaped = html.escape(text, quote=False)
    return re.sub(
        r"\[([^]]+)]\(([^)]+)\)",
        r'<link href="\2" color="#455b08">\1</link>',
        escaped,
    )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReleaseTitle",
            parent=base["Title"],
            fontName="RadeonSans-Bold",
            fontSize=22,
            leading=27,
            textColor=colors.HexColor("#171914"),
            spaceAfter=8 * mm,
            alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "ReleaseSubtitle",
            parent=base["Heading2"],
            fontName="RadeonSans",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#4f5844"),
            spaceAfter=7 * mm,
            alignment=TA_CENTER,
        ),
        "h2": ParagraphStyle(
            "ReleaseH2",
            parent=base["Heading2"],
            fontName="RadeonSans-Bold",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#263300"),
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ReleaseBody",
            parent=base["BodyText"],
            fontName="RadeonSans",
            fontSize=9,
            leading=12.8,
            textColor=colors.HexColor("#20231d"),
            spaceAfter=2 * mm,
        ),
        "bullet": ParagraphStyle(
            "ReleaseBullet",
            parent=base["BodyText"],
            fontName="RadeonSans",
            fontSize=8.7,
            leading=12,
            leftIndent=5 * mm,
            firstLineIndent=-3.5 * mm,
            spaceAfter=1 * mm,
        ),
        "quote": ParagraphStyle(
            "ReleaseQuote",
            parent=base["BodyText"],
            fontName="RadeonSans",
            fontSize=9,
            leading=13,
            leftIndent=6 * mm,
            rightIndent=5 * mm,
            borderColor=colors.HexColor("#9bbb27"),
            borderWidth=1.5,
            borderPadding=4,
            textColor=colors.HexColor("#3e4931"),
            spaceAfter=3 * mm,
        ),
        "table": ParagraphStyle(
            "ReleaseTable",
            parent=base["BodyText"],
            fontName="RadeonSans",
            fontSize=7.1,
            leading=9.1,
        ),
        "table_header": ParagraphStyle(
            "ReleaseTableHeader",
            parent=base["BodyText"],
            fontName="RadeonSans-Bold",
            fontSize=7.1,
            leading=9.1,
            textColor=colors.white,
        ),
        "code": ParagraphStyle(
            "ReleaseCode",
            parent=base["Code"],
            fontName="RadeonMono",
            fontSize=7.2,
            leading=9.5,
            leftIndent=3 * mm,
            rightIndent=3 * mm,
            borderColor=colors.HexColor("#d4d8cc"),
            borderWidth=0.5,
            borderPadding=5,
            backColor=colors.HexColor("#f4f6f1"),
            spaceAfter=3 * mm,
        ),
    }


def _table(lines: list[str], styles: dict[str, ParagraphStyle], width: float) -> LongTable:
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    if len(rows) > 1 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
        rows.pop(1)
    columns = max(len(row) for row in rows)
    normalized = [row + [""] * (columns - len(row)) for row in rows]
    rendered = []
    for row_index, row in enumerate(normalized):
        style = styles["table_header"] if row_index == 0 else styles["table"]
        rendered.append([Paragraph(_inline(cell), style) for cell in row])
    table = LongTable(rendered, colWidths=[width / columns] * columns, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263300")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b9bfb0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7f2")]),
            ]
        )
    )
    return table


def _architecture_diagram(width: float) -> Drawing:
    """Render the release architecture as vector artwork inside the PDF."""
    nominal_width = 720.0
    nominal_height = 190.0
    scale = width / nominal_width
    drawing = Drawing(width, nominal_height * scale)
    group = Group()

    ink = colors.HexColor("#20251a")
    deep = colors.HexColor("#263300")
    accent = colors.HexColor("#91ad35")
    muted = colors.HexColor("#68705e")
    line = colors.HexColor("#cbd1c0")
    paper = colors.HexColor("#fbfcf8")

    def assert_fits(text: str, size: float, maximum: float, *, bold: bool = False) -> None:
        font = "RadeonSans-Bold" if bold else "RadeonSans"
        measured = pdfmetrics.stringWidth(text, font, size)
        if measured > maximum:
            raise ValueError(f"Architecture label exceeds its box: {text!r} ({measured:.1f} > {maximum:.1f})")

    for text in ("Language command", "World RGB", "Wrist RGB", "Proprioception"):
        assert_fits(text, 10, 138, bold=True)
    assert_fits("SmolVLA", 16, 104, bold=True)
    assert_fits("VISION · LANGUAGE · ACTION", 6.1, 104, bold=True)
    assert_fits("SafetyMonitor", 14, 131, bold=True)
    assert_fits("VALIDATE · INTERRUPT · RECOVER", 6.7, 131, bold=True)
    assert_fits("Genesis", 13, 67, bold=True)
    assert_fits("SIMULATION", 6.8, 67, bold=True)
    assert_fits("CommandSession (version)", 9.5, 165, bold=True)
    assert_fits("FailureDetector + RecoveryPolicy", 8.6, 165, bold=True)

    group.add(Rect(0, 0, nominal_width, nominal_height, rx=12, ry=12, fillColor=paper, strokeColor=None))

    def label(x: float, y: float, text: str, size: float, *, color=ink, bold=False, anchor="start") -> None:
        group.add(
            String(
                x,
                y,
                text,
                fontName="RadeonSans-Bold" if bold else "RadeonSans",
                fontSize=size,
                fillColor=color,
                textAnchor=anchor,
            )
        )

    def arrow(x1: float, y: float, x2: float) -> None:
        group.add(Line(x1, y, x2 - 7, y, strokeColor=ink, strokeWidth=2))
        group.add(Polygon([x2 - 7, y - 4, x2, y, x2 - 7, y + 4], fillColor=ink, strokeColor=None))

    label(8, 174, "MULTIMODAL INPUTS", 8, color=muted, bold=True)
    label(235, 174, "LEARNED POLICY", 8, color=muted, bold=True)
    label(410, 174, "EXECUTION BOUNDARY", 8, color=muted, bold=True)

    inputs = [
        (145, "Language command", colors.HexColor("#b7db28")),
        (117, "World RGB", colors.HexColor("#6f9d20")),
        (89, "Wrist RGB", colors.HexColor("#4f7cc2")),
        (61, "Proprioception", colors.HexColor("#d1a51b")),
    ]
    for y, text, dot in inputs:
        group.add(Rect(8, y, 170, 21, rx=5, ry=5, fillColor=colors.white, strokeColor=line, strokeWidth=0.7))
        group.add(Rect(18, y + 7, 7, 7, rx=3.5, ry=3.5, fillColor=dot, strokeColor=None))
        label(32, y + 6, text, 10, bold=True)
        group.add(Line(178, y + 10.5, 191, y + 10.5, strokeColor=ink, strokeWidth=1.4))
    group.add(Line(191, 71.5, 191, 155.5, strokeColor=ink, strokeWidth=1.4))
    arrow(191, 113.5, 226)

    group.add(Rect(235, 84, 118, 67, rx=9, ry=9, fillColor=deep, strokeColor=None))
    label(294, 120, "SmolVLA", 16, color=colors.white, bold=True, anchor="middle")
    label(294, 101, "VISION · LANGUAGE · ACTION", 6.1, color=colors.HexColor("#dcebb0"), bold=True, anchor="middle")

    arrow(353, 117.5, 400)
    label(376, 128, "action", 8, color=muted, bold=True, anchor="middle")

    group.add(Rect(410, 84, 145, 67, rx=9, ry=9, fillColor=colors.white, strokeColor=accent, strokeWidth=1.6))
    label(482.5, 120, "SafetyMonitor", 14, color=deep, bold=True, anchor="middle")
    label(482.5, 101, "VALIDATE · INTERRUPT · RECOVER", 6.7, color=muted, bold=True, anchor="middle")

    arrow(555, 117.5, 625)
    group.add(Rect(634, 84, 78, 67, rx=9, ry=9, fillColor=colors.HexColor("#151811"), strokeColor=None))
    label(673, 120, "Genesis", 13, color=colors.white, bold=True, anchor="middle")
    label(673, 101, "SIMULATION", 6.8, color=colors.HexColor("#c9d995"), bold=True, anchor="middle")

    group.add(Line(482.5, 84, 482.5, 72, strokeColor=accent, strokeWidth=1.8))
    group.add(Rect(392, 12, 181, 60, rx=8, ry=8, fillColor=colors.HexColor("#f7f9f2"), strokeColor=accent, strokeWidth=1.1))
    label(482.5, 46, "CommandSession (version)", 9.5, color=deep, bold=True, anchor="middle")
    label(482.5, 27, "FailureDetector + RecoveryPolicy", 8.6, color=muted, bold=True, anchor="middle")

    group.scale(scale, scale)
    drawing.add(group)
    return drawing


def _story(markdown: str, styles: dict[str, ParagraphStyle], width: float) -> list[object]:
    lines = markdown.splitlines()
    story: list[object] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            story.append(Paragraph(_inline(" ".join(part.strip() for part in paragraph)), styles["body"]))
            paragraph.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            story.append(Preformatted("\n".join(code), styles["code"], maxLineLength=110))
        elif re.fullmatch(r"!\[[^]]*]\((?:\.\./)?docs/figures/architecture-framework-en\.svg\)", stripped):
            flush()
            story.append(_architecture_diagram(width))
            story.append(Spacer(1, 2.5 * mm))
        elif stripped.startswith("|"):
            flush()
            rows: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(lines[index])
                index += 1
            story.append(_table(rows, styles, width))
            story.append(Spacer(1, 2.5 * mm))
            continue
        elif stripped.startswith("# "):
            flush()
            story.append(Paragraph(_inline(stripped[2:]), styles["title"]))
        elif stripped.startswith("## Technical Report"):
            flush()
            story.append(Paragraph(_inline(stripped[3:]), styles["subtitle"]))
        elif stripped.startswith("## "):
            flush()
            story.append(Paragraph(_inline(stripped[3:]), styles["h2"]))
        elif stripped.startswith("> "):
            flush()
            quote = [stripped[2:]]
            while index + 1 < len(lines) and lines[index + 1].strip().startswith("> "):
                index += 1
                quote.append(lines[index].strip()[2:])
            story.append(Paragraph(_inline(" ".join(quote)), styles["quote"]))
        elif re.match(r"^[-*] ", stripped):
            flush()
            story.append(Paragraph(f"• {_inline(stripped[2:])}", styles["bullet"]))
        elif re.match(r"^\d+\. ", stripped):
            flush()
            story.append(Paragraph(_inline(stripped), styles["bullet"]))
        elif not stripped:
            flush()
        else:
            paragraph.append(stripped)
        index += 1
    flush()
    return story


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("RadeonSans", 7.5)
    canvas.setFillColor(colors.HexColor("#68705e"))
    canvas.drawString(document.leftMargin, 10 * mm, "RadeonVLA-Reflex · VisioBot Lab · Track 3")
    canvas.drawRightString(A4[0] - document.rightMargin, 10 * mm, f"Page {document.page}")
    canvas.restoreState()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    _register_fonts()
    styles = _styles()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=12 * mm,
        bottomMargin=15 * mm,
        title="RadeonVLA-Reflex Technical Report",
        author="VisioBot Lab",
        subject="AMD AI DevMaster Track 3 Physical AI Challenge",
    )
    width = A4[0] - document.leftMargin - document.rightMargin
    document.build(_story(source.read_text(encoding="utf-8"), styles, width), onFirstPage=_footer, onLaterPages=_footer)
    print(f"report_pdf={output} bytes={output.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

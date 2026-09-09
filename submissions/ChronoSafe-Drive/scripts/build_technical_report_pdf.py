"""Build the English competition technical report PDF from Markdown source."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "docs" / "TECHNICAL_REPORT.md",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "TECHNICAL_REPORT.pdf",
    )
    return parser.parse_args()


def inline_markup(text: str) -> str:
    value = escape(text.strip())
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(
        r"`([^`]+)`",
        r'<font name="Courier" color="#9f1239">\1</font>',
        value,
    )
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2">\1</link>', value)
    return value


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.1,
            leading=13.2,
            textColor=colors.HexColor("#20262e"),
            spaceAfter=6,
            alignment=TA_LEFT,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=21,
            textColor=colors.HexColor("#9f1239"),
            spaceBefore=12,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            textColor=colors.HexColor("#1f3a5f"),
            spaceBefore=9,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.2,
            leading=13,
            textColor=colors.HexColor("#374151"),
            spaceBefore=7,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "quote": ParagraphStyle(
            "Quote",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9.2,
            leading=13.5,
            leftIndent=10,
            borderColor=colors.HexColor("#dc2626"),
            borderWidth=2,
            borderPadding=6,
            textColor=colors.HexColor("#374151"),
            backColor=colors.HexColor("#fff7ed"),
            spaceAfter=8,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7.6,
            leading=10,
            leftIndent=7,
            rightIndent=7,
            borderColor=colors.HexColor("#cbd5e1"),
            borderWidth=0.5,
            borderPadding=6,
            backColor=colors.HexColor("#f8fafc"),
            spaceBefore=3,
            spaceAfter=7,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.6,
            leading=10,
            textColor=colors.HexColor("#475569"),
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.6,
            leading=10,
            textColor=colors.white,
        ),
        "flow_arrow": ParagraphStyle(
            "FlowArrow",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.1,
            leading=10,
            textColor=colors.HexColor("#64748b"),
            alignment=TA_CENTER,
            spaceAfter=0,
        ),
    }


def architecture_flow(styles: dict[str, ParagraphStyle]) -> Table:
    boxes = [
        "MetaDrive physics simulation + nuScenes camera/LiDAR streams",
        "Controlled single, compound, and timestamp degradation",
        "15-D causal health features over an 8-frame temporal window",
        "Shared GRU with camera, LiDAR, timing, and continuous-risk heads",
        "Worst-domain stress conformal upper-risk calibration",
        "NORMAL -> DEGRADED -> MINIMAL_RISK closed-loop control",
    ]
    data: list[list[object]] = []
    for index, box in enumerate(boxes):
        data.append([Paragraph(f"<b>{inline_markup(box)}</b>", styles["body"])])
        if index != len(boxes) - 1:
            data.append([Paragraph("v", styles["flow_arrow"])])
    table = Table(data, colWidths=[155 * mm], hAlign="CENTER")
    commands = [
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]
    for row in range(0, len(data), 2):
        commands.extend(
            [
                ("BACKGROUND", (0, row), (0, row), colors.HexColor("#f1f5f9")),
                ("BOX", (0, row), (0, row), 0.8, colors.HexColor("#64748b")),
                ("TOPPADDING", (0, row), (0, row), 7),
                ("BOTTOMPADDING", (0, row), (0, row), 7),
            ]
        )
    table.setStyle(TableStyle(commands))
    return table


def markdown_table(lines: list[str], styles: dict[str, ParagraphStyle]) -> Table:
    rows: list[list[Paragraph]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        cell_style = styles["table_header"] if not rows else styles["small"]
        rows.append([Paragraph(inline_markup(cell), cell_style) for cell in cells])
    columns = max(len(row) for row in rows)
    width = 170 * mm / columns
    table = Table(rows, colWidths=[width] * columns, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#94a3b8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ]
        )
    )
    return table


def markdown_story(text: str, styles: dict[str, ParagraphStyle]) -> list[object]:
    lines = text.splitlines()
    story: list[object] = []
    index = 0
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            story.append(Paragraph(inline_markup(" ".join(paragraph_lines)), styles["body"]))
            paragraph_lines.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if index < 4 and stripped.startswith("#"):
            index += 1
            continue
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            language = stripped.removeprefix("```").strip()
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            if language == "mermaid":
                story.append(architecture_flow(styles))
                story.append(Spacer(1, 5))
            else:
                story.append(Preformatted("\n".join(code), styles["code"]))
            index += 1
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            table_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            story.append(markdown_table(table_lines, styles))
            story.append(Spacer(1, 6))
            continue
        heading = re.match(r"^(#{2,4})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            style = styles["h1"] if level == 2 else styles["h2"] if level == 3 else styles["h3"]
            story.append(Paragraph(inline_markup(heading.group(2)), style))
            index += 1
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            quote_lines = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip().removeprefix(">").strip())
                index += 1
            story.append(Paragraph(inline_markup(" ".join(quote_lines)), styles["quote"]))
            continue
        if re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            flush_paragraph()
            ordered = bool(re.match(r"^\d+\.\s+", stripped))
            item_texts: list[str] = []
            while index < len(lines):
                raw_item = lines[index]
                item = raw_item.strip()
                ordered_match = re.match(r"^\d+\.\s+(.+)$", item)
                bullet_match = re.match(r"^[-*]\s+(.+)$", item)
                current_match = ordered_match if ordered else bullet_match
                if current_match:
                    item_texts.append(current_match.group(1))
                    index += 1
                    continue
                if item_texts and raw_item[:1].isspace() and item:
                    item_texts[-1] = f"{item_texts[-1]} {item}"
                    index += 1
                    continue
                if not item:
                    break
                break
            items = [
                ListItem(Paragraph(inline_markup(item_text), styles["body"]))
                for item_text in item_texts
            ]
            list_options = {
                "bulletType": "1" if ordered else "bullet",
                "leftIndent": 16,
                "bulletFontName": "Helvetica",
                "bulletFontSize": 8,
                "spaceAfter": 5,
            }
            if ordered:
                list_options["start"] = "1"
            else:
                list_options["bulletChar"] = "-"
            story.append(ListFlowable(items, **list_options))
            continue
        paragraph_lines.append(stripped)
        index += 1
    flush_paragraph()
    return story


def cover_story(styles: dict[str, ParagraphStyle]) -> list[object]:
    title = ParagraphStyle(
        "CoverTitle",
        fontName="Helvetica-Bold",
        fontSize=25,
        leading=30,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#9f1239"),
    )
    subtitle = ParagraphStyle(
        "CoverSubtitle",
        fontName="Helvetica",
        fontSize=13,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#334155"),
    )
    metric_data = [
        ["Closed-loop MRM", "Timestamp robustness", "AMD ROCm inference"],
        ["20/20 success\n0% premature", "95.08%-99.34%\nstress accuracy", "0.559 ms p50\n1.37M seq/s"],
    ]
    metrics = Table(metric_data, colWidths=[55 * mm] * 3, rowHeights=[10 * mm, 20 * mm])
    metrics.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f1f5f9")),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#111827")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("FONTSIZE", (0, 1), (-1, 1), 11),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#64748b")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#94a3b8")),
            ]
        )
    )
    return [
        Spacer(1, 24 * mm),
        Paragraph("ChronoSafe-Drive", title),
        Spacer(1, 6 * mm),
        Paragraph(
            "Self-Diagnosis, Risk Calibration, and Minimal-Risk Maneuvers under Multi-Sensor Perception Degradation",
            subtitle,
        ),
        Spacer(1, 11 * mm),
        HRFlowable(width="65%", thickness=2, color=colors.HexColor("#dc2626")),
        Spacer(1, 11 * mm),
        Paragraph("AMD Hackathon 2026 - Track 3: Physical AI", subtitle),
        Spacer(1, 4 * mm),
        Paragraph("Competition Technical Report", subtitle),
        Spacer(1, 17 * mm),
        metrics,
        Spacer(1, 17 * mm),
        Paragraph(
            "Platform: AMD Radeon gfx1100 | ROCm/HIP 7.2 | PyTorch 2.9.1 ROCm",
            styles["body"],
        ),
        Paragraph(
            "Evaluation: nuScenes v1.0-trainval + 20 unseen MetaDrive closed-loop seeds",
            styles["body"],
        ),
        Spacer(1, 12 * mm),
        Paragraph("Wang Zhenyu | Wang Guanyu | Han Liuxuan", subtitle),
        Spacer(1, 2 * mm),
        Paragraph("Team submission | August 2026", subtitle),
        PageBreak(),
    ]


def page_decor(canvas, document) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, height - 14 * mm, width - 20 * mm, height - 14 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(20 * mm, height - 11 * mm, "ChronoSafe-Drive | AMD ROCm Physical AI")
    canvas.drawRightString(width - 20 * mm, 11 * mm, f"Page {document.page}")
    canvas.restoreState()


def main() -> None:
    args = parse_args()
    source = args.input if args.input.is_absolute() else PROJECT_ROOT / args.input
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    if not source.is_file():
        raise FileNotFoundError(source)
    styles = make_styles()
    story = cover_story(styles)
    story.extend(markdown_story(source.read_text(encoding="utf-8"), styles))

    benchmark = PROJECT_ROOT / "evidence" / "rocm_inference_benchmark_seed2026" / "benchmark.png"
    if benchmark.is_file():
        benchmark_width = 170 * mm
        benchmark_height = benchmark_width * 949 / 2478
        story.extend(
            [
                Spacer(1, 8),
                KeepTogether(
                    [
                        Paragraph("AMD ROCm benchmark figure", styles["h2"]),
                        Image(str(benchmark), width=benchmark_width, height=benchmark_height),
                    ]
                ),
            ]
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=19 * mm,
        bottomMargin=17 * mm,
        title="ChronoSafe-Drive Technical Report",
        author="Wang Zhenyu; Wang Guanyu; Han Liuxuan",
        subject="AMD Hackathon 2026 - Track 3: Physical AI",
    )
    document.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
    print(f"TECHNICAL REPORT PDF PASS: {output}")


if __name__ == "__main__":
    main()

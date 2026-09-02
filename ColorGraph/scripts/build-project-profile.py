from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
PAGE_W, PAGE_H = A4
MARGIN = 38

NAVY = HexColor("#08111F")
NAVY_2 = HexColor("#101D31")
INK = HexColor("#152238")
MUTED = HexColor("#5F6D82")
PALE = HexColor("#F3F6FA")
LINE = HexColor("#D9E1EB")
CYAN = HexColor("#28B7CE")
CYAN_PALE = HexColor("#DFF5F8")
AMBER = HexColor("#F4A62A")
AMBER_PALE = HexColor("#FFF0D5")
GREEN = HexColor("#2AA879")
RED = HexColor("#D75455")

TOTAL_PAGES = 8


def register_fonts() -> None:
    candidates = [
        (
            Path(r"C:\Windows\Fonts\arial.ttf"),
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
    ]
    for regular, bold in candidates:
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("CG-Regular", str(regular)))
            pdfmetrics.registerFont(TTFont("CG-Bold", str(bold)))
            return
    raise FileNotFoundError("Arial or DejaVu Sans fonts are required")


def split_long_token(token: str, font: str, size: float, width: float) -> list[str]:
    if pdfmetrics.stringWidth(token, font, size) <= width:
        return [token]
    pieces: list[str] = []
    current = ""
    for char in token:
        candidate = current + char
        if current and pdfmetrics.stringWidth(candidate, font, size) > width:
            pieces.append(current)
            current = char
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def wrap_lines(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words: list[str] = []
        for token in paragraph.split():
            words.extend(split_long_token(token, font, size, width))
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if pdfmetrics.stringWidth(candidate, font, size) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def draw_text(
    canvas: Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "CG-Regular",
    size: float = 10,
    leading: float | None = None,
    color: Color = INK,
    max_lines: int | None = None,
) -> float:
    leading = leading or size * 1.35
    lines = wrap_lines(text, font, size, width)
    if max_lines is not None:
        lines = lines[:max_lines]
    canvas.setFillColor(color)
    canvas.setFont(font, size)
    cursor = y
    for line in lines:
        canvas.drawString(x, cursor, line)
        cursor -= leading
    return cursor


def draw_bullets(
    canvas: Canvas,
    items: Iterable[str],
    x: float,
    y: float,
    width: float,
    *,
    size: float = 9.5,
    leading: float = 13,
    gap: float = 7,
    dot_color: Color = CYAN,
) -> float:
    cursor = y
    for item in items:
        lines = wrap_lines(item, "CG-Regular", size, width - 15)
        canvas.setFillColor(dot_color)
        canvas.circle(x + 3, cursor + 2.5, 2.2, fill=1, stroke=0)
        canvas.setFillColor(INK)
        canvas.setFont("CG-Regular", size)
        for index, line in enumerate(lines):
            canvas.drawString(x + 13, cursor - index * leading, line)
        cursor -= len(lines) * leading + gap
    return cursor


def draw_image_cover(
    canvas: Canvas,
    path: Path,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    image = ImageReader(str(path))
    image_w, image_h = image.getSize()
    scale = max(width / image_w, height / image_h)
    draw_w = image_w * scale
    draw_h = image_h * scale
    canvas.saveState()
    canvas.rect(x, y, width, height, stroke=0, fill=0)
    canvas.clipPath(canvas.beginPath())
    canvas.drawImage(
        image,
        x + (width - draw_w) / 2,
        y + (height - draw_h) / 2,
        draw_w,
        draw_h,
        mask="auto",
    )
    canvas.restoreState()


def draw_image_fit(
    canvas: Canvas,
    path: Path,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    background: Color = NAVY,
) -> None:
    canvas.setFillColor(background)
    canvas.roundRect(x, y, width, height, 8, fill=1, stroke=0)
    image = ImageReader(str(path))
    image_w, image_h = image.getSize()
    scale = min(width / image_w, height / image_h)
    draw_w = image_w * scale
    draw_h = image_h * scale
    canvas.drawImage(
        image,
        x + (width - draw_w) / 2,
        y + (height - draw_h) / 2,
        draw_w,
        draw_h,
        mask="auto",
    )


def draw_brand(canvas: Canvas, *, light: bool = False) -> None:
    color = white if light else NAVY
    canvas.setStrokeColor(AMBER)
    canvas.setLineWidth(2.4)
    canvas.arc(MARGIN, PAGE_H - 45, MARGIN + 24, PAGE_H - 21, 55, 270)
    canvas.setFillColor(AMBER)
    canvas.circle(MARGIN + 20, PAGE_H - 33, 2.4, fill=1, stroke=0)
    canvas.setFillColor(color)
    canvas.setFont("CG-Bold", 12)
    canvas.drawString(MARGIN + 32, PAGE_H - 37, "COLORGRAPH")


def draw_footer(canvas: Canvas, page: int, *, dark: bool = False) -> None:
    color = HexColor("#AEBBD0") if dark else MUTED
    canvas.setFillColor(color)
    canvas.setFont("CG-Regular", 7.5)
    canvas.drawString(MARGIN, 19, "AMD Radeon Hackathon 2026 | Track 1 candidate")
    canvas.drawRightString(PAGE_W - MARGIN, 19, f"{page:02d} / {TOTAL_PAGES:02d}")


def page_heading(
    canvas: Canvas,
    kicker: str,
    title: str,
    deck: str,
    page: int,
) -> float:
    draw_brand(canvas)
    canvas.setFillColor(CYAN)
    canvas.setFont("CG-Bold", 8.5)
    canvas.drawString(MARGIN, PAGE_H - 78, kicker.upper())
    canvas.setFillColor(NAVY)
    title_size = 25.0
    title_width = PAGE_W - 2 * MARGIN
    while (
        title_size > 20
        and pdfmetrics.stringWidth(title, "CG-Bold", title_size) > title_width
    ):
        title_size -= 0.5
    canvas.setFont("CG-Bold", title_size)
    canvas.drawString(MARGIN, PAGE_H - 110, title)
    y = draw_text(
        canvas,
        deck,
        MARGIN,
        PAGE_H - 132,
        PAGE_W - 2 * MARGIN,
        size=10,
        leading=13.5,
        color=MUTED,
    )
    draw_footer(canvas, page)
    return y - 12


def draw_metric(
    canvas: Canvas,
    x: float,
    y: float,
    width: float,
    value: str,
    label: str,
    *,
    accent: Color = CYAN,
) -> None:
    canvas.setFillColor(white)
    canvas.roundRect(x, y, width, 66, 8, fill=1, stroke=0)
    canvas.setFillColor(accent)
    canvas.rect(x, y, 4, 66, fill=1, stroke=0)
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 18)
    canvas.drawString(x + 15, y + 36, value)
    draw_text(canvas, label, x + 15, y + 20, width - 25, size=8, color=MUTED)


def rounded_panel(
    canvas: Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: Color = white,
    stroke: Color = LINE,
) -> None:
    canvas.setFillColor(fill)
    canvas.setStrokeColor(stroke)
    canvas.setLineWidth(0.8)
    canvas.roundRect(x, y, width, height, 10, fill=1, stroke=1)


def draw_cover(canvas: Canvas, landscape: Path) -> None:
    draw_image_cover(canvas, landscape, 0, 0, PAGE_W, PAGE_H)
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.setFillAlpha(0.78)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.restoreState()
    draw_brand(canvas, light=True)

    canvas.setFillColor(AMBER)
    canvas.roundRect(MARGIN, PAGE_H - 125, 184, 24, 12, fill=1, stroke=0)
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 8.5)
    canvas.drawCentredString(MARGIN + 92, PAGE_H - 117, "AMD RADEON HACKATHON 2026 | TRACK 1")

    canvas.setFillColor(white)
    canvas.setFont("CG-Bold", 34)
    canvas.drawString(MARGIN, PAGE_H - 210, "Local AI color grading")
    canvas.drawString(MARGIN, PAGE_H - 252, "you can inspect, edit,")
    canvas.drawString(MARGIN, PAGE_H - 294, "and trust.")
    draw_text(
        canvas,
        "ColorGraph turns evidence and creative intent into a typed, reversible "
        "Grade Graph, then validates every candidate on real frames before a "
        "human chooses what to apply.",
        MARGIN,
        PAGE_H - 335,
        430,
        size=13,
        leading=18,
        color=HexColor("#DDE6F2"),
    )

    metric_y = 122
    metric_w = (PAGE_W - 2 * MARGIN - 18) / 3
    draw_metric(canvas, MARGIN, metric_y, metric_w, "ACES 2", "Explicit OCIO color pipeline", accent=CYAN)
    draw_metric(
        canvas,
        MARGIN + metric_w + 9,
        metric_y,
        metric_w,
        "3-way",
        "Audited creative directions",
        accent=AMBER,
    )
    draw_metric(
        canvas,
        MARGIN + 2 * (metric_w + 9),
        metric_y,
        metric_w,
        "Fail-closed",
        "Hard QC + human confirmation",
        accent=GREEN,
    )

    canvas.setFillColor(HexColor("#C3CEE0"))
    canvas.setFont("CG-Regular", 9)
    canvas.drawString(MARGIN, 84, "Project Profile | 02 August 2026")
    canvas.setFillColor(AMBER)
    canvas.drawRightString(PAGE_W - MARGIN, 84, "AMD execution pending - no device claim")
    draw_footer(canvas, 1, dark=True)


def draw_background_page(canvas: Canvas) -> None:
    canvas.setFillColor(PALE)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    y = page_heading(
        canvas,
        "Project background",
        "Keep the camera original. Make the grade explainable.",
        "Creators need the speed of AI without surrendering color science, source "
        "integrity, or editorial control.",
        2,
    )
    left_w = 318
    rounded_panel(canvas, MARGIN, y - 222, left_w, 216)
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 14)
    canvas.drawString(MARGIN + 18, y - 34, "The gap")
    draw_bullets(
        canvas,
        [
            "Manual grading is precise, but slow to explore across shots, masks, and keyframes.",
            "Black-box generative workflows can be fast, but may redraw detail, hide transforms, or make revisions hard to reproduce.",
            "Professional log, high-bit-depth, VFR, and scene-scoped work need explicit technical boundaries.",
            "AI suggestions should remain proposals until measured evidence and a human decision agree.",
        ],
        MARGIN + 18,
        y - 60,
        left_w - 36,
    )

    right_x = MARGIN + left_w + 14
    right_w = PAGE_W - MARGIN - right_x
    rounded_panel(canvas, right_x, y - 222, right_w, 216, fill=NAVY, stroke=NAVY)
    canvas.setFillColor(AMBER)
    canvas.setFont("CG-Bold", 9)
    canvas.drawString(right_x + 16, y - 34, "COLORGRAPH PRINCIPLE")
    canvas.setFillColor(white)
    canvas.setFont("CG-Bold", 17)
    canvas.drawString(right_x + 16, y - 69, "AI proposes.")
    canvas.drawString(right_x + 16, y - 96, "The graph records.")
    canvas.drawString(right_x + 16, y - 123, "QC verifies.")
    canvas.drawString(right_x + 16, y - 150, "The creator decides.")
    draw_text(
        canvas,
        "No candidate silently mutates the current grade.",
        right_x + 16,
        y - 183,
        right_w - 32,
        size=8.5,
        color=HexColor("#B9C7DA"),
    )

    section_y = y - 260
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 14)
    canvas.drawString(MARGIN, section_y, "Target users and scenarios")
    cards = [
        (
            "Independent creators",
            "Fast first-pass balance, look exploration, natural-language revisions, and a portable delivery package.",
            CYAN,
        ),
        (
            "Small post teams",
            "Deterministic candidate review, scoped changes, consistent scenes, quality evidence, and exact undo.",
            AMBER,
        ),
        (
            "Education / evaluation",
            "An inspectable Grade Graph, fixed color transforms, frozen assets, and metrics that separate engineering from release claims.",
            GREEN,
        ),
    ]
    card_w = (PAGE_W - 2 * MARGIN - 20) / 3
    for index, (heading, body, accent) in enumerate(cards):
        x = MARGIN + index * (card_w + 10)
        rounded_panel(canvas, x, section_y - 190, card_w, 168)
        canvas.setFillColor(accent)
        canvas.roundRect(x + 14, section_y - 53, 34, 5, 2.5, fill=1, stroke=0)
        canvas.setFillColor(NAVY)
        canvas.setFont("CG-Bold", 11)
        draw_text(canvas, heading, x + 14, section_y - 77, card_w - 28, font="CG-Bold", size=11, leading=14)
        draw_text(canvas, body, x + 14, section_y - 113, card_w - 28, size=8.5, leading=12, color=MUTED)

    canvas.setFillColor(CYAN_PALE)
    canvas.roundRect(MARGIN, 62, PAGE_W - 2 * MARGIN, 48, 8, fill=1, stroke=0)
    canvas.setFillColor(INK)
    canvas.setFont("CG-Bold", 9.5)
    canvas.drawString(MARGIN + 14, 91, "Outcome")
    draw_text(
        canvas,
        "A local workstation that accelerates creative exploration while leaving a reversible, reviewable technical record.",
        MARGIN + 72,
        91,
        PAGE_W - 2 * MARGIN - 88,
        size=8.8,
        color=INK,
    )


def draw_product_page(canvas: Canvas, ui_image: Path, fallback: Path) -> None:
    canvas.setFillColor(white)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    y = page_heading(
        canvas,
        "Product experience",
        "One workstation from evidence to delivery",
        "The interface keeps source, graded preview, timeline, masks, keyframes, "
        "Agent candidates, graph nodes, and export evidence in the same context.",
        3,
    )
    image_path = ui_image if ui_image.is_file() else fallback
    draw_image_fit(canvas, image_path, MARGIN, y - 300, PAGE_W - 2 * MARGIN, 284)
    canvas.setFillColor(MUTED)
    canvas.setFont("CG-Regular", 7.5)
    canvas.drawString(
        MARGIN,
        y - 313,
        "Current local workstation UI (Chinese localization); this Project Profile is the English submission artifact.",
    )

    flow_y = y - 363
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 13)
    canvas.drawString(MARGIN, flow_y, "Creator flow")
    steps = [
        ("01", "Import", "Local path or upload"),
        ("02", "Analyze", "Shots + color evidence"),
        ("03", "Explore", "Looks + 3 Agent directions"),
        ("04", "Refine", "Masks + keyframes + language"),
        ("05", "Deliver", "Render + QA + package"),
    ]
    step_w = (PAGE_W - 2 * MARGIN - 32) / 5
    for index, (number, heading, detail) in enumerate(steps):
        x = MARGIN + index * (step_w + 8)
        rounded_panel(canvas, x, flow_y - 122, step_w, 100, fill=PALE)
        canvas.setFillColor(CYAN if index < 4 else AMBER)
        canvas.setFont("CG-Bold", 8)
        canvas.drawString(x + 11, flow_y - 43, number)
        canvas.setFillColor(NAVY)
        canvas.setFont("CG-Bold", 10)
        canvas.drawString(x + 11, flow_y - 65, heading)
        draw_text(canvas, detail, x + 11, flow_y - 83, step_w - 22, size=7.4, leading=9.5, color=MUTED)
        if index < len(steps) - 1:
            canvas.setStrokeColor(LINE)
            canvas.setLineWidth(1.4)
            canvas.line(x + step_w + 1, flow_y - 72, x + step_w + 7, flow_y - 72)

    canvas.setFillColor(NAVY_2)
    canvas.roundRect(MARGIN, 58, PAGE_W - 2 * MARGIN, 84, 9, fill=1, stroke=0)
    canvas.setFillColor(AMBER)
    canvas.setFont("CG-Bold", 9)
    canvas.drawString(MARGIN + 16, 118, "REVERSIBLE BY DESIGN")
    draw_text(
        canvas,
        "Every applied command has a precise scope and undo record. Candidate search, playback previews, and final rendering are content-addressed so stale work is invalidated rather than reused silently.",
        MARGIN + 16,
        97,
        PAGE_W - 2 * MARGIN - 32,
        size=9,
        leading=12,
        color=HexColor("#D5DFEC"),
    )


def draw_color_page(canvas: Canvas) -> None:
    canvas.setFillColor(PALE)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    y = page_heading(
        canvas,
        "Core architecture",
        "Color science stays explicit end to end",
        "ColorGraph does not hide color management inside a preset. Transforms, "
        "creative operations, scopes, and output intent are versioned graph data.",
        4,
    )

    pipeline = [
        ("SOURCE", "Metadata + override", CYAN),
        ("INPUT", "IDT / log decode", CYAN),
        ("ACES2065-1", "Interchange", CYAN),
        ("ACEScg", "Scene-linear work", AMBER),
        ("ACEScct", "Creative operators", AMBER),
        ("ACES 2", "Display / view", GREEN),
        ("OUTPUT", "Rec.1886 / Main10", GREEN),
    ]
    pipe_y = y - 102
    node_w = (PAGE_W - 2 * MARGIN - 36) / 7
    for index, (label, detail, accent) in enumerate(pipeline):
        x = MARGIN + index * (node_w + 6)
        rounded_panel(canvas, x, pipe_y, node_w, 74, fill=white)
        canvas.setFillColor(accent)
        canvas.rect(x, pipe_y + 68, node_w, 6, fill=1, stroke=0)
        draw_text(canvas, label, x + 7, pipe_y + 49, node_w - 14, font="CG-Bold", size=7.6, leading=9, color=NAVY)
        draw_text(canvas, detail, x + 7, pipe_y + 25, node_w - 14, size=6.8, leading=8.5, color=MUTED)
        if index < len(pipeline) - 1:
            canvas.setStrokeColor(MUTED)
            canvas.setLineWidth(0.8)
            canvas.line(x + node_w + 1, pipe_y + 37, x + node_w + 5, pipe_y + 37)

    left_y = pipe_y - 30
    panel_w = (PAGE_W - 2 * MARGIN - 12) / 2
    rounded_panel(canvas, MARGIN, left_y - 250, panel_w, 238, fill=white)
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 13)
    canvas.drawString(MARGIN + 16, left_y - 40, "Typed Grade Graph")
    draw_bullets(
        canvas,
        [
            "Strict Pydantic graph contracts with renderer and schema versions.",
            "Project, scene, shot, sub-shot, time, global, mask, and composite scopes.",
            "Exposure, CCT/Duv balance, CDL, contrast, saturation, highlights, curves, LUTs, and PCHIP keyframes.",
            "Scene-isolated looks and content-addressed preview invalidation.",
            "Exact graph diff, candidate contract, undo graph, and export manifest.",
        ],
        MARGIN + 16,
        left_y - 67,
        panel_w - 32,
        size=8.3,
        leading=11.5,
        gap=5,
    )

    right_x = MARGIN + panel_w + 12
    rounded_panel(canvas, right_x, left_y - 250, panel_w, 238, fill=NAVY, stroke=NAVY)
    canvas.setFillColor(AMBER)
    canvas.setFont("CG-Bold", 13)
    canvas.drawString(right_x + 16, left_y - 40, "High-bit-depth render path")
    dark_bullets = [
        "FFprobe preserves range, primaries, transfer, matrix, depth, chroma, HDR, and evidence confidence.",
        "rgb48le handoff and FP32 grading for the formal render.",
        "CFR streaming or VFR PTS reconstruction with frame/audio round-trip gates.",
        "HEVC Main10 hardware selection where verified; software fallback remains explicit.",
        "Post-render QA can apply one bounded, targeted repair and re-verify.",
    ]
    cursor = left_y - 67
    for item in dark_bullets:
        lines = wrap_lines(item, "CG-Regular", 8.3, panel_w - 47)
        canvas.setFillColor(AMBER)
        canvas.circle(right_x + 19, cursor + 2, 2.1, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#D6E0ED"))
        canvas.setFont("CG-Regular", 8.3)
        for idx, line in enumerate(lines):
            canvas.drawString(right_x + 29, cursor - idx * 11.5, line)
        cursor -= len(lines) * 11.5 + 5

    feature_y = left_y - 292
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 13)
    canvas.drawString(MARGIN, feature_y, "Local perception and temporal structure")
    features = [
        ("Shots", "Current detector + explicit shadow alternatives"),
        ("Scene", "CLIP-based evidence and optional local VLM path"),
        ("Regions", "Semantic + depth anchors with temporal propagation"),
        ("Quality", "Highlights, shadows, gamut, structure, flicker, masks"),
    ]
    feature_w = (PAGE_W - 2 * MARGIN - 18) / 4
    for index, (heading, detail) in enumerate(features):
        x = MARGIN + index * (feature_w + 6)
        rounded_panel(canvas, x, feature_y - 98, feature_w, 80, fill=white)
        canvas.setFillColor(CYAN if index % 2 == 0 else AMBER)
        canvas.setFont("CG-Bold", 9)
        canvas.drawString(x + 10, feature_y - 40, heading)
        draw_text(canvas, detail, x + 10, feature_y - 59, feature_w - 20, size=7.2, leading=9.2, color=MUTED)


def draw_agent_page(canvas: Canvas) -> None:
    canvas.setFillColor(white)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    y = page_heading(
        canvas,
        "AI and algorithm design",
        "Creative intelligence inside a deterministic boundary",
        "The Agent reasons over signed evidence and typed capabilities. It cannot "
        "invent renderer nodes, bypass QC, or apply a result without confirmation.",
        5,
    )
    stages = [
        "Evidence pack",
        "Closed-book Director",
        "Typed Strategist",
        "Deterministic compiler",
        "Real-frame search",
        "Hard QC",
        "Human apply",
    ]
    stage_y = y - 68
    stage_w = (PAGE_W - 2 * MARGIN - 36) / 7
    for index, stage in enumerate(stages):
        x = MARGIN + index * (stage_w + 6)
        canvas.setFillColor(NAVY if index < 6 else AMBER)
        canvas.roundRect(x, stage_y, stage_w, 54, 7, fill=1, stroke=0)
        draw_text(
            canvas,
            stage,
            x + 7,
            stage_y + 36,
            stage_w - 14,
            font="CG-Bold",
            size=7.1,
            leading=8.8,
            color=white if index < 6 else NAVY,
        )

    direction_y = stage_y - 42
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 13)
    canvas.drawString(MARGIN, direction_y, "Frozen direction grammar")
    directions = [
        (
            "FAITHFUL",
            "Contrast preserve",
            "0.00 nominal",
            "Keep the source relationship primary.",
            HexColor("#70839D"),
        ),
        (
            "AMPLIFIED",
            "Contrast increase",
            "+0.30 to +0.45",
            "Strengthen hierarchy while retaining detail.",
            CYAN,
        ),
        (
            "COUNTERPOINT",
            "Saturation decrease",
            "-0.55 to -0.40",
            "Create quiet tension without erasing structure.",
            AMBER,
        ),
    ]
    card_w = (PAGE_W - 2 * MARGIN - 16) / 3
    for index, (name, op, value, purpose, accent) in enumerate(directions):
        x = MARGIN + index * (card_w + 8)
        rounded_panel(canvas, x, direction_y - 154, card_w, 132, fill=PALE)
        canvas.setFillColor(accent)
        canvas.rect(x, direction_y - 28, card_w, 6, fill=1, stroke=0)
        canvas.setFillColor(NAVY)
        canvas.setFont("CG-Bold", 11)
        canvas.drawString(x + 13, direction_y - 52, name)
        canvas.setFillColor(accent)
        canvas.setFont("CG-Bold", 10)
        canvas.drawString(x + 13, direction_y - 74, value)
        draw_text(canvas, op, x + 13, direction_y - 94, card_w - 26, size=8.3, color=INK)
        draw_text(canvas, purpose, x + 13, direction_y - 113, card_w - 26, size=7.7, leading=10, color=MUTED)

    gate_y = direction_y - 195
    rounded_panel(canvas, MARGIN, gate_y - 224, PAGE_W - 2 * MARGIN, 206, fill=NAVY, stroke=NAVY)
    canvas.setFillColor(AMBER)
    canvas.setFont("CG-Bold", 13)
    canvas.drawString(MARGIN + 18, gate_y - 46, "Why the boundary matters")
    left_items = [
        "Evidence IDs and SHA-256 inputs are immutable.",
        "Capability catalog is generated from the current Grade Graph.",
        "Direction signature and effect floor reject near-neutral convergence.",
        "Compiler preserves input/output transforms and emits exact undo.",
    ]
    right_items = [
        "Candidates render the same frozen sample frames.",
        "Asset, schema, finite-value, and output-gamut gates are non-waivable.",
        "Provider and Critic stages are optional, budgeted, and audited.",
        "Automatic selection stays off without independent expert calibration.",
    ]
    for column, items in enumerate((left_items, right_items)):
        x = MARGIN + 18 + column * ((PAGE_W - 2 * MARGIN - 50) / 2 + 14)
        width = (PAGE_W - 2 * MARGIN - 50) / 2
        cursor = gate_y - 71
        for item in items:
            lines = wrap_lines(item, "CG-Regular", 8, width - 18)
            canvas.setFillColor(CYAN if column == 0 else AMBER)
            canvas.circle(x + 3, cursor + 2, 2, fill=1, stroke=0)
            canvas.setFillColor(HexColor("#D7E1EE"))
            canvas.setFont("CG-Regular", 8)
            for line_index, line in enumerate(lines):
                canvas.drawString(x + 13, cursor - line_index * 10.5, line)
            cursor -= len(lines) * 10.5 + 7

    canvas.setFillColor(CYAN_PALE)
    canvas.roundRect(MARGIN, 57, PAGE_W - 2 * MARGIN, 53, 8, fill=1, stroke=0)
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 9)
    canvas.drawString(MARGIN + 14, 88, "REAL-FRAME ENGINEERING CHECK")
    draw_text(
        canvas,
        "Tbilisi offline run: 3 strategies compiled, 9 samples rendered, 3/3 candidates hard-pass, 0 illegal-output samples, current graph unchanged.",
        MARGIN + 14,
        73,
        PAGE_W - 2 * MARGIN - 28,
        size=8.3,
        color=INK,
    )


def draw_demo_page(canvas: Canvas, montage: Path) -> None:
    canvas.setFillColor(PALE)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    y = page_heading(
        canvas,
        "Public demo strategy",
        "Use footage that makes the grade visible",
        "A public CC BY-SA lane supports reproduction; the premium DJI lane proves "
        "log/high-bit-depth handling locally without redistributing the source.",
        6,
    )
    if montage.is_file():
        draw_image_fit(canvas, montage, MARGIN, y - 181, PAGE_W - 2 * MARGIN, 164)
    else:
        rounded_panel(canvas, MARGIN, y - 181, PAGE_W - 2 * MARGIN, 164, fill=NAVY)
        draw_text(
            canvas,
            "Run the Tbilisi candidate audit to generate the three-direction comparison.",
            MARGIN + 20,
            y - 95,
            PAGE_W - 2 * MARGIN - 40,
            font="CG-Bold",
            size=13,
            color=white,
        )
    canvas.setFillColor(MUTED)
    canvas.setFont("CG-Regular", 7.1)
    canvas.drawString(
        MARGIN,
        y - 194,
        "Modified stills from Tbilisi life at night - Mostafameraji - CC BY-SA 4.0 | Values shown are typed strategy parameters.",
    )

    table_y = y - 235
    columns = [MARGIN, MARGIN + 104, MARGIN + 253, MARGIN + 382, PAGE_W - MARGIN]
    headers = ["ROLE", "SOURCE", "VISUAL VALUE", "PUBLIC RULE"]
    canvas.setFillColor(NAVY)
    canvas.roundRect(MARGIN, table_y - 29, PAGE_W - 2 * MARGIN, 29, 6, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("CG-Bold", 7.3)
    for index, header in enumerate(headers):
        canvas.drawString(columns[index] + 8, table_y - 18, header)
    rows = [
        (
            "Creative hero",
            "Tbilisi night",
            "Warm/cool city separation",
            "CC BY-SA; attribute + share alike",
        ),
        (
            "Workflow",
            "Snowdonia drone",
            "Cuts, terrain, water, road",
            "CC BY-SA; hash-verified download",
        ),
        (
            "Log proof",
            "DJI M3 Pro Cine",
            "4K ProRes 10-bit D-Log",
            "Local only; finished display needs terms",
        ),
    ]
    row_h = 52
    for row_index, row in enumerate(rows):
        row_top = table_y - 29 - row_index * row_h
        canvas.setFillColor(white if row_index % 2 == 0 else HexColor("#EAF0F6"))
        canvas.rect(MARGIN, row_top - row_h, PAGE_W - 2 * MARGIN, row_h, fill=1, stroke=0)
        for col_index, value in enumerate(row):
            draw_text(
                canvas,
                value,
                columns[col_index] + 8,
                row_top - 17,
                columns[col_index + 1] - columns[col_index] - 14,
                font="CG-Bold" if col_index == 0 else "CG-Regular",
                size=7.5,
                leading=9.5,
                color=NAVY if col_index == 0 else INK,
            )

    decision_y = table_y - 29 - len(rows) * row_h - 36
    panel_w = (PAGE_W - 2 * MARGIN - 12) / 2
    rounded_panel(canvas, MARGIN, decision_y - 104, panel_w, 90, fill=white)
    canvas.setFillColor(CYAN)
    canvas.setFont("CG-Bold", 11)
    canvas.drawString(MARGIN + 15, decision_y - 39, "Rights question")
    draw_text(
        canvas,
        "Does the agreement allow modification and public/commercial display of the finished work? Does it separately allow redistribution of the raw source or an extract?",
        MARGIN + 15,
        decision_y - 64,
        panel_w - 30,
        size=8.3,
        leading=11.5,
        color=INK,
    )
    right_x = MARGIN + panel_w + 12
    rounded_panel(canvas, right_x, decision_y - 104, panel_w, 90, fill=NAVY, stroke=NAVY)
    canvas.setFillColor(AMBER)
    canvas.setFont("CG-Bold", 11)
    canvas.drawString(right_x + 15, decision_y - 39, "Size question")
    draw_text(
        canvas,
        "Even with redistribution rights, the full DJI source is 25.68 GB and a five-second ProRes extract is about 1.05 GB. Neither belongs in normal Git history.",
        right_x + 15,
        decision_y - 64,
        panel_w - 30,
        size=8.3,
        leading=11.5,
        color=HexColor("#D7E1EE"),
    )
    canvas.setFillColor(AMBER_PALE)
    canvas.roundRect(MARGIN, 57, PAGE_W - 2 * MARGIN, 48, 8, fill=1, stroke=0)
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 8.2)
    canvas.drawString(MARGIN + 14, 86, "VIDEO DELIVERABLE PAUSED")
    draw_text(
        canvas,
        "This profile freezes footage and visual direction only. No final 3-5 minute demo video has been created.",
        MARGIN + 14,
        71,
        PAGE_W - 2 * MARGIN - 28,
        size=7.6,
        leading=9.5,
        color=INK,
    )


def draw_amd_page(canvas: Canvas) -> None:
    canvas.setFillColor(white)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    y = page_heading(
        canvas,
        "AMD adaptation",
        "Portable architecture, fail-closed Radeon proof",
        "The compute boundary is designed for PyTorch ROCm. The project does not "
        "convert CUDA preflight results into AMD claims; a supported Radeon host "
        "must produce the final evidence.",
        7,
    )

    canvas.setFillColor(AMBER_PALE)
    canvas.roundRect(MARGIN, y - 55, PAGE_W - 2 * MARGIN, 43, 8, fill=1, stroke=0)
    canvas.setFillColor(RED)
    canvas.setFont("CG-Bold", 9)
    canvas.drawString(MARGIN + 14, y - 31, "STATUS")
    draw_text(
        canvas,
        "Engineering boundary implemented; real AMD Radeon / ROCm execution is pending and intentionally paused.",
        MARGIN + 65,
        y - 31,
        PAGE_W - 2 * MARGIN - 79,
        font="CG-Bold",
        size=8.6,
        color=NAVY,
    )

    section_y = y - 92
    panel_w = (PAGE_W - 2 * MARGIN - 12) / 2
    rounded_panel(canvas, MARGIN, section_y - 258, panel_w, 244, fill=PALE)
    canvas.setFillColor(CYAN)
    canvas.setFont("CG-Bold", 12)
    canvas.drawString(MARGIN + 16, section_y - 42, "Already in the architecture")
    draw_bullets(
        canvas,
        [
            "ComputeBackend exposes device, inference context, synchronization, cache release, and structured identity.",
            "TorchComputeBackend distinguishes HIP from CUDA through torch.version.hip while using standard PyTorch tensor APIs.",
            "Core grading and model paths avoid custom CUDA, Triton, FlashAttention, xFormers, and .cu extensions.",
            "Windows ROCm encoding selects H.264/HEVC AMF only after preflight; software fallback remains explicit.",
            "Stage evidence rejects non-ROCm runtime, non-AMD vendor, empty HIP identity, or unverified tensor placement.",
        ],
        MARGIN + 16,
        section_y - 68,
        panel_w - 32,
        size=8.1,
        leading=11,
        gap=5,
    )

    right_x = MARGIN + panel_w + 12
    rounded_panel(canvas, right_x, section_y - 258, panel_w, 244, fill=NAVY, stroke=NAVY)
    canvas.setFillColor(AMBER)
    canvas.setFont("CG-Bold", 12)
    canvas.drawString(right_x + 16, section_y - 42, "Required on the target Radeon")
    target_steps = [
        "Verify supported GPU, driver, ROCm/HIP, PyTorch wheel, FFmpeg, and AMF identity.",
        "Run doctor and three-repeat CPU FP32 vs ROCm FP32 precision gate.",
        "Run local CLIP, semantic, depth, and configured VLM stages with GPU placement evidence.",
        "Fresh-render the public frozen clip, including mask and no-mask rows.",
        "Verify HEVC Main10, timestamps, masks, quality report, hashes, warm FPS, latency, and peak VRAM.",
        "Repeat the complete run and retain the signed, content-bound evidence package.",
    ]
    cursor = section_y - 69
    for index, item in enumerate(target_steps, start=1):
        canvas.setFillColor(AMBER)
        canvas.circle(right_x + 22, cursor + 1, 9, fill=1, stroke=0)
        canvas.setFillColor(NAVY)
        canvas.setFont("CG-Bold", 7.5)
        canvas.drawCentredString(right_x + 22, cursor - 1.5, str(index))
        lines = wrap_lines(item, "CG-Regular", 8, panel_w - 54)
        canvas.setFillColor(HexColor("#D7E1EE"))
        canvas.setFont("CG-Regular", 8)
        for idx, line in enumerate(lines):
            canvas.drawString(right_x + 40, cursor + 3 - idx * 10.5, line)
        cursor -= max(23, len(lines) * 10.5 + 8)

    map_y = section_y - 296
    canvas.setFillColor(NAVY)
    canvas.setFont("CG-Bold", 13)
    canvas.drawString(MARGIN, map_y, "Honest execution boundary")
    lanes = [
        (
            "RADEON / ROCm GPU",
            "CLIP | semantic | depth | VLM | Grade Graph | LUT | mask blend | ACES 2 output",
            CYAN,
        ),
        (
            "MEDIA / CPU BOUNDARY",
            "Demux | high-bit-depth decode | audio mux | file hash | post-render measurement",
            AMBER,
        ),
    ]
    for index, (heading, body, accent) in enumerate(lanes):
        lane_y = map_y - 62 - index * 74
        canvas.setFillColor(NAVY if index == 0 else PALE)
        canvas.roundRect(MARGIN, lane_y, PAGE_W - 2 * MARGIN, 56, 8, fill=1, stroke=0)
        canvas.setFillColor(accent)
        canvas.rect(MARGIN, lane_y, 6, 56, fill=1, stroke=0)
        canvas.setFillColor(white if index == 0 else NAVY)
        canvas.setFont("CG-Bold", 8.6)
        canvas.drawString(MARGIN + 18, lane_y + 35, heading)
        draw_text(
            canvas,
            body,
            MARGIN + 151,
            lane_y + 35,
            PAGE_W - MARGIN - (MARGIN + 169),
            size=8,
            leading=10.5,
            color=HexColor("#D7E1EE") if index == 0 else MUTED,
        )

    canvas.setFillColor(CYAN_PALE)
    canvas.roundRect(MARGIN, 57, PAGE_W - 2 * MARGIN, 44, 8, fill=1, stroke=0)
    draw_text(
        canvas,
        "Release rule: only evidence whose runtime=rocm, vendor=AMD, HIP identity, tensor placement, encoder preflight, media hashes, and quality gates all agree may be described as AMD-verified.",
        MARGIN + 14,
        84,
        PAGE_W - 2 * MARGIN - 28,
        font="CG-Bold",
        size=8.1,
        leading=10.5,
        color=NAVY,
    )


def draw_delivery_page(canvas: Canvas) -> None:
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    draw_brand(canvas, light=True)
    canvas.setFillColor(CYAN)
    canvas.setFont("CG-Bold", 8.5)
    canvas.drawString(MARGIN, PAGE_H - 78, "DELIVERY AND READINESS")
    canvas.setFillColor(white)
    canvas.setFont("CG-Bold", 27)
    canvas.drawString(MARGIN, PAGE_H - 112, "Reproducible now.")
    canvas.drawString(MARGIN, PAGE_H - 146, "Submission-complete later.")
    draw_text(
        canvas,
        "The non-AMD package is prepared without hiding the remaining competition gates.",
        MARGIN,
        PAGE_H - 173,
        PAGE_W - 2 * MARGIN,
        size=11,
        color=HexColor("#BFCBDB"),
    )

    top_y = PAGE_H - 220
    panel_w = (PAGE_W - 2 * MARGIN - 12) / 2
    canvas.setFillColor(HexColor("#12223A"))
    canvas.roundRect(MARGIN, top_y - 272, panel_w, 254, 10, fill=1, stroke=0)
    canvas.setFillColor(GREEN)
    canvas.setFont("CG-Bold", 12)
    canvas.drawString(MARGIN + 16, top_y - 47, "Prepared")
    prepared = [
        "English source README and architecture",
        "Public media downloader + immutable hashes",
        "Third-party attribution and DJI rights boundary",
        "Visible three-direction strategy contract",
        "Real-frame hard-QC evidence",
        "Non-AMD CI and regression commands",
        "English Project Profile PDF",
    ]
    cursor = top_y - 75
    for item in prepared:
        canvas.setStrokeColor(GREEN)
        canvas.setLineWidth(1.2)
        canvas.circle(MARGIN + 21, cursor + 2, 5, fill=0, stroke=1)
        canvas.line(MARGIN + 18, cursor + 2, MARGIN + 20, cursor - 1)
        canvas.line(MARGIN + 20, cursor - 1, MARGIN + 25, cursor + 5)
        draw_text(canvas, item, MARGIN + 34, cursor + 6, panel_w - 50, size=8.2, color=HexColor("#D7E1EE"))
        cursor -= 27

    right_x = MARGIN + panel_w + 12
    canvas.setFillColor(HexColor("#12223A"))
    canvas.roundRect(right_x, top_y - 272, panel_w, 254, 10, fill=1, stroke=0)
    canvas.setFillColor(AMBER)
    canvas.setFont("CG-Bold", 12)
    canvas.drawString(right_x + 16, top_y - 47, "Still required")
    remaining = [
        "Project source-code license decision",
        "Actual DJI authorization review (if used)",
        "Supported Radeon / ROCm full execution",
        "Measured AMD FPS / latency / VRAM evidence",
        "Final 3-5 minute demo video",
        "PPT or Poster",
        "Public repository + official contest PR",
    ]
    cursor = top_y - 75
    for item in remaining:
        canvas.setStrokeColor(AMBER)
        canvas.setLineWidth(1.1)
        canvas.circle(right_x + 21, cursor + 2, 5, fill=0, stroke=1)
        draw_text(canvas, item, right_x + 34, cursor + 6, panel_w - 50, size=8.2, color=HexColor("#D7E1EE"))
        cursor -= 27

    command_y = top_y - 314
    canvas.setFillColor(white)
    canvas.setFont("CG-Bold", 13)
    canvas.drawString(MARGIN, command_y, "Public reproduction")
    canvas.setFillColor(HexColor("#050B14"))
    canvas.roundRect(MARGIN, command_y - 118, PAGE_W - 2 * MARGIN, 96, 8, fill=1, stroke=0)
    commands = [
        ".\\scripts\\fetch-demo-assets.ps1 -Asset all",
        "uv run --project backend colorgraph analyze .\\demo-assets\\tbilisi-night-canon-eos-m3.ogv --skip-scene-model",
        "npm run build",
        "uv run --project backend pytest",
    ]
    canvas.setFillColor(CYAN)
    canvas.setFont("CG-Regular", 7.7)
    cursor = command_y - 48
    for command in commands:
        canvas.drawString(MARGIN + 16, cursor, command)
        cursor -= 19

    canvas.setFillColor(HexColor("#12223A"))
    canvas.roundRect(MARGIN, 78, PAGE_W - 2 * MARGIN, 92, 9, fill=1, stroke=0)
    canvas.setFillColor(AMBER)
    canvas.setFont("CG-Bold", 10)
    canvas.drawString(MARGIN + 16, 142, "SOURCE AND DOCUMENTATION")
    draw_text(
        canvas,
        "github.com/panbu2007/color  |  README.md  |  docs/SUBMISSION_CHECKLIST.md  |  docs/DEMO_ASSETS.md",
        MARGIN + 16,
        119,
        PAGE_W - 2 * MARGIN - 32,
        font="CG-Bold",
        size=8.5,
        color=white,
    )
    draw_text(
        canvas,
        "ColorGraph makes the creative path faster without making the evidence disappear.",
        MARGIN + 16,
        95,
        PAGE_W - 2 * MARGIN - 32,
        size=8.5,
        color=HexColor("#BFCBDB"),
    )
    draw_footer(canvas, 8, dark=True)


def build_pdf(output: Path) -> None:
    register_fonts()
    landscape = ROOT / "public" / "assets" / "colorgraph-landscape.png"
    ui_image = ROOT / "output" / "playwright" / "colorgraph-final-mvp.png"
    montage = ROOT / "tmp" / "pdfs" / "assets" / "tbilisi-directions.png"
    if not landscape.is_file():
        raise FileNotFoundError(f"missing cover asset: {landscape}")

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(output), pagesize=A4, pageCompression=1)
    canvas.setTitle("ColorGraph Project Profile")
    canvas.setAuthor("ColorGraph")
    canvas.setSubject("AMD Radeon Hackathon 2026 Track 1 project profile")
    canvas.setKeywords("ColorGraph, color grading, AI, ACES, AMD Radeon, ROCm")

    pages = [
        lambda: draw_cover(canvas, landscape),
        lambda: draw_background_page(canvas),
        lambda: draw_product_page(canvas, ui_image, landscape),
        lambda: draw_color_page(canvas),
        lambda: draw_agent_page(canvas),
        lambda: draw_demo_page(canvas, montage),
        lambda: draw_amd_page(canvas),
        lambda: draw_delivery_page(canvas),
    ]
    for index, draw_page in enumerate(pages):
        draw_page()
        if index < len(pages) - 1:
            canvas.showPage()
    canvas.save()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the English ColorGraph Project Profile PDF")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "pdf" / "ColorGraph-Project-Profile.pdf",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    build_pdf(output)
    print(output)


if __name__ == "__main__":
    main()

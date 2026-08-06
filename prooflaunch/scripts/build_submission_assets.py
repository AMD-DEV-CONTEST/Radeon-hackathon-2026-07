from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    Flowable,
    Image as RLImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
NOTEBOOKS = ROOT / "notebooks"
SCREENSHOT = ROOT / "web" / "evidence-desktop-viewport.png"
REFERENCE_ASSET = DOCS / "assets" / "prooflaunch-field-journal-v5-desktop-fold.png"
POSTER_VISUAL = ROOT / "evidence" / "v10" / "web-field-journal-v5-final-mobile-fold-2026-08-06-c.png"

INK = colors.HexColor("#20251F")
SOFT = colors.HexColor("#5D625A")
CREAM = colors.HexColor("#F8F5ED")
PAGE = colors.HexColor("#ECE8DE")
RUST = colors.HexColor("#AA4D2C")
GREEN = colors.HexColor("#2F6C4E")
AMBER = colors.HexColor("#8C5A10")
RED = colors.HexColor("#9D3F34")
LINE = colors.HexColor("#C6C0B4")


def register_fonts() -> tuple[str, str]:
    candidates = [
        (
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ),
        (
            Path("/System/Library/Fonts/Helvetica.ttc"),
            Path("/System/Library/Fonts/Helvetica.ttc"),
        ),
    ]
    for regular, bold in candidates:
        if regular.exists() and bold.exists() and regular.suffix == ".ttf":
            pdfmetrics.registerFont(TTFont("PLSans", str(regular)))
            pdfmetrics.registerFont(TTFont("PLSans-Bold", str(bold)))
            return "PLSans", "PLSans-Bold"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = register_fonts()


class ArchitectureFlow(Flowable):
    def __init__(self, width: float, height: float = 120 * mm) -> None:
        super().__init__()
        self.width = width
        self.height = height

    def draw(self) -> None:
        canvas = self.canv
        canvas.saveState()
        canvas.setFont(FONT_BOLD, 9)
        stages = [
            ("01", "EVIDENCE", "Hash + rights\nLocated claims"),
            ("02", "PLAN", "Claim-bound\nchannel intent"),
            ("03", "CREATE", "Radeon-targeted\nmedia candidates"),
            ("04", "AUDIT", "Six release\ngates"),
            ("05", "REPAIR", "≤2 bounded\nrounds"),
            ("06", "DELIVER", "Human gate\n+ hash ledger"),
        ]
        gap = 5 * mm
        box_w = (self.width - gap) / 2
        box_h = 31 * mm
        y = self.height - box_h
        for index, (number, title, detail) in enumerate(stages):
            column = index % 2
            row = index // 2
            x = column * (box_w + gap)
            y = self.height - (row + 1) * box_h - row * gap
            canvas.setFillColor(CREAM)
            canvas.setStrokeColor(INK)
            canvas.rect(x, y, box_w, box_h, fill=1, stroke=1)
            canvas.setFillColor(RUST)
            canvas.rect(x, y, 14 * mm, box_h, fill=1, stroke=0)
            canvas.setFillColor(colors.white)
            canvas.drawCentredString(x + 7 * mm, y + 14 * mm, number)
            canvas.setFillColor(INK)
            canvas.drawString(x + 18 * mm, y + 20 * mm, title)
            canvas.setFont(FONT, 8)
            for line_index, line in enumerate(detail.splitlines()):
                canvas.drawString(x + 18 * mm, y + 11 * mm - line_index * 4 * mm, line)
            canvas.setFont(FONT_BOLD, 9)
        canvas.restoreState()


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            fontName=FONT_BOLD,
            fontSize=30,
            leading=32,
            textColor=INK,
            spaceAfter=8 * mm,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            fontName=FONT,
            fontSize=14,
            leading=20,
            textColor=SOFT,
            spaceAfter=7 * mm,
        ),
        "h1": ParagraphStyle(
            "H1",
            fontName=FONT_BOLD,
            fontSize=22,
            leading=25,
            textColor=INK,
            spaceAfter=6 * mm,
        ),
        "h2": ParagraphStyle(
            "H2",
            fontName=FONT_BOLD,
            fontSize=12,
            leading=15,
            textColor=RUST,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName=FONT,
            fontSize=9.8,
            leading=14,
            textColor=INK,
            spaceAfter=3.5 * mm,
        ),
        "small": ParagraphStyle(
            "Small",
            fontName=FONT,
            fontSize=8,
            leading=11,
            textColor=SOFT,
        ),
        "eyebrow": ParagraphStyle(
            "Eyebrow",
            fontName=FONT_BOLD,
            fontSize=8,
            leading=10,
            textColor=RUST,
            tracking=1.2,
            spaceAfter=5 * mm,
        ),
        "center": ParagraphStyle(
            "Center",
            fontName=FONT_BOLD,
            fontSize=11,
            leading=14,
            textColor=INK,
            alignment=TA_CENTER,
        ),
    }


ST = styles()


def bullet(text: str) -> Paragraph:
    return Paragraph(f"• {text}", ST["body"])


def page_header(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(PAGE)
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.setFillColor(RUST)
    canvas.rect(0, A4[1] - 7 * mm, A4[0], 7 * mm, fill=1, stroke=0)
    canvas.setFillColor(SOFT)
    canvas.setFont(FONT, 7.5)
    canvas.drawString(18 * mm, 11 * mm, "BANYAN · PROOFLAUNCH · AMD RADEON HACKATHON 2026-07 · TRACK 1")
    canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, f"{doc.page:02d}")
    canvas.restoreState()


def build_profile_pdf() -> None:
    output = DOCS / "ProofLaunch_Project_Profile.pdf"
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=19 * mm,
        bottomMargin=18 * mm,
        title="ProofLaunch Project Profile",
        author="Banyan",
    )
    story = []

    story += [
        Spacer(1, 25 * mm),
        Paragraph("TRACK 1 · MULTIMODAL CONTENT CREATION", ST["eyebrow"]),
        Paragraph("ProofLaunch", ST["title"]),
        Paragraph(
            "Multimodal GTM Studio for AMD Radeon / ROCm",
            ST["subtitle"],
        ),
        Paragraph("TEAM BANYAN", ST["eyebrow"]),
        Spacer(1, 8 * mm),
        Table(
            [
                ["INPUT", "Owned image / PDF / audio / video / text evidence"],
                ["OUTPUT", "Audited image + video campaign pack + evidence ledger"],
                ["CONTROL", "One Supervisor · human approval · maximum two repairs"],
                ["STATUS", "Finished product website ready; live Radeon receipt pending"],
            ],
            colWidths=[30 * mm, 132 * mm],
            style=[
                ("BACKGROUND", (0, 0), (-1, -1), CREAM),
                ("GRID", (0, 0), (-1, -1), 0.6, LINE),
                ("FONTNAME", (0, 0), (0, -1), FONT_BOLD),
                ("FONTNAME", (1, 0), (1, -1), FONT),
                ("TEXTCOLOR", (0, 0), (0, -1), RUST),
                ("TEXTCOLOR", (1, 0), (1, -1), INK),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ],
        ),
        Spacer(1, 18 * mm),
        Paragraph(
            "From product evidence to publish-safe campaign assets—without "
            "fabricated claims, redrawn products, or hidden repair history.",
            ParagraphStyle(
                "Statement",
                parent=ST["h1"],
                fontSize=19,
                leading=24,
                textColor=INK,
                alignment=TA_LEFT,
            ),
        ),
        Spacer(1, 4 * mm),
        RLImage(str(REFERENCE_ASSET), width=80 * mm, height=55.5 * mm, hAlign="CENTER"),
        PageBreak(),
        Paragraph("01 · PROJECT BACKGROUND", ST["eyebrow"]),
        Paragraph("Creative speed is not enough when product truth breaks.", ST["h1"]),
        Paragraph(
            "Generative campaign tools can produce many variants quickly, but "
            "unsupported claims, altered product identity, unreadable text, unsafe "
            "platform layouts, and missing provenance turn generation speed into "
            "release risk.",
            ST["body"],
        ),
        Paragraph("ProofLaunch changes the unit of work", ST["h2"]),
        bullet("Every commercial claim starts as an approved source span and Claim ID."),
        bullet("The original product remains a protected compositing layer."),
        bullet("Every candidate is audited before it can reach export."),
        bullet("Repairs are explicit, bounded, and retained in the evidence history."),
        bullet("Unknown or unavailable proof blocks release instead of becoming a claim."),
        Spacer(1, 8 * mm),
        Table(
            [
                ["WITHOUT PROOFLAUNCH", "WITH PROOFLAUNCH"],
                ["Prompt → image → manual guess", "Evidence → gated campaign pack"],
                ["Untraceable text claims", "Source span → Claim ID → exact copy"],
                ["Product may be redrawn", "Identity Lock protects the original layer"],
                ["Silent retries", "Maximum two recorded repair rounds"],
                ["Export by appearance", "Export by inspectable release gates"],
            ],
            colWidths=[81 * mm, 81 * mm],
            style=[
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), CREAM),
                ("GRID", (0, 0), (-1, -1), 0.6, LINE),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ],
        ),
        PageBreak(),
        Paragraph("02 · USERS & SCENARIOS", ST["eyebrow"]),
        Paragraph("Built for the operator who must defend the final asset.", ST["h1"]),
        Paragraph(
            "<b>Primary users:</b> campaign operators, owner-reviewers, and technical "
            "qualifiers at small ecommerce and hardware organizations.",
            ST["body"],
        ),
        Paragraph("Primary scenario", ST["h2"]),
        ArchitectureFlow(162 * mm, 110 * mm),
        Spacer(1, 5 * mm),
        Table(
            [
                ["HUMAN DECISION", "AUTOMATED ASSISTANCE"],
                ["Approve source claims", "Extract candidate source spans"],
                ["Approve risky repairs", "Produce bounded repair proposal"],
                ["Approve external side effects", "Inspect and prepare deliverables"],
                ["Accept final release evidence", "Hash and package evidence"],
            ],
            colWidths=[81 * mm, 81 * mm],
            style=[
                ("BACKGROUND", (0, 0), (-1, 0), RUST),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), CREAM),
                ("GRID", (0, 0), (-1, -1), 0.6, LINE),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ],
        ),
        PageBreak(),
        Paragraph("03 · SYSTEM ARCHITECTURE", ST["eyebrow"]),
        Paragraph("One Supervisor; many bounded capabilities.", ST["h1"]),
        Paragraph(
            "The Supervisor is the only component allowed to change campaign state, "
            "consume retry budgets, enter export, or request approval for a side "
            "effect. External agents return observations or typed intents.",
            ST["body"],
        ),
        Table(
            [
                ["PROOFLAUNCH SUPERVISOR", "Owns state, approvals, retry budgets and export"],
                ["EVIDENCE + PLAN", "Qwen3-VL · PDF/Whisper · Claim Ledger · Director"],
                ["CREATE", "Radeon-targeted SDXL / LTX adapters · deterministic typography"],
                ["AUDIT + REPAIR", "SigLIP2 · GroundingDINO / SAM2 · CLAP · bounded repair"],
                ["HUMAN-GATED DELIVERY", "Campaign pack · SHA-256 evidence ledger · no autonomous publish/send/spend"],
            ],
            colWidths=[48 * mm, 114 * mm],
            style=[
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), CREAM),
                ("GRID", (0, 0), (-1, -1), 0.8, LINE),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (0, -1), FONT_BOLD),
                ("FONTNAME", (1, 1), (1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.4),
                ("LEADING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ],
        ),
        Spacer(1, 4 * mm),
        Paragraph("Agent remix boundary", ST["h2"]),
        bullet("Diffusers supplies the actual optional local Radeon generation adapter."),
        bullet("Pillow supplies deterministic typography and immutable-layer compositing."),
        bullet("ComfyUI remains an AMD-supported alternative backend, not bundled code."),
        bullet(
            "Qwen3-VL, GroundingDINO, Gemma, SDXL, SigLIP2, LTX, SAM2, "
            "and CLAP are configured for sequential residency."
        ),
        bullet("No upstream framework owns ProofLaunch release state."),
        PageBreak(),
        Paragraph("04 · MODELS & ALGORITHMS", ST["eyebrow"]),
        Paragraph("Models propose; deterministic gates decide release.", ST["h1"]),
        Table(
            [
                ["CAPABILITY", "IMPLEMENTATION", "BOUNDARY"],
                [
                    "Input understanding",
                    "Qwen3-VL + GroundingDINO + PDF + Whisper",
                    "Located source evidence",
                ],
                [
                    "Audience Pulse",
                    "Gemma 4 E4B-it + six-label emotion LoRA",
                    "Not conversion prediction or diagnosis",
                ],
                [
                    "Radeon Studio",
                    "Radeon-targeted SDXL still + LTX video adapters",
                    "No closed online API on the key inference path",
                ],
                [
                    "Identity Lock",
                    "Exact layer + decoded H.264 tolerance",
                    "Pre/post-codec identity",
                ],
                [
                    "Video consistency",
                    "SAM2 tracking + CLAP + A/V timing",
                    "Temporal product and cue evidence",
                ],
                [
                    "Typography",
                    "Deterministic rendering",
                    "Exact claims, model IDs, price, CTA",
                ],
                [
                    "Release Audit",
                    "Mechanical + SigLIP2 score",
                    "Six fail-closed release gates",
                ],
                [
                    "Evidence",
                    "SHA-256-linked JSONL ledger",
                    "Tampering invalidates verification",
                ],
            ],
            colWidths=[32 * mm, 67 * mm, 63 * mm],
            style=[
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), CREAM),
                ("GRID", (0, 0), (-1, -1), 0.6, LINE),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 7.8),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ],
        ),
        Spacer(1, 7 * mm),
        Paragraph("Fail-closed decisions", ST["h2"]),
        bullet("No approved source-bound claim → stop."),
        bullet("No generated asset → stop."),
        bullet("Critical finding after two repairs → stop."),
        bullet("No deliverable or provenance evidence → stop."),
        PageBreak(),
        Paragraph("05 · AMD RADEON / ROCm ADAPTATION", ST["eyebrow"]),
        Paragraph("The GPU path is designed around evidence and bounded memory.", ST["h1"]),
        bullet("Multi-GPU-first execution contract with a verified single-card fallback profile."),
        bullet("No default bitsandbytes 4-bit dependency."),
        bullet("ModelScope-local model and dataset snapshots."),
        bullet("PyTorch CUDA-compatible API surface on ROCm."),
        bullet("Sequential model loading and explicit release between large stages."),
        bullet("Frozen 450-case matrix + 30 full audio-video cases."),
        bullet("Protocol, V7 build, and named baseline settings are hash-bound."),
        bullet("Nine phase-batched passes enforce one resident model at a time."),
        bullet("Latency, peak VRAM, model reference, seed, and output hash are mandatory."),
        Spacer(1, 6 * mm),
        Table(
            [
                ["CURRENT V10 EVIDENCE", "STATUS"],
                ["Web product surface · 46 routes / 60 API contracts", "Observed locally"],
                ["UI / route validation / final integrity locks", "17/17 · 10/10 · 4/4"],
                ["Source/model/data drift locks", "Observed locally"],
                ["Radeon execution contract", "Mechanically verified"],
                ["Active Radeon instance", "Not observed"],
                ["Real post-training model evaluation", "Not observed"],
                ["Real image/video generation benchmark", "Not observed"],
                ["Independent 4A human evaluation", "Not observed"],
                ["External publication or spend", "Disabled"],
            ],
            colWidths=[120 * mm, 42 * mm],
            style=[
                ("BACKGROUND", (0, 0), (-1, 0), RUST),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), CREAM),
                ("GRID", (0, 0), (-1, -1), 0.6, LINE),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (1, 1), (1, 4), GREEN),
                ("TEXTCOLOR", (1, 5), (1, 8), RED),
                ("TEXTCOLOR", (1, 9), (1, 9), AMBER),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ],
        ),
        PageBreak(),
        Paragraph("06 · VERIFICATION & SUBMISSION GATE", ST["eyebrow"]),
        Paragraph("Submission readiness is machine-readable and fail-closed.", ST["h1"]),
        Table(
            [
                ["EVIDENCE", "RESULT"],
                ["Product-critical regression", "827 / 827 passed"],
                ["UI tests", "17 / 17 passed"],
                ["Route validation", "10 / 10 passed"],
                ["Web product surface", "46 routes / 60 API contracts"],
                ["Final integrity locks", "4 / 4 passed"],
                ["Run-bound deliverables", "10 / 10 registered"],
                ["Automatic publish / send / spend", "0"],
                ["Source/model/data lock drift", "Fail-closed"],
                ["Live Radeon model inference receipt", "Not observed"],
                ["Demo Video · 3–5 minutes recommended", "Not observed"],
                ["Official fork + compliant PR", "Not executed"],
                ["Final Evidence Seal", "Not sealed"],
            ],
            colWidths=[108 * mm, 54 * mm],
            style=[
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), CREAM),
                ("GRID", (0, 0), (-1, -1), 0.6, LINE),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (1, 1), (1, 9), GREEN),
                ("TEXTCOLOR", (1, 10), (1, -1), RED),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ],
        ),
        Spacer(1, 8 * mm),
        Paragraph("Official Track 1 package", ST["h2"]),
        bullet("English Project Profile PDF."),
        bullet("Complete source repository and reproduction README."),
        bullet("Demo Video showing actual Radeon execution (3–5 minutes recommended)."),
        bullet("Supplementary English deck."),
        bullet("Fork + English PR titled: Track 1, Banyan, ProofLaunch: Multimodal GTM Studio."),
        Spacer(1, 8 * mm),
        Paragraph(
            "A pull request is intentionally blocked until every P0 artifact in "
            "SUBMISSION_GATE.json passes. This document records present evidence; it "
            "does not replace the required Radeon run or video.",
            ParagraphStyle(
                "Gate",
                parent=ST["body"],
                backColor=CREAM,
                borderColor=RUST,
                borderWidth=1,
                borderPadding=10,
                textColor=INK,
            ),
        ),
    ]
    doc.build(story, onFirstPage=page_header, onLaterPages=page_header)


def add_textbox(slide, x, y, w, h, text, size, color, bold=False, font="Arial"):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.clear()
    paragraph = frame.paragraphs[0]
    paragraph.text = text
    paragraph.font.name = font
    paragraph.font.size = Pt(size)
    paragraph.font.bold = bold
    paragraph.font.color.rgb = color
    return box


def build_poster() -> None:
    output = DOCS / "ProofLaunch_Poster.pptx"
    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = RGBColor(236, 232, 222)

    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.16), prs.slide_height)
    accent.fill.solid()
    accent.fill.fore_color.rgb = RGBColor(170, 77, 44)
    accent.line.fill.background()

    add_textbox(
        slide,
        Inches(0.55),
        Inches(0.34),
        Inches(7.5),
        Inches(0.32),
        "TEAM BANYAN · AMD RADEON HACKATHON 2026-07 · TRACK 1",
        10,
        RGBColor(170, 77, 44),
        True,
    )
    add_textbox(
        slide,
        Inches(0.55),
        Inches(0.72),
        Inches(7.5),
        Inches(0.8),
        "ProofLaunch",
        36,
        RGBColor(32, 37, 31),
        True,
    )
    add_textbox(
        slide,
        Inches(0.55),
        Inches(1.46),
        Inches(7.8),
        Inches(0.62),
        "Multimodal GTM Studio for AMD Radeon / ROCm",
        15,
        RGBColor(93, 98, 90),
        False,
    )

    stages = ["EVIDENCE", "PLAN", "CREATE", "AUDIT", "REPAIR ≤2", "DELIVER"]
    stage_x = Inches(0.55)
    stage_y = Inches(2.25)
    stage_w = Inches(0.99)
    gap = Inches(0.05)
    for index, stage in enumerate(stages):
        shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            stage_x + index * (stage_w + gap),
            stage_y,
            stage_w,
            Inches(0.72),
        )
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(248, 245, 237)
        shape.line.color.rgb = RGBColor(145, 140, 130)
        frame = shape.text_frame
        frame.clear()
        p = frame.paragraphs[0]
        p.text = f"{index + 1:02d}\n{stage}"
        p.alignment = PP_ALIGN.CENTER
        p.font.name = "Arial"
        p.font.size = Pt(8.5)
        p.font.bold = True
        p.font.color.rgb = RGBColor(32, 37, 31)

    add_textbox(
        slide,
        Inches(0.55),
        Inches(3.30),
        Inches(3.4),
        Inches(0.34),
        "WHY IT IS DIFFERENT",
        11,
        RGBColor(170, 77, 44),
        True,
    )
    differentiators = [
        "Image/PDF/audio/video evidence keeps source locators.",
        "The original product stays protected in still and video.",
        "Post-codec identity, SAM2, CLAP, and A/V gates expose drift.",
        "Radeon preflight, 450-case runner/compiler, and ≤2 repairs fail closed.",
    ]
    for index, item in enumerate(differentiators):
        add_textbox(
            slide,
            Inches(0.55),
            Inches(3.70 + index * 0.53),
            Inches(4.9),
            Inches(0.38),
            f"0{index + 1}  {item}",
            11,
            RGBColor(32, 37, 31),
            index == 0,
        )

    add_textbox(
        slide,
        Inches(0.55),
        Inches(6.12),
        Inches(6.2),
        Inches(0.46),
        "One Supervisor owns state, approval, retry budgets, and release evidence.",
        12,
        RGBColor(32, 37, 31),
        True,
    )
    add_textbox(
        slide,
        Inches(0.55),
        Inches(6.65),
        Inches(6.3),
        Inches(0.34),
        "827/827 product-critical · UI 17/17 · routes 10/10 · final locks 4/4 · live Radeon/video/PR remain open.",
        9,
        RGBColor(157, 63, 52),
        False,
    )

    poster_visual = POSTER_VISUAL if POSTER_VISUAL.exists() else REFERENCE_ASSET
    if poster_visual.exists():
        with Image.open(poster_visual) as image:
            image_ratio = image.width / image.height
        target_h = Inches(5.55)
        target_w = target_h * image_ratio
        if target_w > Inches(5.55):
            target_w = Inches(5.55)
            target_h = target_w / image_ratio
        if target_h > Inches(5.6):
            target_h = Inches(5.6)
            target_w = target_h * image_ratio
        slide.shapes.add_picture(
            str(poster_visual),
            Inches(8.75),
            Inches(0.70),
            width=target_w,
            height=target_h,
        )
        frame = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(8.70),
            Inches(0.65),
            target_w + Inches(0.10),
            target_h + Inches(0.10),
        )
        frame.fill.background()
        frame.line.color.rgb = RGBColor(32, 37, 31)
        frame.line.width = Pt(1.2)
        add_textbox(
            slide,
            Inches(7.05),
            Inches(6.45),
            Inches(5.7),
            Inches(0.32),
            "FIELD JOURNAL V5 · FINISHED PRODUCT WEBSITE · HUMAN-GATED RELEASE",
            8,
            RGBColor(157, 63, 52),
            True,
        )
    prs.save(output)


def build_notebook() -> None:
    NOTEBOOKS.mkdir(parents=True, exist_ok=True)
    output = NOTEBOOKS / "prooflaunch_radeon_gate_v2.ipynb"
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# ProofLaunch Radeon submission gate\n",
                "\n",
                "Run only after the kernel status is **Connected**. This Notebook "
                "does not publish, send, overwrite the original Gemma Notebook, or "
                "claim success before evidence exists.\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from pathlib import Path\n",
                "import hashlib, json, os, platform, subprocess, sys\n",
                "\n",
                "print('python:', sys.version)\n",
                "print('platform:', platform.platform())\n",
                "print('cwd:', Path.cwd())\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": ["## 1. Unpack and verify the uploaded source\n"],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "archive = Path('prooflaunch-track1-submission-ready.tar.gz')\n",
                "parts = sorted(Path('.').glob('prooflaunch-track1.part-*'))\n",
                "if not archive.exists() and parts:\n",
                "    with archive.open('wb') as destination:\n",
                "        for part in parts:\n",
                "            destination.write(part.read_bytes())\n",
                "    print(f'reassembled {len(parts)} parts into {archive}')\n",
                "if not archive.exists():\n",
                "    archive = Path('prooflaunch-agent-remix-radeon-ready.tar.gz')\n",
                "assert archive.exists(), f'Missing upload: {archive}'\n",
                "digest = hashlib.sha256(archive.read_bytes()).hexdigest()\n",
                "print('archive:', archive)\n",
                "print('sha256:', digest)\n",
                "subprocess.run(['tar', '-xzf', str(archive)], check=True)\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": ["## 2. Run the deterministic control-plane gate\n"],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "repo = Path('prooflaunch_submission') if Path('prooflaunch_submission').exists() else Path('prooflaunch_agent_remix')\n",
                "env = {**os.environ, 'PYTHONPATH': str(repo / 'src')}\n",
                "tests = subprocess.run(\n",
                "    [sys.executable, '-m', 'unittest', 'discover', '-s', str(repo / 'tests'), '-v'],\n",
                "    env=env, text=True, capture_output=True\n",
                ")\n",
                "print(tests.stdout)\n",
                "print(tests.stderr)\n",
                "assert tests.returncode == 0, 'Control-plane tests failed'\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": ["## 3. Record the AMD Radeon runtime\n"],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "import torch\n",
                "runtime = {\n",
                "    'torch_version': torch.__version__,\n",
                "    'gpu_available': torch.cuda.is_available(),\n",
                "    'gpu_count': torch.cuda.device_count(),\n",
                "    'device_name': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,\n",
                "}\n",
                "print(json.dumps(runtime, indent=2))\n",
                "assert runtime['gpu_available'], 'AMD Radeon GPU is not available'\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 4. Bind the fine-tuned Gemma classifier\n",
                "\n",
                "This cell expects `predict_emotion_ft` to exist in the active "
                "kernel. If the original training Notebook uses a different kernel, "
                "load the saved LoRA adapter explicitly before continuing.\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from prooflaunch_remix.audience_pulse import GemmaAudiencePulse\n",
                "\n",
                "assert 'predict_emotion_ft' in globals(), 'predict_emotion_ft is not loaded in this kernel'\n",
                "audience_pulse = GemmaAudiencePulse(\n",
                "    classifier=predict_emotion_ft,\n",
                "    model_ref='google/gemma-4-E4B-it+emotion-lora:modelscope-single-radeon',\n",
                ")\n",
                "print('Gemma Audience Pulse adapter ready')\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 5. Required evidence before submission\n",
                "\n",
                "- Record post-fine-tuning evaluation.\n",
                "- Run one frozen real visual-generation fixture.\n",
                "- Record model, seed, latency, peak VRAM, and output SHA-256.\n",
                "- Complete audit → bounded repair → export.\n",
                "- Record the Demo Video; official guidance recommends 3–5 minutes.\n",
                "- Change `SUBMISSION_GATE.json` to `ready` only when every P0 gate passes.\n",
            ],
        },
    ]
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3 (ipykernel)",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    output.write_text(json.dumps(notebook, indent=2), encoding="utf-8")


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    build_profile_pdf()
    build_poster()
    for path in (
        DOCS / "ProofLaunch_Project_Profile.pdf",
        DOCS / "ProofLaunch_Poster.pptx",
    ):
        print(f"created {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate the reviewed Silent Vision project profile and poster assets.

This module is the canonical copy and layout source for generated submission
artifacts. The Markdown files under ``docs/submission`` are reviewed reference
copy and must be updated alongside high-risk copy or status changes here.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import qrcode
from PIL import Image, ImageOps
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A3, A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
PROFILE_SOURCE = ROOT / "docs/submission/project-profile-source.md"
POSTER_SOURCE = ROOT / "docs/submission/poster-copy.md"
SUBMISSION = ROOT / "submission"
PDF_OUTPUT = ROOT / "output/pdf"
REPOSITORY_URL = "https://github.com/fangjixin/silent-vision"
POSTER_SCENE_DIR = SUBMISSION / "assets/poster"
POSTER_SCENES = (
    ("POST-SURGERY", POSTER_SCENE_DIR / "post-surgery.png", (0.50, 0.42)),
    ("REHABILITATION", POSTER_SCENE_DIR / "rehabilitation.png", (0.50, 0.42)),
    (
        "ACCESSIBLE COMMUNICATION",
        POSTER_SCENE_DIR / "accessible-communication.png",
        (0.50, 0.48),
    ),
    (
        "SILENT CONTROL INPUT",
        POSTER_SCENE_DIR / "silent-control-input.png",
        (0.50, 0.48),
    ),
)
PROFILE_EVIDENCE_STATUS = (
    "Official Radeon evidence: 12/12 phrase top-1, 5/12 known accepted, "
    "5/5 accepted known phrases correct, and 9/10 unrelated clips rejected. "
    "Inventory, checkpoint, and report lineage are evidentiary and verified."
)
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
CJK_FONT = "STSong-Light"

CHARCOAL = HexColor("#101418")
OFF_WHITE = HexColor("#F4F1EA")
RADEON_RED = HexColor("#ED1C24")
MUTED = HexColor("#56616A")
LINE = HexColor("#CFD1CC")
WHITE = HexColor("#FFFFFF")
PALE_RED = HexColor("#FDE7E7")
PALE_GRAY = HexColor("#E8E8E3")


def _read_reviewed_copy() -> tuple[str, str]:
    profile = PROFILE_SOURCE.read_text(encoding="utf-8")
    poster = POSTER_SOURCE.read_text(encoding="utf-8")
    required = {
        "profile": (
            profile,
            [
                "Applicant: Jixin Fang",
                REPOSITORY_URL,
                "Hello, please turn on the light.",
                "Have you eaten?",
                "user selects the language",
                "selected-language softmax",
                "Measured Radeon Evidence",
            ],
        ),
        "poster": (
            poster,
            [
                REPOSITORY_URL,
                "SILENT VISION",
                "PERSONALIZED FIXED-PHRASE PROTOTYPE",
                "A VOICE WITHOUT SOUND.",
                "Visual communication for people who can form words but cannot speak them aloud.",
                "POST-SURGERY",
                "REHABILITATION",
                "ACCESSIBLE COMMUNICATION",
                "SILENT CONTROL INPUT",
                "Four registered phrases · Chinese + English · Exact phrase or safe UNKNOWN",
                "Camera-only · No audio capture · ROCm PyTorch on AMD Radeon",
                "does not directly control a device",
                "not open-vocabulary lipreading",
            ],
        ),
    }
    missing = [
        f"{document}: {phrase}"
        for document, (text, phrases) in required.items()
        for phrase in phrases
        if phrase not in " ".join(text.split())
    ]
    if missing:
        raise ValueError(f"Reviewed submission copy is missing: {missing}")
    return profile, poster


def _wrap(text: str, width: float, font: str, size: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _paragraph(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "Helvetica",
    size: float = 10.5,
    leading: float = 15,
    color: Color = CHARCOAL,
) -> float:
    pdf.setFillColor(color)
    pdf.setFont(font, size)
    for line in _wrap(text, width, font, size):
        pdf.drawString(x, y, line)
        y -= leading
    return y


def _label(pdf: canvas.Canvas, text: str, x: float, y: float, color: Color = RADEON_RED) -> None:
    pdf.setFillColor(color)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(x, y, text.upper())


def _card(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    body: str,
    *,
    accent: Color = RADEON_RED,
    fill: Color = WHITE,
    title_size: float = 13,
    body_font: str = "Helvetica",
    body_size: float = 9.5,
    leading: float = 13.5,
) -> None:
    pdf.setFillColor(fill)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(x, y, width, height, 9, fill=1, stroke=1)
    pdf.setFillColor(accent)
    pdf.roundRect(x, y + height - 8, width, 8, 5, fill=1, stroke=0)
    pdf.setFillColor(CHARCOAL)
    pdf.setFont("Helvetica-Bold", title_size)
    pdf.drawString(x + 14, y + height - 31, title)
    _paragraph(
        pdf,
        body,
        x + 14,
        y + height - 50,
        width - 28,
        font=body_font,
        size=body_size,
        leading=leading,
        color=MUTED,
    )


def _arrow(pdf: canvas.Canvas, x1: float, y1: float, x2: float, y2: float) -> None:
    pdf.setStrokeColor(RADEON_RED)
    pdf.setFillColor(RADEON_RED)
    pdf.setLineWidth(1.8)
    pdf.line(x1, y1, x2, y2)
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 >= x1 else -1
        points = [x2, y2, x2 - 6 * direction, y2 + 4, x2 - 6 * direction, y2 - 4]
    else:
        direction = 1 if y2 >= y1 else -1
        points = [x2, y2, x2 - 4, y2 - 6 * direction, x2 + 4, y2 - 6 * direction]
    path = pdf.beginPath()
    path.moveTo(points[0], points[1])
    path.lineTo(points[2], points[3])
    path.lineTo(points[4], points[5])
    path.close()
    pdf.drawPath(path, fill=1, stroke=0)


def _profile_shell(
    pdf: canvas.Canvas,
    page_number: int,
    title: str,
    subtitle: str,
) -> None:
    width, height = A4
    pdf.setFillColor(OFF_WHITE)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setFillColor(RADEON_RED)
    pdf.rect(0, height - 13, width, 13, fill=1, stroke=0)
    _label(pdf, "Silent Vision / Track 1", 42, height - 39, MUTED)
    pdf.setFillColor(CHARCOAL)
    pdf.setFont("Helvetica-Bold", 26)
    pdf.drawString(42, height - 78, title)
    _paragraph(pdf, subtitle, 42, height - 101, width - 84, size=10, leading=14, color=MUTED)
    pdf.setStrokeColor(LINE)
    pdf.line(42, 38, width - 42, 38)
    pdf.setFont("Helvetica", 8.5)
    pdf.setFillColor(MUTED)
    pdf.drawString(42, 23, "Jixin Fang  |  github.com/fangjixin/silent-vision")
    pdf.drawRightString(width - 42, 23, f"{page_number} / 6")


def _profile_page_one(pdf: canvas.Canvas) -> None:
    _profile_shell(
        pdf,
        1,
        "Silent Vision",
        "Personalized fixed-phrase recognition from a short camera clip with audio disabled.",
    )
    width, height = A4
    _label(pdf, "Project profile", 42, height - 144)
    pdf.setFont("Helvetica-Bold", 35)
    pdf.setFillColor(CHARCOAL)
    pdf.drawString(42, height - 192, "One silent clip.")
    pdf.setFillColor(RADEON_RED)
    pdf.setFont("Helvetica-Bold", 31)
    pdf.drawString(42, height - 235, "One inspectable phrase decision.")
    _paragraph(
        pdf,
        "Silent Vision recognizes a small catalog of personalized fixed phrases. It is not open-vocabulary lipreading. Exact accepted text and intent come from the registered catalog.",
        42,
        height - 276,
        width - 84,
        size=11,
        leading=16,
    )
    card_width = (width - 96) / 2
    catalog_cards = [
        ("zh_light_on_hello", "你好，请帮我打开灯  ->  LIGHT_ON", CJK_FONT),
        ("zh_chat_meal", "你吃饭了吗？  ->  CHAT_OTHER", CJK_FONT),
        ("en_light_on_hello", "Hello, please turn on the light.  ->  LIGHT_ON", "Helvetica"),
        ("en_chat_meal", "Have you eaten?  ->  CHAT_OTHER", "Helvetica"),
    ]
    positions = [
        (42, 423),
        (54 + card_width, 423),
        (42, 347),
        (54 + card_width, 347),
    ]
    for (phrase_id, phrase, font), (x, y) in zip(catalog_cards, positions):
        _card(
            pdf,
            x,
            y,
            card_width,
            62,
            phrase_id,
            phrase,
            title_size=8.2,
            body_font=font,
            body_size=8.1,
            leading=10,
        )
    pdf.setFillColor(CHARCOAL)
    pdf.roundRect(42, 196, width - 84, 126, 10, fill=1, stroke=0)
    _label(pdf, "Current status", 60, 294, RADEON_RED)
    _paragraph(
        pdf,
        "The user selects the language before recording; the service does not infer it. Selected-language softmax then scores only the enabled phrases for that language. CPU code prepares the mouth clip, and the fixed-phrase Torch model runs on AMD Radeon through ROCm.",
        60,
        268,
        width - 120,
        size=10.5,
        leading=15,
        color=WHITE,
    )
    pdf.setFillColor(PALE_RED)
    pdf.roundRect(42, 102, width - 84, 64, 9, fill=1, stroke=0)
    _label(pdf, "Radeon evidence", 58, 144)
    _paragraph(
        pdf,
        "Frozen final evaluation: 12/12 phrase top-1, 5/12 known accepted, and 9/10 unrelated clips rejected. Personalized same-speaker scope.",
        58,
        122,
        width - 116,
        size=10,
        leading=14,
    )


def _profile_page_two(pdf: canvas.Canvas) -> None:
    _profile_shell(
        pdf,
        2,
        "Target users",
        "A deliberate visual input for one user and a small registered phrase catalog.",
    )
    width, _ = A4
    cards = [
        ("Creator control input", "Another application can map an accepted intent to a capture, cue, or editing action."),
        ("Accessible service", "A small visual phrase set can supplement other communication channels at a service desk."),
        ("Noisy workspace", "A deliberate visual command can help when microphone recognition is unreliable."),
        ("Privacy-sensitive room", "The browser captures video without enabling the microphone or continuous audio recording."),
    ]
    card_width = (width - 96) / 2
    positions = [(42, 500), (54 + card_width, 500), (42, 328), (54 + card_width, 328)]
    for (title, body), (x, y) in zip(cards, positions):
        _card(pdf, x, y, card_width, 142, title, body, body_size=9.8)
    pdf.setFillColor(CHARCOAL)
    pdf.roundRect(42, 170, width - 84, 116, 10, fill=1, stroke=0)
    _label(pdf, "Product boundary", 60, 256)
    _paragraph(
        pdf,
        'Silent Vision answers "which registered phrase best fits this visible mouth sequence?" It does not claim a transcript or cross-speaker generalization. The current source implements recognition, not a downstream creator or device action.',
        60,
        228,
        width - 120,
        size=11,
        leading=16,
        color=WHITE,
    )
    _paragraph(
        pdf,
        "An integrator still defines allowed intents, confirmation rules, retention policy, and failure handling.",
        42,
        128,
        width - 84,
        size=10,
        leading=14,
        color=MUTED,
    )


def _profile_page_three(pdf: canvas.Canvas) -> None:
    _profile_shell(
        pdf,
        3,
        "Product workflow and safety",
        "One short recording, one catalog decision, and a fail-closed rejection boundary.",
    )
    width, _ = A4
    steps = [
        ("01", "Capture", "User selects zh or en, then records one 2-5 second WebM clip with audio disabled."),
        ("02", "Preprocess", "Decode, detect one face, align, and crop the mouth on CPU."),
        ("03", "Classify", "Run selected-language softmax, phrase logits, and a normalized embedding on Radeon."),
        ("04", "Gate", "Require checkpoint probability and phrase-centroid distance."),
        ("05", "Route", "Return exact catalog text or reject the clip as UNKNOWN."),
    ]
    y = 615
    for index, title, body in steps:
        pdf.setFillColor(WHITE)
        pdf.setStrokeColor(LINE)
        pdf.roundRect(60, y, width - 120, 68, 9, fill=1, stroke=1)
        pdf.setFillColor(RADEON_RED)
        pdf.setFont("Helvetica-Bold", 20)
        pdf.drawString(76, y + 25, index)
        pdf.setFillColor(CHARCOAL)
        pdf.setFont("Helvetica-Bold", 13)
        pdf.drawString(126, y + 39, title)
        _paragraph(pdf, body, 126, y + 20, width - 214, size=9.5, leading=12, color=MUTED)
        if index != "05":
            _arrow(pdf, width / 2, y - 3, width / 2, y - 15)
        y -= 89
    pdf.setFillColor(PALE_RED)
    pdf.roundRect(42, 104, width - 84, 68, 9, fill=1, stroke=0)
    _label(pdf, "Safety rule", 58, 150)
    _paragraph(
        pdf,
        "Both calibrated gates must pass. Heuristic UNKNOWN carries no matched phrase text and cannot execute. Top-1 margin is diagnostic only.",
        58,
        128,
        width - 116,
        size=9.8,
        leading=13.5,
    )


def _profile_page_four(pdf: canvas.Canvas) -> None:
    _profile_shell(
        pdf,
        4,
        "System architecture",
        "CPU media preprocessing feeds one fixed-phrase model on AMD Radeon through ROCm.",
    )
    width, _ = A4
    box_width = 112
    x_values = [42, 173, 304, 435]
    stages = [
        ("Browser", "WebM, audio off"),
        ("CPU decode", "PyAV at 25 FPS"),
        ("CPU vision", "Face, align, crop"),
        ("Radeon", "Torch on cuda:0"),
    ]
    for i, ((title, body), x) in enumerate(zip(stages, x_values)):
        _card(pdf, x, 540, box_width, 112, title, body, body_size=8.4, leading=11.5)
        if i < len(stages) - 1:
            _arrow(pdf, x + box_width + 4, 596, x_values[i + 1] - 5, 596)
    _arrow(pdf, width / 2, 530, width / 2, 490)
    pdf.setFillColor(CHARCOAL)
    pdf.roundRect(90, 419, width - 180, 70, 9, fill=1, stroke=0)
    _label(pdf, "Model input", 108, 463)
    _paragraph(
        pdf,
        "A [batch, time, 96, 96] grayscale mouth tensor.",
        108,
        440,
        width - 216,
        size=10.5,
        leading=14,
        color=WHITE,
    )
    branch_width = 148
    branch_x = [42, 224, 406]
    backends = [
        ("Visual maps", "16 x 16 appearance plus signed adjacent-frame motion."),
        ("Temporal model", "64-feature projection and two depthwise-separable blocks."),
        ("Phrase outputs", "Attentive embedding, dynamic phrase head, catalog mapping."),
    ]
    for (title, body), x in zip(backends, branch_x):
        _arrow(pdf, width / 2, 410, x + branch_width / 2, 365)
        _card(pdf, x, 255, branch_width, 105, title, body, body_size=8.7, leading=12)
        _arrow(pdf, x + branch_width / 2, 247, width / 2, 212)
    pdf.setFillColor(PALE_RED)
    pdf.roundRect(90, 135, width - 180, 76, 9, fill=1, stroke=0)
    _label(pdf, "Shared decision boundary", 108, 185)
    _paragraph(
        pdf,
        "User-selected language + selected-language softmax, then probability and predicted phrase centroid distance for exact catalog text or UNKNOWN.",
        108,
        160,
        width - 216,
        size=9.7,
        leading=13,
    )


def _profile_page_five(pdf: canvas.Canvas) -> None:
    _profile_shell(
        pdf,
        5,
        "Model and algorithm",
        "A small temporal model learns phrase classes and a calibrated embedding boundary.",
    )
    width, _ = A4
    pipeline = [
        ("Appearance + motion", "Downsample to 16 x 16 and compute signed adjacent-frame differences"),
        ("64-feature projection", "Learn a compact visual representation for every frame"),
        ("2 temporal blocks", "Residual depthwise and pointwise one-dimensional convolutions"),
        ("Embedding + phrase head", "Attentive pooling, normalized embedding, dynamic catalog classes"),
    ]
    y = 590
    for i, (title, body) in enumerate(pipeline):
        pdf.setFillColor(WHITE)
        pdf.setStrokeColor(LINE)
        pdf.roundRect(60, y, width - 120, 72, 9, fill=1, stroke=1)
        pdf.setFillColor(RADEON_RED)
        pdf.circle(86, y + 36, 14, fill=1, stroke=0)
        pdf.setFillColor(WHITE)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawCentredString(86, y + 33, str(i + 1))
        pdf.setFillColor(CHARCOAL)
        pdf.setFont("Helvetica-Bold", 12.5)
        pdf.drawString(114, y + 43, title)
        _paragraph(pdf, body, 114, y + 24, width - 204, size=9.2, leading=12, color=MUTED)
        if i < len(pipeline) - 1:
            _arrow(pdf, width / 2, y - 3, width / 2, y - 16)
        y -= 96
    card_width = (width - 96) / 2
    _card(
        pdf,
        42,
        130,
        card_width,
        112,
        "Acceptance",
        "The top phrase must pass the global minimum probability and its maximum cosine distance from the training centroid. Margin is diagnostic only.",
        body_size=8.7,
        leading=12,
    )
    _card(
        pdf,
        54 + card_width,
        130,
        card_width,
        112,
        "Catalog boundary",
        "Selected-language softmax is applied before gating. UNKNOWN is not trained; accepted exact text and intent come from the checkpoint catalog.",
        body_size=8.7,
        leading=12,
    )


def _profile_page_six(pdf: canvas.Canvas) -> None:
    _profile_shell(
        pdf,
        6,
        "AMD Radeon and ROCm",
        "The official path fails closed unless the fixed-phrase Torch model can use ROCm cuda:0.",
    )
    width, _ = A4
    card_width = (width - 96) / 2
    _card(
        pdf,
        42,
        500,
        card_width,
        148,
        "CPU preprocessing",
        "PyAV decode, 25 FPS resampling, MediaPipe face detection, alignment, and 96 x 96 mouth cropping.",
        accent=MUTED,
    )
    _arrow(pdf, 54 + card_width - 8, 574, 54 + card_width + 8, 574)
    _card(
        pdf,
        54 + card_width,
        500,
        card_width,
        148,
        "Radeon classification",
        "PyTorch runs visual maps, temporal blocks, attentive embedding, phrase logits, and centroid comparison through ROCm.",
    )
    _label(pdf, "Reproduction guards", 42, 458)
    guards = [
        "torch.version.hip must be non-empty.",
        "cuda:0 must be visible and accept an allocation.",
        "A non-empty fixed-phrase checkpoint must be provided.",
    ]
    y = 420
    for guard in guards:
        pdf.setFillColor(RADEON_RED)
        pdf.circle(53, y + 4, 4, fill=1, stroke=0)
        _paragraph(pdf, guard, 68, y, width - 110, size=10.5, leading=14)
        y -= 35
    pdf.setFillColor(PALE_RED)
    pdf.roundRect(42, 240, width - 84, 90, 9, fill=1, stroke=0)
    _label(pdf, "Evidence status", 58, 304)
    _paragraph(
        pdf,
        PROFILE_EVIDENCE_STATUS,
        58,
        278,
        width - 116,
        size=9.7,
        leading=13.5,
    )
    _label(pdf, "Run identity", 42, 207)
    _paragraph(
        pdf,
        "PyTorch 2.9.1 | ROCm HIP 7.2 | cuda:0 | gfx1100 | 46,405 parameters | checkpoint c70d28ae2ed84ee4b2cb0811ebff18870e7b905c1540bc96a782656fba385453",
        42,
        180,
        width - 84,
        size=10,
        leading=15,
    )
    pdf.setFillColor(CHARCOAL)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(42, 105, REPOSITORY_URL)


def build_profile_pdf(output: Path) -> None:
    """Create the six-page A4 project profile."""
    _read_reviewed_copy()
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output), pagesize=A4, invariant=1, pageCompression=1)
    pdf.setTitle("Silent Vision Project Profile")
    pdf.setAuthor("Jixin Fang")
    pdf.setSubject("Track 1 project profile")
    pages = [
        _profile_page_one,
        _profile_page_two,
        _profile_page_three,
        _profile_page_four,
        _profile_page_five,
        _profile_page_six,
    ]
    for page in pages:
        page(pdf)
        pdf.showPage()
    pdf.save()


def _qr_image() -> ImageReader:
    code = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=12,
        border=4,
    )
    code.add_data(REPOSITORY_URL)
    code.make(fit=True)
    image = code.make_image(fill_color="#101418", back_color="#FFFFFF")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return ImageReader(buffer)


def _poster_image_reader(
    path: Path,
    width: float,
    height: float,
    centering: tuple[float, float],
) -> ImageReader:
    if not path.is_file():
        raise FileNotFoundError(f"Poster scene image not found: {path}")
    target = (max(1, round(width * 2)), max(1, round(height * 2)))
    with Image.open(path) as source:
        fitted = ImageOps.fit(
            source.convert("RGB"),
            target,
            Image.Resampling.LANCZOS,
            centering=centering,
        )
        buffer = io.BytesIO()
        fitted.save(buffer, format="JPEG", quality=92, optimize=True)
    buffer.seek(0)
    return ImageReader(buffer)


def _draw_poster_scene(
    pdf: canvas.Canvas,
    *,
    label: str,
    path: Path,
    centering: tuple[float, float],
    x: float,
    y: float,
    width: float,
    height: float,
    label_at_top: bool,
) -> None:
    reader = _poster_image_reader(path, width, height, centering)
    pdf.drawImage(
        reader,
        x,
        y,
        width,
        height,
        preserveAspectRatio=False,
        mask="auto",
    )
    label_y = y + height - 34 if label_at_top else y
    pdf.saveState()
    pdf.setFillAlpha(0.72)
    pdf.setFillColor(CHARCOAL)
    pdf.rect(x, label_y, width, 34, fill=1, stroke=0)
    pdf.restoreState()
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(x + 14, label_y + 13, label)


def build_poster_pdf(output: Path) -> None:
    """Create the one-page A3 portrait poster."""
    _read_reviewed_copy()
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output), pagesize=A3, invariant=1, pageCompression=1)
    pdf.setTitle("Silent Vision Poster")
    pdf.setAuthor("Jixin Fang")
    pdf.setSubject("Track 1 project poster")
    width, height = A3

    footer_height = 340
    mosaic_height = height - footer_height
    column_width = width / 2
    row_height = mosaic_height / 2
    for index, (label, path, centering) in enumerate(POSTER_SCENES):
        column = index % 2
        top_row = index < 2
        _draw_poster_scene(
            pdf,
            label=label,
            path=path,
            centering=centering,
            x=column * column_width,
            y=footer_height + (row_height if top_row else 0),
            width=column_width,
            height=row_height,
            label_at_top=top_row,
        )

    band_height = 128
    band_y = footer_height + row_height - band_height / 2
    pdf.saveState()
    pdf.setFillAlpha(0.82)
    pdf.setFillColor(CHARCOAL)
    pdf.rect(0, band_y, width, band_height, fill=1, stroke=0)
    pdf.restoreState()
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(52, band_y + 105, "SILENT VISION")
    pdf.setFillColor(RADEON_RED)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(158, band_y + 105, "PERSONALIZED FIXED-PHRASE PROTOTYPE")
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 38)
    pdf.drawString(52, band_y + 55, "A VOICE WITHOUT SOUND.")
    _paragraph(
        pdf,
        "Visual communication for people who can form words but cannot speak them aloud.",
        52,
        band_y + 27,
        width - 104,
        size=11.5,
        leading=14,
        color=WHITE,
    )

    pdf.setFillColor(OFF_WHITE)
    pdf.rect(0, 0, width, footer_height, fill=1, stroke=0)
    pdf.setFillColor(RADEON_RED)
    pdf.rect(0, footer_height - 8, width, 8, fill=1, stroke=0)
    _paragraph(
        pdf,
        "Four registered phrases · Chinese + English · Exact phrase or safe UNKNOWN",
        52,
        245,
        width - 104,
        font="Helvetica-Bold",
        size=16,
        leading=20,
    )
    _paragraph(
        pdf,
        "Camera-only · No audio capture · ROCm PyTorch on AMD Radeon",
        52,
        169,
        width - 104,
        font="Helvetica-Bold",
        size=14,
        leading=18,
        color=RADEON_RED,
    )
    _paragraph(
        pdf,
        "Target-user scenes · Structured decisions for separate integration · No direct device control",
        52,
        137,
        width - 52 - 112 - 48,
        size=9.5,
        leading=13,
        color=MUTED,
    )

    qr_size = 112
    qr_x = width - 52 - qr_size
    pdf.drawImage(
        _qr_image(),
        qr_x,
        48,
        qr_size,
        qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )
    pdf.setFillColor(CHARCOAL)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(52, 72, "github.com/fangjixin/silent-vision")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(52, 48, "Track 1 · Jixin Fang")
    pdf.showPage()
    pdf.save()


def build_poster_png(pdf: Path, output: Path) -> None:
    """Render the poster PDF to a 150 DPI PNG preview with Poppler."""
    executable = shutil.which("pdftoppm")
    if executable is None:
        raise RuntimeError("Poppler is required: install pdftoppm to render the poster PNG")
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = output.with_suffix("")
    subprocess.run(
        [executable, "-png", "-singlefile", "-r", "150", str(pdf), str(prefix)],
        check=True,
    )
    if not output.exists():
        raise RuntimeError(f"Poppler did not create the expected preview: {output}")


def main() -> None:
    SUBMISSION.mkdir(parents=True, exist_ok=True)
    PDF_OUTPUT.mkdir(parents=True, exist_ok=True)
    profile = SUBMISSION / "Silent-Vision-Project-Profile.pdf"
    poster = SUBMISSION / "Silent-Vision-Poster.pdf"
    poster_png = SUBMISSION / "Silent-Vision-Poster.png"
    build_profile_pdf(profile)
    build_poster_pdf(poster)
    build_poster_png(poster, poster_png)
    shutil.copyfile(profile, PDF_OUTPUT / profile.name)
    shutil.copyfile(poster, PDF_OUTPUT / poster.name)
    print(f"Generated {profile.relative_to(ROOT)}")
    print(f"Generated {poster.relative_to(ROOT)}")
    print(f"Generated {poster_png.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

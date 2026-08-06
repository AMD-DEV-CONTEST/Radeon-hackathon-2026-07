#!/usr/bin/env python3
"""Render an eight-slide 4:5 social carousel for the 40-Asset Interview."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.local_campaign_pack import _font
from scripts.render_gtm_three_beat_video_challenger import _seal


EDITORIAL = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v16/b2b-codex-editorial-war-room-receipt.json"
VIDEO = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview/video-challenger-receipt.json"
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/carousel-challenger-v1-40-asset-interview"

W, H = 2160, 2700
INK = (12, 12, 11)
PAPER = (242, 239, 232)
LIME = (218, 255, 61)
CORAL = (255, 101, 72)
BLUE = (66, 103, 255)
WHITE = (251, 250, 247)
MUTED = (97, 95, 89)
LINE = (191, 187, 177)
SAFE = 130


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int, *, bold: bool = False, fill=INK, spacing: int = 16) -> None:
    draw.multiline_text(xy, text, font=_font(size, bold=bold), fill=fill, spacing=spacing)


def _base(number: int, *, dark: bool = False, accent=CORAL) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (W, H), INK if dark else PAPER)
    draw = ImageDraw.Draw(image)
    fg = WHITE if dark else INK
    draw.text((SAFE, 92), "PROOFLAUNCH / FIELD NOTE 01", font=_font(36, bold=True), fill=fg)
    draw.text((W - SAFE - 110, 92), f"{number:02d}/08", font=_font(36, bold=True), fill=accent)
    draw.line((SAFE, 164, W - SAFE, 164), fill=accent, width=8)
    draw.text((SAFE, H - 120), "THE 40-ASSET INTERVIEW  ·  HUMAN RELEASE REQUIRED", font=_font(28, bold=True), fill=fg)
    return image, draw


def _grid(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], selected: int = 27) -> None:
    left, top, right, bottom = box
    cols, rows, gap = 8, 5, 18
    card_w = (right - left - (cols - 1) * gap) // cols
    card_h = (bottom - top - (rows - 1) * gap) // rows
    for index in range(cols * rows):
        x = left + index % cols * (card_w + gap)
        y = top + index // cols * (card_h + gap)
        active = index == selected
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=18, fill=LIME if active else WHITE, outline=INK, width=4)
        if active:
            draw.text((x + 26, y + card_h // 2 - 18), "REVIEW", font=_font(26, bold=True), fill=INK)
        else:
            draw.line((x + 30, y + 30, x + card_w - 30, y + card_h - 30), fill=CORAL, width=9)
            draw.line((x + card_w - 30, y + 30, x + 30, y + card_h - 30), fill=CORAL, width=9)


def _pill(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, color: tuple[int, int, int], *, width: int = 650) -> None:
    draw.rounded_rectangle((x, y, x + width, y + 142), radius=71, fill=color)
    draw.text((x + 52, y + 43), label, font=_font(44, bold=True), fill=INK if color != BLUE else WHITE)


def _slides() -> list[Image.Image]:
    slides: list[Image.Image] = []

    image, draw = _base(1, dark=True, accent=LIME)
    _text(draw, (SAFE, 400), "DON’T HIRE AI\nTO MAKE\n40 ASSETS.", 165, bold=True, fill=WHITE, spacing=0)
    draw.rounded_rectangle((SAFE, 1510, W - SAFE, 2140), radius=48, fill=LIME)
    _text(draw, (SAFE + 70, 1600), "HIRE IT TO\nREJECT 39.", 150, bold=True, spacing=0)
    _text(draw, (SAFE, 2280), "Output is cheap. Release judgment is the interview.", 54, fill=WHITE)
    slides.append(image)

    image, draw = _base(2, accent=CORAL)
    _text(draw, (SAFE, 320), "FORTY POLISHED\nCARDS WALK IN.", 132, bold=True, spacing=4)
    _grid(draw, (SAFE, 860, W - SAFE, 2010))
    _text(draw, (SAFE, 2145), "39 contain a desired outcome written as if the market already confirmed it.", 54, bold=True)
    slides.append(image)

    image, draw = _base(3, dark=True, accent=CORAL)
    _text(draw, (SAFE, 350), "THE WRONG\nINTERVIEW QUESTION", 126, bold=True, fill=WHITE, spacing=4)
    draw.rounded_rectangle((SAFE, 980, W - SAFE, 1550), radius=46, outline=CORAL, width=8)
    _text(draw, (SAFE + 70, 1070), "“HOW MUCH\nCAN IT MAKE?”", 126, bold=True, fill=CORAL, spacing=4)
    _text(draw, (SAFE, 1740), "A fluent model can finish the sentence.\nThat does not make the sentence true.", 66, fill=WHITE)
    slides.append(image)

    image, draw = _base(4, accent=BLUE)
    _text(draw, (SAFE, 320), "EVERY CLAIM GETS\nONE OF FOUR LABELS.", 118, bold=True, spacing=4)
    _pill(draw, SAFE, 950, "FACT", LIME)
    _pill(draw, 1090, 950, "INFERENCE", (164, 190, 255), width=940)
    _pill(draw, SAFE, 1205, "HYPOTHESIS", (255, 200, 80), width=900)
    _pill(draw, 1190, 1205, "BLOCKED", CORAL, width=840)
    _text(draw, (SAFE, 1710), "Then require:", 48, bold=True, fill=MUTED)
    _text(draw, (SAFE, 1800), "SOURCE  ·  EVIDENCE OBJECT\nRELEASE OWNER  ·  REVERSAL CONDITION", 72, bold=True, spacing=24)
    slides.append(image)

    image, draw = _base(5, dark=True, accent=(255, 200, 80))
    _text(draw, (SAFE, 330), "THE SEDUCTIVE\nSENTENCE", 126, bold=True, fill=WHITE, spacing=2)
    draw.rounded_rectangle((SAFE, 940, W - SAFE, 1570), radius=48, fill=(28, 29, 32), outline=(255, 200, 80), width=8)
    _text(draw, (SAFE + 72, 1060), "“TURN INTEREST INTO\nQUALIFIED PIPELINE.”", 102, bold=True, fill=WHITE, spacing=15)
    _pill(draw, SAFE, 1770, "HYPOTHESIS", (255, 200, 80), width=850)
    _text(draw, (SAFE, 2050), "Observed audience response: —\nObserved pipeline event: —\nRelease decision: BLOCK", 58, fill=WHITE, spacing=22)
    slides.append(image)

    image, draw = _base(6, accent=LIME)
    _text(draw, (SAFE, 330), "ONE CARD\nEARNS REVIEW.", 142, bold=True, spacing=0)
    draw.rounded_rectangle((SAFE, 1010, W - SAFE, 1920), radius=55, fill=INK)
    _text(draw, (SAFE + 75, 1120), "SUPPORTED CLAUSE", 46, bold=True, fill=LIME)
    _text(draw, (SAFE + 75, 1260), "Compiles a rights-bound\nbrief into review-ready\nGTM assets.", 82, bold=True, fill=WHITE, spacing=20)
    _text(draw, (SAFE + 75, 1720), "RELEASE OWNER  ·  HUMAN", 40, bold=True, fill=(190, 194, 214))
    _text(draw, (SAFE, 2070), "The other 39 rejections were useful work.", 64, bold=True)
    slides.append(image)

    image, draw = _base(7, dark=True, accent=BLUE)
    _text(draw, (SAFE, 330), "RUN THE\nFOUR-LINE\nINTERVIEW.", 145, bold=True, fill=WHITE, spacing=0)
    prompts = [
        "1  What exact clause is supported?",
        "2  Which evidence object supports it?",
        "3  What remains hypothesis?",
        "4  Who can release—or refuse—it?",
    ]
    for index, prompt in enumerate(prompts):
        y = 1320 + index * 235
        draw.line((SAFE, y + 90, SAFE + 55, y + 90), fill=LIME if index == 0 else CORAL, width=12)
        draw.text((SAFE + 90, y + 40), prompt, font=_font(58, bold=True), fill=WHITE)
    slides.append(image)

    image, draw = _base(8, accent=CORAL)
    _text(draw, (SAFE, 330), "TRY IT ON\nONE CURRENT\nDRAFT.", 154, bold=True, spacing=0)
    _text(draw, (SAFE, 1320), "Hide the product name.\nLabel the smoothest outcome sentence.\nAsk for its evidence object.", 68, bold=True, spacing=25)
    draw.rounded_rectangle((SAFE, 1900, W - SAFE, 2250), radius=42, fill=CORAL)
    _text(draw, (SAFE + 62, 1990), "IF THE EVIDENCE OR OWNER\nIS BLANK, STOP.", 72, bold=True, spacing=10)
    _text(draw, (SAFE, 2375), "Synthetic capability case · no market lift, conversion, revenue or superiority claimed.", 35, fill=MUTED)
    slides.append(image)

    return slides


def render(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    output.resolve().relative_to(ROOT)
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    for source in (EDITORIAL, VIDEO):
        if not source.is_file():
            raise SystemExit(f"required source missing: {source}")
    output.mkdir(parents=True, exist_ok=True)
    slides = _slides()
    slide_rows = []
    for index, image in enumerate(slides, 1):
        path = output / f"slide-{index:02d}.png"
        image.save(path, "PNG", optimize=True)
        slide_rows.append({"index": index, "path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "bytes": path.stat().st_size, "width": image.width, "height": image.height})

    pdf = output / "prooflaunch-40-asset-interview-carousel-v1.pdf"
    slides[0].save(pdf, "PDF", save_all=True, append_images=slides[1:], resolution=144)
    contact = Image.new("RGB", (W, 2700), (32, 32, 31))
    for index, slide in enumerate(slides):
        thumb = ImageOps.fit(slide, (500, 625), method=Image.Resampling.LANCZOS)
        x = 55 + index % 4 * 525
        y = 55 + index // 4 * 1280
        contact.paste(thumb, (x, y))
        ImageDraw.Draw(contact).text((x, y + 650), f"{index + 1:02d}", font=_font(42, bold=True), fill=WHITE)
    contact_path = output / "contact-sheet.png"
    contact.save(contact_path, "PNG", optimize=True)

    payload = {
        "schema": "ProofLaunchGTM40AssetInterviewCarouselReceiptV1",
        "creative_concept": "The 40-Asset Interview",
        "format": {"width": W, "height": H, "aspect_ratio": "4:5", "slide_count": len(slides)},
        "slides": slide_rows,
        "pdf": {"path": str(pdf.relative_to(ROOT)), "sha256": sha256_file(pdf), "bytes": pdf.stat().st_size},
        "contact_sheet": {"path": str(contact_path.relative_to(ROOT)), "sha256": sha256_file(contact_path), "bytes": contact_path.stat().st_size},
        "source_bindings": [
            {"role": "editorial_war_room", "path": str(EDITORIAL.relative_to(ROOT)), "sha256": sha256_file(EDITORIAL)},
            {"role": "dual_aspect_video", "path": str(VIDEO.relative_to(ROOT)), "sha256": sha256_file(VIDEO)},
        ],
        "open_source_modifications": ["Pillow deterministic 4:5 compositor", "content-addressed artifact receipt"],
        "human_preference_observed": False,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "external_publish_executed": False,
        "truth_boundary": "This receipt proves an eight-slide rights-clear campaign challenger and exact media dimensions. It does not prove human preference, named-product superiority, 4A quality, publication effect, conversion or revenue.",
    }
    receipt = _seal(payload)
    receipt_path = output / "carousel-receipt.json"
    atomic_write_text(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "slide_count": len(slides), "content_sha256": receipt["content_sha256"]}, sort_keys=True))
    return receipt


if __name__ == "__main__":
    render()

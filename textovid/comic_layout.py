# -*- coding: utf-8 -*-
"""Textovid — Comic page assembly (4K A4 at 300 DPI)

Assembles generated panel images into a full comic page with:
  - 2×2 panel grid
  - Speech bubbles (Pillow-drawn ellipses + text)
  - SFX text overlays
  - Captions at the bottom of each panel
"""

from __future__ import annotations

import textwrap
from PIL import Image, ImageDraw, ImageFont
from config import (
    PAGE_W, PAGE_H, PANELS_PER_PAGE, GUTTER, MARGIN,
    BUBBLE_FONT_SIZE, SFX_FONT_SIZE, BUBBLE_PADDING, OUTPUT_DIR,
)

# ── Font resolution (with CJK fallback) ──────────────────────────────
_FONT_CACHE: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = f"{size}_{bold}"
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/chinese/NotoSansSC-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold
        else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in candidates:
        try:
            font = ImageFont.truetype(path, size)
            _FONT_CACHE[key] = font
            return font
        except (OSError, IOError):
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _draw_speech_bubble(
    draw: ImageDraw.ImageDraw,
    cx: int, cy: int,
    text: str,
    max_width: int = 400,
) -> None:
    """Draw a white speech bubble with black text."""
    if not text or not text.strip():
        return

    font = _get_font(BUBBLE_FONT_SIZE)
    lines = []
    for line in text.split("\n"):
        wrapped = textwrap.wrap(line, width=30) or [""]
        lines.extend(wrapped)

    # Measure text block
    line_heights = []
    max_line_w = 0
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font)
        lw = bbox[2] - bbox[0]
        lh = bbox[3] - bbox[1]
        line_heights.append(lh + 4)
        max_line_w = max(max_line_w, lw)

    total_h = sum(line_heights)
    bw = max_line_w + BUBBLE_PADDING * 2
    bh = total_h + BUBBLE_PADDING * 2

    # Position bubble above (cx, cy)
    bx1 = cx - bw // 2
    by1 = cy - bh - 20
    bx2 = cx + bw // 2
    by2 = cy - 20

    # Draw bubble background
    draw.ellipse([bx1, by1, bx2, by2], fill="white", outline="black", width=2)
    # Tail pointer
    draw.polygon(
        [(cx - 8, by2), (cx + 8, by2), (cx, cy)],
        fill="white", outline="black",
    )

    # Draw text lines
    ty = by1 + BUBBLE_PADDING
    for i, ln in enumerate(lines):
        bbox = draw.textbbox((0, 0), ln, font=font)
        lw = bbox[2] - bbox[0]
        x = cx - lw // 2
        draw.text((x, ty), ln, fill="black", font=font)
        ty += line_heights[i]


def _draw_sfx(
    draw: ImageDraw.ImageDraw,
    cx: int, cy: int,
    sfx: str,
) -> None:
    """Draw a bold SFX overlay at (cx, cy)."""
    if not sfx or not sfx.strip():
        return
    font = _get_font(SFX_FONT_SIZE, bold=True)
    # Outline effect
    for dx in (-2, 0, 2):
        for dy in (-2, 0, 2):
            draw.text((cx + dx, cy + dy), sfx.upper(), fill="yellow", font=font)
    draw.text((cx, cy), sfx.upper(), fill="red", font=font)


def _draw_caption(
    draw: ImageDraw.ImageDraw,
    px: int, py: int, pw: int, ph: int,
    caption: str,
) -> None:
    """Draw a caption box at the bottom of a panel."""
    if not caption or not caption.strip():
        return
    font = _get_font(BUBBLE_FONT_SIZE - 4)
    lines = textwrap.wrap(caption, width=40)[:3]
    box_h = 12 + len(lines) * (BUBBLE_FONT_SIZE - 2 + 4)
    box_y = py + ph - box_h - 8
    draw.rectangle(
        [px + 8, box_y, px + pw - 8, box_y + box_h],
        fill="white", outline="black", width=1,
    )
    ty = box_y + 6
    for ln in lines:
        draw.text((px + 16, ty), ln, fill="black", font=font)
        ty += BUBBLE_FONT_SIZE - 2 + 4


def assemble_comic_page(
    panels: list[dict],
    images: list["PIL.Image.Image"],
) -> str:
    """Assemble up to 4 panel images into a full comic page.

    Parameters
    ----------
    panels : list of panel dicts from story_engine
    images  : list of PIL Images (same length as panels)

    Returns
    -------
    Path to the saved PNG file.
    """
    page = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    draw = ImageDraw.Draw(page)

    n = min(len(panels), PANELS_PER_PAGE, len(images))
    cols, rows = 2, 2

    avail_w = PAGE_W - MARGIN * 2 - GUTTER * (cols - 1)
    avail_h = PAGE_H - MARGIN * 2 - GUTTER * (rows - 1)
    pw = avail_w // cols
    ph = avail_h // rows

    for idx in range(n):
        row, col = divmod(idx, cols)
        px = MARGIN + col * (pw + GUTTER)
        py = MARGIN + row * (ph + GUTTER)

        # Resize and paste panel image
        img = images[idx].convert("RGB").resize((pw, ph), Image.LANCZOS)
        page.paste(img, (px, py))

        # Panel border
        draw.rectangle([px, py, px + pw - 1, py + ph - 1], outline="black", width=3)

        panel = panels[idx]

        # Speech bubble
        if panel.get("dialogue"):
            _draw_speech_bubble(draw, px + pw // 2, py + ph // 3, panel["dialogue"], max_width=pw - 40)

        # SFX
        if panel.get("sfx"):
            _draw_sfx(draw, px + pw // 2 - 40, py + ph // 2, panel["sfx"])

        # Caption
        if panel.get("caption"):
            _draw_caption(draw, px, py, pw, ph, panel["caption"])

    import os
    out_path = os.path.join(OUTPUT_DIR, "comic_page.png")
    page.save(out_path, "PNG", dpi=(300, 300))
    return out_path

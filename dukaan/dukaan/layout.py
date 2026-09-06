"""Turn a styled product shot into a finished creative.

This is deliberately not a model. Generative text rendering is still the
weakest part of image models, and a seller's price and phone number have to be
exactly right, so the headline is composited with real type over the generated
backdrop. The model makes the picture look good; the compositor makes the words
legible.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .spec import Brief, Format, Style

# Fonts that ship with macOS and most Linux images, in preference order.
_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_headline(
    draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int, start: int
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Largest type size where the headline still fits its band.

    Shrinking to fit rather than truncating, because a seller's headline is
    their words and silently cutting it would be worse than smaller type.
    """
    size = start
    while size > 12:
        font = _font(size)
        lines = _wrap(draw, text, font, max_w)
        height = len(lines) * int(size * 1.18)
        if height <= max_h:
            return font, lines
        size -= 2
    font = _font(12)
    return font, _wrap(draw, text, font, max_w)


def compose(base: Image.Image, brief: Brief, fmt: Format, style: Style) -> Image.Image:
    """Composite the headline band over a styled product shot."""
    canvas = base.convert("RGB").resize(fmt.size, Image.LANCZOS)
    draw = ImageDraw.Draw(canvas, "RGBA")

    band_h = int(fmt.height * fmt.text_band)
    top = fmt.height - band_h

    # A soft scrim so type stays legible whatever the model produced underneath.
    for i in range(band_h):
        alpha = int(235 * (i / band_h) ** 0.65)
        draw.line([(0, top + i), (fmt.width, top + i)], fill=(*style.backdrop, alpha))

    pad = int(fmt.width * 0.055)
    max_w = fmt.width - 2 * pad
    head_h = int(band_h * (0.52 if brief.subline else 0.72))

    font, lines = _fit_headline(draw, brief.headline, max_w, head_h, int(fmt.height * 0.075))
    line_h = int(font.size * 1.18)
    y = top + int(band_h * 0.16)
    for line in lines:
        draw.text((pad, y), line, font=font, fill=style.ink)
        y += line_h

    if brief.subline:
        sub_font = _font(max(int(font.size * 0.46), 13))
        sub_lines = _wrap(draw, brief.subline, sub_font, max_w)
        y += int(line_h * 0.18)
        for line in sub_lines[:2]:
            draw.text((pad, y), line, font=sub_font, fill=(*style.ink, 215))
            y += int(sub_font.size * 1.25)

    return canvas


def contact_strip(canvas: Image.Image, text: str, style: Style) -> Image.Image:
    """Optional footer for a phone number or handle, kept exact."""
    if not text:
        return canvas
    out = canvas.copy()
    draw = ImageDraw.Draw(out, "RGBA")
    font = _font(max(int(out.height * 0.026), 13))
    w = draw.textlength(text, font=font)
    pad = int(out.width * 0.03)
    box_h = int(font.size * 2.0)
    draw.rounded_rectangle(
        [(out.width - w - pad * 2.4, out.height - box_h - pad), (out.width - pad, out.height - pad)],
        radius=box_h // 2,
        fill=(*style.ink, 235),
    )
    draw.text(
        (out.width - w - pad * 1.7, out.height - box_h - pad + (box_h - font.size) / 2 - 2),
        text,
        font=font,
        fill=style.backdrop,
    )
    return out

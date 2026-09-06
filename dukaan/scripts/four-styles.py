"""One photograph under every look, side by side.

Regenerated from the same packs the style grid uses, so the two figures cannot
disagree about what a style currently produces. That mattered once already: the
daylight style was retuned and this figure kept showing the old one.

Usage: four-styles.py [product] [out.png]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

STYLES = ("studio", "festive", "daylight", "midnight")
CELL = 420
CAP = 44
BG = (17, 17, 21)
FG = (238, 238, 242)


def _font(size, bold=False):
    for n in ("/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(n, size, index=1 if bold else 0)
        except OSError:
            continue
    return ImageFont.load_default()


def build(product: str = "brass-ewer", out_path: str = "docs/gallery/one-photo-four-styles.png") -> Path:
    cells = []
    for style in STYLES:
        p = Path(f"out/matrix-{style}/{product}/{style}_square.png")
        if not p.exists():
            raise FileNotFoundError(f"{p} is missing. Run scripts/matrix first.")
        cells.append((style, Image.open(p).convert("RGB")))

    sheet = Image.new("RGB", (CELL * len(cells), CELL + CAP), BG)
    d = ImageDraw.Draw(sheet)
    for i, (style, im) in enumerate(cells):
        im = im.copy()
        im.thumbnail((CELL - 8, CELL - 8), Image.LANCZOS)
        sheet.paste(im, (i * CELL + (CELL - im.width) // 2, 4))
        d.text((i * CELL + 10, CELL + 12), style, font=_font(22, bold=True), fill=FG)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"wrote {out}  {sheet.size[0]}x{sheet.size[1]}  ({product})")
    return out


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "brass-ewer",
          sys.argv[2] if len(sys.argv) > 2 else "docs/gallery/one-photo-four-styles.png")

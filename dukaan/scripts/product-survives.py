"""Build the figure that shows the product surviving generation.

The claim this supports is the one the whole tool rests on: a seller cannot post
a picture of a bangle that is not the bangle they will ship. Because
`strength=0.7` lets the model alter the product, that has to be shown rather
than asserted.

It is shown rather than scored on purpose. A pixel metric against the plate
measures the camera move, not the product: the motion prompt pushes the camera
in, so by the last frames the object is legitimately larger and in a different
place, and a mask taken from the plate lands on the wrong pixels. Several
attempts at aligning that away disagreed with what the crops plainly show, so
the crops are the evidence. Each row is one product: the plate the model was
given, then the frames the pack actually selected.

Usage: product-survives.py [out.png]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from dukaan.spec import STYLES_BY_NAME

#: Built from the festive column of the style matrix, because festive is the
#: look whose background changes most, which is exactly the contrast this
#: figure exists to show. Same packs the grid uses, so the two cannot disagree.
PACKS = [
    ("out/matrix-festive/gilt-bangles", "gilt bangles"),
    ("out/matrix-festive/brass-ewer", "brass ewer"),
    ("out/matrix-festive/silver-bracelet", "silver bracelet"),
]
PAD = 0.06
CELL = 300
LABEL_W = 190
BG = (17, 17, 21)
FG = (238, 238, 242)
DIM = (150, 150, 162)


def _font(size, bold=False):
    for n in ("/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(n, size, index=1 if bold else 0)
        except OSError:
            continue
    return ImageFont.load_default()


def product_box(plate: Image.Image, backdrop) -> tuple[int, int, int, int]:
    """The product's bounding box, found by differencing the flat style wash."""
    arr = np.asarray(plate.convert("RGB"), dtype=np.int16)
    delta = np.abs(arr - np.array(backdrop, dtype=np.int16)).sum(axis=2)
    ys, xs = np.nonzero(delta > 8)
    w, h = plate.size
    px, py = int(w * PAD), int(h * PAD)
    return (max(int(xs.min()) - px, 0), max(int(ys.min()) - py, 0),
            min(int(xs.max()) + px, w), min(int(ys.max()) + py, h))


def build(out_path: str) -> Path:
    rows = []
    for pack_dir, label in PACKS:
        d = Path(pack_dir)
        man = json.loads(sorted(d.glob("*_manifest.json"))[0].read_text())
        style = man["style"]
        plate = Image.open(d / f"{style}_plate.png").convert("RGB")
        box = product_box(plate, STYLES_BY_NAME[style].backdrop)

        cells = [("plate, what the model was given", plate.crop(box))]
        frames = d / f"{style}_clip_frames"
        for name, idx in man["still_from_frame"].items():
            f = Image.open(frames / f"{int(idx):03d}.png").convert("RGB").resize(plate.size)
            cells.append((f"{name}, frame {idx}", f.crop(box)))
        rows.append((f"{label} / {style}", cells))

    ncol = max(len(c) for _, c in rows)
    W = LABEL_W + ncol * CELL
    H = 64 + len(rows) * (CELL + 34)
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    d.text((22, 22), "The product survives the generation", font=_font(28, bold=True), fill=FG)

    y = 64
    for label, cells in rows:
        d.text((22, y + CELL // 2 - 8), label, font=_font(17), fill=FG)
        for i, (cap, im) in enumerate(cells):
            x = LABEL_W + i * CELL
            im = im.copy()
            im.thumbnail((CELL - 12, CELL - 12), Image.LANCZOS)
            sheet.paste(im, (x + (CELL - im.width) // 2, y + (CELL - im.height) // 2))
            d.text((x + 8, y + CELL + 6), cap, font=_font(14), fill=DIM)
        y += CELL + 34

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"wrote {out}  {sheet.size[0]}x{sheet.size[1]}")
    return out


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "docs/gallery/product-survives.png")

# -*- coding: utf-8 -*-
"""Generate assets/examples from samples (run inside the project copy)."""
from pathlib import Path
import sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter

BASE = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SRC = BASE / "samples"
OUT = BASE / "assets" / "examples"
OUT.mkdir(parents=True, exist_ok=True)


def prep(name, src_name, max_side=1024):
    img = Image.open(SRC / src_name).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    img.save(OUT / name, "JPEG", quality=88)
    print(name, img.size)
    return img


s03 = prep("inpaint_dress.jpg", "s03.png")
s09 = prep("inpaint_multi.jpg", "s09.png")
prep("outpaint_room.jpg", "s06.png")
prep("remove_wm.jpg", "s05.png")
prep("remove_orange.jpg", "s09.png")
prep("remove_silver.jpg", "s07.png")
prep("style_anime.jpg", "s05.png")
prep("bg_beach.jpg", "s08.png")
prep("split_hat.jpg", "s01.png")


def mask_over(name, img, boxes):
    m = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(m)
    w, h = img.size
    for (x0, y0, x1, y1) in boxes:
        d.ellipse([x0 * w, y0 * h, x1 * w, y1 * h], fill=(255, 255, 255, 255))
    m.save(OUT / name)
    print(name, img.size)


def mask_preview(name, img, mask_name):
    """Visible preview for the Examples table (red = pre-brushed area)."""
    base = img.convert("RGBA")
    mask = Image.open(OUT / mask_name).convert("L")
    fill = Image.new("RGBA", base.size, (237, 28, 36, 0))
    fill.putalpha(mask.point(lambda a: 72 if a > 16 else 0))
    edge = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(9)), mask)
    red = Image.new("RGBA", base.size, (237, 28, 36, 0))
    red.putalpha(edge.point(lambda a: 220 if a else 0))
    preview = Image.alpha_composite(Image.alpha_composite(base, fill), red)
    preview.convert("RGB").save(OUT / name, "JPEG", quality=90, optimize=True)
    print(name, preview.size)


mask_over("inpaint_dress_mask.png", s03, [(0.28, 0.42, 0.80, 0.78)])
mask_over("inpaint_multi_mask.png", s09, [(0.06, 0.04, 0.94, 0.96)])
mask_preview("inpaint_dress_preview.jpg", s03, "inpaint_dress_mask.png")
mask_preview("inpaint_multi_preview.jpg", s09, "inpaint_multi_mask.png")
print("ASSETS_OK")

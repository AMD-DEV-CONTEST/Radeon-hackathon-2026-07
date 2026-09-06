"""Render the still frames of the demo video.

The terminal half of the video is recorded by vhs. This is the other half: what
actually came out, which for a content-creation tool is the point. Slides are
written at the same size as the terminal capture so the two concatenate without
a rescale.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dukaan.layout import _font  # noqa: E402

W, H = 1400, 800
BG = (17, 17, 21)
INK = (238, 238, 242)
DIM = (150, 150, 160)
ACCENT = (206, 50, 50)


def _slide() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def _title(d: ImageDraw.ImageDraw, text: str, sub: str = "", y: int = 60) -> int:
    d.text((80, y), text, font=_font(46), fill=INK)
    d.line([(80, y + 66), (200, y + 66)], fill=ACCENT, width=4)
    if sub:
        d.text((80, y + 86), sub, font=_font(22), fill=DIM)
        return y + 140
    return y + 100


def title_card(out: Path) -> None:
    img, d = _slide()
    d.text((80, 300), "Dukaan", font=_font(84), fill=INK)
    d.line([(80, 405), (300, 405)], fill=ACCENT, width=5)
    d.text((80, 430), "One product photo in, a shop's worth of creatives out.",
           font=_font(30), fill=INK)
    d.text((80, 476), "Generated on an AMD Radeon GPU through ROCm.", font=_font(30), fill=DIM)
    d.text((80, 690), "AMD DevMaster, Track 1: Multimodal Content Creation Tools",
           font=_font(20), fill=DIM)
    img.save(out)


def pipeline_card(out: Path, photo: Path, plate: Path) -> None:
    img, d = _slide()
    y = _title(d, "What the model is given",
               "The product is cut out and placed on a flat wash. Nothing else.")
    box = 330
    for i, (path, label) in enumerate([(photo, "the seller's photo"), (plate, "the plate")]):
        im = Image.open(path).convert("RGB")
        im.thumbnail((box, box), Image.LANCZOS)
        x = 150 + i * 620
        img.paste(im, (x, y + 40))
        d.text((x, y + 40 + im.height + 18), label, font=_font(22), fill=DIM)
    d.text((150 + 330 + 100, y + 190), "->", font=_font(56), fill=ACCENT)
    img.save(out)


def formats_card(out: Path, square: Path, story: Path, banner: Path, frames: tuple[int, int, int]) -> None:
    img, d = _slide()
    y = _title(d, "Three formats, one GPU pass",
               "Each still is a different moment of the same generated clip.")
    box = 340
    loaded = []
    for path, label in ((square, "square, frame %d" % frames[0]),
                        (story, "story, frame %d" % frames[1]),
                        (banner, "banner, frame %d" % frames[2])):
        im = Image.open(path).convert("RGB")
        im.thumbnail((box + 140, box), Image.LANCZOS)
        loaded.append((im, label))

    gap = 56
    total = sum(im.width for im, _ in loaded) + gap * (len(loaded) - 1)
    x = (W - total) // 2
    # The three shapes have different heights, so they are centred on a shared
    # baseline band rather than hung from a common top edge.
    band_top, band_h = y + 30, H - (y + 30) - 90
    for im, label in loaded:
        top = band_top + (band_h - im.height) // 2
        img.paste(im, (x, top))
        d.text((x, band_top + band_h + 16), label, font=_font(20), fill=DIM)
        x += im.width + gap
    img.save(out)


def gallery_card(out: Path, packs: list[tuple[Path, str, str]]) -> None:
    """Every pack in one frame, so the range of looks is visible at a glance."""
    img, d = _slide()
    y = _title(d, "Three products, three looks",
               "Same pipeline, one model load shared. Only the style name changed.")
    box = 330
    loaded = [(Image.open(p).convert("RGB"), style, secs) for p, style, secs in packs]
    for im, _, _ in loaded:
        im.thumbnail((box, box), Image.LANCZOS)
    gap = 60
    total = sum(im.width for im, _, _ in loaded) + gap * (len(loaded) - 1)
    x = (W - total) // 2
    top = y + 50
    for im, style, secs in loaded:
        img.paste(im, (x, top))
        d.text((x, top + im.height + 18), style, font=_font(24), fill=INK)
        d.text((x, top + im.height + 50), secs, font=_font(20), fill=DIM)
        x += im.width + gap
    img.save(out)


def styles_card(out: Path, sheet: Path) -> None:
    img, d = _slide()
    y = _title(d, "One photo, four looks",
               "Only the style name changed. The product is identical in all four.")
    im = Image.open(sheet).convert("RGB")
    im.thumbnail((W - 160, H - y - 120), Image.LANCZOS)
    img.paste(im, ((W - im.width) // 2, y + 40))
    img.save(out)


def batching_card(out: Path) -> None:
    img, d = _slide()
    y = _title(d, "A shop has a catalogue, not a photo",
               "The model load is paid once for the batch, not once per product.")
    rows = [
        ("checkpoint + text encoder load", "17.9 s", "paid once", INK),
        ("first product", "45.8 s", "", DIM),
        ("second product", "34.6 s", "same work, warmer GPU", DIM),
        ("third product", "23.2 s", "", DIM),
        ("3 products batched", "125 s", "vs ~186 s separately", ACCENT),
    ]
    ry = y + 30
    for a, b, c, colour in rows:
        d.text((110, ry), a, font=_font(26), fill=colour)
        d.text((640, ry), b, font=_font(26), fill=colour)
        d.text((820, ry), c, font=_font(22), fill=colour)
        ry += 54
    img.save(out)


def finding_card(out: Path) -> None:
    img, d = _slide()
    y = _title(d, "The instance cannot run its own template",
               "ComfyUI holds every model a graph touches for the life of the process.")
    rows = [
        ("LTX-2.3 diffusion checkpoint", "43 GB", DIM),
        ("Gemma 3 12B text encoder", "23 GB", DIM),
        ("Total to load", "66 GB", INK),
        ("Container cap", "55 GB", ACCENT),
    ]
    ry = y + 30
    for label, value, colour in rows:
        d.text((110, ry), label, font=_font(28), fill=colour)
        d.text((760, ry), value, font=_font(28), fill=colour)
        ry += 52
    d.line([(110, ry + 6), (900, ry + 6)], fill=(60, 60, 70), width=2)
    d.text((110, ry + 30),
           "Loading both trips the cap and the platform restarts the container",
           font=_font(24), fill=INK)
    d.text((110, ry + 62),
           "mid-prompt. It presents as a network fault. It is not.",
           font=_font(24), fill=INK)
    img.save(out)



def _test_count() -> int:
    """How many tests the suite actually collects, right now."""
    import subprocess
    try:
        out = subprocess.run([".venv/bin/python", "-m", "pytest", "--collect-only", "-q"],
                             capture_output=True, text=True, timeout=120).stdout
        m = re.search(r"(\d+) tests? collected", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    raise SystemExit("could not count tests; refusing to print a guess on a slide")

def fix_card(out: Path) -> None:
    img, d = _slide()
    y = _title(d, "Two processes that never overlap",
               "Peak becomes max(43, 23) instead of 43 + 23.")
    rows = [
        ("phase", "peak container RAM", "wall", INK),
        ("encode, text encoder only", "35.4 GB", "33 s", DIM),
        ("sample, checkpoint only", "51.2 GB", "55 s", DIM),
        ("stock template, one process", "trips 55 GB, restarts", "n/a", ACCENT),
    ]
    ry = y + 30
    for a, b, c, colour in rows:
        d.text((110, ry), a, font=_font(26), fill=colour)
        d.text((640, ry), b, font=_font(26), fill=colour)
        d.text((1060, ry), c, font=_font(26), fill=colour)
        ry += 54
    d.text((110, ry + 40), "65 s of GPU time per pack. 49 frames at 768x768, with audio.",
           font=_font(26), fill=INK)
    # Counted, not typed. This slide said 30 while the suite had grown to 37,
    # and the tape beside it said 26. A number on a slide is a number that rots.
    d.text((110, ry + 82), f"{_test_count()} tests, none of which need a GPU.",
           font=_font(26), fill=DIM)
    img.save(out)


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/dukaan-slides")
    src = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("out/brass-ewer")
    dest.mkdir(parents=True, exist_ok=True)

    import json

    manifests = sorted(src.glob("*_manifest.json"))
    if not manifests:
        sys.exit(f"no pack found in {src}; run `dukaan pack` first")
    man = json.loads(manifests[0].read_text())
    style, f = man["style"], man["still_from_frame"]

    title_card(dest / "01-title.png")
    pipeline_card(dest / "02-pipeline.png",
                  Path("examples") / f"{man['product']}.png",
                  src / f"{style}_plate.png")
    formats_card(dest / "03-formats.png", src / f"{style}_square.png",
                 src / f"{style}_story.png", src / f"{style}_banner.png",
                 (f["square"], f["story"], f["banner"]))
    # Pinned to the style matrix rather than whatever `out/` happens to hold.
    # Scanning the directory picked up whichever packs were oldest, so this card
    # kept showing output from before the cutout was repaired while the gallery
    # beside it showed the fixed version.
    packs = []
    for d, style in (("out/matrix-festive/brass-ewer", "festive"),
                     ("out/matrix-midnight/gilt-bangles", "midnight"),
                     ("out/matrix-studio/silver-bracelet", "studio")):
        d = Path(d)
        m = sorted(d.glob("*_manifest.json"))
        if not m:
            continue
        mm = json.loads(m[0].read_text())
        square = d / f"{style}_square.png"
        if square.exists():
            run = mm.get("run", {})
            secs = run.get("sample_seconds") or run.get("seconds")
            packs.append((square, style, f"{secs} s of sampling" if secs else ""))
    if len(packs) >= 2:
        gallery_card(dest / "04-gallery.png", packs[:3])

    sheet = Path("docs/gallery/one-photo-four-styles.png")
    if sheet.exists():
        styles_card(dest / "05-styles.png", sheet)
    finding_card(dest / "06-finding.png")
    fix_card(dest / "07-fix.png")
    batching_card(dest / "08-batching.png")
    for p in sorted(dest.glob("*.png")):
        print(p, Image.open(p).size)

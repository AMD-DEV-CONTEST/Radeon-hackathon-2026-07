#!/usr/bin/env python3
"""Render the visual-QA contact sheets recorded in submission/ARTIFACT_MANIFEST.json.

Three sheets are produced, each a dark-background grid of the pages or cards it
summarises:

- ``docs/assets/deck-contact.png``  — the ten Track 2 deck slides (5x2);
- ``docs/assets/spec-contact.png``  — the nine specification PDF pages (3x3);
- ``docs/assets/video-contact.png`` — the six current video cards (3x2).

The sheets are inspection evidence, not submission deliverables: they let a
reviewer confirm at a glance that the regenerated deck, specification and video
cards carry the intended figures. Regenerate them whenever the deck, the
specification PDF or the video cards change, then refresh the manifest hashes.

Requires ``pdftoppm`` (poppler-utils) and Pillow.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BACKGROUND = (13, 13, 15)
MARGIN = 8
GAP = 8


def _grid(
    images: list[Image.Image],
    columns: int,
    cell: tuple[int, int],
    canvas: tuple[int, int] | None = None,
) -> Image.Image:
    """Paste ``images`` into a ``columns``-wide grid of ``cell``-sized thumbnails.

    ``canvas`` pins the exact output size when the cell arithmetic leaves a
    rounding remainder, so a regenerated sheet keeps the dimensions recorded in
    the manifest.
    """
    width, height = cell
    rows = (len(images) + columns - 1) // columns
    size = canvas or (
        MARGIN * 2 + columns * width + (columns - 1) * GAP,
        MARGIN * 2 + rows * height + (rows - 1) * GAP,
    )
    sheet = Image.new("RGB", size, BACKGROUND)
    for index, image in enumerate(images):
        column, row = index % columns, index // columns
        sheet.paste(
            image.convert("RGB").resize((width, height), Image.LANCZOS),
            (MARGIN + column * (width + GAP), MARGIN + row * (height + GAP)),
        )
    return sheet


def _pdf_pages(pdf: Path, work: Path) -> list[Image.Image]:
    prefix = work / pdf.stem
    subprocess.run(
        ["pdftoppm", "-png", "-r", "72", str(pdf), str(prefix)],
        check=True,
        capture_output=True,
    )
    return [Image.open(page) for page in sorted(work.glob(f"{pdf.stem}-*.png"))]


def main() -> None:
    assets = ROOT / "docs" / "assets"
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        deck = _pdf_pages(ROOT / "submission" / "NuclidePath_Track2_Deck.pdf", work)
        _grid(deck, columns=5, cell=(256, 144)).save(assets / "deck-contact.png")

        spec = _pdf_pages(
            ROOT / "submission" / "NuclidePath_Project_Specification.pdf", work
        )
        _grid(spec, columns=3, cell=(320, 452)).save(assets / "spec-contact.png")

    cards = sorted((ROOT / "private-deliverables" / "current-video-assets").glob("slide-*.png"))
    _grid(
        [Image.open(card) for card in cards],
        columns=3,
        cell=(325, 184),
        canvas=(1008, 392),
    ).save(assets / "video-contact.png")

    for sheet in ("deck-contact.png", "spec-contact.png", "video-contact.png"):
        print(assets / sheet)


if __name__ == "__main__":
    main()

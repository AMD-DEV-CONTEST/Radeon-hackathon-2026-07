"""What a campaign pack is.

Formats are the shapes a small seller actually posts: a square for the feed,
a vertical for stories and reels, a wide banner for a marketplace header.
Keeping them declarative means the pack can grow without touching the
compositor.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Format:
    name: str
    width: int
    height: int
    #: where the headline sits, as a fraction of height
    text_band: float
    note: str

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def aspect(self) -> float:
        return self.width / self.height


FORMATS: tuple[Format, ...] = (
    Format("square", 1024, 1024, 0.24, "feed post"),
    Format("story", 1024, 1820, 0.20, "stories and reels, 9:16"),
    Format("banner", 1820, 1024, 0.28, "marketplace or shop header, 16:9"),
)

FORMATS_BY_NAME = {f.name: f for f in FORMATS}


@dataclass(frozen=True)
class Style:
    """A look the seller can pick without knowing what a prompt is."""

    name: str
    prompt: str
    negative: str
    #: background wash behind the product, used when composing the plate
    backdrop: tuple[int, int, int]
    ink: tuple[int, int, int]
    #: What the camera and the scene do over the clip. Kept apart from the
    #: look because the model is generating motion, and asking for a still
    #: product with a moving world is what keeps the product recognisable.
    motion_prompt: str = (
        "A product commercial. The product sits still and stays exactly as it is. "
        "The camera pushes in very slowly. Only the light and the background move."
    )

    @property
    def label(self) -> str:
        return self.name.replace("_", " ")


STYLES: tuple[Style, ...] = (
    Style(
        "studio",
        "professional product photography, seamless studio backdrop, soft key light, "
        "subtle reflection, crisp focus, commercial catalogue quality",
        "clutter, harsh shadow, text, watermark, distorted product",
        (243, 240, 234),
        (26, 26, 26),
    ),
    Style(
        "festive",
        "warm festive product shot, marigold and deep red tones, soft bokeh string lights, "
        "celebratory indian festival mood, rich saturated colour",
        "clutter, text, watermark, distorted product, dull",
        (58, 12, 22),
        (255, 232, 186),
    ),
    Style(
        "daylight",
        "fresh daylight product shot, pale wooden surface, soft diffused morning "
        "light, gentle shadows, honest everyday look",
        "clutter, text, watermark, distorted product, artificial, window frame, "
        "hard shadow edge, split background, reshaped product, closed gap, "
        "thicker object, changed proportions",
        # Pale birch, deliberately between two failures. At (238, 232, 220) this
        # style sat within a few values of studio's (243, 240, 234) and produced
        # the same picture twice. At a full oak (198, 168, 132) it was properly
        # distinct, but the plate had drifted far enough from the product that
        # conditioning weakened and the model re-interpreted the silver
        # bracelet: an open flat bangle came back as a closed thick ring, which
        # is the one thing this tool must not do. Backdrop choice is a
        # conditioning strength dial, not a palette.
        (224, 203, 175),
        (38, 30, 22),
    ),
    Style(
        "midnight",
        "premium product shot on dark matte surface, single dramatic rim light, "
        "deep contrast, luxury minimal",
        "clutter, text, watermark, distorted product, washed out",
        (16, 18, 24),
        (240, 240, 245),
    ),
)

STYLES_BY_NAME = {s.name: s for s in STYLES}


@dataclass
class Brief:
    """One seller's ask: a photo, a line of text, a look."""

    product: str
    headline: str
    subline: str = ""
    style: str = "studio"

    def styled(self) -> Style:
        if self.style not in STYLES_BY_NAME:
            raise ValueError(
                f"unknown style {self.style!r}, pick one of: {', '.join(STYLES_BY_NAME)}"
            )
        return STYLES_BY_NAME[self.style]

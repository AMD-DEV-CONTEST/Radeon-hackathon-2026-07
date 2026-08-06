"""Small fixed palettes used by pixelify."""

from __future__ import annotations

import numpy as np

PALETTES: dict[str, tuple[str, ...]] = {
    "gameboy": ("0f380f", "306230", "8bac0f", "9bbc0f"),
    "pico8": (
        "000000",
        "1d2b53",
        "7e2553",
        "008751",
        "ab5236",
        "5f574f",
        "c2c3c7",
        "fff1e8",
        "ff004d",
        "ffa300",
        "ffec27",
        "00e436",
        "29adff",
        "83769c",
        "ff77a8",
        "ffccaa",
    ),
    "nes": (
        "000000",
        "fcfcfc",
        "f8b800",
        "f83800",
        "d82800",
        "a80020",
        "9878f8",
        "6844fc",
        "0058f8",
        "00a8f8",
        "00b800",
        "00a800",
        "b8f818",
        "f8d878",
        "f87858",
        "7c7c7c",
    ),
}


def get_palette(name: str) -> np.ndarray:
    return np.asarray(
        [[int(color[i : i + 2], 16) for i in (0, 2, 4)] for color in PALETTES[name]],
        dtype=np.uint8,
    )

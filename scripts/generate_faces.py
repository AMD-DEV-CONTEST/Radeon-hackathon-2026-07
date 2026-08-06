#!/usr/bin/env python
"""Generate a few "lovely face" avatar options via the Z-Image-Turbo service.

These become optional avatar choices for the frontend dotted-face. They are
GENERIC faces (no real-person reference), so we vary style instead of identity.

Usage: .venv/bin/python scripts/generate_faces.py [--out frontend/faces]
"""
from __future__ import annotations

import argparse
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE = os.getenv("IMAGE_SERVICE_URL", "http://127.0.0.1:8090")

# (filename, prompt) — varied styles so the user has a real choice of look.
# The prompts are tuned for the dotted-face: a HEAD-AND-SHOULDERS crop that is
# fully inside the frame (clear margin on every side), a clean SOLID background,
# and high-contrast features (dark irises, clear brows, a defined mouth) so the
# stipple generator can carve out recognisable eyes/mouth/emotion.
FACES = [
    ("face_realistic.png",
     "a warm friendly photorealistic portrait of a person, gentle smile, "
     "big bright eyes with visible dark irises and catchlights, defined "
     "eyebrows, soft studio lighting, head and shoulders centered, plain solid "
     "light grey background, the whole head fully inside the frame with clear "
     "margin on all sides, high detail, symmetrical, front-facing"),
    ("face_illustration.png",
     "a cute soft kawaii illustration portrait of a friendly person, LARGE "
     "expressive eyes with dark irises and white highlights, defined dark "
     "eyebrows, a clear gentle smile with distinct lips, smooth flat pastel "
     "skin, head and shoulders centered, plain solid clean background, the "
     "whole head fully inside the frame with clear margin on all sides, "
     "front view, symmetrical, simple storybook style"),
    ("face_minimal.png",
     "a minimalist elegant flat illustration portrait, calm friendly "
     "expression with a soft smile, large clear dark eyes, simple solid "
     "neutral background, head and shoulders centered with the whole head "
     "fully inside the frame and clear margin on all sides, front-facing, "
     "clean vector style"),
]


def gen(prompt: str, out_path: str, size: int = 768, seed: int = 7) -> int:
    if os.path.exists(out_path):
        print(f"  skip (exists): {os.path.basename(out_path)}")
        return 0
    resp = requests.post(
        f"{SERVICE}/generate",
        json={"prompt": prompt, "w": size, "h": size, "seed": seed, "out": out_path},
        timeout=240,
    )
    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text[:160]}")
        return 1
    print(f"  ok {os.path.basename(out_path)} ({len(resp.content)} bytes)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "frontend", "faces"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    print(f"service: {SERVICE}")
    for i, (fname, prompt) in enumerate(FACES):
        print(f"[{i+1}/{len(FACES)}] {fname}")
        gen(prompt, os.path.join(args.out, fname), seed=7 + i * 13)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Pre-load Kokoro TTS models + voices so the first real diary reply isn't slow.

Kokoro downloads its model and voice `.pt` files from the HuggingFace mirror on
first use. On this box that pull is slow through the proxy, so run this once at
deploy time (or inside the compose startup) to populate the HF cache and warm
the in-process pipeline cache. Safe to re-run; downloads are cached.

Usage:
    ./.venv/bin/python scripts/warm_kokoro.py
"""
from __future__ import annotations

import time

from tts import kokoro_tts as K


def main() -> None:
    for lang, text in (
        ("zh", "预热语音合成模型。"),
        ("en", "Warming up the speech synthesis model."),
    ):
        t0 = time.time()
        out = K.synthesize(text, f"/tmp/kokoro_warm_{lang}", lang=lang)
        dt = time.time() - t0
        if out:
            print(f"[{lang}] warmed in {dt:.1f}s -> {out}")
        else:
            print(f"[{lang}] FAILED to warm up (check kokoro install)")


if __name__ == "__main__":
    main()

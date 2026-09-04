#!/usr/bin/env python3
"""Create proportional paragraph-level SRT captions from VIDEO_NARRATION.md."""
from __future__ import annotations

import argparse
import re
import textwrap
from pathlib import Path


def stamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--narration", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.narration.read_text(encoding="utf-8")
    body = source.split("**Target:** 3–5 minutes", 1)[-1].strip()
    paragraphs = [" ".join(item.split()) for item in body.split("\n\n") if item.strip()]
    sentences = [sentence for paragraph in paragraphs for sentence in re.split(r"(?<=[.!?])\s+", paragraph)]
    captions: list[str] = []
    for sentence in sentences:
        lines = textwrap.wrap(sentence, width=44)
        captions.extend("\n".join(lines[start : start + 2]) for start in range(0, len(lines), 2))
    weights = [len(item.split()) for item in captions]
    total = sum(weights)
    cursor = 0.0
    blocks: list[str] = []
    for index, (caption, weight) in enumerate(zip(captions, weights, strict=True), start=1):
        end = args.duration if index == len(captions) else cursor + args.duration * weight / total
        blocks.append(f"{index}\n{stamp(cursor)} --> {stamp(end)}\n{caption}\n")
        cursor = end
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(blocks), encoding="utf-8")
    print(f"captions={len(blocks)} duration={args.duration:.3f}s output={args.output}")


if __name__ == "__main__":
    main()

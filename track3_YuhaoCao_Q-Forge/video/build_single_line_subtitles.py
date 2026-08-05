#!/usr/bin/env python3
"""Build exact, single-line SRT cues from ElevenLabs character alignment."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def stamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def chunks(text: str) -> list[tuple[int, int, str]]:
    """Split at speech-friendly boundaries while keeping every cue one line."""
    spans: list[tuple[int, int, str]] = []
    start = 0
    words = 0
    for match in re.finditer(r"\S+", text):
        words += 1
        token = match.group()
        strong = bool(re.search(r"[.!?]$", token))
        soft = bool(re.search(r"[;:,]$", token))
        display_length = len(" ".join(text[start : match.end()].split()))
        # Six words stays comfortably inside a 1920-wide frame even for long
        # technical vocabulary. Strong punctuation may end a shorter cue.
        if strong or (words >= 4 and soft) or words >= 6 or (words >= 2 and display_length >= 64):
            end = match.end()
            line = " ".join(text[start:end].split())
            if line:
                spans.append((start, end, line))
            start = end
            while start < len(text) and text[start].isspace():
                start += 1
            words = 0
    if start < len(text):
        line = " ".join(text[start:].split())
        if line:
            spans.append((start, len(text), line))
    return spans


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", type=Path, default=Path("video/narration.txt"))
    parser.add_argument("--alignment", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("video/subtitles.srt"))
    parser.add_argument(
        "--time-scale",
        type=float,
        default=1.0,
        help="Multiply alignment timestamps, for example after a final atempo pass.",
    )
    args = parser.parse_args()

    text = args.text.read_text(encoding="utf-8")
    payload = json.loads(args.alignment.read_text(encoding="utf-8"))
    alignment = payload.get("alignment") or payload["normalized_alignment"]
    characters = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    aligned_text = "".join(characters)
    if " ".join(aligned_text.split()) != " ".join(text.split()):
        raise ValueError("Alignment text does not match narration")

    # Alignment indexes refer to its own character stream. Locate each normalized
    # cue in that stream sequentially, preserving exact speech timestamps.
    cursor = 0
    cues = []
    normalized_source = " ".join(text.split())
    display_replacements = {
        "four-hundred-and-fifty-million-parameter": "450M-parameter",
        "vision-language-action": "VLA",
    }
    for _, _, line in chunks(normalized_source):
        index = aligned_text.find(line, cursor)
        if index < 0:
            raise ValueError(f"Could not locate cue in alignment: {line!r}")
        last = index + len(line) - 1
        display_line = line
        for source, replacement in display_replacements.items():
            display_line = display_line.replace(source, replacement)
        cues.append(
            (starts[index] * args.time_scale, ends[last] * args.time_scale, display_line)
        )
        cursor = last + 1

    blocks = []
    for number, (start, end, line) in enumerate(cues, 1):
        blocks.append(f"{number}\n{stamp(start)} --> {stamp(end)}\n{line}")
    args.output.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

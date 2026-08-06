#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED = (
    "brief.md",
    "app/index.html",
    "subtitles.srt",
    "video.mp4",
    "poster.png",
)


@dataclass
class Subtitle:
    start: float
    end: float
    text: str


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)


def parse_time(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def parse_srt(path: Path) -> list[Subtitle]:
    raw = path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        return []

    blocks = re.split(r"\n\s*\n", raw)
    subtitles: list[Subtitle] = []
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            raise ValueError(f"Malformed SRT block: {block[:100]!r}")
        timing_index = 1 if re.fullmatch(r"\d+", lines[0]) else 0
        if timing_index >= len(lines) or " --> " not in lines[timing_index]:
            raise ValueError(f"Missing SRT timing line: {block[:100]!r}")
        start_text, end_text = lines[timing_index].split(" --> ", 1)
        start, end = parse_time(start_text), parse_time(end_text)
        if end <= start:
            raise ValueError("Subtitle end time must be after start time")
        text = "\n".join(lines[timing_index + 1 :]).strip()
        if not text:
            raise ValueError("Subtitle text cannot be empty")
        subtitles.append(Subtitle(start=start, end=end, text=text))

    for previous, current in zip(subtitles, subtitles[1:]):
        if current.start + 0.01 < previous.start:
            raise ValueError("Subtitles are not in chronological order")
    return subtitles


def ffprobe(path: Path) -> dict:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,avg_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def main() -> int:
    run_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    errors: list[str] = []

    for relative in REQUIRED:
        path = run_dir / relative
        if not path.exists():
            errors.append(f"missing required output: {relative}")
        elif path.is_file() and path.stat().st_size == 0:
            errors.append(f"empty output file: {relative}")

    if errors:
        for error in errors:
            fail(error)
        return 1

    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (run_dir / "app").rglob("*")
        if path.is_file() and path.suffix.lower() in {".html", ".js", ".mjs", ".ts"}
    )
    if "renderFrame" not in source_text:
        errors.append("app source does not appear to expose renderFrame(t)")
    if "LIVE_SCIENCE_META" not in source_text:
        errors.append("app source does not appear to define LIVE_SCIENCE_META")

    try:
        subtitles = parse_srt(run_dir / "subtitles.srt")
        if not subtitles:
            errors.append("subtitles.srt contains no subtitle cues")
    except Exception as exc:
        errors.append(f"invalid subtitles.srt: {exc}")
        subtitles = []

    try:
        probe = ffprobe(run_dir / "video.mp4")
        duration = float(probe["format"]["duration"])
        video_streams = [
            stream
            for stream in probe.get("streams", [])
            if stream.get("codec_type") == "video"
        ]
        if not video_streams:
            errors.append("video.mp4 has no video stream")
            width = height = 0
        else:
            width = int(video_streams[0].get("width", 0))
            height = int(video_streams[0].get("height", 0))
        if duration <= 0:
            errors.append("video.mp4 duration is not positive")
        if width < 1280 or height < 720:
            errors.append(
                f"video resolution {width}×{height} is below the Phase 1 minimum 1280×720"
            )
        if subtitles and subtitles[-1].end > duration + 1.5:
            errors.append(
                f"last subtitle ends at {subtitles[-1].end:.2f}s, "
                f"after video duration {duration:.2f}s"
            )
    except FileNotFoundError:
        errors.append("ffprobe is not installed or not in PATH")
        duration = 0.0
        width = height = 0
    except Exception as exc:
        errors.append(f"could not inspect video.mp4: {exc}")
        duration = 0.0
        width = height = 0

    try:
        from PIL import Image

        with Image.open(run_dir / "poster.png") as image:
            if image.width < 640 or image.height < 360:
                errors.append(
                    f"poster resolution {image.width}×{image.height} is unexpectedly small"
                )
    except ImportError:
        pass
    except Exception as exc:
        errors.append(f"poster.png is invalid: {exc}")

    if errors:
        for error in errors:
            fail(error)
        return 1

    print("PASS: Phase 1 outputs are structurally valid.")
    print(f"  video: {width}×{height}, {duration:.2f}s")
    print(f"  subtitles: {len(subtitles)} cues")
    print(f"  run directory: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

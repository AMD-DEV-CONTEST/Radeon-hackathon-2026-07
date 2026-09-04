#!/usr/bin/env python3
"""Build the NuclidePath narrated 3–5 minute demo video.

The generated MP4 is intentionally kept outside Git; the public submission uses
its hosted URL. All subprocesses use argv lists, never a shell.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

WIDTH, HEIGHT, FPS = 1920, 1080, 30


def run(*args: str) -> None:
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def static_segment(image: Path, seconds: float, output: Path) -> None:
    video_filter = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={FPS},format=yuv420p"
    )
    run(
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-t",
        f"{seconds:.3f}",
        "-vf",
        video_filter,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        str(output),
    )


def live_segment(source: Path, seconds: float, output: Path) -> None:
    source_duration = duration(source)
    speed = seconds / source_duration
    video_filter = (
        f"setpts={speed:.9f}*PTS,"
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={FPS},format=yuv420p"
    )
    run(
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-t",
        f"{seconds:.3f}",
        "-vf",
        video_filter,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        str(output),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--narration", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--dashboard", type=Path, required=True)
    parser.add_argument("--uncertainty", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg and ffprobe are required")
    required = [
        args.live,
        args.narration,
        args.dashboard,
        args.uncertainty,
        *(args.assets_dir / f"slide-{number}.png" for number in ("01", "03", "05", "06", "08", "09")),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing input files: {missing}")

    audio_duration = duration(args.narration)
    if not 180.0 <= audio_duration <= 300.0:
        raise SystemExit(f"narration must be 3–5 minutes, got {audio_duration:.2f}s")

    # Timings follow the narration: context, architecture, live workflow,
    # physics, uncertainty, auditability, AMD evidence, conclusion.
    fixed = [30.0, 17.0, 53.0, 55.0, 35.0, 28.0, 21.0, 31.0]
    # Preserve the narrative proportions for shorter valid 3–5 minute audio
    # while reserving at least ten seconds for the closing card.
    if sum(fixed) > audio_duration - 10.0:
        scale = (audio_duration - 10.0) / sum(fixed)
        fixed = [seconds * scale for seconds in fixed]
    closing = audio_duration - sum(fixed)
    if closing < 8.0:
        raise SystemExit("narration too short for the declared visual sequence")
    sequence: list[tuple[str, Path, float]] = [
        ("static", args.assets_dir / "slide-01.png", fixed[0]),
        ("static", args.assets_dir / "slide-03.png", fixed[1]),
        ("live", args.live, fixed[2]),
        ("static", args.assets_dir / "slide-05.png", fixed[3]),
        ("static", args.uncertainty, fixed[4]),
        ("static", args.dashboard, fixed[5]),
        ("static", args.assets_dir / "slide-06.png", fixed[6]),
        ("static", args.assets_dir / "slide-08.png", fixed[7]),
        ("static", args.assets_dir / "slide-09.png", closing),
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nuclidepath-video-", dir=args.output.parent) as temp_name:
        temp = Path(temp_name)
        segments: list[Path] = []
        for index, (kind, source, seconds) in enumerate(sequence, start=1):
            target = temp / f"segment-{index:02d}.mp4"
            if kind == "live":
                live_segment(source, seconds, target)
            else:
                static_segment(source, seconds, target)
            segments.append(target)

        concat = temp / "concat.txt"
        concat.write_text("".join(f"file '{path}'\n" for path in segments), encoding="utf-8")
        visuals = temp / "visuals.mp4"
        run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(visuals))
        run(
            "ffmpeg",
            "-y",
            "-i",
            str(visuals),
            "-i",
            str(args.narration),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(args.output),
        )

    final_duration = duration(args.output)
    if not 180.0 <= final_duration <= 300.0:
        raise SystemExit(f"final video outside 3–5 minutes: {final_duration:.2f}s")
    print(json.dumps({"output": str(args.output), "duration_s": final_duration, "resolution": [WIDTH, HEIGHT], "fps": FPS}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Assemble Phase 3 segments while removing duplicate boundary frames."""

from __future__ import annotations

import argparse
import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any


class AssemblyError(RuntimeError):
    pass


def probe(path: Path, count_frames: bool = False) -> dict[str, Any]:
    command = ["ffprobe", "-v", "error", "-select_streams", "v:0"]
    if count_frames:
        command.append("-count_frames")
    command.extend([
        "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames",
        "-of", "json", str(path),
    ])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise AssemblyError(f"no video stream: {path}")
    return streams[0]


def assemble(inputs: list[Path], output: Path) -> dict[str, Any]:
    if not inputs:
        raise AssemblyError("no segment videos")
    metadata = [probe(path, count_frames=True) for path in inputs]
    signature = {(item["width"], item["height"], item["r_frame_rate"]) for item in metadata}
    if len(signature) != 1:
        raise AssemblyError(f"incompatible segment video formats: {sorted(signature)}")
    filters: list[str] = []
    labels: list[str] = []
    for index in range(len(inputs)):
        trim = "" if index == 0 else "trim=start_frame=1,"
        filters.append(f"[{index}:v:0]{trim}setpts=PTS-STARTPTS,format=yuv420p[v{index}]")
        labels.append(f"[v{index}]")
    filters.append("".join(labels) + f"concat=n={len(inputs)}:v=1:a=0[outv]")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-loglevel", "error"]
    for path in inputs:
        command.extend(["-i", str(path)])
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[outv]", "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(output),
    ])
    subprocess.run(command, check=True)
    expected = sum(int(item["nb_read_frames"]) for item in metadata) - (len(inputs) - 1)
    result = probe(output, count_frames=True)
    actual = int(result["nb_read_frames"])
    if actual != expected:
        raise AssemblyError(f"frame count mismatch for {output}: expected {expected}, got {actual}")
    fps = float(Fraction(result["r_frame_rate"]))
    return {"path": str(output), "frames": actual, "fps": fps, "width": result["width"], "height": result["height"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--kind", choices=("base", "final", "both"), default="both")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    timeline = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))
    ids = [item["id"] for item in timeline.get("segments", [])]
    if not ids:
        raise AssemblyError("timeline has no segments")
    report: dict[str, Any] = {}
    if args.kind in {"base", "both"}:
        inputs = [run_dir / "segments" / segment_id / "video.mp4" for segment_id in ids]
        for path in inputs:
            if not path.is_file():
                raise FileNotFoundError(path)
        report["base"] = assemble(inputs, run_dir / "base_video.mp4")
    if args.kind in {"final", "both"}:
        inputs = [run_dir / "segments" / segment_id / "annotated.mp4" for segment_id in ids]
        for path in inputs:
            if not path.is_file():
                raise FileNotFoundError(path)
        report["final"] = assemble(inputs, run_dir / "final_video.mp4")
    (run_dir / "assembly.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

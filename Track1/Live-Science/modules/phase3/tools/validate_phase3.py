#!/usr/bin/env python3
"""Validate a complete Phase 3 run and its source traceability."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any


class ValidationError(RuntimeError):
    pass


def require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValidationError(f"missing or empty file: {path}")


def probe(path: Path) -> dict[str, Any]:
    if shutil.which("ffprobe") is None:
        import av

        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            frames = sum(1 for _ in container.decode(stream))
            return {
                "width": stream.width,
                "height": stream.height,
                "r_frame_rate": str(stream.average_rate),
                "nb_read_frames": str(frames),
                "frames": frames,
                "fps": float(stream.average_rate),
            }
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise ValidationError(f"no video stream: {path}")
    stream = streams[0]
    stream["frames"] = int(stream["nb_read_frames"])
    stream["fps"] = float(Fraction(stream["r_frame_rate"]))
    return stream


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--phase1-run", type=Path, required=True)
    parser.add_argument("--phase2-run", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    for path in (args.phase1_run.resolve() / "bridge/manifest.json", args.phase2_run.resolve() / "selected_anchors.json"):
        require_file(path)
    for path in (run_dir / "timeline.json", run_dir / "base_video.mp4", run_dir / "final_video.mp4", run_dir / "report.md"):
        require_file(path)
    timeline = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))
    segments = timeline.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValidationError("timeline.json must contain at least one segment")
    ids: list[str] = []
    segment_streams: list[dict[str, Any]] = []
    for item in segments:
        segment_id = item.get("id")
        if not isinstance(segment_id, str) or not segment_id or "/" in segment_id or ".." in segment_id:
            raise ValidationError(f"invalid segment id: {segment_id!r}")
        if segment_id in ids:
            raise ValidationError(f"duplicate segment id: {segment_id}")
        ids.append(segment_id)
        segment_dir = run_dir / "segments" / segment_id
        for name in ("start.png", "end.png", "prompt.txt", "video.mp4", "annotated.mp4", "subtitles.srt"):
            require_file(segment_dir / name)
        if item.get("sourceType", "generated") == "generated":
            for name in ("workflow_api.json", "generation.json"):
                require_file(segment_dir / name)
            generation = json.loads((segment_dir / "generation.json").read_text(encoding="utf-8"))
            if generation.get("status") != "complete":
                raise ValidationError(f"segment {segment_id} generation is not complete")
        segment_streams.append(probe(segment_dir / "video.mp4"))
    signatures = {(item["width"], item["height"], item["r_frame_rate"]) for item in segment_streams}
    if len(signatures) != 1:
        raise ValidationError(f"incompatible segment formats: {sorted(signatures)}")
    expected_frames = sum(item["frames"] for item in segment_streams) - (len(segment_streams) - 1)
    base, final = probe(run_dir / "base_video.mp4"), probe(run_dir / "final_video.mp4")
    if base["frames"] != expected_frames:
        raise ValidationError(f"base video has {base['frames']} frames; expected {expected_frames}")
    if final["frames"] != expected_frames:
        raise ValidationError(f"final video has {final['frames']} frames; expected {expected_frames}")
    result = {
        "status": "passed", "segmentCount": len(ids), "segments": ids,
        "expectedFrames": expected_frames, "base": base, "final": final,
    }
    if not args.check_only:
        (run_dir / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Phase 3 validation passed: {len(ids)} segments, {expected_frames} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

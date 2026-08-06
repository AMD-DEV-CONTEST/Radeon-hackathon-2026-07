#!/usr/bin/env python3
"""Run all generated Phase 3 timeline segments serially."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    timeline = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))
    runner = Path(__file__).resolve().parent / "run_ltx_flf.py"
    segments = timeline.get("segments", [])
    if not segments:
        raise RuntimeError("timeline has no segments")
    for segment in segments:
        segment_id = segment["id"]
        if segment.get("sourceType", "generated") != "generated":
            print(f"Skipping non-generated segment {segment_id}", flush=True)
            continue
        segment_dir = run_dir / "segments" / segment_id
        video = segment_dir / "video.mp4"
        generation = segment_dir / "generation.json"
        if not args.force and not args.prepare_only and video.is_file() and generation.is_file():
            metadata = json.loads(generation.read_text(encoding="utf-8"))
            if metadata.get("status") == "complete":
                print(f"Skipping completed segment {segment_id}", flush=True)
                continue
        command = [
            sys.executable, str(runner), str(run_dir), "--segment-id", segment_id,
            "--server", args.server, "--timeout", str(args.timeout),
        ]
        if args.prepare_only:
            command.append("--prepare-only")
        subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

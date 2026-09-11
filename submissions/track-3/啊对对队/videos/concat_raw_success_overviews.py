#!/usr/bin/env python3
"""Stream-copy the audited successful overview episodes in episode order."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from fractions import Fraction
from pathlib import Path

import av


SUCCESS_IDS = (0, 1, 2, 4, 6, 7, 8, 9)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_video(path: Path) -> dict:
    container = av.open(str(path))
    stream = container.streams.video[0]
    fps = float(stream.average_rate or stream.guessed_rate or 0)
    frames = 0
    nonblank_samples: list[bool] = []
    try:
        for frame in container.decode(video=0):
            if frames in (0, 1) or frames % 100 == 0:
                extrema = frame.to_image().convert("RGB").getextrema()
                nonblank_samples.append(any(high > 0 for _low, high in extrema))
            frames += 1
    finally:
        container.close()
    if frames == 0 or fps <= 0:
        raise RuntimeError(f"undecodable source: {path}")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "codec": stream.codec_context.name,
        "resolution": [stream.width, stream.height],
        "fps": fps,
        "frame_count_decoded": frames,
        "duration_seconds_from_decoded_frames": frames / fps,
        "sample_frames_nonblank": nonblank_samples,
        "full_decode_passed": all(nonblank_samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    if tuple(metadata["required_episode_ids"]) != SUCCESS_IDS:
        raise RuntimeError("metadata does not name the required eight successful episodes")
    overview_rows = [row for row in metadata["source_audit"] if not row.get("role")]
    rows_by_episode = {int(row["episode_index"]): row for row in overview_rows}
    if tuple(sorted(rows_by_episode)) != SUCCESS_IDS:
        raise RuntimeError("metadata overview sources do not match required episode IDs")

    sources = []
    for episode in SUCCESS_IDS:
        metadata_row = rows_by_episode[episode]
        source = Path(metadata_row["path"])
        audit = audit_video(source)
        if audit["sha256"] != metadata_row["sha256"]:
            raise RuntimeError(f"source hash mismatch for episode {episode}: {source}")
        if audit["frame_count_decoded"] != metadata_row["frame_count_decoded"]:
            raise RuntimeError(f"source frame-count mismatch for episode {episode}: {source}")
        audit["episode_index"] = episode
        audit["metadata_sha256"] = metadata_row["sha256"]
        sources.append(audit)

    first = sources[0]
    for source in sources[1:]:
        for field in ("codec", "resolution", "fps"):
            if source[field] != first[field]:
                raise RuntimeError(f"source streams differ on {field}: {source['path']}")
    concat_list = args.out_dir / "raw_success_overview_concat.txt"
    concat_list.write_text(
        "".join(f"file '{Path(source['path']).as_posix()}'\n" for source in sources),
        encoding="utf-8",
    )
    output = args.out_dir / "raw_success_overviews_episode_order.mp4"
    command = [
        str(args.ffmpeg), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-map", "0:v:0", "-c:v", "copy", "-movflags", "+faststart", str(output),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output_audit = audit_video(output)
    expected_frames = sum(source["frame_count_decoded"] for source in sources)
    expected_duration = sum(source["duration_seconds_from_decoded_frames"] for source in sources)
    checks = {
        "stream_copy_requested": True,
        "source_hashes_match_metadata": True,
        "all_sources_full_decode": all(source["full_decode_passed"] for source in sources),
        "output_full_decode": output_audit["full_decode_passed"],
        "output_frame_count_matches_source_total": output_audit["frame_count_decoded"] == expected_frames,
        "output_duration_matches_source_total": abs(output_audit["duration_seconds_from_decoded_frames"] - expected_duration) < 1e-9,
        "output_codec_matches_sources": output_audit["codec"] == first["codec"],
        "output_resolution_matches_sources": output_audit["resolution"] == first["resolution"],
        "output_fps_matches_sources": output_audit["fps"] == first["fps"],
    }
    manifest = {
        "title": "Raw successful overview episode sequence",
        "episode_order": list(SUCCESS_IDS),
        "operation": "ffmpeg concat demuxer with -c:v copy; no trim, subtitles, cards, scaling, rate change, or transitions",
        "ffmpeg_command": command,
        "sources": sources,
        "expected_total_frame_count": expected_frames,
        "expected_total_duration_seconds": expected_duration,
        "output": output_audit,
        "checks": checks,
    }
    (args.out_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not all(checks.values()):
        raise RuntimeError(f"concat validation failed: {checks}")
    print(json.dumps({"output": output_audit, "checks": checks}, indent=2))


if __name__ == "__main__":
    main()

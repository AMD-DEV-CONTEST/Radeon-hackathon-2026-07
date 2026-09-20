#!/usr/bin/env python3
"""Validate the completed eight-shard CutleryLong 3DGS dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import av


VIDEO_KEYS = (
    "observation.images.cam_high",
    "observation.images.cam_left_wrist",
    "observation.images.cam_right_wrist",
)
EXPECTED_VIDEO_SHAPES = {
    "observation.images.cam_high": [3, 480, 848],
    "observation.images.cam_left_wrist": [3, 480, 640],
    "observation.images.cam_right_wrist": [3, 480, 640],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    args = parse_args()
    shards = sorted(args.dataset_root.glob("shard-??-of-08"))
    errors: list[str] = []
    if len(shards) != 8:
        errors.append(f"expected 8 shards, found {len(shards)}")
    records: list[dict[str, Any]] = []
    shard_summaries = []
    shell_hashes = set()
    for shard_index, shard in enumerate(shards):
        expected_episodes = 13 if shard_index < 4 else 12
        info_path = shard / "meta" / "info.json"
        manifest_path = shard / "source_manifest.jsonl"
        receipt_path = shard / "visual_shell_receipt.json"
        for path in (info_path, manifest_path, receipt_path):
            if not path.is_file():
                errors.append(f"missing {path}")
        if not all(path.is_file() for path in (info_path, manifest_path, receipt_path)):
            continue
        info = json.loads(info_path.read_text(encoding="utf-8"))
        manifest = read_jsonl(manifest_path)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        shell_hashes.add(receipt["visual_shell_profile_sha256"])
        total_episodes = int(info.get("total_episodes", -1))
        total_frames = int(info.get("total_frames", -1))
        manifest_frames = sum(int(record["frames"]) for record in manifest)
        if total_episodes != expected_episodes:
            errors.append(
                f"{shard.name}: episodes={total_episodes}, expected={expected_episodes}"
            )
        if len(manifest) != total_episodes:
            errors.append(
                f"{shard.name}: manifest={len(manifest)}, info={total_episodes}"
            )
        if manifest_frames != total_frames:
            errors.append(
                f"{shard.name}: manifest_frames={manifest_frames}, info={total_frames}"
            )
        if int(info.get("fps", -1)) != 20:
            errors.append(f"{shard.name}: fps={info.get('fps')}, expected=20")
        for numeric_key in ("observation.state", "action"):
            feature = info.get("features", {}).get(numeric_key, {})
            if feature.get("dtype") != "float32" or feature.get("shape") != [16]:
                errors.append(f"{shard.name}: invalid feature {numeric_key}: {feature}")
        for key in VIDEO_KEYS:
            feature = info.get("features", {}).get(key, {})
            if (
                feature.get("dtype") != "video"
                or feature.get("shape") != EXPECTED_VIDEO_SHAPES[key]
            ):
                errors.append(f"{shard.name}: invalid video feature {key}: {feature}")
            video_files = list((shard / "videos" / key).rglob("*.mp4"))
            if not video_files or any(path.stat().st_size == 0 for path in video_files):
                errors.append(f"{shard.name}: invalid video files for {key}")
            for video_path in video_files:
                try:
                    with av.open(str(video_path)) as container:
                        stream = container.streams.video[0]
                        frame = next(container.decode(video=0))
                        expected = EXPECTED_VIDEO_SHAPES[key]
                        if [frame.height, frame.width] != expected[1:]:
                            errors.append(
                                f"{video_path}: decoded shape "
                                f"{[frame.height, frame.width]} expected={expected[1:]}"
                            )
                        decoded_fps = (
                            round(float(stream.average_rate))
                            if stream.average_rate is not None
                            else None
                        )
                        if decoded_fps != 20:
                            errors.append(
                                f"{video_path}: decoded fps={stream.average_rate}, "
                                "expected=20"
                            )
                except Exception as exc:
                    errors.append(
                        f"{video_path}: decode failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
        for record in manifest:
            record = dict(record)
            record["dataset_shard"] = shard.name
            records.append(record)
        shard_summaries.append(
            {
                "shard": shard.name,
                "root": str(shard),
                "episodes": total_episodes,
                "frames": total_frames,
                "bytes": sum(
                    path.stat().st_size for path in shard.rglob("*") if path.is_file()
                ),
            }
        )

    source_ids = [record["source_id"] for record in records]
    seeds = [int(record["seed"]) for record in records]
    official = [
        record for record in records if record["source_kind"] == "official_expert"
    ]
    privileged = [
        record
        for record in records
        if record["source_kind"] == "privileged_closed_loop"
    ]
    replacements = [
        record for record in records if "replaces_official_source_id" in record
    ]
    if len(records) != 100:
        errors.append(f"total records={len(records)}, expected=100")
    if len(set(source_ids)) != len(source_ids):
        errors.append("source_id values are not unique")
    if len(set(seeds)) != len(seeds):
        errors.append("seed values are not unique")
    if len(official) != 30 or len(privileged) != 70:
        errors.append(
            f"composition official={len(official)} privileged={len(privileged)}, "
            "expected 30/70"
        )
    if len(replacements) != 2:
        errors.append(f"replacements={len(replacements)}, expected=2")
    if any(not bool(record.get("success")) for record in records):
        errors.append("one or more selected trajectories are not successful")
    if len(shell_hashes) != 1:
        errors.append(f"visual shell hashes are inconsistent: {sorted(shell_hashes)}")
    for record in records:
        source = Path(record["source_path"])
        if not source.is_file():
            errors.append(f"missing source file {source}")
        elif sha256(source) != record["source_sha256"]:
            errors.append(f"source hash mismatch {source}")

    payload = {
        "status": "passed" if not errors else "failed",
        "task": "DishwasherUnloadCutleryLong",
        "format": "LeRobot Dataset v3, eight physical shards",
        "fps": 20,
        "cameras": {
            "cam_high": [3, 480, 848],
            "cam_left_wrist": [3, 480, 640],
            "cam_right_wrist": [3, 480, 640],
        },
        "action": {"dimension": 16, "mode": "absolute joint position"},
        "episodes": len(records),
        "frames": sum(summary["frames"] for summary in shard_summaries),
        "official_expert_successes": len(official),
        "privileged_closed_loop_successes": len(privileged),
        "replaced_incompatible_official_demos": [
            record["replaces_official_source_id"] for record in replacements
        ],
        "unique_seeds": len(set(seeds)),
        "visual_shell_profile_sha256": next(iter(shell_hashes), None),
        "shards": shard_summaries,
        "records": records,
        "errors": errors,
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"VALIDATION {payload['status']} episodes={payload['episodes']} "
        f"frames={payload['frames']} official={len(official)} "
        f"privileged={len(privileged)} errors={len(errors)}"
    )
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

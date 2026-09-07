#!/usr/bin/env python3
"""Export one certified Physical-2K world-camera success clip per L1 task."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

FRUITS = ("apple", "banana", "lemon", "orange", "plum")
DESTINATIONS = ("blue_left", "blue_right", "white_left", "white_right")
EXPECTED_TASKS = tuple(
    f"{fruit}_{destination}" for fruit in FRUITS for destination in DESTINATIONS
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    return completed.stdout.strip()


def select_certificates(dataset_root: Path) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for path in sorted((dataset_root / "certificates").glob("episode_*.json")):
        certificate = json.loads(path.read_text(encoding="utf-8"))
        task_id = certificate.get("task_id")
        if task_id not in EXPECTED_TASKS or task_id in selected:
            continue
        report = certificate.get("success_report") or {}
        if not (
            certificate.get("success") is True
            and certificate.get("strict_physics") is True
            and certificate.get("rigid_pose_write_guard") is True
            and certificate.get("kinematic_intervention_count") == 0
            and report.get("success") is True
        ):
            continue
        certificate["certificate_path"] = str(path.relative_to(dataset_root))
        selected[task_id] = certificate

    missing = sorted(set(EXPECTED_TASKS) - set(selected))
    if missing:
        raise RuntimeError(f"No certified success found for: {missing}")
    return selected


def episode_rows(dataset_root: Path) -> dict[int, dict[str, Any]]:
    columns = [
        "episode_index",
        "videos/observation.images.world/chunk_index",
        "videos/observation.images.world/file_index",
        "videos/observation.images.world/from_timestamp",
        "videos/observation.images.world/to_timestamp",
    ]
    table = pq.read_table(dataset_root / "meta/episodes/chunk-000/file-000.parquet", columns=columns)
    return {int(row["episode_index"]): row for row in table.to_pylist()}


def export_clip(
    *,
    dataset_root: Path,
    output_dir: Path,
    task_id: str,
    certificate: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, Any]:
    chunk_index = int(row["videos/observation.images.world/chunk_index"])
    file_index = int(row["videos/observation.images.world/file_index"])
    start = float(row["videos/observation.images.world/from_timestamp"])
    end = float(row["videos/observation.images.world/to_timestamp"])
    duration = end - start
    source = dataset_root / (
        f"videos/observation.images.world/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4"
    )
    if not source.is_file():
        raise FileNotFoundError(source)

    video = output_dir / f"{task_id}.mp4"
    poster = output_dir / f"{task_id}.webp"
    video.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-ss",
            f"{start:.6f}",
            "-t",
            f"{duration:.6f}",
            "-an",
            "-vf",
            "fps=20,scale=640:480:flags=lanczos,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(video),
        ]
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-sseof",
            "-0.05",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-compression_level",
            "6",
            str(poster),
        ]
    )
    probe = json.loads(
        run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=width,height,avg_frame_rate:format=duration,size",
                "-of",
                "json",
                str(video),
            ]
        )
    )
    stream = probe["streams"][0]
    actual_duration = float(probe["format"]["duration"])
    if (stream["width"], stream["height"], stream["avg_frame_rate"]) != (640, 480, "20/1"):
        raise RuntimeError(f"Unexpected video format for {task_id}: {stream}")
    if actual_duration < duration - 0.15:
        raise RuntimeError(f"Truncated video for {task_id}: {actual_duration:.3f} < {duration:.3f}")

    return {
        "task_id": task_id,
        "episode_index": int(certificate["episode_index"]),
        "seed": int(certificate["seed"]),
        "instruction": certificate["instruction"],
        "strict_physics": True,
        "kinematic_intervention_count": 0,
        "certificate_path": certificate["certificate_path"],
        "source_video": str(source.relative_to(dataset_root)),
        "source_from_timestamp": start,
        "source_to_timestamp": end,
        "duration_s": actual_duration,
        "frame_count": int(certificate["frame_count"]),
        "video": str(video),
        "video_sha256": sha256(video),
        "poster": str(poster),
        "poster_sha256": sha256(poster),
        "final_goal_positions": certificate.get("final_goal_positions") or {},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-revision", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = select_certificates(args.dataset_root)
    rows = episode_rows(args.dataset_root)
    examples = []
    for task_id in EXPECTED_TASKS:
        certificate = selected[task_id]
        episode_index = int(certificate["episode_index"])
        if episode_index not in rows:
            raise KeyError(f"Episode {episode_index} is absent from metadata")
        example = export_clip(
            dataset_root=args.dataset_root,
            output_dir=args.output_dir,
            task_id=task_id,
            certificate=certificate,
            row=rows[episode_index],
        )
        examples.append(example)
        print(
            f"[world-success] {task_id} episode={episode_index:04d} seed={example['seed']} "
            f"duration={example['duration_s']:.2f}s sha256={example['video_sha256']}"
        )

    manifest = {
        "schema_version": 1,
        "dataset": "a3124371940/radeonvla_reflex_physical_2k",
        "dataset_revision": args.dataset_revision,
        "camera": "observation.images.world",
        "selection": "lowest episode_index with a strict-physics success certificate per task",
        "num_tasks": len(examples),
        "tasks": examples,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest={args.manifest}")


if __name__ == "__main__":
    main()

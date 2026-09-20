#!/usr/bin/env python3
"""Validate a complete DishwasherUnloadCutleryLong LeRobot v3 collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import av
import numpy as np
import pyarrow.parquet as pq
from PIL import Image, ImageDraw


CAMERAS = {
    "observation.images.cam_high": (848, 480),
    "observation.images.cam_left_wrist": (640, 480),
    "observation.images.cam_right_wrist": (640, 480),
}
EXPECTED_EPISODES = 32
EXPECTED_FPS = 20.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(item: tuple[Path, str, int, int]) -> dict:
    path, camera, episode_index, expected_frames = item
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,nb_frames:format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    decode = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    error = None
    payload = {}
    if probe.returncode == 0:
        try:
            payload = json.loads(probe.stdout)
        except json.JSONDecodeError as exc:
            error = f"invalid ffprobe JSON: {exc}"
    else:
        error = probe.stderr.strip() or f"ffprobe exit {probe.returncode}"
    streams = payload.get("streams", [])
    stream = streams[0] if streams else {}
    fmt = payload.get("format", {})
    width, height = CAMERAS[camera]
    frame_rate = stream.get("avg_frame_rate", "0/1")
    numerator, denominator = (int(value) for value in frame_rate.split("/"))
    fps = numerator / denominator if denominator else 0.0
    frames = int(stream.get("nb_frames", -1))
    duration = float(fmt.get("duration", math.nan))
    checks = {
        "probe": probe.returncode == 0 and bool(streams),
        "decode": decode.returncode == 0,
        "codec_h264": stream.get("codec_name") == "h264",
        "resolution": (stream.get("width"), stream.get("height"))
        == (width, height),
        "fps": math.isclose(fps, EXPECTED_FPS, abs_tol=1e-6),
        "frame_count": frames == expected_frames,
        "duration": math.isclose(
            duration, expected_frames / EXPECTED_FPS, abs_tol=0.06
        ),
    }
    return {
        "path": str(path),
        "camera": camera,
        "episode_index": episode_index,
        "bytes": int(fmt.get("size", path.stat().st_size)),
        "codec": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "fps": fps,
        "frames": frames,
        "duration_seconds": duration,
        "checks": checks,
        "error": error or (decode.stderr.strip() if decode.returncode else None),
        "passed": all(checks.values()),
    }


def middle_frame(path: Path, frame_index: int) -> Image.Image:
    with av.open(str(path)) as container:
        for index, frame in enumerate(container.decode(video=0)):
            if index == frame_index:
                return frame.to_image().convert("RGB")
    raise RuntimeError(f"frame {frame_index} is missing from {path}")


def make_contact_sheet(
    dataset_root: Path, frame_counts: dict[int, int], output: Path
) -> None:
    episodes = [0, 10, 21, 31]
    cameras = list(CAMERAS)
    cell_width, image_height, label_height = 424, 240, 28
    canvas = Image.new(
        "RGB", (cell_width * len(cameras), (image_height + label_height) * len(episodes)), "black"
    )
    draw = ImageDraw.Draw(canvas)
    for row, episode_index in enumerate(episodes):
        for column, camera in enumerate(cameras):
            video = (
                dataset_root
                / "videos"
                / camera
                / "chunk-000"
                / f"file-{episode_index:03d}.mp4"
            )
            frame = middle_frame(video, frame_counts[episode_index] // 2)
            frame = frame.resize((cell_width, image_height), Image.Resampling.LANCZOS)
            x = column * cell_width
            y = row * (image_height + label_height)
            canvas.paste(frame, (x, y))
            draw.rectangle((x, y + image_height, x + cell_width, y + image_height + label_height), fill="black")
            draw.text(
                (x + 8, y + image_height + 7),
                f"episode {episode_index:02d} | {camera.removeprefix('observation.images.')}",
                fill="white",
            )
    canvas.save(output)


def validate(dataset_root: Path, workers: int) -> dict:
    info = json.loads((dataset_root / "meta/info.json").read_text())
    receipt = json.loads((dataset_root / "run-receipt.json").read_text())

    data_files = sorted((dataset_root / "data").glob("chunk-*/*.parquet"))
    frame_counts: dict[int, int] = {}
    total_rows = 0
    action_nan = action_inf = state_nan = state_inf = 0
    shape_errors = []
    index_errors = []
    for path in data_files:
        table = pq.read_table(path)
        rows = table.num_rows
        total_rows += rows
        actions = np.asarray(table["action"].to_pylist(), dtype=np.float32)
        states = np.asarray(table["observation.state"].to_pylist(), dtype=np.float32)
        episode_indices = np.asarray(
            table["episode_index"].to_pylist(), dtype=np.int64
        ).reshape(-1)
        frame_indices = np.asarray(
            table["frame_index"].to_pylist(), dtype=np.int64
        ).reshape(-1)
        timestamps = np.asarray(
            table["timestamp"].to_pylist(), dtype=np.float32
        ).reshape(-1)
        unique_episodes = np.unique(episode_indices)
        if len(unique_episodes) != 1:
            index_errors.append(f"{path}: multiple episode indices")
            continue
        episode_index = int(unique_episodes[0])
        frame_counts[episode_index] = rows
        if actions.shape != (rows, 16) or states.shape != (rows, 16):
            shape_errors.append(
                f"{path}: action={actions.shape}, state={states.shape}"
            )
        action_nan += int(np.isnan(actions).sum())
        action_inf += int(np.isinf(actions).sum())
        state_nan += int(np.isnan(states).sum())
        state_inf += int(np.isinf(states).sum())
        if not np.array_equal(frame_indices, np.arange(rows)):
            index_errors.append(f"{path}: frame_index is not contiguous")
        if len(timestamps) and (
            not math.isclose(float(timestamps[0]), 0.0, abs_tol=1e-6)
            or not np.all(np.diff(timestamps) > 0)
        ):
            index_errors.append(f"{path}: timestamps are invalid")

    episode_meta_files = sorted(
        (dataset_root / "meta/episodes").glob("chunk-*/*.parquet")
    )
    episode_meta_rows = sum(pq.read_table(path).num_rows for path in episode_meta_files)

    receipt_episodes = receipt.get("episodes", [])
    receipt_counts = {
        index: int(episode["frames"])
        for index, episode in enumerate(receipt_episodes)
    }
    count_mismatches = {
        index: {"data": frame_counts.get(index), "receipt": frames}
        for index, frames in receipt_counts.items()
        if frame_counts.get(index) != frames
    }

    video_items = []
    for camera in CAMERAS:
        for path in sorted((dataset_root / "videos" / camera).glob("chunk-*/*.mp4")):
            episode_index = int(path.stem.removeprefix("file-"))
            video_items.append(
                (path, camera, episode_index, frame_counts.get(episode_index, -1))
            )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        videos = list(executor.map(probe_video, video_items))

    renderer_environments = receipt.get("environments", [])
    rendered_frames = sum(
        int(env["visual_shell"]["gaussian_rendered_frames"])
        for env in renderer_environments
    )
    renderer_passed = all(
        env["visual_shell"].get("enabled")
        and env["visual_shell"].get("strict")
        and env["visual_shell"].get("last_error") is None
        and env["visual_shell"]["background_physics"]
        == {"body_count": 0, "geom_count": 0, "collision_count": 0}
        for env in renderer_environments
    )

    checks = {
        "info_total_episodes_32": info.get("total_episodes") == EXPECTED_EPISODES,
        "receipt_episode_count_32": len(receipt_episodes) == EXPECTED_EPISODES,
        "receipt_all_saved": all(ep.get("saved") for ep in receipt_episodes),
        "receipt_all_reward_1": all(ep.get("reward") == 1.0 for ep in receipt_episodes),
        "receipt_unique_uuids_32": len({ep["demo_uuid"] for ep in receipt_episodes})
        == EXPECTED_EPISODES,
        "receipt_dataset_actions_absolute": {
            ep.get("dataset_action_representation") for ep in receipt_episodes
        }
        == {"absolute"},
        "data_file_count_32": len(data_files) == EXPECTED_EPISODES,
        "episode_meta_file_count_32": len(episode_meta_files) == EXPECTED_EPISODES,
        "episode_meta_rows_32": episode_meta_rows == EXPECTED_EPISODES,
        "data_episode_indices_0_31": sorted(frame_counts) == list(range(EXPECTED_EPISODES)),
        "total_rows_match_info": total_rows == info.get("total_frames") == 21018,
        "data_receipt_frame_counts_match": not count_mismatches,
        "action_state_shapes_16": not shape_errors,
        "action_state_finite": action_nan + action_inf + state_nan + state_inf == 0,
        "frame_and_timestamp_indices_valid": not index_errors,
        "video_file_count_96": len(videos) == EXPECTED_EPISODES * len(CAMERAS),
        "all_videos_probe_and_decode": all(video["passed"] for video in videos),
        "strict_3dgs_renderer": renderer_passed,
        "gaussian_render_count_exact": rendered_frames
        == (total_rows + EXPECTED_EPISODES) * len(CAMERAS),
    }
    return {
        "schema_version": 1,
        "status": "passed" if all(checks.values()) else "failed",
        "package_scope": "complete DishwasherUnloadCutleryLong official-32 collection",
        "dataset_root": str(dataset_root),
        "checks": checks,
        "summary": {
            "episodes": len(receipt_episodes),
            "unique_demo_uuids": len({ep["demo_uuid"] for ep in receipt_episodes}),
            "saved_reward_1": sum(
                bool(ep.get("saved")) and ep.get("reward") == 1.0
                for ep in receipt_episodes
            ),
            "total_frames": total_rows,
            "state_shape": [total_rows, 16],
            "action_shape": [total_rows, 16],
            "source_action_representations": dict(
                Counter(ep["source_action_representation"] for ep in receipt_episodes)
            ),
            "dataset_action_representations": sorted(
                {ep["dataset_action_representation"] for ep in receipt_episodes}
            ),
            "video_files": len(videos),
            "video_bytes": sum(video["bytes"] for video in videos),
            "gaussian_rendered_frames": rendered_frames,
            "renderer_environment_count": len(renderer_environments),
            "visual_status": receipt.get("visual_status"),
        },
        "numeric_integrity": {
            "action_nan": action_nan,
            "action_inf": action_inf,
            "state_nan": state_nan,
            "state_inf": state_inf,
            "shape_errors": shape_errors,
            "index_errors": index_errors,
            "frame_count_mismatches": count_mismatches,
        },
        "episodes": [
            {
                "episode_index": index,
                "demo_index": episode["demo_index"],
                "demo_uuid": episode["demo_uuid"],
                "seed": episode["seed"],
                "frames": episode["frames"],
                "reward": episode["reward"],
                "saved": episode["saved"],
                "source_action_representation": episode[
                    "source_action_representation"
                ],
                "dataset_action_representation": episode[
                    "dataset_action_representation"
                ],
                "dataset_actions_sha256": episode["dataset_actions_sha256"],
            }
            for index, episode in enumerate(receipt_episodes)
        ],
        "videos": videos,
        "boundary": {
            "package_completeness": "passed",
            "visual_quality": "known issue; technical renderer pass does not imply visual approval",
            "source_runtime": "BiGym 4.0.0 / MuJoCo 3.1.5",
            "collection_runtime": "BiGym 4.1.0 / MuJoCo 3.10.0",
        },
    }


def write_sha256sums(dataset_root: Path, output: Path) -> None:
    paths = sorted(
        path
        for path in dataset_root.rglob("*")
        if path.is_file() and path != output
    )
    lines = [f"{sha256(path)}  {path.relative_to(dataset_root)}" for path in paths]
    output.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    root = args.dataset_root.resolve()
    report = validate(root, args.workers)
    report_path = root / "FULL_COLLECTION_VALIDATION.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if report["status"] == "passed":
        make_contact_sheet(
            root,
            {ep["episode_index"]: ep["frames"] for ep in report["episodes"]},
            root / "formal32-four-episode-three-camera-contact-sheet.png",
        )
        (root / "_COMPLETE").write_text(
            "complete_32_unique_reward_1_technical_pass_visual_boundary_recorded\n"
        )
        write_sha256sums(root, root / "SHA256SUMS")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(json.dumps(report["checks"], indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

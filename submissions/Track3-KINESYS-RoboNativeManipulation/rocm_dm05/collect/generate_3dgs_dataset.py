#!/usr/bin/env python3
"""Replay official and privileged CutleryLong demos into 3DGS LeRobot shards."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from demonstrations.demo import Demo
from lerobot.configs import RGBEncoderConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset

from dim_utils import UNIFORM_DIM, pad_to_16
from env_utils import CAMERAS, build_env, get_state
from tasks import TASKS
try:
    from tools.desktop_demo_recorder.enhanced_randomization import (
        apply_enhanced_randomization,
    )
    from tools.desktop_demo_recorder.privileged_policy import (
        SUPPORTED_TASK,
        dishwasher_unload_cutlery_status,
    )
except ModuleNotFoundError:
    from enhanced_randomization import apply_enhanced_randomization
    from privileged_policy import SUPPORTED_TASK, dishwasher_unload_cutlery_status


LOG = logging.getLogger("cutlery-3dgs-shard")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--privileged-manifest", type=Path, required=True)
    parser.add_argument("--official-audit", type=Path, default=None)
    parser.add_argument("--visual-shell-profile", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--num-shards", type=int, default=4)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument(
        "--probe-source",
        choices=("official_expert", "privileged_closed_loop"),
        default=None,
    )
    parser.add_argument("--probe-source-id", default=None)
    parser.add_argument("--allow-failed-official", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--vcodec", default="h264")
    parser.add_argument("--image-writer-threads", type=int, default=4)
    return parser.parse_args()


def build_features() -> dict[str, Any]:
    features: dict[str, Any] = {}
    for spec in CAMERAS:
        features[f"observation.images.{spec.lr_key}"] = {
            "dtype": "video",
            "shape": (3, spec.resolution[0], spec.resolution[1]),
            "names": ["channels", "height", "width"],
        }
    features["observation.state"] = {
        "dtype": "float32",
        "shape": (UNIFORM_DIM,),
        "names": None,
    }
    features["action"] = {
        "dtype": "float32",
        "shape": (UNIFORM_DIM,),
        "names": None,
    }
    return features


def load_items(
    official_dir: Path,
    privileged_manifest: Path,
    official_audit: Path | None = None,
    require_complete: bool = True,
) -> list[dict[str, Any]]:
    official_items = [
        {
            "source_kind": "official_expert",
            "source_id": path.stem,
            "path": str(path),
            "expanded_randomization": False,
        }
        for path in sorted(official_dir.glob("*.safetensors"))
    ]
    if len(official_items) != 32:
        raise RuntimeError(f"Expected 32 official demos, found {len(official_items)}")
    privileged_items = []
    for line in privileged_manifest.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("status") != "success":
            continue
        privileged_items.append(
            {
                "source_kind": "privileged_closed_loop",
                "source_id": f"seed{int(record['seed'])}",
                "path": str(record["output"]),
                "expanded_randomization": True,
                "collection_record": record,
            }
        )
    if official_audit is None:
        items = [*official_items, *privileged_items]
        if require_complete and len(items) != 100:
            raise RuntimeError(
                f"Expected 100 total successful demos, found {len(items)}"
            )
        return items

    audit = json.loads(official_audit.read_text(encoding="utf-8"))
    audit_by_id = {record["source_id"]: record for record in audit["records"]}
    failed_indices = [
        index
        for index, item in enumerate(official_items)
        if not bool(audit_by_id[item["source_id"]]["success"])
    ]
    needed_privileged = 68 + len(failed_indices)
    if len(privileged_items) < needed_privileged:
        raise RuntimeError(
            f"Need {needed_privileged} successful privileged demos after audit, "
            f"found {len(privileged_items)}"
        )
    for replacement_offset, official_index in enumerate(failed_indices):
        replacement = dict(privileged_items[68 + replacement_offset])
        replacement["replaces_official_source_id"] = official_items[official_index][
            "source_id"
        ]
        official_items[official_index] = replacement
    items = [*official_items, *privileged_items[:68]]
    if len(items) != 100:
        raise RuntimeError(f"Expected 100 planned demos, found {len(items)}")
    return items


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def replay_item(
    dataset: LeRobotDataset,
    env: Any,
    mojo: Any,
    item: dict[str, Any],
    allow_failed_official: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    source_path = Path(item["path"])
    demo = Demo.from_safetensors(source_path)
    seed = int(demo.seed)
    obs, _ = env.reset(seed=seed)
    randomization = None
    if item["expanded_randomization"]:
        randomization = apply_enhanced_randomization(env, seed).to_dict()
        obs = env.get_observation()
    actions = [
        np.asarray(timestep.executed_action, dtype=np.float32)
        for timestep in demo.timesteps
    ]
    if not actions:
        raise RuntimeError(f"No actions in {source_path}")
    reward = 0.0
    terminated = False
    truncated = False
    executed_frames = 0
    for action in actions:
        state = get_state(env.robot, obs, mojo)
        frame = {
            "observation.images.cam_high": obs["rgb_head"],
            "observation.images.cam_left_wrist": obs["rgb_left_wrist"],
            "observation.images.cam_right_wrist": obs["rgb_right_wrist"],
            "observation.state": pad_to_16(state, SUPPORTED_TASK),
            "action": pad_to_16(action, SUPPORTED_TASK),
            "task": TASKS[SUPPORTED_TASK]["prompt"],
        }
        dataset.add_frame(frame)
        obs, reward, terminated, truncated, _ = env.step(action)
        executed_frames += 1
        reward = float(reward)
        if terminated or truncated:
            break

    status = dishwasher_unload_cutlery_status(env)
    success = bool(status["success"] or reward > 0)
    if not success:
        if not (allow_failed_official and item["source_kind"] == "official_expert"):
            dataset.clear_episode_buffer()
            raise RuntimeError(
                f"Replay failed for {item['source_id']}: "
                f"reward={reward} status={status}"
            )
    dataset.save_episode()
    record = {
        "source_kind": item["source_kind"],
        "source_id": item["source_id"],
        "source_path": str(source_path),
        "source_sha256": sha256(source_path),
        "seed": seed,
        "source_action_count": len(actions),
        "frames": executed_frames,
        "reward": reward,
        "success": success,
        "expanded_randomization": bool(item["expanded_randomization"]),
        "randomization": randomization,
        "final_privileged_state": status,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if "replaces_official_source_id" in item:
        record["replaces_official_source_id"] = item[
            "replaces_official_source_id"
        ]
    return record


def main() -> None:
    args = parse_args()
    if not 0 <= args.shard_index < args.num_shards:
        raise ValueError("shard-index must be in [0, num-shards)")
    items = load_items(
        args.official_dir,
        args.privileged_manifest,
        official_audit=args.official_audit,
        require_complete=not args.probe,
    )
    if args.probe_source is not None:
        items = [item for item in items if item["source_kind"] == args.probe_source]
    if args.probe_source_id is not None:
        items = [item for item in items if item["source_id"] == args.probe_source_id]
    selected = [
        item
        for index, item in enumerate(items)
        if index % args.num_shards == args.shard_index
    ]
    if args.probe:
        selected = selected[:1]
    output_dir = args.output_root / (
        f"shard-{args.shard_index:02d}-of-{args.num_shards:02d}"
    )
    if args.force and output_dir.exists():
        shutil.rmtree(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"Output already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    dataset = LeRobotDataset.create(
        repo_id=f"local/cutlery_long_3dgs_100_shard_{args.shard_index:02d}",
        fps=20,
        features=build_features(),
        root=output_dir,
        use_videos=True,
        image_writer_threads=args.image_writer_threads,
        rgb_encoder=RGBEncoderConfig(vcodec=args.vcodec),
    )
    manifest_path = output_dir / "source_manifest.jsonl"
    shell_receipt = {
        "visual_shell_profile": str(args.visual_shell_profile),
        "visual_shell_profile_sha256": sha256(args.visual_shell_profile),
        "shard_index": args.shard_index,
        "num_shards": args.num_shards,
        "selected_episodes": len(selected),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "visual_shell_receipt.json").write_text(
        json.dumps(shell_receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    env = build_env(
        SUPPORTED_TASK,
        control_frequency=20,
        with_cameras=True,
        visual_shell_profile=args.visual_shell_profile,
        visual_shell_strict=True,
    )
    mojo = env.action_mode._mojo
    completed = 0
    try:
        for index, item in enumerate(selected, start=1):
            LOG.info(
                "shard=%s episode=%s/%s source=%s:%s",
                args.shard_index,
                index,
                len(selected),
                item["source_kind"],
                item["source_id"],
            )
            record = replay_item(
                dataset,
                env,
                mojo,
                item,
                allow_failed_official=args.allow_failed_official,
            )
            record["shard_episode_index"] = completed
            write_jsonl(manifest_path, record)
            completed += 1
            LOG.info(
                "saved=%s/%s frames=%s elapsed=%ss",
                completed,
                len(selected),
                record["frames"],
                record["elapsed_seconds"],
            )
    finally:
        env.close()
        dataset.finalize()
    if completed != len(selected):
        raise RuntimeError(f"Completed only {completed}/{len(selected)} episodes")
    LOG.info("Shard complete: %s episodes -> %s", completed, output_dir)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    main()

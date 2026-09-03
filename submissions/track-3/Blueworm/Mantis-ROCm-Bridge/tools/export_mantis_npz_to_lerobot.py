#!/usr/bin/env python3
"""Export strict simulator NPZ captures into a fresh LeRobot Mantis dataset."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.episode_export import (
    MantisLeRobotExportSession,
    create_lerobot_dataset_sink,
)
from mantis_rocm_bridge.episode_state import replay_stage_trace


ROOT = Path(__file__).resolve().parents[1]


def _apply_trace(session: MantisLeRobotExportSession, trace: dict) -> None:
    events = trace.get("events")
    if not isinstance(events, list):
        raise ContractError("stage trace events must be a list")
    for event in events:
        if not isinstance(event, dict):
            raise ContractError("stage trace event must be an object")
        common = {
            "policy_step": event.get("policy_step"),
            "details": event.get("details"),
        }
        if event.get("status") == "completed":
            session.complete_stage(event.get("stage"), **common)
        elif event.get("status") == "failed":
            session.fail_stage(
                event.get("stage"),
                failure_stage=event.get("failure_stage"),
                **common,
            )
        else:
            raise ContractError("stage trace status must be completed or failed")


def _load_capture_manifest(path: Path) -> tuple[str, list[dict]]:
    manifest = load_json(path)
    if manifest.get("schema_version") != 1:
        raise ContractError("capture manifest schema_version must be 1")
    repo_id = manifest.get("repo_id")
    episodes = manifest.get("episodes")
    if not isinstance(repo_id, str) or not repo_id:
        raise ContractError("capture manifest repo_id must be non-empty")
    if not isinstance(episodes, list) or not episodes:
        raise ContractError("capture manifest episodes must be a non-empty list")
    return repo_id, episodes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_manifest", type=Path)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--use-videos", action="store_true")
    parser.add_argument(
        "--port", type=Path, default=ROOT / "configs/mantis-port-config.json"
    )
    parser.add_argument(
        "--interface",
        type=Path,
        default=ROOT / "configs/mantis-lerobot-interface-v1.json",
    )
    parser.add_argument(
        "--task", type=Path, default=ROOT / "configs/task-pack-v1.json"
    )
    parser.add_argument(
        "--export-contract",
        type=Path,
        default=ROOT / "configs/sim-episode-export-v1.json",
    )
    parser.add_argument(
        "--allow-unverified-sim-gripper",
        action="store_true",
        help="Required for the currently simulation-verified/hardware-unverified gripper map.",
    )
    args = parser.parse_args()
    try:
        import numpy as np
    except ImportError as exc:
        raise ContractError("NPZ export requires NumPy") from exc

    target = args.dataset_root.resolve()
    if target.exists():
        parser.error(f"refusing to overwrite dataset root: {target}")
    staging = target.with_name(target.name + ".staging")
    if staging.exists():
        parser.error(f"staging path already exists: {staging}")
    repo_id, episode_specs = _load_capture_manifest(args.capture_manifest)
    base = args.capture_manifest.resolve().parent
    port = load_json(args.port)
    interface = load_json(args.interface)
    task = load_json(args.task)
    export_contract = load_json(args.export_contract)

    prepared = []
    for index, spec in enumerate(episode_specs):
        if not isinstance(spec, dict):
            raise ContractError(f"capture episode {index} must be an object")
        seed = spec.get("seed")
        npz_path = (base / spec.get("npz", "")).resolve()
        trace_path = (base / spec.get("stage_trace", "")).resolve()
        trace = load_json(trace_path)
        if trace.get("seed") != seed:
            raise ContractError(f"capture {index} seed and stage trace seed disagree")
        generation_mode = trace.get("generation_mode", "online")
        effective_policy_step_limit = trace.get("effective_policy_step_limit")
        g1_claim = trace.get("g1_claim", False)
        trace_receipt = replay_stage_trace(
            task,
            trace,
            g1_claim=g1_claim,
            generation_mode=generation_mode,
            effective_policy_step_limit=effective_policy_step_limit,
        )
        if trace_receipt["success"] is not True:
            raise ContractError(
                f"capture {index} stage trace is not a successful strict episode"
            )
        required_arrays = export_contract["capture_arrays"]
        with np.load(npz_path, allow_pickle=False) as archive:
            if set(archive.files) != set(required_arrays):
                missing = sorted(set(required_arrays) - set(archive.files))
                extra = sorted(set(archive.files) - set(required_arrays))
                raise ContractError(
                    f"capture {index} array mismatch: missing={missing}, extra={extra}"
                )
            # NPZ members are compressed and cannot be memory-mapped. Loading
            # each member once avoids decompressing an entire camera tensor for
            # every frame slice during export.
            capture = {name: archive[name] for name in required_arrays}
        frame_count = int(capture["timestamps_s"].shape[0])
        if frame_count < int(export_contract["minimum_frames_per_episode"]):
            raise ContractError(f"capture {index} is shorter than the export minimum")
        expected_shapes = {
            "physical_state": (frame_count, 18),
            "physical_action": (frame_count, 18),
            "env_cam": (frame_count, 240, 320, 3),
            "left_wrist_cam": (frame_count, 240, 424, 3),
            "right_wrist_cam": (frame_count, 240, 424, 3),
        }
        for key, expected_shape in expected_shapes.items():
            if tuple(capture[key].shape) != expected_shape:
                raise ContractError(
                    f"capture {index} {key} shape must be {expected_shape}"
                )
        prepared.append(
            (seed, capture, trace, generation_mode, effective_policy_step_limit, g1_claim)
        )

    sink = create_lerobot_dataset_sink(
        repo_id=repo_id,
        root=staging,
        interface=interface,
        use_videos=args.use_videos,
    )
    session = MantisLeRobotExportSession(
        sink=sink,
        port=port,
        interface=interface,
        task=task,
        export_contract=export_contract,
        allow_unverified_gripper=args.allow_unverified_sim_gripper,
    )
    receipts = []
    camera_arrays = {
        "observation.images.env_cam": "env_cam",
        "observation.images.left_wrist_cam": "left_wrist_cam",
        "observation.images.right_wrist_cam": "right_wrist_cam",
    }
    for (
        seed,
        capture,
        trace,
        generation_mode,
        effective_policy_step_limit,
        g1_claim,
    ) in prepared:
        session.begin_episode(
            seed=seed,
            generation_mode=generation_mode,
            effective_policy_step_limit=effective_policy_step_limit,
        )
        _apply_trace(session, trace)
        for frame_index, timestamp in enumerate(capture["timestamps_s"]):
            images = {
                feature: capture[array_name][frame_index]
                for feature, array_name in camera_arrays.items()
            }
            session.add_frame(
                timestamp_s=float(timestamp),
                physical_state=capture["physical_state"][frame_index],
                physical_action=capture["physical_action"][frame_index],
                images=images,
            )
        receipt = session.finish_episode(g1_claim=g1_claim)
        receipts.append(receipt)
        if receipt["dataset_acceptance"] != "accepted":
            raise ContractError("capture manifest contains a failed strict episode")
    result = session.finalize()
    result["episode_receipts"] = receipts
    result["repo_id"] = repo_id
    result["use_videos"] = args.use_videos
    (staging / "strict_episode_outcomes.json").write_text(
        json.dumps({"episodes": result["episodes"]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (staging / "sim_export_receipt.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(staging, target)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate a recorded LeRobot dataset before training."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from radeonvla.paths import DATASETS_DIR
from radeonvla.protocol import ACTION_DIM, IMAGE_KEYS, JOINT_NAMES


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default="visiobot/radeonvla_reflex")
    parser.add_argument("--dataset-root", type=Path, default=None)
    parser.add_argument("--max-frames", type=int, default=32, help="Sample up to N frames for image checks.")
    parser.add_argument("--expected-episodes", type=int, default=0, help="Require exactly N episodes (0 disables).")
    parser.add_argument(
        "--episodes-per-task",
        type=int,
        default=0,
        help="Require exactly N certified successful episodes for each manifest task (0 disables).",
    )
    parser.add_argument(
        "--require-strict-physics",
        action="store_true",
        help="Require zero-assist manifest flags and one strict certificate per successful episode.",
    )
    parser.add_argument(
        "--video-backend",
        default="pyav",
        help="Video decoder backend (default pyav; avoids torchcodec FFmpeg ABI issues).",
    )
    parser.add_argument("--json", type=Path, default=None, help="Optional report path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    args = parse_args(argv)
    from radeonvla.paths import PROJECT_ROOT

    root = Path(args.dataset_root or (DATASETS_DIR / args.repo_id.split("/")[-1]))
    if not root.is_absolute():
        root = (PROJECT_ROOT / root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset root not found: {root}")
    if not (root / "meta" / "info.json").is_file():
        raise FileNotFoundError(
            f"Local LeRobot dataset incomplete under {root} (missing meta/info.json). "
            "Record with: python -m radeonvla.record_dataset --overwrite ..."
        )

    ds = LeRobotDataset(args.repo_id, root=str(root), video_backend=args.video_backend)
    n = len(ds)
    if n == 0:
        raise RuntimeError("Dataset has zero frames.")

    meta_features = ds.features
    report: dict = {
        "repo_id": args.repo_id,
        "root": str(root),
        "num_frames": n,
        "num_episodes": getattr(ds, "num_episodes", None),
        "fps": getattr(ds, "fps", None),
        "features": {k: {"dtype": v.get("dtype"), "shape": v.get("shape")} for k, v in meta_features.items()},
        "errors": [],
        "warnings": [],
    }

    num_episodes = int(getattr(ds, "num_episodes", 0) or 0)
    if args.expected_episodes > 0 and num_episodes != args.expected_episodes:
        report["errors"].append(f"Episode count {num_episodes} != expected {args.expected_episodes}")

    manifest_path = root / "recording_manifest.json"
    manifest = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report["errors"].append(f"Invalid recording manifest JSON: {exc}")
    elif args.require_strict_physics or args.episodes_per_task > 0:
        report["errors"].append("Missing recording_manifest.json required by formal validation")

    certificates = []
    certificate_paths = sorted((root / "certificates").glob("episode_*.json"))
    for certificate_path in certificate_paths:
        try:
            certificates.append(json.loads(certificate_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            report["errors"].append(f"Invalid certificate {certificate_path.name}: {exc}")
    report["strict_certificate_count"] = len(certificates)

    if args.require_strict_physics:
        if manifest is not None:
            strict_manifest = (
                manifest.get("strict_physics") is True
                and manifest.get("rigid_pose_write_guard") is True
                and manifest.get("kinematic_grasp_assist") is False
                and manifest.get("placement_nudge") is False
                and int(manifest.get("failures_saved", -1)) == 0
            )
            if not strict_manifest:
                report["errors"].append("Manifest does not prove strict zero-assist physical recording")
        if len(certificates) != num_episodes:
            report["errors"].append(
                f"Strict certificate count {len(certificates)} != dataset episodes {num_episodes}"
            )
        indices = [int(item.get("episode_index", -1)) for item in certificates]
        if sorted(indices) != list(range(num_episodes)):
            report["errors"].append("Strict certificate episode indices are missing, duplicated, or non-contiguous")
        seeds = [item.get("seed") for item in certificates]
        if len(set(seeds)) != len(seeds):
            report["errors"].append("Strict certificates contain duplicate rollout seeds")
        invalid = [
            int(item.get("episode_index", -1))
            for item in certificates
            if item.get("success") is not True
            or item.get("strict_physics") is not True
            or item.get("rigid_pose_write_guard") is not True
            or item.get("kinematic_intervention_count") != 0
        ]
        if invalid:
            report["errors"].append(f"Episodes without strict zero-intervention success certificates: {invalid}")
        metadata_tasks = {
            int(episode["episode_index"]): list(episode.get("tasks") or []) for episode in ds.meta.episodes
        }
        task_mismatches = [
            int(item.get("episode_index", -1))
            for item in certificates
            if item.get("instruction") not in metadata_tasks.get(int(item.get("episode_index", -1)), [])
        ]
        if task_mismatches:
            report["errors"].append(f"Certificate/dataset instruction mismatches: {task_mismatches}")
        certificate_commits = {str(item.get("source_commit")) for item in certificates}
        raw_manifest_commits = manifest.get("source_commits") if manifest is not None else None
        if raw_manifest_commits is None:
            raw_manifest_commits = [manifest.get("source_commit") if manifest is not None else None]
        manifest_commits = {str(item) for item in raw_manifest_commits}
        if manifest_commits & {"unknown", "None", ""}:
            report["errors"].append(
                f"Manifest contains unknown source revisions: {sorted(manifest_commits)}"
            )
        if certificate_commits != manifest_commits:
            report["errors"].append(
                f"Certificate source revisions {sorted(map(str, certificate_commits))} "
                f"do not match manifest revisions {sorted(manifest_commits)}"
            )

    if args.episodes_per_task > 0:
        if manifest is None:
            report["errors"].append("Cannot validate per-task quota without a recording manifest")
        else:
            task_cycle = list(manifest.get("task_cycle") or [])
            task_counts = {task_id: 0 for task_id in task_cycle}
            for certificate in certificates:
                task_id = certificate.get("task_id")
                if certificate.get("success") is True and task_id in task_counts:
                    task_counts[task_id] += 1
            bad_counts = {
                task_id: count for task_id, count in task_counts.items() if count != args.episodes_per_task
            }
            report["certified_successes_per_task"] = task_counts
            if not task_cycle:
                report["errors"].append("Manifest task_cycle is empty")
            if bad_counts:
                report["errors"].append(
                    f"Certified per-task quota is not exactly {args.episodes_per_task}: {bad_counts}"
                )

    # "task" is stored as episode language via task_index in LeRobot 0.6, not always a tensor feature.
    required = {"observation.state", "action", *IMAGE_KEYS}
    missing = sorted(required - set(meta_features))
    if missing:
        report["errors"].append(f"Missing features: {missing}")

    for key in ("observation.state", "action"):
        if key in meta_features:
            shape = tuple(meta_features[key].get("shape") or ())
            if shape != (ACTION_DIM,):
                report["errors"].append(f"{key} shape {shape} != ({ACTION_DIM},)")

    # Sample frames.
    idxs = np.linspace(0, n - 1, num=min(args.max_frames, n), dtype=int)
    black = 0
    nan_count = 0
    tasks: set[str] = set()
    for i in idxs:
        item = ds[int(i)]
        state = np.asarray(item["observation.state"])
        action = np.asarray(item["action"])
        if not np.isfinite(state).all() or not np.isfinite(action).all():
            nan_count += 1
        if state.shape[-1] != ACTION_DIM or action.shape[-1] != ACTION_DIM:
            report["errors"].append(f"Frame {i}: bad state/action shape {state.shape}/{action.shape}")
        for cam in IMAGE_KEYS:
            if cam not in item:
                report["errors"].append(f"Frame {i}: missing {cam}")
                continue
            img = np.asarray(item[cam])
            if img.ndim == 3 and img.shape[0] in (1, 3) and img.shape[-1] not in (1, 3):
                # CHW -> HWC for stats
                img_hwc = np.transpose(img, (1, 2, 0))
            else:
                img_hwc = img
            # LeRobot may return float images in [0, 1] or uint8 in [0, 255].
            mean_val = float(np.mean(img_hwc))
            if np.issubdtype(img_hwc.dtype, np.floating) and mean_val <= 1.5:
                nearly_black = mean_val < 0.02
            else:
                nearly_black = mean_val < 1.0
            if nearly_black:
                black += 1
        task = item.get("task")
        if task is not None:
            if isinstance(task, (list, tuple)):
                tasks.add(str(task[0]))
            else:
                tasks.add(str(task))

    report["sampled_frames"] = int(len(idxs))
    report["black_image_samples"] = black
    report["non_finite_samples"] = nan_count
    report["sample_tasks"] = sorted(tasks)
    report["joint_names_expected"] = list(JOINT_NAMES)

    if black > 0:
        report["warnings"].append(
            f"{black}/{len(idxs) * len(IMAGE_KEYS)} sampled camera panels look nearly black "
            "(common with broken EGL/OpenGL on headless laptops; re-check on AMD Radeon with working GL)"
        )
        # Fail only when essentially all sampled panels are black — unusable for vision training.
        if black >= len(idxs) * len(IMAGE_KEYS):
            report["errors"].append("All sampled camera images are nearly black")
    if nan_count > 0:
        report["errors"].append(f"{nan_count} sampled frames have NaN/Inf")
    if not tasks:
        report["warnings"].append("No language task strings found on sampled frames")

    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")

    if report["errors"]:
        print("[validate] FAILED")
        return 1
    print("[validate] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

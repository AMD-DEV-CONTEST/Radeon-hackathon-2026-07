"""Merge strict-physics LeRobot collection shards into one auditable dataset.

The LeRobot aggregator handles parquet/video/task index rewriting.  This wrapper adds
the RadeonVLA-Reflex guarantees that the generic aggregator does not know about:
strict-physics certificate validation, certificate reindexing, a combined collection
manifest, and atomic publication of the merged directory.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from radeonvla.artifact_io import atomic_write_json
from radeonvla.paths import PROJECT_ROOT


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="+", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--episodes-per-task", type=int, default=50)
    parser.add_argument(
        "--concatenate-files",
        action="store_true",
        help="Repack parquet/video files instead of retaining source file boundaries.",
    )
    return parser.parse_args(argv)


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON {path}: {exc}") from exc


def _source_manifest(root: Path) -> dict:
    for name in ("recording_manifest.json", "recording_progress.json"):
        path = root / name
        if path.is_file():
            return _load_json(path)
    raise FileNotFoundError(f"No recording manifest/progress found under {root}")


def _load_certificates(root: Path, expected_episodes: int) -> list[dict]:
    pending = sorted((root / "certificates" / ".pending").glob("episode_*.json"))
    if pending:
        raise RuntimeError(f"Source has unresolved pending certificates: {root} ({len(pending)})")
    paths = sorted((root / "certificates").glob("episode_*.json"))
    certificates = [_load_json(path) for path in paths]
    indices = [int(item.get("episode_index", -1)) for item in certificates]
    if indices != list(range(expected_episodes)):
        raise RuntimeError(
            f"Certificate indices under {root} are not contiguous 0..{expected_episodes - 1}: {indices[:8]}"
        )
    invalid = [
        index
        for index, item in enumerate(certificates)
        if item.get("success") is not True
        or item.get("strict_physics") is not True
        or item.get("rigid_pose_write_guard") is not True
        or item.get("kinematic_intervention_count") != 0
    ]
    if invalid:
        raise RuntimeError(f"Source contains non-strict certificates under {root}: {invalid[:16]}")
    return certificates


def _manifest_source_commits(manifest: dict) -> set[str]:
    """Return the audited source revisions represented by one dataset manifest."""
    raw = manifest.get("source_commits")
    if raw is None:
        raw = [manifest.get("source_commit")]
    if not isinstance(raw, list):
        raise RuntimeError("Manifest source_commits must be a list when present")
    revisions = {str(item) for item in raw}
    if not revisions or revisions & {"unknown", "None", ""}:
        raise RuntimeError(f"Manifest does not contain known source revisions: {sorted(revisions)}")
    return revisions


def _preflight_source(root: Path) -> tuple[dict, list[dict]]:
    info_path = root / "meta" / "info.json"
    if not info_path.is_file():
        raise FileNotFoundError(f"LeRobot metadata missing: {info_path}")
    info = _load_json(info_path)
    episodes = int(info.get("total_episodes", -1))
    if episodes <= 0:
        raise RuntimeError(f"Source has no episodes: {root}")
    manifest = _source_manifest(root)
    strict_manifest = (
        manifest.get("strict_physics") is True
        and manifest.get("rigid_pose_write_guard") is True
        and manifest.get("kinematic_grasp_assist") is False
        and manifest.get("placement_nudge") is False
        and int(manifest.get("failures_saved", -1)) == 0
    )
    if not strict_manifest:
        raise RuntimeError(f"Source manifest does not prove strict physical collection: {root}")
    certificates = _load_certificates(root, episodes)
    if len(certificates) != episodes:
        raise RuntimeError(f"Certificate count {len(certificates)} != episodes {episodes}: {root}")
    manifest_successes = int(manifest.get("successes", -1))
    if manifest_successes != episodes:
        raise RuntimeError(f"Manifest successes {manifest_successes} != episodes {episodes}: {root}")
    certificate_revisions = {str(item.get("source_commit")) for item in certificates}
    manifest_revisions = _manifest_source_commits(manifest)
    if certificate_revisions != manifest_revisions:
        raise RuntimeError(
            f"Certificate source revisions {sorted(certificate_revisions)} do not match "
            f"manifest revisions {sorted(manifest_revisions)}: {root}"
        )
    return manifest, certificates


def _ordered_task_cycle(manifests: list[dict], certificates: list[list[dict]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for manifest in manifests:
        for task_id in manifest.get("task_cycle") or []:
            if task_id not in seen:
                seen.add(task_id)
                ordered.append(str(task_id))
    for shard in certificates:
        for certificate in shard:
            task_id = str(certificate.get("task_id", ""))
            if task_id and task_id not in seen:
                seen.add(task_id)
                ordered.append(task_id)
    return ordered


def _combined_manifest(
    *,
    repo_id: str,
    output_root: Path,
    source_roots: list[Path],
    manifests: list[dict],
    certificates: list[list[dict]],
    episodes_per_task: int,
) -> dict:
    flat = [item for shard in certificates for item in shard]
    task_cycle = _ordered_task_cycle(manifests, certificates)
    task_counts = Counter(str(item["task_id"]) for item in flat)
    bad_counts = {
        task: task_counts.get(task, 0)
        for task in task_cycle
        if task_counts.get(task, 0) != episodes_per_task
    }
    if not task_cycle or bad_counts:
        raise RuntimeError(f"Merged per-task quota is not exactly {episodes_per_task}: {bad_counts}")
    seeds = [item.get("seed") for item in flat]
    if len(set(seeds)) != len(seeds):
        raise RuntimeError("Merged shards contain duplicate rollout seeds")
    revisions = {str(item.get("source_commit")) for item in flat}
    manifest_revisions = set().union(*(_manifest_source_commits(item) for item in manifests))
    if not revisions or revisions & {"unknown", "None", ""}:
        raise RuntimeError(f"Merged shards contain unknown source revisions: {sorted(revisions)}")
    if revisions != manifest_revisions:
        raise RuntimeError(
            f"Certificate source revisions {sorted(revisions)} do not match "
            f"source manifests {sorted(manifest_revisions)}"
        )

    first = manifests[0]
    attempts = sum(int(item.get("attempts", 0)) for item in manifests)
    total = len(flat)
    return {
        "status": "complete",
        "updated_at": datetime.now(UTC).isoformat(),
        "repo_id": repo_id,
        "dataset_root": str(output_root),
        "fps": first.get("fps"),
        "image_size": first.get("image_size"),
        "joint_names": first.get("joint_names"),
        "features": first.get("features"),
        "requested_successes": total,
        "episodes_per_task_target": episodes_per_task,
        "successes": total,
        "failures_saved": 0,
        "attempts": attempts,
        "max_attempts": sum(int(item.get("max_attempts", 0)) for item in manifests),
        "scheduler_index": total,
        "fail_streak": 0,
        "per_task_successes": {task: task_counts[task] for task in task_cycle},
        "missing_task_coverage": [],
        "coverage_complete": True,
        "require_coverage": True,
        "task_cycle": task_cycle,
        "suite": first.get("suite", "basic"),
        "seed": first.get("seed"),
        "source_seeds": [item.get("seed") for item in manifests],
        "backend": first.get("backend"),
        "video_codec": first.get("video_codec"),
        "dr_appearance": first.get("dr_appearance"),
        "dr_object_color": first.get("dr_object_color"),
        "dr_table_jitter": first.get("dr_table_jitter"),
        "dr_fov_jitter": first.get("dr_fov_jitter"),
        "dr_rebuild_every": first.get("dr_rebuild_every"),
        "dr_runtime": first.get("dr_runtime"),
        "dr_friction_ratio_range": first.get("dr_friction_ratio_range"),
        "dr_mass_ratio_range": first.get("dr_mass_ratio_range"),
        "dr_camera_position_jitter": first.get("dr_camera_position_jitter"),
        "dr_camera_lookat_jitter": first.get("dr_camera_lookat_jitter"),
        "kinematic_grasp_assist": False,
        "placement_nudge": False,
        "strict_physics": True,
        "rigid_pose_write_guard": True,
        "certificate_schema_version": first.get("certificate_schema_version", 1),
        "source_commit": next(iter(revisions)) if len(revisions) == 1 else None,
        "source_commits": sorted(revisions),
        "source_dirty": None,
        "collection_mode": "parallel_task_shards",
        "aggregation_sources": [
            {
                "repo_id": manifest.get("repo_id"),
                "root": str(root),
                "successes": len(shard),
                "seed": manifest.get("seed"),
                "source_commits": sorted(_manifest_source_commits(manifest)),
            }
            for root, manifest, shard in zip(source_roots, manifests, certificates, strict=True)
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.episodes_per_task <= 0:
        raise ValueError("--episodes-per-task must be greater than zero")
    sources = [_resolve(path) for path in args.sources]
    output_root = _resolve(args.output_root)
    staging_root = output_root.with_name(f".{output_root.name}.merge.inprogress")
    if output_root.exists():
        raise FileExistsError(f"Output already exists: {output_root}")
    if staging_root.exists():
        raise FileExistsError(f"Incomplete merge exists; inspect it before retrying: {staging_root}")

    manifests: list[dict] = []
    certificates: list[list[dict]] = []
    for source in sources:
        manifest, shard_certificates = _preflight_source(source)
        manifests.append(manifest)
        certificates.append(shard_certificates)
    combined = _combined_manifest(
        repo_id=args.repo_id,
        output_root=output_root,
        source_roots=sources,
        manifests=manifests,
        certificates=certificates,
        episodes_per_task=args.episodes_per_task,
    )

    from lerobot.datasets.aggregate import aggregate_datasets

    aggregate_datasets(
        repo_ids=[str(item["repo_id"]) for item in manifests],
        aggr_repo_id=args.repo_id,
        roots=sources,
        aggr_root=staging_root,
        concatenate_videos=args.concatenate_files,
        concatenate_data=args.concatenate_files,
    )

    certificate_dir = staging_root / "certificates"
    certificate_dir.mkdir(parents=True, exist_ok=False)
    offset = 0
    for shard in certificates:
        for certificate in shard:
            merged = dict(certificate)
            merged["episode_index"] = int(certificate["episode_index"]) + offset
            atomic_write_json(certificate_dir / f"episode_{merged['episode_index']:06d}.json", merged)
        offset += len(shard)
    atomic_write_json(staging_root / "recording_manifest.json", combined)
    atomic_write_json(staging_root / "recording_progress.json", combined)

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    reopened = LeRobotDataset(args.repo_id, root=staging_root, video_backend="pyav")
    if int(reopened.num_episodes) != len([item for shard in certificates for item in shard]):
        raise RuntimeError(f"Merged dataset reopened with only {reopened.num_episodes} episodes")
    staging_root.rename(output_root)
    print(f"[merge] published {reopened.num_episodes} episodes -> {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

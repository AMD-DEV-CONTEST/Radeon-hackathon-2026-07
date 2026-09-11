#!/usr/bin/env python3
"""Merge audited PI0.5 residual datasets and preserve recovery provenance."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from parcel_sorter.mobile_pi05_contract import (
    MOBILE_PI05_RESIDUAL_ACTION_NAMES,
    MOBILE_PI05_STATE_NAMES,
)
from parcel_sorter.mobile_dataset import (
    infer_mobile_policy_modality,
    mobile_policy_visual_keys,
)
from parcel_sorter.mobile_pi05_normalization import (
    constant_dimensions,
    stabilize_quantile_stats,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode-neutral-task",
        default=None,
        help="replace all task text with one mode-blind instruction",
    )
    args = parser.parse_args()
    sources = [path.resolve() for path in args.source]
    if len(sources) < 2:
        parser.error("at least two source datasets are required")
    if args.output.exists():
        parser.error("output must not already exist")

    manifests = []
    manifest_paths = []
    for source in sources:
        manifest_path = _find_dataset_manifest(source)
        if not manifest_path.is_file() or not (source / "meta/info.json").is_file():
            parser.error(f"source is not a PI0.5 training dataset: {source}")
        manifest_paths.append(manifest_path)
        info = json.loads((source / "meta/info.json").read_text(encoding="utf-8"))
        manifests.append(
            _bind_visual_contract(
                json.loads(manifest_path.read_text(encoding="utf-8")),
                info.get("features", {}),
            )
        )
    reference = manifests[0]
    for source, manifest in zip(sources[1:], manifests[1:], strict=True):
        for key in (
            "state_dimension",
            "action_dimension",
            "state_names",
            "action_names",
            "mode_conditioning_policy",
            "lift_residual_supervision",
            "policy_visual_modality",
            "policy_visual_keys",
            "action_contract",
            "expert_reference_used",
        ):
            if manifest.get(key) != reference.get(key):
                parser.error(f"contract mismatch in {source}: {key}")

    editor = shutil.which("lerobot-edit-dataset")
    if editor is None:
        adjacent = Path(sys.executable).parent / "lerobot-edit-dataset"
        editor = str(adjacent) if adjacent.is_file() else None
    if editor is None:
        parser.error("lerobot-edit-dataset is required")
    command = [
        editor,
        "--operation.type",
        "merge",
        "--operation.repo_ids",
        json.dumps(["local/mobile-pi05-verified-recovery"] * len(sources)),
        "--operation.roots",
        json.dumps([str(path) for path in sources]),
        "--operation.concatenate_videos",
        "false",
        "--operation.concatenate_data",
        "false",
        "--new_repo_id",
        "local/mobile-pi05-verified-recovery-merged",
        "--new_root",
        str(args.output.resolve()),
        "--push_to_hub",
        "false",
    ]
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

    task_language_policy = "source_text"
    if args.mode_neutral_task:
        _replace_task_text(args.output, args.mode_neutral_task)
        task_language_policy = "mode_neutral_shared_instruction_v1"
    state_names = tuple(str(name) for name in reference["state_names"])
    action_names = tuple(str(name) for name in reference["action_names"])
    normalization_summary = _recompute_global_vector_stats(
        args.output, state_names=state_names, action_names=action_names
    )

    merged_episode_manifests = []
    next_episode_index = 0
    for source, manifest in zip(sources, manifests, strict=True):
        for item in manifest.get("episode_manifests", ()):
            merged_episode_manifests.append(
                {
                    **item,
                    "episode_index": next_episode_index,
                    "source_dataset": str(source),
                    "source_episode_index": item.get("episode_index"),
                }
            )
            next_episode_index += 1
    info = json.loads((args.output / "meta/info.json").read_text(encoding="utf-8"))
    output_visual = _bind_visual_contract({}, info.get("features", {}))
    if output_visual["policy_visual_keys"] != reference["policy_visual_keys"]:
        raise RuntimeError("merged dataset visual features differ from source contract")
    output_manifest = {
        "schema_version": 1,
        "protocol": (
            "pash-pi05-absolute-merged-v1"
            if reference.get("action_contract") == "absolute_v1"
            else "pash-pi05-residual-merged-v1"
        ),
        "source_datasets": [str(path) for path in sources],
        "source_manifest_sha256": [_sha256(path) for path in manifest_paths],
        "source_replay_counts": dict(Counter(str(path) for path in sources)),
        "output_dataset": str(args.output.resolve()),
        "episodes": int(info["total_episodes"]),
        "frames": int(info["total_frames"]),
        "state_dimension": reference["state_dimension"],
        "state_names": reference["state_names"],
        "action_dimension": reference["action_dimension"],
        "action_names": reference["action_names"],
        "action_contract": reference.get("action_contract", "residual_v1"),
        "expert_reference_used": reference.get("expert_reference_used", True),
        "target_leakage_audit": reference.get("target_leakage_audit"),
        "policy_visual_modality": reference["policy_visual_modality"],
        "policy_visual_keys": reference["policy_visual_keys"],
        "mode_conditioning_policy": reference.get(
            "mode_conditioning_policy", "pregrasp_hidden"
        ),
        "task_language_policy": task_language_policy,
        "mode_neutral_task": args.mode_neutral_task,
        "task_metadata_sha256": _sha256(args.output / "meta/tasks.parquet"),
        "lift_residual_supervision": reference.get(
            "lift_residual_supervision", "stage_constant_v1"
        ),
        "verified_recovery_summaries": sorted(
            {
                str(manifest["verified_recovery_summary"])
                for manifest in manifests
                if manifest.get("verified_recovery_summary")
            }
        ),
        "nonzero_contact_residual_frames": sum(
            int(manifest.get("nonzero_contact_residual_frames", 0))
            for manifest in manifests
        ),
        "nonzero_base_command_frames": sum(
            int(manifest.get("nonzero_base_command_frames", 0))
            for manifest in manifests
        ),
        "normalization_stats_policy": "recomputed_merged_frames_quantiles_with_degenerate_fallback_v1",
        "normalization_summary": normalization_summary,
        "episode_manifests": merged_episode_manifests,
        "mode_episode_counts": {
            mode: sum(
                mode in item.get("grasp_modes", ())
                for item in merged_episode_manifests
            )
            for mode in ("top_suction", "side_suction", "cooperative_cradle")
        },
        "output_data_sha256": {
            str(path.relative_to(args.output)).replace("\\", "/"): _sha256(path)
            for path in sorted(args.output.glob("data/**/*.parquet"))
        },
        "claim_boundary": (
            "merged verified absolute-action training data; current-tool state is "
            "observation-derived, repeated sources are sampling weights, and failed "
            "rollouts are excluded"
            if reference.get("action_contract") == "absolute_v1"
            else "merged training data only; each corrective source retains a verified "
            "collector summary, repeated sources are training weights rather than "
            "independent samples, and failed rollouts are excluded"
        ),
    }
    if output_manifest["episodes"] != len(merged_episode_manifests):
        raise RuntimeError("merged episode count does not match provenance manifest")
    output_manifest_name = (
        "PI05_ABSOLUTE_DATASET_MANIFEST.json"
        if reference.get("action_contract") == "absolute_v1"
        else "PI05_RESIDUAL_DATASET_MANIFEST.json"
    )
    (args.output / output_manifest_name).write_text(
        json.dumps(output_manifest, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in output_manifest.items() if key != "episode_manifests"},
            indent=2,
        )
    )
    return 0


def _bind_visual_contract(
    manifest: dict[str, object], features: dict[str, object]
) -> dict[str, object]:
    """Derive and verify policy-facing camera keys for old and new manifests."""

    result = dict(manifest)
    modality = infer_mobile_policy_modality(features)
    keys = list(mobile_policy_visual_keys(modality))
    if result.get("policy_visual_modality") not in (None, modality):
        raise ValueError("residual manifest policy visual modality mismatch")
    if result.get("policy_visual_keys") not in (None, keys):
        raise ValueError("residual manifest policy visual keys mismatch")
    result["policy_visual_modality"] = modality
    result["policy_visual_keys"] = keys
    return result


def _find_dataset_manifest(root: Path) -> Path:
    paths = [
        path
        for path in (
            root / "PI05_RESIDUAL_DATASET_MANIFEST.json",
            root / "PI05_ABSOLUTE_DATASET_MANIFEST.json",
        )
        if path.is_file()
    ]
    if len(paths) != 1:
        raise ValueError(f"expected one PI0.5 dataset manifest in {root}")
    return paths[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _replace_task_text(root: Path, task: str) -> None:
    """Remove grasp-mode wording without changing episode or frame identities."""

    import pyarrow as pa
    import pyarrow.parquet as pq

    if not task.strip():
        raise ValueError("mode-neutral task must not be empty")
    tasks_path = root / "meta/tasks.parquet"
    table = pq.read_table(tasks_path)
    task_index = table.schema.get_field_index("task")
    if task_index < 0:
        raise RuntimeError("tasks metadata has no task column")
    table = table.set_column(
        task_index,
        "task",
        pa.array([task] * table.num_rows, type=table.schema.field(task_index).type),
    )
    pq.write_table(table, tasks_path)

    for path in sorted((root / "meta/episodes").glob("**/*.parquet")):
        episode_table = pq.read_table(path)
        tasks_index = episode_table.schema.get_field_index("tasks")
        if tasks_index < 0:
            continue
        field_type = episode_table.schema.field(tasks_index).type
        if pa.types.is_list(field_type) or pa.types.is_large_list(field_type):
            values = [[task] for _ in range(episode_table.num_rows)]
        else:
            values = [task] * episode_table.num_rows
        episode_table = episode_table.set_column(
            tasks_index,
            "tasks",
            pa.array(values, type=field_type),
        )
        pq.write_table(episode_table, path)


def _recompute_global_vector_stats(
    root: Path,
    *,
    state_names: tuple[str, ...] = MOBILE_PI05_STATE_NAMES,
    action_names: tuple[str, ...] = MOBILE_PI05_RESIDUAL_ACTION_NAMES,
) -> dict[str, dict[str, list[str]]]:
    """Replace LeRobot's weighted per-source quantiles with true merged-frame stats."""

    import numpy as np
    import pyarrow.parquet as pq

    feature_names = {
        "observation.state": state_names,
        "action": action_names,
    }
    values: dict[str, list[list[float]]] = {key: [] for key in feature_names}
    files = sorted(root.glob("data/**/*.parquet"))
    if not files:
        raise RuntimeError("merged PI0.5 dataset contains no parquet files")
    for path in files:
        table = pq.read_table(path, columns=list(feature_names))
        for row in table.to_pylist():
            for feature, names in feature_names.items():
                vector = [float(value) for value in row[feature]]
                if len(vector) != len(names):
                    raise RuntimeError(f"merged {feature} dimension mismatch")
                values[feature].append(vector)

    stats_path = root / "meta/stats.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    summary = {}
    for feature, names in feature_names.items():
        feature_stats, fallback = stabilize_quantile_stats(
            _vector_stats(values[feature], np), names
        )
        stats[feature] = feature_stats
        summary[feature] = {
            "constant_dimensions": list(constant_dimensions(feature_stats, names)),
            "degenerate_quantile_fallback_dimensions": list(fallback),
        }
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return summary


def _vector_stats(values: list[list[float]], np: object) -> dict[str, list[float]]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": [len(values)],
        "min": array.min(axis=0).tolist(),
        "max": array.max(axis=0).tolist(),
        "mean": array.mean(axis=0).tolist(),
        "std": array.std(axis=0).tolist(),
        "q01": np.quantile(array, 0.01, axis=0).tolist(),
        "q10": np.quantile(array, 0.10, axis=0).tolist(),
        "q50": np.quantile(array, 0.50, axis=0).tolist(),
        "q90": np.quantile(array, 0.90, axis=0).tolist(),
        "q99": np.quantile(array, 0.99, axis=0).tolist(),
    }


if __name__ == "__main__":
    raise SystemExit(main())

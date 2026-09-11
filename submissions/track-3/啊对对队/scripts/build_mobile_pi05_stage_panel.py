#!/usr/bin/env python3
"""Freeze a stage-complete, action-labeled PI0.5 research panel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from parcel_sorter.mobile_pi05_contract import MOBILE_STAGE_NAMES, PI05_GRASP_MODES
from parcel_sorter.mobile_pi05_research_protocol import (
    PI05_DEVELOPMENT_ROLE,
    PI05_TINY_OVERFIT_ROLE,
    build_stage_panel,
    file_sha256,
    independent_source_identity,
)


def _manifest_path(root: Path) -> Path:
    matches = [
        path
        for path in (
            root / "PI05_ABSOLUTE_DATASET_MANIFEST.json",
            root / "PI05_RESIDUAL_DATASET_MANIFEST.json",
            root / "PI05_INCREMENTAL_DATASET_MANIFEST.json",
        )
        if path.is_file()
    ]
    if len(matches) != 1:
        raise ValueError("dataset must contain exactly one PI0.5 provenance manifest")
    return matches[0]


def _episode_sources(manifest: dict[str, Any]) -> dict[int, str]:
    entries = list(manifest.get("episode_manifests") or ())
    if not entries:
        raise ValueError("dataset manifest contains no episode provenance")
    result: dict[int, str] = {}
    for item in entries:
        episode_index = int(item.get("episode_index", -1))
        if episode_index < 0 or episode_index in result:
            raise ValueError("episode provenance indices must be unique and non-negative")
        result[episode_index] = independent_source_identity(item)
    return result


def _stage_id(value: Any) -> int:
    if isinstance(value, list):
        if len(value) != 1:
            raise ValueError("stage id column must contain one value")
        value = value[0]
    result = int(value)
    if not 0 <= result < len(MOBILE_STAGE_NAMES):
        raise ValueError(f"invalid stage id: {result}")
    return result


def read_labeled_observations(
    dataset_root: Path, manifest: dict[str, Any], manifest_sha256: str
) -> list[dict[str, Any]]:
    """Read only label/provenance columns; images are never loaded."""

    if manifest.get("action_contract") != "absolute_v1":
        raise ValueError("stage-complete action panels currently require absolute_v1 labels")
    import pyarrow.parquet as pq

    sources = _episode_sources(manifest)
    files = sorted(dataset_root.glob("data/**/*.parquet"))
    if not files:
        raise ValueError("dataset contains no LeRobot Parquet files")
    observations: list[dict[str, Any]] = []
    fallback_index = 0
    for path in files:
        schema_names = set(pq.read_schema(path).names)
        required = {"episode_index", "observation.stage_id", "action"}
        if not required <= schema_names:
            missing = sorted(required - schema_names)
            raise ValueError(f"Parquet file lacks action-panel columns: {missing}")
        columns = sorted(required | ({"index"} if "index" in schema_names else set()))
        for row in pq.read_table(path, columns=columns).to_pylist():
            episode_index = int(row["episode_index"])
            if episode_index not in sources:
                raise ValueError(f"episode {episode_index} lacks provenance")
            action = tuple(float(value) for value in row["action"])
            if len(action) != 23:
                raise ValueError("absolute action label must contain 23 values")
            dataset_index = int(row.get("index", fallback_index))
            fallback_index += 1
            mode = PI05_GRASP_MODES[
                max(range(3), key=action[19:22].__getitem__)
            ]
            stage = MOBILE_STAGE_NAMES[_stage_id(row["observation.stage_id"])]
            observations.append(
                {
                    "observation_id": f"{manifest_sha256[:12]}-{dataset_index:08d}",
                    "dataset_index": dataset_index,
                    "episode_index": episode_index,
                    "source_identity": sources[episode_index],
                    "grasp_mode": mode,
                    "stage": stage,
                    "action_label_available": True,
                }
            )
    return observations


def _all_source_identities(manifest_path: Path) -> set[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return set(_episode_sources(manifest).values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument(
        "--role",
        choices=(PI05_TINY_OVERFIT_ROLE, PI05_DEVELOPMENT_ROLE),
        required=True,
    )
    parser.add_argument("--training-manifest", type=Path)
    parser.add_argument("--minimum-per-cell", type=int, default=1)
    parser.add_argument("--minimum-independent-sources-per-mode", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.dataset_root.resolve()
    manifest_path = _manifest_path(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sha256 = file_sha256(manifest_path)
    if args.role == PI05_DEVELOPMENT_ROLE and args.training_manifest is None:
        parser.error("heldout_action_development requires --training-manifest")
    minimum_sources = args.minimum_independent_sources_per_mode
    if minimum_sources is None:
        minimum_sources = 1 if args.role == PI05_TINY_OVERFIT_ROLE else 2
    training_sources = (
        _all_source_identities(args.training_manifest.resolve())
        if args.training_manifest is not None
        else set()
    )
    try:
        payload = build_stage_panel(
            read_labeled_observations(root, manifest, manifest_sha256),
            role=args.role,
            dataset_root=root,
            dataset_manifest_sha256=manifest_sha256,
            minimum_observations_per_mode_stage=args.minimum_per_cell,
            minimum_independent_sources_per_mode=minimum_sources,
            training_source_identities=training_sources,
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

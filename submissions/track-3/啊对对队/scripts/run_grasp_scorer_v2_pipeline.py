#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.grasp_model_selection import select_grasp_scorer_candidate
from parcel_sorter.grasp_scoring import sha256_file
from scripts.audit_grasp_candidate_model_selection_v2_protocol import (
    audit_protocol,
)
from scripts.build_grasp_candidate_dataset import run as build_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen two-stage grasp scorer v2 model pipeline."
    )
    parser.add_argument("phase", choices=("train", "development"))
    parser.add_argument(
        "--model-protocol",
        type=Path,
        default=PROJECT_ROOT / "configs/grasp_candidate_model_selection_v2.toml",
    )
    parser.add_argument(
        "--collection-protocol",
        type=Path,
        default=PROJECT_ROOT / "configs/grasp_candidate_learning_v2.toml",
    )
    parser.add_argument(
        "--collection-root",
        type=Path,
        default=PROJECT_ROOT / "outputs/grasp-scorer-v2/candidates",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "outputs/grasp-scorer-v2/model-selection",
    )
    return parser.parse_args()


def load_model_protocol(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def dataset_group_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    groups: dict[str, str] = {}
    for row in payload["rows"]:
        group_id = str(row["group_id"])
        split = str(row["split"])
        previous = groups.setdefault(group_id, split)
        if previous != split:
            raise ValueError(f"dataset group crosses splits: {group_id}")
    return dict(Counter(groups.values()))


def validate_dataset_groups(
    payload: Mapping[str, Any],
    expected: Mapping[str, int],
) -> dict[str, int]:
    observed = dataset_group_counts(payload)
    if observed != dict(expected):
        raise ValueError(f"dataset group counts differ: {observed} != {dict(expected)}")
    return observed


def training_commands(
    protocol: Mapping[str, Any],
    *,
    python: str,
    dataset: Path,
    output_dir: Path,
) -> list[tuple[str, list[str]]]:
    common = protocol["common_training"]
    commands = []
    for candidate in protocol["candidates"]:
        name = str(candidate["name"])
        command = [
            python,
            str(PROJECT_ROOT / protocol["implementation"]["trainer"]),
            "--dataset",
            str(dataset),
            "--output-dir",
            str(output_dir / name),
            "--train-split",
            str(common["train_split"]),
            "--steps",
            str(common["steps"]),
            "--hidden-width",
            str(common["hidden_width"]),
            "--learning-rate",
            str(common["learning_rate"]),
            "--weight-decay",
            str(common["weight_decay"]),
            "--seed",
            str(common["seed"]),
            "--device",
            str(common["device"]),
            "--objective",
            str(candidate["objective"]),
            "--safety-pair-weight",
            str(candidate["safety_pair_weight"]),
            "--success-pair-weight",
            str(candidate["success_pair_weight"]),
        ]
        commands.append((name, command))
    return commands


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _build_dataset(
    collection_protocol: Path,
    manifests: Sequence[Path],
    output: Path,
) -> dict[str, Any]:
    namespace = argparse.Namespace(
        protocol=collection_protocol,
        input=[],
        manifest=list(manifests),
        output=output,
    )
    payload = build_dataset(namespace)
    _write_json(output, payload)
    return payload


def _run_command(command: Sequence[str]) -> None:
    subprocess.run(list(command), cwd=PROJECT_ROOT, check=True)


def _validate_training_summary(
    summary: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    protocol: Mapping[str, Any],
    expected_dataset_sha256: str,
) -> None:
    common = protocol["common_training"]
    checks = {
        "objective": candidate["objective"],
        "parameter_count": common["parameter_count"],
        "steps": common["steps"],
        "hidden_width": common["hidden_width"],
        "seed": common["seed"],
        "learning_rate": common["learning_rate"],
        "weight_decay": common["weight_decay"],
        "safety_pair_weight": candidate["safety_pair_weight"],
        "success_pair_weight": candidate["success_pair_weight"],
        "train_group_count": protocol["source"]["expected_train_groups"],
        "dataset_file_sha256": expected_dataset_sha256,
    }
    for key, expected in checks.items():
        if summary.get(key) != expected:
            raise ValueError(
                f"training summary {key} differs: {summary.get(key)!r} != {expected!r}"
            )
    if not summary.get("hip_version") or "AMD" not in str(summary.get("device_name")):
        raise ValueError("training summary does not prove AMD ROCm execution")


def run_train(args: argparse.Namespace, protocol: Mapping[str, Any]) -> dict[str, Any]:
    collection_root = args.collection_root.resolve()
    development_manifest = collection_root / "development/manifest.json"
    holdout_manifest = collection_root / "holdout/manifest.json"
    if development_manifest.exists() or holdout_manifest.exists():
        raise PermissionError(
            "train checkpoints must freeze before development or holdout collection"
        )
    output_dir = args.output_dir.resolve()
    freeze_manifest_path = output_dir / "train-freeze-manifest.json"
    if freeze_manifest_path.exists():
        raise FileExistsError("train freeze manifest already exists")
    dataset_path = output_dir / "train-dataset.json"
    dataset = _build_dataset(
        args.collection_protocol.resolve(),
        (collection_root / "train/manifest.json",),
        dataset_path,
    )
    validate_dataset_groups(
        dataset,
        {"train": int(protocol["source"]["expected_train_groups"])},
    )
    dataset_sha256 = sha256_file(dataset_path)
    models = []
    candidate_by_name = {
        str(row["name"]): row for row in protocol["candidates"]
    }
    for name, command in training_commands(
        protocol,
        python=sys.executable,
        dataset=dataset_path,
        output_dir=output_dir / "models",
    ):
        _run_command(command)
        model_dir = output_dir / "models" / name
        summary_path = model_dir / "summary.json"
        checkpoint_path = model_dir / "grasp_scorer.pt"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        _validate_training_summary(
            summary,
            candidate=candidate_by_name[name],
            protocol=protocol,
            expected_dataset_sha256=dataset_sha256,
        )
        models.append(
            {
                "name": name,
                "objective": candidate_by_name[name]["objective"],
                "summary": str(summary_path),
                "summary_sha256": sha256_file(summary_path),
                "checkpoint": str(checkpoint_path),
                "checkpoint_sha256": sha256_file(checkpoint_path),
            }
        )
    result = {
        "schema_version": "1.0",
        "status": "train_checkpoints_frozen_before_development",
        "model_protocol": str(args.model_protocol.resolve()),
        "model_protocol_sha256": sha256_file(args.model_protocol),
        "collection_protocol_sha256": sha256_file(args.collection_protocol),
        "pipeline": str(Path(__file__).resolve()),
        "pipeline_sha256": sha256_file(Path(__file__).resolve()),
        "dataset": str(dataset_path),
        "dataset_sha256": dataset_sha256,
        "dataset_payload_sha256": dataset["dataset_sha256"],
        "group_counts": dataset_group_counts(dataset),
        "development_manifest_observed": False,
        "holdout_manifest_observed": False,
        "models": models,
    }
    _write_json(freeze_manifest_path, result)
    return result


def _load_frozen_models(
    path: Path,
    *,
    expected_model_protocol_sha256: str,
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "train_checkpoints_frozen_before_development":
        raise ValueError("training freeze manifest has an unexpected status")
    if payload.get("model_protocol_sha256") != expected_model_protocol_sha256:
        raise ValueError("training freeze manifest uses a different model protocol")
    for row in payload["models"]:
        if sha256_file(row["checkpoint"]) != row["checkpoint_sha256"]:
            raise ValueError(f"frozen checkpoint hash differs: {row['name']}")
    return payload["models"]


def run_development(
    args: argparse.Namespace,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    collection_root = args.collection_root.resolve()
    if (collection_root / "holdout/manifest.json").exists():
        raise PermissionError("holdout was opened before model selection")
    output_dir = args.output_dir.resolve()
    train_freeze_path = output_dir / "train-freeze-manifest.json"
    models = _load_frozen_models(
        train_freeze_path,
        expected_model_protocol_sha256=sha256_file(args.model_protocol),
    )
    dataset_path = output_dir / "train-development-dataset.json"
    dataset = _build_dataset(
        args.collection_protocol.resolve(),
        (
            collection_root / "train/manifest.json",
            collection_root / "development/manifest.json",
        ),
        dataset_path,
    )
    validate_dataset_groups(
        dataset,
        {
            "train": int(protocol["source"]["expected_train_groups"]),
            "development": int(protocol["source"]["expected_development_groups"]),
        },
    )
    development = protocol["development"]
    evaluations = []
    evaluator = PROJECT_ROOT / protocol["implementation"]["evaluator"]
    for model in models:
        output = output_dir / "development" / f"{model['name']}.json"
        command = [
            sys.executable,
            str(evaluator),
            "--dataset",
            str(dataset_path),
            "--checkpoint",
            str(model["checkpoint"]),
            "--split",
            "development",
            "--device",
            str(protocol["common_training"]["device"]),
            "--output",
            str(output),
            "--warmup",
            str(development["latency_warmup"]),
            "--benchmark-repeats",
            str(development["latency_repeats"]),
            "--latency-group-id",
            str(development["latency_group_id"]),
        ]
        _run_command(command)
        payload = json.loads(output.read_text(encoding="utf-8"))
        evaluations.append((str(model["name"]), payload, output))
    selection = select_grasp_scorer_candidate(
        [(name, payload) for name, payload, _path in evaluations],
        expected_group_count=int(development["expected_group_count"]),
        expected_profile_group_count=int(
            development["expected_profile_group_count"]
        ),
        expected_profiles=development["expected_profiles"],
        max_warm_p95_ms=float(development["max_warm_batch_p95_ms"]),
    )
    selection.update(
        {
            "model_protocol": str(args.model_protocol.resolve()),
            "model_protocol_sha256": sha256_file(args.model_protocol),
            "pipeline": str(Path(__file__).resolve()),
            "pipeline_sha256": sha256_file(Path(__file__).resolve()),
            "train_freeze_manifest": str(train_freeze_path),
            "train_freeze_manifest_sha256": sha256_file(train_freeze_path),
            "dataset": str(dataset_path),
            "dataset_sha256": sha256_file(dataset_path),
            "evaluation_artifacts": [
                {
                    "name": name,
                    "path": str(path),
                    "sha256": sha256_file(path),
                }
                for name, _payload, path in evaluations
            ],
        }
    )
    _write_json(output_dir / "development-selection.json", selection)
    return selection


def main() -> int:
    args = parse_args()
    audit_protocol(args.model_protocol.resolve())
    protocol = load_model_protocol(args.model_protocol.resolve())
    if args.phase == "train":
        result = run_train(args, protocol)
    else:
        result = run_development(args, protocol)
    print(
        json.dumps(
            {
                "phase": args.phase,
                "status": result["status"],
                "selected": result.get("selected"),
                "holdout_opened": result.get("holdout_opened", False),
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build compact, verifiable evidence for a completed model sweep."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_sweep_evidence(
    sweep_root: Path,
    dataset_split: Path,
    *,
    expected_steps: int,
    expected_models: tuple[str, ...] = ("act",),
    expected_modalities: tuple[str, ...] = ("rgb", "rgb-d"),
    expected_seeds: tuple[int, ...] = (11, 22, 33),
) -> dict[str, Any]:
    if expected_steps < 1:
        raise ValueError("expected_steps must be positive")
    status_path = sweep_root / "sweep_status.csv"
    if not status_path.is_file():
        raise ValueError(f"sweep status is missing: {status_path}")
    if not dataset_split.is_file():
        raise ValueError(f"dataset split is missing: {dataset_split}")

    with status_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required_fields = {"model", "modality", "seed", "status"}
    if not rows or not required_fields.issubset(rows[0]):
        raise ValueError("sweep status has no rows or does not match the expected schema")

    expected = {
        (model, modality, seed)
        for model in expected_models
        for modality in expected_modalities
        for seed in expected_seeds
    }
    observed: dict[tuple[str, str, int], dict[str, str]] = {}
    for row in rows:
        key = (row["model"], row["modality"], int(row["seed"]))
        if key in observed:
            raise ValueError(f"duplicate sweep cell: {key}")
        observed[key] = row
    if observed.keys() != expected:
        missing = sorted(expected - observed.keys())
        extra = sorted(observed.keys() - expected)
        raise ValueError(f"sweep cells differ; missing={missing}, extra={extra}")

    cells = []
    for model, modality, seed in sorted(expected):
        row = observed[(model, modality, seed)]
        status = int(row["status"])
        if status != 0:
            raise ValueError(f"sweep cell failed: {(model, modality, seed)} status={status}")

        cell_name = f"{model}-{modality}-seed{seed}"
        log_path = sweep_root / f"{cell_name}.log"
        checkpoint = (
            sweep_root
            / cell_name
            / "checkpoints"
            / f"{expected_steps:06d}"
            / "pretrained_model"
        )
        train_config_path = checkpoint / "train_config.json"
        policy_config_path = checkpoint / "config.json"
        for required_path in (log_path, train_config_path, policy_config_path):
            if not required_path.is_file():
                raise ValueError(f"required sweep artifact is missing: {required_path}")

        train_config = _load_json(train_config_path)
        policy_config = _load_json(policy_config_path)
        if int(train_config.get("steps", -1)) != expected_steps:
            raise ValueError(f"{cell_name} has unexpected training steps")
        if int(train_config.get("seed", -1)) != seed:
            raise ValueError(f"{cell_name} has unexpected seed")
        if train_config.get("policy", {}).get("type") != model:
            raise ValueError(f"{cell_name} has unexpected policy type")
        if policy_config.get("use_amp") is not True:
            raise ValueError(f"{cell_name} did not enable AMP")

        feature_names = set(policy_config.get("input_features", {}))
        expected_visual = {"observation.images.overhead_rgb"}
        if modality == "rgb-d":
            expected_visual.add("observation.images.overhead_depth_rgb")
        observed_visual = {name for name in feature_names if ".images." in name}
        if observed_visual != expected_visual:
            raise ValueError(
                f"{cell_name} visual inputs differ; "
                f"expected={sorted(expected_visual)}, observed={sorted(observed_visual)}"
            )

        files = []
        for artifact in sorted(path for path in checkpoint.iterdir() if path.is_file()):
            files.append(
                {
                    "name": artifact.name,
                    "bytes": artifact.stat().st_size,
                    "sha256": sha256_file(artifact),
                }
            )
        cells.append(
            {
                "model": model,
                "modality": modality,
                "seed": seed,
                "status": status,
                "steps": expected_steps,
                "amp": True,
                "visual_inputs": sorted(observed_visual),
                "log": {
                    "path": log_path.as_posix(),
                    "bytes": log_path.stat().st_size,
                    "sha256": sha256_file(log_path),
                },
                "checkpoint": {
                    "path": checkpoint.as_posix(),
                    "files": files,
                },
            }
        )

    return {
        "schema_version": 1,
        "claim_scope": "integration_smoke_only_not_model_selection",
        "contract": {
            "models": list(expected_models),
            "modalities": list(expected_modalities),
            "seeds": list(expected_seeds),
            "steps": expected_steps,
            "cell_count": len(expected),
        },
        "dataset_split": {
            "path": dataset_split.as_posix(),
            "bytes": dataset_split.stat().st_size,
            "sha256": sha256_file(dataset_split),
        },
        "sweep_status": {
            "path": status_path.as_posix(),
            "bytes": status_path.stat().st_size,
            "sha256": sha256_file(status_path),
        },
        "cells": cells,
    }


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload

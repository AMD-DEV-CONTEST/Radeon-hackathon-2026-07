#!/usr/bin/env python3
"""Rebuild the matched PI0.5 training dataset with synchronized wrist RGB-D."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


MODE_NEUTRAL_TASK = "Recover contact and transport the parcel to the marked destination."
GROUP_COUNTS = {"top_side": 3, "side": 2, "cradle": 2}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _successful_config(summary_path: Path, *, group: str) -> dict[str, Any]:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    successful = [item for item in payload.get("results", ()) if item.get("success")]
    observed_order = [str(item.get("episode_id")) for item in successful]
    declared_order = list(map(str, payload.get("successful_episode_order", ())))
    if declared_order != observed_order:
        raise ValueError(f"successful episode order mismatch in {summary_path}")
    if len(successful) != GROUP_COUNTS[group]:
        raise ValueError(
            f"R14 {group} source must contain {GROUP_COUNTS[group]} successful episodes"
        )
    episodes = []
    for item in successful:
        recovery = item.get("recovery_label") or {}
        if not recovery.get("verified_success"):
            raise ValueError(f"R14 source is not a verified recovery: {item.get('episode_id')}")
        parameters = dict(item.get("parameters") or {})
        if str(parameters.get("episode_id")) != str(item.get("episode_id")):
            raise ValueError("collector result and parameter episode ids differ")
        if any(key in parameters for key in ("success", "outcome", "failure_stage")):
            raise ValueError("R14 collection parameters contain outcome leakage")
        episodes.append(parameters)
    return {
        "schema_version": 1,
        "collection_id": f"pi05-r14-{group}-wrist-paired-v1",
        "source_collection_summary": str(summary_path.resolve()),
        "source_collection_summary_sha256": _sha256(summary_path),
        "selection_policy": "verified_successes_in_frozen_source_order",
        "policy_visual_modality": "rgbd_wrist",
        "episodes": episodes,
    }


def _run(command: list[str], *, cwd: Path, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(json.dumps({"command": command}) + "\n")
        log.flush()
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"R14 dataset stage failed with exit code {completed.returncode}: {log_path}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dataset", type=Path, required=True)
    parser.add_argument("--top-side-summary", type=Path, required=True)
    parser.add_argument("--side-summary", type=Path, required=True)
    parser.add_argument("--cradle-summary", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("configs/catalog_v2.toml"))
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument("--state-atol", type=float, default=1e-6)
    parser.add_argument("--action-atol", type=float, default=1e-6)
    args = parser.parse_args()
    if args.output_root.exists():
        parser.error("R14 output root must not already exist")
    if args.state_atol < 0.0 or args.action_atol < 0.0:
        parser.error("pairing tolerances must be non-negative")
    inputs = {
        "top_side": args.top_side_summary.resolve(),
        "side": args.side_summary.resolve(),
        "cradle": args.cradle_summary.resolve(),
    }
    for path in (args.baseline_dataset, args.catalog, *inputs.values()):
        if not path.exists():
            parser.error(f"R14 input does not exist: {path}")

    root = Path(__file__).resolve().parent.parent
    output = args.output_root.resolve()
    output.mkdir(parents=True)
    manifest_path = output / "R14_WRIST_DATASET_BUILD.json"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "protocol": "pi05-r14-wrist-paired-dataset-build-v1",
        "status": "running",
        "baseline_dataset": str(args.baseline_dataset.resolve()),
        "policy_visual_modality": "rgbd_wrist",
        "source_summaries": {
            group: {"path": str(path), "sha256": _sha256(path)}
            for group, path in inputs.items()
        },
        "source_replay_counts": {"top_side": 2, "side": 1, "cradle": 1},
        "failed_rollouts_as_training_labels": False,
        "training_initialization": "fixed_pi05_base_not_upstream_adapter",
        "stages": [],
        "claim_boundary": "Dataset build and pairing audit only; no VLA capability is measured.",
    }
    _write_json(manifest_path, manifest)

    try:
        group_outputs: dict[str, dict[str, Path]] = {}
        for group, summary in inputs.items():
            config = _successful_config(summary, group=group)
            config_path = output / "configs" / f"{group}.json"
            _write_json(config_path, config)
            collection = output / "collections" / group
            _run(
                [
                    sys.executable,
                    str(root / "scripts/collect_mobile_suction_dataset_rocm.py"),
                    "--config",
                    str(config_path),
                    "--output",
                    str(collection),
                    "--backend",
                    args.backend,
                    "--wrist-rgbd",
                ],
                cwd=root,
                log_path=output / "logs" / f"collect-{group}.log",
            )
            residual = output / "residuals" / group
            _run(
                [
                    sys.executable,
                    str(root / "scripts/build_mobile_pi05_residual_dataset.py"),
                    "--source",
                    str(collection / "lerobot_dataset"),
                    "--output",
                    str(residual),
                    "--catalog",
                    str(args.catalog.resolve()),
                    "--collection-summary",
                    str(collection / "collection-summary.json"),
                ],
                cwd=root,
                log_path=output / "logs" / f"residual-{group}.log",
            )
            group_outputs[group] = {"collection": collection, "residual": residual}
            manifest["stages"].append(f"{group}_residual_completed")
            _write_json(manifest_path, manifest)

        merged = output / "merged-mode-neutral"
        _run(
            [
                sys.executable,
                str(root / "scripts/merge_mobile_pi05_residual_datasets.py"),
                "--source",
                str(group_outputs["top_side"]["residual"]),
                "--source",
                str(group_outputs["top_side"]["residual"]),
                "--source",
                str(group_outputs["side"]["residual"]),
                "--source",
                str(group_outputs["cradle"]["residual"]),
                "--output",
                str(merged),
                "--mode-neutral-task",
                MODE_NEUTRAL_TASK,
            ],
            cwd=root,
            log_path=output / "logs/merge.log",
        )
        manifest["stages"].append("weighted_merge_completed")
        _write_json(manifest_path, manifest)

        final_dataset = output / "pi05-r14-wrist-observable-language"
        _run(
            [
                sys.executable,
                str(root / "scripts/contextualize_mobile_pi05_dataset.py"),
                str(merged),
                str(final_dataset),
            ],
            cwd=root,
            log_path=output / "logs/contextualize.log",
        )
        pairing_path = output / "wrist-pairing-audit.json"
        _run(
            [
                sys.executable,
                str(root / "scripts/audit_mobile_pi05_visual_pairing.py"),
                str(args.baseline_dataset.resolve()),
                str(final_dataset),
                "--state-atol",
                str(args.state_atol),
                "--action-atol",
                str(args.action_atol),
                "--output",
                str(pairing_path),
            ],
            cwd=root,
            log_path=output / "logs/pairing.log",
        )
        residual_audit = output / "residual-dataset-audit.json"
        _run(
            [
                sys.executable,
                str(root / "scripts/audit_mobile_pi05_residual_dataset.py"),
                "--dataset-root",
                str(final_dataset),
                "--output",
                str(residual_audit),
                "--min-recovery-episodes",
                "7",
            ],
            cwd=root,
            log_path=output / "logs/residual-audit.log",
        )
        manifest.update(
            {
                "status": "passed",
                "stages": [
                    *manifest["stages"],
                    "contextualization_completed",
                    "single_factor_pairing_passed",
                    "residual_audit_passed",
                ],
                "final_dataset": str(final_dataset),
                "pairing_audit": str(pairing_path),
                "pairing_audit_sha256": _sha256(pairing_path),
                "residual_audit": str(residual_audit),
                "residual_audit_sha256": _sha256(residual_audit),
                "r14_training_allowed": True,
            }
        )
        _write_json(manifest_path, manifest)
    except Exception as exc:
        manifest.update(
            {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "r14_training_allowed": False,
            }
        )
        _write_json(manifest_path, manifest)
        raise

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

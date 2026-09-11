#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.grasp_scoring import (
    load_grasp_collection_activation_policy,
    load_grasp_split_protocol,
    sha256_file,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a frozen grasp-candidate collection split in isolated processes."
    )
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/catalog_v2.toml")
    parser.add_argument("--backend", choices=("cpu", "rocm"), default="rocm")
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--unlock-holdout",
        action="store_true",
        help="required to execute the frozen holdout split",
    )
    return parser.parse_args()


def planned_runs(
    protocol: Path,
    split: str,
    output_dir: Path,
) -> list[dict[str, Any]]:
    assignments = load_grasp_split_protocol(protocol)
    rows = [
        {
            "profile": profile,
            "episode": episode,
            "split": assigned_split,
            "output": str(output_dir / split / profile / f"{episode}.json"),
        }
        for (profile, episode), assigned_split in assignments.items()
        if assigned_split == split
    ]
    if not rows:
        raise ValueError(f"protocol contains no assignments for split {split}")
    return sorted(rows, key=lambda row: (str(row["profile"]), int(row["episode"])))


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validated_output(
    output: Path,
    row: Mapping[str, Any],
    *,
    backend: str,
    config: Path,
    max_candidates: int,
    repeats: int,
    planning_activation_policy: str,
) -> dict[str, Any]:
    payload = json.loads(output.read_text(encoding="utf-8"))
    if (
        str(payload.get("profile")) != str(row["profile"])
        or int(payload.get("episode", -1)) != int(row["episode"])
    ):
        raise ValueError(f"collection output does not match frozen run: {output}")
    if str(payload.get("backend")) != backend:
        raise ValueError(f"collection output backend does not match: {output}")
    if Path(str(payload.get("config", ""))).resolve() != config.resolve():
        raise ValueError(f"collection output config does not match: {output}")
    if int(payload.get("repeat_count", -1)) != repeats:
        raise ValueError(f"collection output repeat count is invalid: {output}")
    contract = payload.get("contract")
    if not isinstance(contract, Mapping):
        raise ValueError(f"collection output has no controller contract: {output}")
    if not bool(contract.get("controller_faithful")) or not bool(
        contract.get("fresh_scene_per_rollout")
    ):
        raise ValueError(f"collection output violates controller contract: {output}")
    observed_activation_policy = str(
        contract.get("planning_activation_policy", "reset-fallback")
    )
    expected_reset_gate = planning_activation_policy == "reset-fallback"
    if (
        not bool(contract.get("collision_checked_reset_enabled"))
        or observed_activation_policy != planning_activation_policy
        or bool(contract.get("reset_fallback_gate_enabled")) != expected_reset_gate
    ):
        raise ValueError(f"collection output violates reset contract: {output}")

    source_status = str(payload.get("status", ""))
    tested = payload.get("tested_candidate_ids")
    rollouts = payload.get("rollouts")
    ranked = payload.get("ranked_rollouts")
    if not all(isinstance(value, list) for value in (tested, rollouts, ranked)):
        raise ValueError(f"collection output has malformed rollout lists: {output}")
    if source_status == "complete":
        if not bool(contract.get("transport_contract_enabled")) or int(
            contract.get("max_grasp_retries", -1)
        ) != 0:
            raise ValueError(f"collection output violates transport contract: {output}")
        expected_rollouts = len(tested) * repeats
        tested_ids = [str(candidate_id) for candidate_id in tested]
        expected_keys = {
            (candidate_id, repeat)
            for candidate_id in tested_ids
            for repeat in range(repeats)
        }
        rollout_keys = {
            (str(rollout.get("candidate_id")), int(rollout.get("repeat", -1)))
            for rollout in rollouts
            if isinstance(rollout, Mapping)
        }
        ranked_keys = {
            (str(rollout.get("candidate_id")), int(rollout.get("repeat", -1)))
            for rollout in ranked
            if isinstance(rollout, Mapping)
        }
        if (
            not tested
            or len(tested_ids) > max_candidates
            or len(set(tested_ids)) != len(tested_ids)
            or len(rollouts) != expected_rollouts
            or len(ranked) != expected_rollouts
            or rollout_keys != expected_keys
            or ranked_keys != expected_keys
        ):
            raise ValueError(f"collection output is incomplete: {output}")
    elif source_status in {
        "skipped_inactive_reset_gate",
        "skipped_ineligible_geometry",
    }:
        if (
            bool(contract.get("reset_fallback_gate_satisfied"))
            or bool(contract.get("labels_generated"))
            or tested
            or rollouts
            or ranked
        ):
            raise ValueError(f"inactive-gate output contains labels: {output}")
    else:
        raise ValueError(
            f"collection output has unsupported status {source_status!r}: {output}"
        )
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    if min(args.max_candidates, args.repeats) < 1:
        raise ValueError("candidate and repeat budgets must be positive")
    if args.split == "holdout" and not args.unlock_holdout:
        raise PermissionError(
            "holdout collection is locked; pass --unlock-holdout only after model selection"
        )
    protocol = args.protocol.resolve()
    planning_activation_policy = load_grasp_collection_activation_policy(protocol)
    output_dir = args.output_dir.resolve()
    rows = planned_runs(protocol, args.split, output_dir)
    manifest_path = output_dir / args.split / "manifest.json"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "protocol": str(protocol),
        "protocol_sha256": sha256_file(protocol),
        "split": args.split,
        "backend": args.backend,
        "max_candidates": args.max_candidates,
        "repeats": args.repeats,
        "planning_activation_policy": planning_activation_policy,
        "dry_run": args.dry_run,
        "planned_episode_count": len(rows),
        "planned_max_rollouts": len(rows) * args.max_candidates * args.repeats,
        "runs": [],
    }
    labeler = PROJECT_ROOT / "scripts/diagnose_counterfactual_grasp_candidates.py"
    for row in rows:
        output = Path(str(row["output"]))
        command = [
            sys.executable,
            str(labeler),
            "--config",
            str(args.config.resolve()),
            "--profile",
            str(row["profile"]),
            "--episode",
            str(row["episode"]),
            "--backend",
            args.backend,
            "--all-candidates",
            "--max-candidates",
            str(args.max_candidates),
            "--repeats",
            str(args.repeats),
            "--inactive-gate",
            "skip",
            "--planning-activation",
            planning_activation_policy,
            "--output",
            str(output),
        ]
        record = {**row, "command": command, "status": "planned"}
        manifest["runs"].append(record)
        if args.dry_run:
            continue
        if output.exists():
            if not args.resume:
                raise FileExistsError(
                    f"collection output already exists: {output}; pass --resume to audit and skip"
                )
            payload = _validated_output(
                output,
                row,
                backend=args.backend,
                config=args.config,
                max_candidates=args.max_candidates,
                repeats=args.repeats,
                planning_activation_policy=planning_activation_policy,
            )
            source_status = str(payload["status"])
            record.update(
                {
                    "status": (
                        "skipped_inactive_gate"
                        if source_status.startswith("skipped_")
                        else "reused"
                    ),
                    "source_status": source_status,
                    "sha256": sha256_file(output),
                }
            )
            _write_manifest(manifest_path, manifest)
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        record["status"] = "running"
        _write_manifest(manifest_path, manifest)
        completed: subprocess.CompletedProcess[Any] | None = None
        accepted_cleanup_failure = False
        try:
            completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
            payload = _validated_output(
                output,
                row,
                backend=args.backend,
                config=args.config,
                max_candidates=args.max_candidates,
                repeats=args.repeats,
                planning_activation_policy=planning_activation_policy,
            )
            if completed.returncode != 0:
                accepted_cleanup_failure = completed.returncode in {
                    128 + signal.SIGSEGV,
                    -signal.SIGSEGV,
                }
                if not accepted_cleanup_failure:
                    raise subprocess.CalledProcessError(completed.returncode, command)
        except BaseException:
            record["status"] = "failed"
            if completed is not None:
                record["child_returncode"] = completed.returncode
            _write_manifest(manifest_path, manifest)
            raise
        source_status = str(payload["status"])
        record.update(
            {
                "status": (
                    "skipped_inactive_gate"
                    if source_status.startswith("skipped_")
                    else "complete"
                ),
                "source_status": source_status,
                "child_returncode": completed.returncode,
                "accepted_cleanup_failure": accepted_cleanup_failure,
                "sha256": sha256_file(output),
            }
        )
        _write_manifest(manifest_path, manifest)
    if args.dry_run:
        return manifest
    manifest["complete_episode_count"] = sum(
        row["status"] in {"complete", "reused"} for row in manifest["runs"]
    )
    manifest["skipped_inactive_gate_count"] = sum(
        row["status"] == "skipped_inactive_gate" for row in manifest["runs"]
    )
    manifest["processed_episode_count"] = (
        manifest["complete_episode_count"] + manifest["skipped_inactive_gate_count"]
    )
    _write_manifest(manifest_path, manifest)
    return manifest


def main() -> int:
    args = parse_args()
    payload = run(args)
    print(
        json.dumps(
            {
                "split": payload["split"],
                "dry_run": payload["dry_run"],
                "planned_episode_count": payload["planned_episode_count"],
                "planned_max_rollouts": payload["planned_max_rollouts"],
                "planning_activation_policy": payload[
                    "planning_activation_policy"
                ],
                "manifest": str(args.output_dir.resolve() / args.split / "manifest.json"),
                "runs": payload["runs"] if args.dry_run else None,
            },
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail closed unless a pure-PI0.5 LIBERO wiring run is complete and coherent."""

from __future__ import annotations

import argparse
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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def gate_wiring(
    run_root: Path,
    *,
    expected_episodes: int,
    minimum_successes: int,
) -> dict[str, Any]:
    if expected_episodes not in (1, 3):
        raise ValueError("expected_episodes must be 1 or 3")
    if not 0 <= minimum_successes <= expected_episodes:
        raise ValueError("minimum_successes is outside the episode range")

    contract_path = run_root / "run-contract.json"
    summary_path = run_root / "run-summary.json"
    eval_info_path = run_root / "eval" / "eval_info.json"
    missing = [path for path in (contract_path, summary_path, eval_info_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing wiring artifacts: {missing}")

    contract = load_json(contract_path)
    summary = load_json(summary_path)
    eval_info = load_json(eval_info_path)
    scope = contract.get("run_scope") or {}
    errors: list[str] = []
    if contract.get("policy_classification") != "pure_pi05_vla":
        errors.append("not_pure_pi05_vla")
    for field in ("expert_reference_allowed", "expert_fallback_allowed", "parcel_harness_allowed"):
        if contract.get(field) is not False:
            errors.append(f"{field}_not_false")
    if contract.get("phase") != "wiring" or scope.get("score_eligible") is not False:
        errors.append("not_non_scoring_wiring")
    if scope.get("episodes_per_task") != expected_episodes:
        errors.append("contract_episode_count_mismatch")
    if len(scope.get("suites") or []) != 1 or len(scope.get("task_ids") or []) != 1:
        errors.append("wiring_scope_not_single_task")
    if summary.get("returncode") != 0:
        errors.append("runner_returncode_nonzero")

    per_task = eval_info.get("per_task") or []
    if len(per_task) != 1:
        errors.append("eval_task_count_mismatch")
        successes: list[bool] = []
    else:
        task = per_task[0]
        successes = [bool(value) for value in task.get("metrics", {}).get("successes", [])]
        if task.get("task_group") != scope.get("suites", [None])[0]:
            errors.append("eval_suite_mismatch")
        if int(task.get("task_id", -1)) != int(scope.get("task_ids", [-1])[0]):
            errors.append("eval_task_id_mismatch")
    if len(successes) != expected_episodes:
        errors.append("eval_episode_count_mismatch")
    success_count = sum(successes)
    if success_count < minimum_successes:
        errors.append("success_floor_not_met")
    if int((eval_info.get("overall") or {}).get("n_episodes", -1)) != expected_episodes:
        errors.append("overall_episode_count_mismatch")

    return {
        "schema_version": 1,
        "protocol": "pi05-libero-pure-vla-wiring-gate-v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "run_root": str(run_root.resolve()),
        "expected_episodes": expected_episodes,
        "minimum_successes": minimum_successes,
        "successes": success_count,
        "outcomes": successes,
        "contract_sha256": sha256_file(contract_path),
        "eval_info_sha256": sha256_file(eval_info_path),
        "claim_boundary": "Development wiring only; never a benchmark or confirmation score.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--expected-episodes", type=int, choices=(1, 3), required=True)
    parser.add_argument("--minimum-successes", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = gate_wiring(
        args.run_root,
        expected_episodes=args.expected_episodes,
        minimum_successes=args.minimum_successes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

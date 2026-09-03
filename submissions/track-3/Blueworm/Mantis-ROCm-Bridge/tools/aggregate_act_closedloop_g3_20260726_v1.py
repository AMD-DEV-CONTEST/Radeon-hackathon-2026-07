#!/usr/bin/env python3
"""Fail-closed aggregate publisher for the frozen AMD ACT G3 seed set.

The episode runner intentionally publishes large, immutable receipts.  This
tool verifies every episode manifest and a compact, receipt-hash-bound audit
sidecar before evaluating the exact seeds 101..110.  It never loads all dense
episode telemetry into aggregate memory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

from mantis_rocm_bridge.act_closedloop_g3 import (
    G3_SEEDS,
    aggregate_receipt_claim_boundary,
    build_failure_taxonomy,
    evaluate_g3_promotion,
    validate_config,
)


PASS_RC = 0
FAIL_RC = 2
BLOCK_RC = 3


class AggregateError(RuntimeError):
    """An evidence, identity, or protocol defect that blocks aggregation."""


def _reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AggregateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise AggregateError(f"non-finite JSON constant: {value}")


def _assert_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise AggregateError(f"non-finite number at {path}")
    if isinstance(value, dict):
        for key, child in value.items():
            _assert_finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_finite(child, f"{path}[{index}]")


def load_json(path: Path) -> Any:
    try:
        value = json.loads(
            path.read_text(),
            object_pairs_hook=_reject_duplicate,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AggregateError(f"invalid JSON {path}: {exc}") from exc
    _assert_finite(value)
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(directory: Path, manifest_name: str) -> str:
    manifest = directory / manifest_name
    if not manifest.is_file():
        raise AggregateError(f"missing manifest: {manifest}")
    seen: set[str] = set()
    for line_number, raw in enumerate(manifest.read_text().splitlines(), 1):
        if not raw:
            continue
        parts = raw.split("  ", 1)
        if len(parts) != 2:
            raise AggregateError(
                f"invalid manifest line {manifest}:{line_number}"
            )
        expected, name = parts
        if (
            len(expected) != 64
            or any(char not in "0123456789abcdef" for char in expected)
            or not name
        ):
            raise AggregateError(
                f"invalid manifest entry {manifest}:{line_number}"
            )
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name in seen:
            raise AggregateError(
                f"unsafe or duplicate manifest path {manifest}:{line_number}"
            )
        seen.add(name)
        target = directory / relative
        if not target.is_file():
            raise AggregateError(f"manifest target missing: {target}")
        actual = sha256_file(target)
        if actual != expected:
            raise AggregateError(
                f"manifest digest mismatch: {target} {actual} != {expected}"
            )
    if not seen:
        raise AggregateError(f"empty manifest: {manifest}")
    return sha256_file(manifest)


def write_text_fresh(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o644)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
    except Exception:
        raise


def write_json_fresh(path: Path, value: Any) -> None:
    write_text_fresh(
        path,
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )


def copy_fresh(source: Path, target: Path) -> None:
    if not source.is_file():
        raise AggregateError(f"missing aggregate evidence input: {source}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, 0o644)
    try:
        with source.open("rb") as src, os.fdopen(descriptor, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
    except Exception:
        raise


def _episode_paths(
    seed: int,
    *,
    seed101_dir: Path,
    batch_root: Path,
    audit_root: Path,
) -> tuple[Path, Path]:
    if seed == 101:
        return seed101_dir, seed101_dir / "semantic_audit.json"
    return batch_root / f"seed{seed}", audit_root / f"seed{seed}.audit.json"


def _validate_episode_audit(
    seed: int,
    episode_dir: Path,
    audit_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cli_manifest_sha = verify_manifest(episode_dir, "SHA256SUMS")
    if seed == 101:
        verify_manifest(episode_dir, "final_evidence.SHA256SUMS")
        admission = (episode_dir / "seed101_batch_admission.status").read_text()
        if admission.strip() != "PASS":
            raise AggregateError("seed 101 batch admission is not PASS")

    if not audit_path.is_file():
        raise AggregateError(f"missing compact audit: {audit_path}")
    audit = load_json(audit_path)
    if not isinstance(audit, dict):
        raise AggregateError(f"compact audit is not an object: {audit_path}")

    receipt_path = episode_dir / "receipt.json"
    receipt_sha = sha256_file(receipt_path)
    manifest_sha = sha256_file(episode_dir / "SHA256SUMS")
    if seed != 101:
        if audit.get("receipt_sha256") != receipt_sha:
            raise AggregateError(f"seed {seed} receipt hash binding mismatch")
        if audit.get("cli_manifest_sha256") != manifest_sha:
            raise AggregateError(f"seed {seed} manifest hash binding mismatch")
        child_exit = audit.get("child_exit_code")
        output_exit = audit.get("output_exit_code")
        expected_exit = audit.get("expected_exit_code")
        if not (
            isinstance(child_exit, int)
            and child_exit == output_exit
            and child_exit == expected_exit
        ):
            raise AggregateError(f"seed {seed} child/output exit binding mismatch")

    observed_seed = int(audit.get("seed", -1))
    if observed_seed != seed:
        raise AggregateError(
            f"seed identity mismatch: expected {seed}, got {observed_seed}"
        )
    if audit.get("terminal") is not True:
        raise AggregateError(f"seed {seed} lacks a terminal receipt")
    if audit.get("infrastructure_failure") is not False:
        raise AggregateError(f"seed {seed} has an infrastructure failure")
    terminal_reason = str(audit.get("terminal_reason", ""))
    if not terminal_reason or terminal_reason == "runtime_error":
        raise AggregateError(
            f"seed {seed} has blocking terminal reason {terminal_reason!r}"
        )
    identity_issues = audit.get("runtime_identity_issues", [])
    if identity_issues:
        raise AggregateError(f"seed {seed} runtime identity drift: {identity_issues}")

    exit_code_path = episode_dir / "exit_code.txt"
    try:
        exit_code = int(exit_code_path.read_text().strip())
    except (OSError, ValueError) as exc:
        raise AggregateError(f"invalid seed {seed} exit_code.txt") from exc
    task_success = bool(audit.get("task_success"))
    expected_exit = 0 if task_success else 2
    if exit_code != expected_exit:
        raise AggregateError(
            f"seed {seed} exit/task mismatch: {exit_code} != {expected_exit}"
        )

    safety_count = int(audit.get("safety_failure_count", 0))
    has_safety = bool(audit.get("has_safety_failure", safety_count > 0))
    if has_safety != (safety_count > 0):
        raise AggregateError(f"seed {seed} safety count/flag mismatch")
    policy_count = int(audit.get("policy_step_count", 0))
    evaluator_count = int(audit.get("strict_evaluator_row_count", 0))
    if policy_count <= 0 or evaluator_count != policy_count:
        raise AggregateError(
            f"seed {seed} invalid policy/evaluator coverage "
            f"{policy_count}/{evaluator_count}"
        )
    started = load_json(episode_dir / "started.json")
    if not isinstance(started, dict):
        raise AggregateError(f"seed {seed} started.json is not an object")
    if int(started.get("seed", -1)) != seed:
        raise AggregateError(f"seed {seed} started.json identity mismatch")
    input_hashes = started.get("input_hashes")
    if not isinstance(input_hashes, dict) or not input_hashes:
        raise AggregateError(f"seed {seed} missing started input hashes")
    label = str(
        audit.get(
            "failure_taxonomy_label",
            "task_success" if task_success else terminal_reason,
        )
    )
    receipt_summary = {
        "seed": seed,
        "task_success": task_success,
        "terminal": True,
        "terminal_reason": terminal_reason,
        "infrastructure_failure": False,
        "has_safety_failure": has_safety,
        "safety_failure_count": safety_count,
        "safety_failure_reasons": list(audit.get("safety_failure_reasons", [])),
        "failure_taxonomy_label": label,
        "runtime_identity": {"identity_issues": []},
    }
    inventory = {
        "seed": seed,
        "episode_dir": str(episode_dir),
        "audit_path": str(audit_path),
        "task_success": task_success,
        "terminal_reason": terminal_reason,
        "safety_failure_count": safety_count,
        "exit_code": exit_code,
        "receipt_sha256": receipt_sha,
        "cli_manifest_sha256": cli_manifest_sha,
        "audit_sha256": sha256_file(audit_path),
        "started_sha256": sha256_file(episode_dir / "started.json"),
        "started_gate_id": started.get("gate_id"),
        "started_input_hashes": input_hashes,
    }
    return receipt_summary, inventory


def _validate_exact_order(receipts: list[dict[str, Any]]) -> None:
    observed = [int(row.get("seed", -1)) for row in receipts]
    expected = list(G3_SEEDS)
    if observed != expected:
        raise AggregateError(
            f"exact frozen seed order required: {observed} != {expected}"
        )


def _hash_inventory(paths: Iterable[Path]) -> str:
    rows = []
    for path in sorted(paths, key=lambda item: str(item)):
        if not path.is_file():
            raise AggregateError(f"missing inventory file: {path}")
        rows.append(f"{sha256_file(path)}  {path}\n")
    return "".join(rows)


def _source_inventory(project: Path, this_script: Path) -> str:
    return _hash_inventory(
        [
            project / "configs/act-closedloop-g3-v1.json",
            project / "src/mantis_rocm_bridge/act_closedloop_g3.py",
            project / "tools/run_genesis_act_closedloop_g3.py",
            project / "tests/test_act_closedloop_g3.py",
            this_script,
        ]
    )


def _checkpoint_inventory(checkpoint: Path) -> str:
    model_root = checkpoint / "pretrained_model"
    files = [path for path in model_root.rglob("*") if path.is_file()]
    if not files:
        raise AggregateError(f"empty checkpoint model root: {model_root}")
    return _hash_inventory(files)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gate", type=Path)
    parser.add_argument("--task-config", type=Path)
    parser.add_argument("--seed101-dir", type=Path)
    parser.add_argument("--batch-root", type=Path)
    parser.add_argument("--audit-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    for name in (
        "started-at-file",
        "finished-at-file",
        "gpu-before",
        "gpu-during",
        "gpu-after",
        "kfd-before",
        "kfd-during",
        "kfd-after",
    ):
        parser.add_argument(f"--{name}", dest=name.replace("-", "_"), type=Path)
    return parser.parse_args(argv)


def _required_args(args: argparse.Namespace) -> None:
    missing = [
        name
        for name, value in vars(args).items()
        if name != "self_test" and value is None
    ]
    if missing:
        raise AggregateError(f"missing required arguments: {missing}")


def _publish_manifest(output_dir: Path) -> None:
    rows = []
    for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if path.name == "final_evidence.SHA256SUMS" or not path.is_file():
            continue
        rows.append(f"{sha256_file(path)}  {path.name}\n")
    write_text_fresh(output_dir / "final_evidence.SHA256SUMS", "".join(rows))
    verify_manifest(output_dir, "final_evidence.SHA256SUMS")


def _self_test() -> int:
    candidates = []
    configured = os.environ.get("MANTIS_G3_PROJECT")
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            Path(__file__).resolve().parents[1],
            Path(
                "/workspace/"
                "mantis_rocm_bridge_project_v16_act_closedloop_g3_"
                "gripper_contract_003_20260726_v1"
            ),
        ]
    )
    project = next(
        (
            candidate
            for candidate in candidates
            if (candidate / "configs/act-closedloop-g3-v1.json").is_file()
        ),
        None,
    )
    if project is None:
        raise AggregateError(
            "self-test cannot locate the frozen G3 project; set MANTIS_G3_PROJECT"
        )
    gate = load_json(project / "configs/act-closedloop-g3-v1.json")
    validate_config(gate)

    def rows(successes: int, safety_seed: int | None = None) -> list[dict[str, Any]]:
        result = []
        for index, seed in enumerate(G3_SEEDS):
            success = index < successes
            safety = seed == safety_seed
            result.append(
                {
                    "seed": seed,
                    "task_success": success,
                    "terminal": True,
                    "terminal_reason": "task_success" if success else "timeout",
                    "has_safety_failure": safety,
                    "safety_failure_count": int(safety),
                    "failure_taxonomy_label": (
                        "collision_safety"
                        if safety
                        else ("task_success" if success else "timeout")
                    ),
                }
            )
        return result

    passing = rows(6)
    _validate_exact_order(passing)
    assert evaluate_g3_promotion(passing, gate)["g3_pass"] is True
    failing = rows(5)
    _validate_exact_order(failing)
    fail_decision = evaluate_g3_promotion(failing, gate)
    assert fail_decision["g3_pass"] is False
    assert fail_decision["batch_complete"] is True
    safety = rows(10, safety_seed=110)
    assert evaluate_g3_promotion(safety, gate)["g3_pass"] is False
    drifted = rows(6)
    drifted[0], drifted[1] = drifted[1], drifted[0]
    try:
        _validate_exact_order(drifted)
    except AggregateError:
        pass
    else:
        raise AssertionError("seed-order drift was not blocked")
    print("SELF_TEST_PASS pass/fail/safety/order")
    return 0


def run(args: argparse.Namespace) -> int:
    _required_args(args)
    output_dir: Path = args.output_dir
    try:
        os.mkdir(output_dir, 0o755)
    except FileExistsError as exc:
        raise AggregateError(f"refusing existing aggregate directory: {output_dir}") from exc

    errors: list[str] = []
    receipts: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    gate: dict[str, Any] = {}
    task: dict[str, Any] = {}
    try:
        gate = load_json(args.gate)
        task = load_json(args.task_config)
        validate_config(gate)
        for seed in G3_SEEDS:
            episode_dir, audit_path = _episode_paths(
                seed,
                seed101_dir=args.seed101_dir,
                batch_root=args.batch_root,
                audit_root=args.audit_root,
            )
            receipt, row = _validate_episode_audit(seed, episode_dir, audit_path)
            receipts.append(receipt)
            inventory.append(row)
        _validate_exact_order(receipts)
        baseline_gate_id = inventory[0]["started_gate_id"]
        baseline_input_hashes = inventory[0]["started_input_hashes"]
        for row in inventory[1:]:
            if row["started_gate_id"] != baseline_gate_id:
                raise AggregateError(
                    f"seed {row['seed']} started gate identity drift"
                )
            if row["started_input_hashes"] != baseline_input_hashes:
                raise AggregateError(
                    f"seed {row['seed']} immutable input hash drift"
                )
    except Exception as exc:  # fail closed and preserve a BLOCK aggregate
        errors.append(f"{type(exc).__name__}:{exc}")

    status = "BLOCK"
    exit_code = BLOCK_RC
    promotion: dict[str, Any] = {
        "g3_pass": False,
        "blocked": True,
        "batch_complete": False,
        "observed_episodes": len(receipts),
        "expected_seeds": list(G3_SEEDS),
        "observed_seeds": [row["seed"] for row in receipts],
    }
    taxonomy: dict[str, Any] = {
        "taxonomy": [],
        "counts": {},
        "safety_failure_episodes": [],
        "task_success_count": sum(bool(row.get("task_success")) for row in receipts),
        "total_episodes": len(receipts),
    }
    if not errors:
        promotion = evaluate_g3_promotion(receipts, gate)
        taxonomy_values = task.get("evaluation", {}).get("failure_taxonomy", [])
        if not isinstance(taxonomy_values, list) or not taxonomy_values:
            errors.append("AggregateError:missing frozen failure taxonomy")
        else:
            taxonomy = build_failure_taxonomy(receipts, taxonomy=taxonomy_values)
            if promotion["g3_pass"]:
                status, exit_code = "PASS", PASS_RC
            elif promotion["batch_complete"] and promotion["no_seed_replacement"]:
                status, exit_code = "FAIL", FAIL_RC

    if errors:
        status, exit_code = "BLOCK", BLOCK_RC

    try:
        source_text = _source_inventory(args.project, Path(__file__).resolve())
        checkpoint_text = _checkpoint_inventory(args.checkpoint)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}:{exc}")
        status, exit_code = "BLOCK", BLOCK_RC
        source_text = ""
        checkpoint_text = ""

    summary = {
        "schema_version": 1,
        "gate_id": gate.get("gate_id"),
        "task_id": gate.get("task_id"),
        "protocol": gate.get("protocol"),
        "phase": gate.get("phase"),
        "status": status,
        "exit_code": exit_code,
        "promotion": promotion,
        "episode_summaries": receipts,
        "claim_boundary": (
            aggregate_receipt_claim_boundary(gate, bool(promotion.get("g3_pass")))
            if gate
            else "BLOCK aggregate: no performance claim."
        ),
        "errors": errors,
    }
    write_json_fresh(output_dir / "g3_summary.json", summary)
    write_json_fresh(output_dir / "failure_taxonomy.json", taxonomy)
    write_json_fresh(
        output_dir / "diagnostic.json",
        {
            "status": status,
            "errors": errors,
            "verified_episode_count": len(receipts),
            "expected_seeds": list(G3_SEEDS),
        },
    )
    write_text_fresh(
        output_dir / "episode_inventory.txt",
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in inventory),
    )
    write_text_fresh(output_dir / "source_files.txt", source_text)
    write_text_fresh(output_dir / "checkpoint_files.txt", checkpoint_text)
    write_text_fresh(output_dir / "status", status + "\n")
    write_text_fresh(output_dir / "exit_code.txt", f"{exit_code}\n")
    copy_fresh(args.started_at_file, output_dir / "started_at_utc.txt")
    copy_fresh(args.finished_at_file, output_dir / "finished_at_utc.txt")
    for source, name in (
        (args.gpu_before, "gpu_before.txt"),
        (args.gpu_during, "gpu_during.txt"),
        (args.gpu_after, "gpu_after.txt"),
        (args.kfd_before, "kfd_before.txt"),
        (args.kfd_during, "kfd_during.txt"),
        (args.kfd_after, "kfd_after.txt"),
    ):
        copy_fresh(source, output_dir / name)
    _publish_manifest(output_dir)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.self_test:
        return _self_test()
    try:
        return run(args)
    except AggregateError as exc:
        print(f"G3_AGGREGATE_BLOCK:{exc}", file=sys.stderr)
        return BLOCK_RC


if __name__ == "__main__":
    sys.exit(main())

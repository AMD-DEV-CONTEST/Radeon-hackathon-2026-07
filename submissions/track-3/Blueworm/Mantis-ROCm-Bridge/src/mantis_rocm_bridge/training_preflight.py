"""Strict ACT-on-ROCm training preflight and reproducible command assembly."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .amd_persistence import validate_durable_output_path
from .contracts import ContractError, load_json


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContractError(f"cannot hash required file {path}: {exc}") from exc
    return digest.hexdigest()


def _check_training_contract(
    training: dict[str, Any],
    interface: dict[str, Any],
    task: dict[str, Any],
) -> None:
    if training.get("schema_version") != 1:
        raise ContractError("ACT ROCm contract schema_version must be 1")
    if training.get("framework") != "LeRobot" or training.get("policy_type") != "act":
        raise ContractError("baseline must use the LeRobot ACT policy")
    if training.get("policy_device_api") != "cuda":
        raise ContractError("ROCm PyTorch must be addressed through the cuda device API")
    if training.get("robot_type") != interface.get("robot_type"):
        raise ContractError("training and interface robot_type values disagree")
    if training.get("upstream_revision") != interface.get("upstream_revision"):
        raise ContractError("training and Mantis interface upstream revisions disagree")
    if training.get("task_id") != task.get("task_id"):
        raise ContractError("training and task contract task_id values disagree")
    policy = training.get("policy")
    if not isinstance(policy, dict):
        raise ContractError("training policy must be an object")
    if policy.get("normalization") != "MEAN_STD":
        raise ContractError("ACT baseline must use recomputed Mantis mean/std statistics")
    for field in ("chunk_size", "n_action_steps", "n_obs_steps"):
        if not isinstance(policy.get(field), int) or policy[field] <= 0:
            raise ContractError(f"training policy.{field} must be a positive integer")
    if policy.get("push_to_hub") is not False:
        raise ContractError(
            "ACT ROCm contract must set policy.push_to_hub=false "
            "(LeRobot 0.4.4 requires policy.repo_id when push_to_hub is enabled)"
        )
    for field in ("steps", "batch_size", "num_workers", "save_freq", "eval_freq", "log_freq"):
        value = training.get(field)
        if not isinstance(value, int) or value <= 0:
            raise ContractError(f"training {field} must be a positive integer")
    if not isinstance(training.get("seed"), int) or training["seed"] < 0:
        raise ContractError("training seed must be a non-negative integer")


def _dataset_checks(
    dataset_root: Path,
    dataset_receipt: dict[str, Any],
    interface: dict[str, Any],
    interface_path: Path,
) -> dict[str, bool]:
    info_path = dataset_root / "meta" / "info.json"
    stats_path = dataset_root / "meta" / "stats.json"
    files_present = info_path.is_file() and stats_path.is_file()
    checks = {
        "dataset_metadata_gate_pass": dataset_receipt.get("dataset_metadata_gate_pass") is True,
        "dataset_act_ready": dataset_receipt.get("policy_ready", {}).get("act") is True,
        "dataset_interface_match": (
            dataset_receipt.get("interface_id") == interface.get("interface_id")
            and dataset_receipt.get("upstream_revision") == interface.get("upstream_revision")
        ),
        "dataset_contract_hash_match": (
            dataset_receipt.get("contract_sha256") == _sha256(interface_path)
        ),
        "dataset_metadata_files_present": files_present,
        "dataset_metadata_hashes_match": False,
    }
    if files_present:
        checks["dataset_metadata_hashes_match"] = (
            dataset_receipt.get("info_sha256") == _sha256(info_path)
            and dataset_receipt.get("stats_sha256") == _sha256(stats_path)
        )
    return checks


def _rocm_checks(rocm_receipt: dict[str, Any]) -> dict[str, bool]:
    torch_receipt = rocm_receipt.get("torch", {})
    if not isinstance(torch_receipt, dict):
        torch_receipt = {}
    return {
        "strict_rocm_runtime": rocm_receipt.get("strict_rocm_pass") is True,
        "torch_hip_build": bool(torch_receipt.get("hip_version")),
        "torch_cuda_api_available": torch_receipt.get("cuda_api_available") is True,
        "amd_device_visible": int(torch_receipt.get("device_count", 0)) > 0,
    }


def _dense_audit_checks(
    dense_receipt: dict[str, Any] | None,
    dataset_receipt: dict[str, Any],
    task: dict[str, Any],
) -> dict[str, bool]:
    if dense_receipt is None:
        return {
            "dense_demonstration_gate_pass": False,
            "dense_audit_dataset_match": False,
            "dense_audit_task_match": False,
        }
    return {
        "dense_demonstration_gate_pass": (
            dense_receipt.get("dense_demonstration_gate_pass") is True
        ),
        "dense_audit_dataset_match": (
            dense_receipt.get("info_sha256") == dataset_receipt.get("info_sha256")
            and dense_receipt.get("stats_sha256") == dataset_receipt.get("stats_sha256")
        ),
        "dense_audit_task_match": (
            dense_receipt.get("task_id") == task.get("task_id")
            and dense_receipt.get("protocol") == task.get("protocol_version")
        ),
    }


def _scripted_protocol_matches(
    scripted_receipt: dict[str, Any],
    task: dict[str, Any],
) -> bool:
    """True if the scripted receipt protocol matches the task contract.

    The legacy normalized schema carries ``protocol``; the canonical generator
    schema carries ``protocol_version``. Accept either against the task's
    ``protocol_version``.
    """
    expected = task.get("protocol_version")
    return (
        scripted_receipt.get("protocol_version") == expected
        or scripted_receipt.get("protocol") == expected
    )


def _is_canonical_generator_receipt(scripted_receipt: dict[str, Any]) -> bool:
    """True if the receipt is the canonical generator schema, not legacy."""

    return any(
        key in scripted_receipt
        for key in ("generation_mode", "strict_stability_rows", "scripted_g1_pass")
    )


def _strict_row_is_clean(row: Any) -> bool:
    """Require the underlying strict safety and physics checks to pass."""

    if not isinstance(row, dict):
        return False
    strict = row.get("strict")
    if not isinstance(strict, dict) or strict.get("frame_success") is not True:
        return False
    checks = strict.get("checks")
    if not isinstance(checks, dict):
        return False
    return (
        checks.get("no_safety_failure") is True
        and checks.get("no_physics_divergence") is True
    )


def _canonical_g1_success(
    scripted_receipt: dict[str, Any],
    task: dict[str, Any],
) -> bool:
    """Fail-closed success gate for the canonical generator receipt."""

    required = task.get("success_stable_frames")
    if (
        not isinstance(required, int)
        or isinstance(required, bool)
        or required <= 0
    ):
        return False
    if scripted_receipt.get("generation_mode") != "online":
        return False
    if scripted_receipt.get("scripted_g1_pass") is not True:
        return False
    if scripted_receipt.get("g1_claim") is not True:
        return False
    if scripted_receipt.get("episode_success_claim") is not True:
        return False
    rows = scripted_receipt.get("strict_stability_rows")
    if not isinstance(rows, list) or len(rows) < required:
        return False
    if any(not _strict_row_is_clean(row) for row in rows[-required:]):
        return False
    final_consecutive = rows[-1].get("consecutive_success_frames")
    return (
        isinstance(final_consecutive, int)
        and not isinstance(final_consecutive, bool)
        and final_consecutive >= required
    )


def _canonical_g1_safety(scripted_receipt: dict[str, Any]) -> bool:
    """Canonical safety requires an explicitly empty failure list."""

    failures = scripted_receipt.get("safety_failures")
    return isinstance(failures, list) and not failures


def _scripted_g1_checks(
    scripted_receipt: dict[str, Any] | None,
    task: dict[str, Any],
) -> dict[str, bool]:
    if scripted_receipt is None:
        return {
            "scripted_g1_success": False,
            "scripted_g1_contract_match": False,
            "scripted_g1_safety_pass": False,
        }
    if _is_canonical_generator_receipt(scripted_receipt):
        return {
            "scripted_g1_success": _canonical_g1_success(scripted_receipt, task),
            "scripted_g1_contract_match": (
                scripted_receipt.get("task_id") == task.get("task_id")
                and _scripted_protocol_matches(scripted_receipt, task)
            ),
            "scripted_g1_safety_pass": _canonical_g1_safety(scripted_receipt),
        }
    return {
        "scripted_g1_success": (
            scripted_receipt.get("success") is True
            and scripted_receipt.get("g1_claim") is True
        ),
        "scripted_g1_contract_match": (
            scripted_receipt.get("task_id") == task.get("task_id")
            and _scripted_protocol_matches(scripted_receipt, task)
        ),
        "scripted_g1_safety_pass": (
            scripted_receipt.get("safety_failures") == 0
            and scripted_receipt.get("physics_divergence") is False
        ),
    }


def build_act_rocm_preflight(
    *,
    dataset_root: Path,
    dataset_repo_id: str,
    output_dir: Path,
    training_contract_path: Path,
    interface_contract_path: Path,
    task_contract_path: Path,
    dataset_receipt: dict[str, Any],
    rocm_receipt: dict[str, Any],
    dense_receipt: dict[str, Any] | None = None,
    scripted_g1_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a non-executing training receipt and exact LeRobot argv."""

    if not isinstance(dataset_repo_id, str) or not dataset_repo_id.strip():
        raise ContractError("dataset_repo_id must be a non-empty string")
    dataset_root = dataset_root.resolve()
    output_dir = output_dir.resolve()
    training_contract_path = training_contract_path.resolve()
    interface_contract_path = interface_contract_path.resolve()
    task_contract_path = task_contract_path.resolve()

    training = load_json(training_contract_path)
    interface = load_json(interface_contract_path)
    task = load_json(task_contract_path)
    _check_training_contract(training, interface, task)

    checks: dict[str, bool] = {}
    checks.update(_dataset_checks(dataset_root, dataset_receipt, interface, interface_contract_path))
    checks.update(_rocm_checks(rocm_receipt))
    checks.update(_dense_audit_checks(dense_receipt, dataset_receipt, task))
    checks.update(_scripted_g1_checks(scripted_g1_receipt, task))
    checks["fresh_output_directory"] = not output_dir.exists()
    persistence_aware = training.get("persistence_layout_contract") is not None
    if persistence_aware:
        try:
            validate_durable_output_path(
                dataset_root.as_posix(), label="training dataset_root"
            )
            checks["dataset_under_persistence_root"] = True
        except ContractError:
            checks["dataset_under_persistence_root"] = False
        try:
            validate_durable_output_path(
                output_dir.as_posix(), label="training output_dir"
            )
            checks["output_under_persistence_root"] = True
        except ContractError:
            checks["output_under_persistence_root"] = False
        checks["persistence_contract_reference"] = (
            training.get("persistence_layout_contract")
            == "configs/amd-persistence-layout-v2.json"
        )
        checks["training_contract_execution_authorized"] = (
            training.get("execution_authorized") is True
        )

    command_contract_checks = {
        name: value
        for name, value in checks.items()
        if name
        not in {
            "dense_demonstration_gate_pass",
            "dense_audit_dataset_match",
            "dense_audit_task_match",
            "scripted_g1_success",
            "scripted_g1_contract_match",
            "scripted_g1_safety_pass",
        }
    }
    command_contract_ready = all(command_contract_checks.values())
    training_authorized = bool(checks) and all(checks.values())
    policy = training["policy"]
    argv = [
        "lerobot-train",
        f"--dataset.repo_id={dataset_repo_id}",
        f"--dataset.root={dataset_root}",
        "--policy.type=act",
        "--policy.device=cuda",
        f"--output_dir={output_dir}",
        f"--job_name={training['training_id']}",
        f"--seed={training['seed']}",
        f"--steps={training['steps']}",
        f"--batch_size={training['batch_size']}",
        f"--num_workers={training['num_workers']}",
        f"--save_freq={training['save_freq']}",
        f"--eval_freq={training['eval_freq']}",
        f"--log_freq={training['log_freq']}",
        f"--save_checkpoint={str(training['save_checkpoint']).lower()}",
        f"--wandb.enable={str(training['wandb_enabled']).lower()}",
        f"--policy.chunk_size={policy['chunk_size']}",
        f"--policy.n_action_steps={policy['n_action_steps']}",
        f"--policy.n_obs_steps={policy['n_obs_steps']}",
        "--policy.push_to_hub=false",
    ]
    return {
        "schema_version": 1,
        "training_id": training["training_id"],
        "task_id": task["task_id"],
        "interface_id": interface["interface_id"],
        "upstream_revision": training["upstream_revision"],
        "dataset_repo_id": dataset_repo_id,
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "checks": checks,
        "command_contract_ready": command_contract_ready,
        "training_authorized": training_authorized,
        "argv": argv,
        "policy_device_semantics": training["policy_device_semantics"],
        "training_contract_sha256": _sha256(training_contract_path),
        "interface_contract_sha256": _sha256(interface_contract_path),
        "task_contract_sha256": _sha256(task_contract_path),
        "claim_boundary": training["claim_boundary"],
    }

"""Fail-closed path contracts for the official AMD persistence boundary.

This module validates local contracts only. It never creates directories,
migrates data, connects to a cloud worker, or authorizes a GPU workload.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .contracts import ContractError


PERSISTENT_ROOT = "/workspace/persistent"
RESOLVED_MOUNT_ROOT = "/persistent"
PROJECT_ROOT = "/workspace/persistent/mantis-track3"
PERSISTENCE_CONTRACT_PATH = "configs/amd-persistence-layout-v2.json"

EXPECTED_DURABLE_DIRECTORIES = {
    "virtual_environment": f"{PROJECT_ROOT}/envs/rdna",
    "project_source": f"{PROJECT_ROOT}/src/mantis-rocm-bridge",
    "genesis_source": f"{PROJECT_ROOT}/src/Genesis",
    "datasets": f"{PROJECT_ROOT}/datasets",
    "training": f"{PROJECT_ROOT}/training",
    "evidence": f"{PROJECT_ROOT}/evidence",
    "external_assets": f"{PROJECT_ROOT}/assets/external",
    "cache": f"{PROJECT_ROOT}/cache",
    "backup_staging": f"{PROJECT_ROOT}/backup-staging",
}

EXPECTED_CACHE_ENVIRONMENT = {
    "HF_HOME": f"{PROJECT_ROOT}/cache/huggingface",
    "HF_LEROBOT_HOME": f"{PROJECT_ROOT}/cache/huggingface/lerobot",
    "MODELSCOPE_CACHE": f"{PROJECT_ROOT}/cache/modelscope",
}

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def load_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ContractError(f"persistence contract must be a JSON object: {path}")
    return data


def _pure_absolute_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ContractError(f"{label} must be an absolute POSIX path")
    path = PurePosixPath(value)
    if ".." in path.parts or "." in path.parts:
        raise ContractError(f"{label} must not contain traversal components")
    if path.as_posix() != value:
        raise ContractError(f"{label} must use canonical POSIX spelling")
    return path


def is_strict_descendant(path: str, root: str = PERSISTENT_ROOT) -> bool:
    candidate = _pure_absolute_path(path, "path")
    boundary = _pure_absolute_path(root, "root")
    if candidate == boundary:
        return False
    try:
        candidate.relative_to(boundary)
    except ValueError:
        return False
    return True


def validate_durable_output_path(
    path: str,
    *,
    label: str = "durable output",
    persistent_root: str = PERSISTENT_ROOT,
) -> str:
    candidate = _pure_absolute_path(path, label)
    boundary = _pure_absolute_path(persistent_root, "persistent_root")
    if candidate == boundary:
        raise ContractError(f"{label} must be below, not equal to, {persistent_root}")
    try:
        candidate.relative_to(boundary)
    except ValueError as exc:
        raise ContractError(
            f"{label} must be a descendant of {persistent_root}: {path}"
        ) from exc
    return candidate.as_posix()


def validate_persistence_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != 2:
        raise ContractError("AMD persistence schema_version must be 2")
    if contract.get("status") != "cloud_pvc_write_read_delete_verified":
        raise ContractError("unsupported AMD persistence contract status")

    provenance = contract.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ContractError("AMD persistence provenance must be an object")
    adoption = provenance.get("participant_adoption")
    if not isinstance(adoption, Mapping):
        raise ContractError("participant adoption provenance must be an object")
    if adoption.get("classification") != "user_stated":
        raise ContractError("participant adoption must remain user_stated")
    if adoption.get("workspace_link") != PERSISTENT_ROOT:
        raise ContractError("participant-adopted workspace link changed")
    if adoption.get("resolved_mount_root") != RESOLVED_MOUNT_ROOT:
        raise ContractError("participant-adopted mount root changed")
    canary = provenance.get("cloud_write_canary")
    if not isinstance(canary, Mapping):
        raise ContractError("cloud write canary provenance must be an object")
    for key in (
        "exclusive_create",
        "fsync_completed",
        "readback_match",
        "canary_deleted",
        "canary_absent_after_delete",
    ):
        if canary.get(key) is not True:
            raise ContractError(f"cloud_write_canary.{key} must be true")
    digest = canary.get("cloud_receipt_sha256")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ContractError("cloud write canary receipt hash is invalid")

    roots = contract.get("roots")
    if not isinstance(roots, Mapping):
        raise ContractError("AMD persistence roots must be an object")
    expected_roots = {
        "workspace_root": "/workspace",
        "persistent_root": PERSISTENT_ROOT,
        "resolved_mount_root": RESOLVED_MOUNT_ROOT,
        "project_root": PROJECT_ROOT,
    }
    if dict(roots) != expected_roots:
        raise ContractError("AMD persistence roots changed")

    directories = contract.get("durable_directories")
    if not isinstance(directories, Mapping):
        raise ContractError("durable_directories must be an object")
    if dict(directories) != EXPECTED_DURABLE_DIRECTORIES:
        raise ContractError("AMD durable directory layout changed")
    for label, path in directories.items():
        validate_durable_output_path(
            str(path), label=f"durable_directories.{label}"
        )

    cache = contract.get("persistent_cache_environment")
    if cache != EXPECTED_CACHE_ENVIRONMENT:
        raise ContractError("AMD persistent cache environment changed")
    for label, path in EXPECTED_CACHE_ENVIRONMENT.items():
        validate_durable_output_path(path, label=f"persistent_cache_environment.{label}")

    runtime_policy = contract.get("runtime_policy")
    if not isinstance(runtime_policy, Mapping):
        raise ContractError("runtime_policy must be an object")
    for key in (
        "durable_outputs_must_be_descendants_of_persistent_root",
        "direct_workspace_children_are_ephemeral_unless_persistent_link",
        "resolve_persistent_link_to_expected_mount_root",
        "fail_closed_before_training_if_boundary_invalid",
        "fail_closed_before_inference_if_boundary_invalid",
        "fail_closed_before_evaluation_if_boundary_invalid",
    ):
        if runtime_policy.get(key) is not True:
            raise ContractError(f"runtime_policy.{key} must be true")
    if runtime_policy.get("required_visible_gpu_count") != 1:
        raise ContractError("runtime_policy.required_visible_gpu_count must be 1")

    storage = contract.get("storage_claims")
    if not isinstance(storage, Mapping):
        raise ContractError("storage_claims must be an object")
    if storage.get("pvc_observed") is not True:
        raise ContractError("storage_claims.pvc_observed must be true")
    if storage.get("persistent_mount_is_nfs") is not True:
        raise ContractError("storage_claims.persistent_mount_is_nfs must be true")
    if storage.get("persistent_mount_is_direct_local_ssd") is not False:
        raise ContractError(
            "storage_claims.persistent_mount_is_direct_local_ssd must be false"
        )
    if storage.get("single_session_write_read_delete_verified") is not True:
        raise ContractError(
            "storage_claims.single_session_write_read_delete_verified must be true"
        )
    if storage.get("persistence_across_restart_or_recreation_verified") is not False:
        raise ContractError(
            "persistence across restart or recreation must remain unverified"
        )

    migration = contract.get("migration_policy")
    if not isinstance(migration, Mapping):
        raise ContractError("migration_policy must be an object")
    for key in (
        "copy_before_delete",
        "source_and_destination_sha256_required",
        "destination_independent_verification_required",
        "no_clobber",
        "retain_source_until_off_host_backup_verified",
        "off_host_backup_required_before_destructive_cleanup",
    ):
        if migration.get(key) is not True:
            raise ContractError(f"migration_policy.{key} must be true")

    historical = contract.get("historical_immutability")
    if not isinstance(historical, Mapping):
        raise ContractError("historical_immutability must be an object")
    if historical.get("preserve_legacy_paths_in_historical_receipts") is not True:
        raise ContractError("historical receipt paths must remain immutable")
    legacy = historical.get("preserve_legacy_contracts")
    if not isinstance(legacy, list) or len(legacy) < 5:
        raise ContractError("legacy contract hash pins are incomplete")
    for item in legacy:
        if not isinstance(item, Mapping):
            raise ContractError("legacy contract pins must be objects")
        if not isinstance(item.get("path"), str) or not item["path"]:
            raise ContractError("legacy contract path must be non-empty")
        if not isinstance(item.get("sha256"), str) or not _SHA256_RE.fullmatch(
            item["sha256"]
        ):
            raise ContractError("legacy contract sha256 must be lowercase hex")

    claim = contract.get("claim_boundary")
    if not isinstance(claim, str) or "does not prove" not in claim:
        raise ContractError("AMD persistence claim boundary is incomplete")


def validate_runtime_against_persistence(
    runtime: Mapping[str, Any],
    persistence: Mapping[str, Any],
) -> None:
    validate_persistence_contract(persistence)
    if runtime.get("schema_version") != 3:
        raise ContractError("persistence-aware AMD runtime schema_version must be 3")
    if runtime.get("persistence_layout_contract") != PERSISTENCE_CONTRACT_PATH:
        raise ContractError("AMD runtime persistence contract reference changed")
    platform = runtime.get("platform")
    if not isinstance(platform, Mapping):
        raise ContractError("AMD runtime platform must be an object")
    expected_platform_paths = {
        "persistent_root": PERSISTENT_ROOT,
        "project_root": PROJECT_ROOT,
        "virtual_environment": EXPECTED_DURABLE_DIRECTORIES["virtual_environment"],
    }
    for key, expected in expected_platform_paths.items():
        if platform.get(key) != expected:
            raise ContractError(f"AMD runtime platform.{key} changed")

    genesis = runtime.get("genesis")
    if not isinstance(genesis, Mapping) or genesis.get("install_root") != (
        EXPECTED_DURABLE_DIRECTORIES["genesis_source"]
    ):
        raise ContractError("AMD runtime Genesis path is outside the frozen layout")
    if runtime.get("persistent_cache_environment") != EXPECTED_CACHE_ENVIRONMENT:
        raise ContractError("AMD runtime cache paths are outside the frozen layout")


def verify_legacy_contract_hashes(
    contract: Mapping[str, Any],
    *,
    repository_root: str | Path,
) -> list[dict[str, Any]]:
    validate_persistence_contract(contract)
    root = Path(repository_root)
    pins = contract["historical_immutability"]["preserve_legacy_contracts"]
    results: list[dict[str, Any]] = []
    for pin in pins:
        path = root / pin["path"]
        if not path.is_file():
            raise ContractError(f"legacy contract missing: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != pin["sha256"]:
            raise ContractError(f"legacy contract hash mismatch: {pin['path']}")
        results.append({"path": pin["path"], "sha256": digest, "verified": True})
    return results


def build_persistence_audit(
    contract: Mapping[str, Any],
    *,
    runtime: Mapping[str, Any] | None = None,
    durable_paths: Mapping[str, str] | None = None,
    check_filesystem: bool = False,
) -> dict[str, Any]:
    validate_persistence_contract(contract)
    if runtime is not None:
        validate_runtime_against_persistence(runtime, contract)

    checked_paths: dict[str, str] = {}
    for label, path in (durable_paths or {}).items():
        checked_paths[label] = validate_durable_output_path(path, label=label)

    root = Path(PERSISTENT_ROOT)
    resolved_root = Path(RESOLVED_MOUNT_ROOT)
    filesystem = {
        "checked": check_filesystem,
        "persistent_root_exists": None,
        "persistent_root_is_directory": None,
        "persistent_root_is_symlink": None,
        "resolved_mount_matches_contract": None,
        "persistent_root_writable": None,
    }
    if check_filesystem:
        filesystem = {
            "checked": True,
            "persistent_root_exists": root.exists(),
            "persistent_root_is_directory": root.is_dir(),
            "persistent_root_is_symlink": root.is_symlink(),
            "resolved_mount_matches_contract": (
                root.exists() and root.resolve() == resolved_root
            ),
            "persistent_root_writable": root.is_dir() and os.access(root, os.W_OK),
        }
        if not all(
            filesystem[key]
            for key in (
                "persistent_root_exists",
                "persistent_root_is_directory",
                "persistent_root_is_symlink",
                "resolved_mount_matches_contract",
                "persistent_root_writable",
            )
        ):
            raise ContractError(
                f"persistent root filesystem gate failed: {filesystem}"
            )

    return {
        "schema_version": 2,
        "contract_id": contract["contract_id"],
        "status": "PASS",
        "persistent_root": PERSISTENT_ROOT,
        "resolved_mount_root": RESOLVED_MOUNT_ROOT,
        "project_root": PROJECT_ROOT,
        "runtime_contract_checked": runtime is not None,
        "durable_paths": checked_paths,
        "filesystem": filesystem,
        "claim_boundary": (
            "PASS proves only local contract consistency and any explicitly requested "
            "filesystem observations. It does not prove PVC persistence across reset, "
            "AMD runtime readiness, data migration, training, inference, or evaluation."
        ),
    }

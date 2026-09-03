"""Metadata gate for Mantis LeRobot demonstrations.

The gate is deliberately independent of LeRobot and pandas.  It rejects the
known zero-variance shoulder-roll failure before a dataset can enter an ACT,
SmolVLA, or PI0.5 training run.  Dense trajectory quality remains a separate
audit because metadata statistics alone cannot prove action/state alignment.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .contracts import ContractError


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"required LeRobot metadata file is missing: {path}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"LeRobot metadata root must be an object: {path}")
    return value


def _numeric_stat(
    stats: dict[str, Any], feature: str, statistic: str, dimension: int
) -> list[float] | None:
    raw = stats.get(feature, {}).get(statistic)
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != dimension:
        raise ContractError(
            f"{feature}.{statistic} must contain exactly {dimension} values"
        )
    values = [float(value) for value in raw]
    if not all(math.isfinite(value) for value in values):
        raise ContractError(f"{feature}.{statistic} contains non-finite values")
    return values


def audit_mantis_dataset_metadata(
    dataset_root: Path, contract_path: Path
) -> dict[str, Any]:
    """Return an immutable-ready audit receipt without reading bulk frames."""

    contract = _load_json(contract_path)
    if contract.get("schema_version") != 1:
        raise ContractError("Mantis LeRobot interface schema_version must be 1")
    info_path = dataset_root / "meta" / "info.json"
    stats_path = dataset_root / "meta" / "stats.json"
    info = _load_json(info_path)
    stats = _load_json(stats_path)
    issues: list[str] = []

    if info.get("robot_type") != contract["robot_type"]:
        issues.append("robot_type_mismatch")
    if float(info.get("fps", -1)) != float(contract["fps"]):
        issues.append("fps_mismatch")

    features = info.get("features", {})
    state_names = features.get("observation.state", {}).get("names")
    action_names = features.get("action", {}).get("names")
    if state_names != contract["state_names"]:
        issues.append("state_names_or_order_mismatch")
    if action_names != contract["action_names"]:
        issues.append("action_names_or_order_mismatch")
    if state_names != action_names:
        issues.append("state_action_names_mismatch")

    for key, shape in contract["camera_features"].items():
        actual_shape = features.get(key, {}).get("shape")
        if actual_shape != shape:
            issues.append(f"camera_shape_mismatch:{key}")

    dimension = len(contract["action_names"])
    required_by_policy = contract["policy_statistics"]
    policy_ready: dict[str, bool] = {}
    loaded_stats: dict[tuple[str, str], list[float] | None] = {}
    for policy, required_stats in required_by_policy.items():
        ready = True
        for feature in ("observation.state", "action"):
            for statistic in required_stats:
                values = _numeric_stat(stats, feature, statistic, dimension)
                loaded_stats[(feature, statistic)] = values
                if values is None:
                    issues.append(f"missing_stat:{policy}:{feature}:{statistic}")
                    ready = False
        policy_ready[policy] = ready

    minimum_std = float(contract["minimum_feature_std"])
    for feature in ("observation.state", "action"):
        std = loaded_stats.get((feature, "std"))
        if std is not None:
            for index, value in enumerate(std):
                if value < minimum_std:
                    issues.append(f"low_std:{feature}:{index}")
                    policy_ready["act"] = False
                    policy_ready["smolvla"] = False

    action_std = loaded_stats.get(("action", "std"))
    for index in contract["known_zero_action_guard_indices"]:
        if action_std is None or action_std[int(index)] < minimum_std:
            issues.append(f"known_zero_action_guard:{int(index)}")
            policy_ready["act"] = False
            policy_ready["smolvla"] = False

    for feature in ("observation.state", "action"):
        q01 = loaded_stats.get((feature, "q01"))
        q99 = loaded_stats.get((feature, "q99"))
        if q01 is not None and q99 is not None and any(
            high <= low for low, high in zip(q01, q99)
        ):
            issues.append(f"invalid_quantile_span:{feature}")
            policy_ready["pi05"] = False

    unique_issues = sorted(set(issues))
    return {
        "schema_version": 1,
        "interface_id": contract["interface_id"],
        "upstream_revision": contract["upstream_revision"],
        "dataset_metadata_gate_pass": not unique_issues,
        "policy_ready": policy_ready,
        "issues": unique_issues,
        "total_episodes": info.get("total_episodes"),
        "total_frames": info.get("total_frames"),
        "fps": info.get("fps"),
        "info_sha256": _sha256(info_path),
        "stats_sha256": _sha256(stats_path),
        "contract_sha256": _sha256(contract_path),
        "evidence_boundary": contract["evidence_boundary"],
    }

"""Dense LeRobot parquet and expert-outcome gate for Mantis demonstrations."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContractError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _finite_vector(value: Any, dimension: int) -> list[float] | None:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)) or len(value) != dimension:
        return None
    try:
        result = [float(component) for component in value]
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(component) for component in result) else None


def iter_parquet_rows(dataset_root: Path, required_columns: list[str]) -> Iterator[dict[str, Any]]:
    """Yield selected columns from sorted parquet files without loading video data."""

    parquet_files = sorted((dataset_root / "data").rglob("*.parquet"))
    if not parquet_files:
        raise ContractError(f"no LeRobot parquet files found below {dataset_root / 'data'}")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ContractError("dense parquet audit requires pyarrow") from exc
    for parquet_path in parquet_files:
        parquet = pq.ParquetFile(parquet_path)
        missing = sorted(set(required_columns) - set(parquet.schema_arrow.names))
        if missing:
            raise ContractError(f"{parquet_path} is missing required columns: {missing}")
        for batch in parquet.iter_batches(columns=required_columns, batch_size=4096):
            yield from batch.to_pylist()


def _parse_outcomes(
    outcomes: dict[str, Any],
    *,
    task_id: str,
    protocol: str,
) -> tuple[dict[int, dict[str, Any]], list[str]]:
    raw_episodes = outcomes.get("episodes")
    if not isinstance(raw_episodes, list):
        return {}, ["episode_outcomes_missing"]
    parsed: dict[int, dict[str, Any]] = {}
    issues: list[str] = []
    for raw in raw_episodes:
        if not isinstance(raw, dict):
            issues.append("invalid_episode_outcome")
            continue
        episode_index = raw.get("episode_index")
        if not isinstance(episode_index, int) or episode_index < 0:
            issues.append("invalid_episode_outcome_index")
            continue
        if episode_index in parsed:
            issues.append(f"duplicate_episode_outcome:{episode_index}")
            continue
        if raw.get("task_id") != task_id or raw.get("protocol") != protocol:
            issues.append(f"episode_outcome_contract_mismatch:{episode_index}")
        if raw.get("success") is not True:
            issues.append(f"expert_episode_not_successful:{episode_index}")
        if raw.get("safety_failures") != 0:
            issues.append(f"expert_episode_safety_failure:{episode_index}")
        if raw.get("physics_divergence") is not False:
            issues.append(f"expert_episode_physics_invalid:{episode_index}")
        parsed[episode_index] = raw
    return parsed, issues


def audit_dense_rows(
    rows: Iterable[dict[str, Any]],
    *,
    gate: dict[str, Any],
    expected_total_frames: int,
    expected_total_episodes: int,
    outcomes: dict[str, Any],
) -> dict[str, Any]:
    """Audit frame order/timebase/vectors and bind every episode to strict success."""

    if gate.get("schema_version") != 1:
        raise ContractError("dense dataset gate schema_version must be 1")
    dimension = int(gate["action_dimension"])
    if int(gate["state_dimension"]) != dimension:
        raise ContractError("dense state and action dimensions must match")
    fps = float(gate["fps"])
    tolerance = float(gate["timestamp_delta_tolerance_s"])
    minimum_frames = int(gate["minimum_frames_per_episode"])
    minimum_std = float(gate["minimum_observed_action_std"])
    guard_indices = [int(index) for index in gate["guard_action_indices"]]
    if (
        fps <= 0
        or tolerance < 0
        or minimum_frames <= 0
        or minimum_std < 0
        or any(index < 0 or index >= dimension for index in guard_indices)
    ):
        raise ContractError("dense gate numeric limits are invalid")

    parsed_outcomes, issues = _parse_outcomes(
        outcomes,
        task_id=gate["task_id"],
        protocol=gate["protocol"],
    )
    counts = [0] * dimension
    means = [0.0] * dimension
    m2 = [0.0] * dimension
    episode_frame_counts: dict[int, int] = {}
    observed_episodes: set[int] = set()
    previous_episode: int | None = None
    previous_frame = -1
    previous_timestamp = 0.0
    total_rows = 0

    for row in rows:
        row_number = total_rows
        total_rows += 1
        if not isinstance(row, dict):
            issues.append(f"row_not_object:{row_number}")
            continue
        index = row.get("index")
        episode = row.get("episode_index")
        frame = row.get("frame_index")
        timestamp = row.get("timestamp")
        if index != row_number:
            issues.append(f"global_index_discontinuity:{row_number}")
        if not isinstance(episode, int) or episode < 0:
            issues.append(f"invalid_episode_index:{row_number}")
            continue
        if not isinstance(frame, int) or frame < 0:
            issues.append(f"invalid_frame_index:{row_number}")
            continue
        try:
            timestamp = float(timestamp)
        except (TypeError, ValueError):
            timestamp = math.nan
        if not math.isfinite(timestamp):
            issues.append(f"invalid_timestamp:{row_number}")
            continue
        if previous_episode is None or episode != previous_episode:
            if episode in observed_episodes:
                issues.append(f"episode_not_contiguous:{episode}")
            if previous_episode is not None and episode != previous_episode + 1:
                issues.append(f"episode_index_discontinuity:{episode}")
            if frame != 0:
                issues.append(f"episode_does_not_start_at_zero:{episode}")
            previous_frame = -1
            previous_timestamp = timestamp - 1.0 / fps
            previous_episode = episode
            observed_episodes.add(episode)
            if abs(timestamp) > tolerance:
                issues.append(f"episode_timestamp_not_zero:{episode}")
        if frame != previous_frame + 1:
            issues.append(f"frame_index_discontinuity:{episode}:{frame}")
        expected_delta = 1.0 / fps
        if abs((timestamp - previous_timestamp) - expected_delta) > tolerance:
            issues.append(f"timestamp_delta_mismatch:{episode}:{frame}")
        previous_frame = frame
        previous_timestamp = timestamp
        episode_frame_counts[episode] = episode_frame_counts.get(episode, 0) + 1

        state = _finite_vector(row.get("observation.state"), dimension)
        action = _finite_vector(row.get("action"), dimension)
        if state is None:
            issues.append(f"invalid_state_vector:{row_number}")
        if action is None:
            issues.append(f"invalid_action_vector:{row_number}")
            continue
        for vector_index, value in enumerate(action):
            counts[vector_index] += 1
            delta = value - means[vector_index]
            means[vector_index] += delta / counts[vector_index]
            m2[vector_index] += delta * (value - means[vector_index])

    if total_rows != expected_total_frames:
        issues.append("total_frames_mismatch")
    if len(observed_episodes) != expected_total_episodes:
        issues.append("total_episodes_mismatch")
    if observed_episodes != set(parsed_outcomes):
        issues.append("episode_outcome_coverage_mismatch")
    for episode, frame_count in sorted(episode_frame_counts.items()):
        if frame_count < minimum_frames:
            issues.append(f"episode_too_short:{episode}")

    action_std = [
        math.sqrt(m2[index] / counts[index]) if counts[index] else 0.0
        for index in range(dimension)
    ]
    for index in guard_indices:
        if action_std[index] < minimum_std:
            issues.append(f"low_observed_action_std:{index}")

    unique_issues = sorted(set(issues))
    return {
        "dense_demonstration_gate_pass": not unique_issues,
        "issues": unique_issues,
        "audited_frames": total_rows,
        "audited_episodes": len(observed_episodes),
        "episode_frame_counts": {
            str(key): value for key, value in sorted(episode_frame_counts.items())
        },
        "observed_action_std": action_std,
        "guard_action_indices": guard_indices,
        "successful_outcomes": sum(
            outcome.get("success") is True for outcome in parsed_outcomes.values()
        ),
    }


def audit_mantis_dense_dataset(
    *,
    dataset_root: Path,
    metadata_receipt: dict[str, Any],
    outcomes: dict[str, Any],
    gate_path: Path,
) -> dict[str, Any]:
    """Audit an on-disk LeRobot dataset and return a preflight-compatible receipt."""

    dataset_root = dataset_root.resolve()
    gate_path = gate_path.resolve()
    gate = load_json(gate_path)
    info_path = dataset_root / "meta" / "info.json"
    stats_path = dataset_root / "meta" / "stats.json"
    info = load_json(info_path)
    expected_frames = info.get("total_frames")
    expected_episodes = info.get("total_episodes")
    if not isinstance(expected_frames, int) or expected_frames <= 0:
        raise ContractError("meta/info.json total_frames must be a positive integer")
    if not isinstance(expected_episodes, int) or expected_episodes <= 0:
        raise ContractError("meta/info.json total_episodes must be a positive integer")
    metadata_match = (
        metadata_receipt.get("dataset_metadata_gate_pass") is True
        and metadata_receipt.get("info_sha256") == _sha256(info_path)
        and metadata_receipt.get("stats_sha256") == _sha256(stats_path)
    )
    audit = audit_dense_rows(
        iter_parquet_rows(dataset_root, gate["required_columns"]),
        gate=gate,
        expected_total_frames=expected_frames,
        expected_total_episodes=expected_episodes,
        outcomes=outcomes,
    )
    issues = list(audit["issues"])
    if not metadata_match:
        issues.append("metadata_receipt_or_hash_mismatch")
    unique_issues = sorted(set(issues))
    audit.update(
        {
            "schema_version": 1,
            "gate_id": gate["gate_id"],
            "task_id": gate["task_id"],
            "protocol": gate["protocol"],
            "dense_demonstration_gate_pass": not unique_issues,
            "issues": unique_issues,
            "info_sha256": _sha256(info_path),
            "stats_sha256": _sha256(stats_path),
            "gate_contract_sha256": _sha256(gate_path),
            "claim_boundary": gate["claim_boundary"],
        }
    )
    return audit

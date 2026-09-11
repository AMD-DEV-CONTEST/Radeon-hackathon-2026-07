"""Leakage-resistant initial-observation captures for PI0.5 evaluation."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .mobile_pi05_contract import (
    MOBILE_PI05_STATE_NAMES,
    PI05_GRASP_MODES,
    decode_pi05_context,
)


PI05_HELDOUT_CAPTURE_PROTOCOL = "pi05-heldout-initial-observation-v1"
PI05_HELDOUT_WORKSPACE_BLOCK_PROTOCOL = "pi05-heldout-workspace-block-v1"
PI05_HELDOUT_ARRAY_KEYS = (
    "overhead_rgb",
    "overhead_depth_m",
    "observation_state",
)


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pi05_workspace_block(
    block: Mapping[str, Any], panel: Mapping[str, Any]
) -> dict[str, Any]:
    if block.get("protocol") != PI05_HELDOUT_WORKSPACE_BLOCK_PROTOCOL:
        raise ValueError("held-out workspace block protocol mismatch")
    if block.get("panel_collection_id") != panel.get("collection_id"):
        raise ValueError("workspace block targets a different held-out panel")
    if block.get("panel_sha256") != canonical_payload_sha256(panel):
        raise ValueError("workspace block held-out panel SHA-256 mismatch")
    episodes = {str(item["episode_id"]): item for item in panel.get("episodes", ())}
    assignments = list(block.get("assignments") or ())
    assignment_ids = [str(item.get("episode_id") or "") for item in assignments]
    if set(assignment_ids) != set(episodes) or len(assignment_ids) != len(
        set(assignment_ids)
    ):
        raise ValueError("workspace block must assign every panel episode exactly once")
    positions_by_mode: dict[str, Counter[float]] = {
        mode: Counter() for mode in PI05_GRASP_MODES
    }
    for item in assignments:
        episode_id = str(item["episode_id"])
        position = float(item.get("pedestal_x_m", math.nan))
        if not math.isfinite(position) or not -0.80 <= position <= 0.10:
            raise ValueError("workspace pedestal position must be finite and in range")
        mode = str(episodes[episode_id].get("grasp_mode"))
        if mode not in positions_by_mode:
            raise ValueError(f"unsupported held-out grasp mode: {mode}")
        positions_by_mode[mode][round(position, 6)] += 1
    reference = positions_by_mode[PI05_GRASP_MODES[0]]
    if any(positions_by_mode[mode] != reference for mode in PI05_GRASP_MODES[1:]):
        raise ValueError("workspace positions must be balanced across grasp modes")
    return {
        "status": "passed",
        "protocol": PI05_HELDOUT_WORKSPACE_BLOCK_PROTOCOL,
        "assignments": len(assignments),
        "positions_per_mode": sorted(reference.elements()),
        "block_sha256": canonical_payload_sha256(block),
        "claim_boundary": (
            "Workspace blocking removes mode-position confounding only; it does not "
            "measure routing or closed-loop capability."
        ),
    }


def write_pi05_heldout_observation(
    path: str | Path,
    *,
    rgb: Any,
    depth_m: Any,
    observation_state: Any,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    import numpy as np

    destination = Path(path)
    if destination.suffix != ".npz":
        raise ValueError("held-out observation path must use .npz")
    if destination.exists() or destination.with_suffix(".json").exists():
        raise FileExistsError(f"held-out observation already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    arrays = {
        "overhead_rgb": np.asarray(rgb, dtype=np.uint8)[..., :3],
        "overhead_depth_m": np.asarray(depth_m, dtype=np.float32),
        "observation_state": np.asarray(observation_state, dtype=np.float32),
    }
    _validate_arrays(arrays)
    _validate_metadata(metadata)
    np.savez_compressed(destination, **arrays)
    payload = {
        "schema_version": 1,
        "protocol": PI05_HELDOUT_CAPTURE_PROTOCOL,
        "split": "heldout_observation_do_not_train",
        "observation_file": destination.name,
        "observation_sha256": file_sha256(destination),
        "array_keys": list(PI05_HELDOUT_ARRAY_KEYS),
        "rgb_shape": list(arrays["overhead_rgb"].shape),
        "depth_shape": list(arrays["overhead_depth_m"].shape),
        "state_dimension": int(arrays["observation_state"].shape[0]),
        **dict(metadata),
        "contains_actions": False,
        "contains_recovery": False,
        "contains_outcome": False,
        "claim_boundary": (
            "First settled pregrasp observation only; no policy action was executed "
            "and no action, recovery, or outcome is stored."
        ),
    }
    sidecar = destination.with_suffix(".json")
    sidecar.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validate_pi05_heldout_observation(destination, sidecar)
    return payload


def validate_pi05_heldout_observation(
    observation_path: str | Path, metadata_path: str | Path
) -> dict[str, Any]:
    import numpy as np

    observation = Path(observation_path)
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    if metadata.get("protocol") != PI05_HELDOUT_CAPTURE_PROTOCOL:
        raise ValueError("held-out observation protocol mismatch")
    if "do_not_train" not in str(metadata.get("split")):
        raise ValueError("held-out observation must be marked do_not_train")
    if metadata.get("observation_sha256") != file_sha256(observation):
        raise ValueError("held-out observation SHA-256 mismatch")
    if any(bool(metadata.get(key)) for key in (
        "contains_actions",
        "contains_recovery",
        "contains_outcome",
    )):
        raise ValueError("held-out observation contains forbidden supervision")
    _validate_metadata(metadata)
    with np.load(observation, allow_pickle=False) as loaded:
        if set(loaded.files) != set(PI05_HELDOUT_ARRAY_KEYS):
            raise ValueError("held-out observation contains unexpected arrays")
        arrays = {key: loaded[key] for key in PI05_HELDOUT_ARRAY_KEYS}
    _validate_arrays(arrays)
    context = decode_pi05_context(arrays["observation_state"].tolist())
    if context.grasp_mode_conditioned:
        raise ValueError("held-out state leaks the hidden grasp mode")
    if context.stage != "pregrasp":
        raise ValueError("held-out observation must be captured at pregrasp")
    return {
        "status": "passed",
        "protocol": PI05_HELDOUT_CAPTURE_PROTOCOL,
        "episode_id": str(metadata["episode_id"]),
        "observation_sha256": str(metadata["observation_sha256"]),
        "expected_mode_hidden": True,
        "action_arrays": 0,
        "claim_boundary": (
            "Capture integrity and absence of action supervision only; no model was probed."
        ),
    }


def validate_pi05_heldout_collection(
    root: str | Path,
    panel: Mapping[str, Any],
    block: Mapping[str, Any],
) -> dict[str, Any]:
    collection_root = Path(root).resolve()
    manifest_path = collection_root / "PI05_HELDOUT_OBSERVATION_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("protocol") != "pi05-heldout-observation-collection-v1":
        raise ValueError("held-out collection manifest protocol mismatch")
    if "do_not_train" not in str(manifest.get("split")):
        raise ValueError("held-out collection must be marked do_not_train")
    if any(bool(manifest.get(key)) for key in (
        "contains_actions",
        "contains_recovery",
        "contains_outcome",
    )):
        raise ValueError("held-out collection contains forbidden supervision")
    if manifest.get("panel_sha256") != canonical_payload_sha256(panel):
        raise ValueError("held-out collection panel SHA-256 mismatch")
    if manifest.get("workspace_block_sha256") != canonical_payload_sha256(block):
        raise ValueError("held-out collection workspace-block SHA-256 mismatch")
    validate_pi05_workspace_block(block, panel)
    panel_episodes = {
        str(item["episode_id"]): item for item in panel.get("episodes", ())
    }
    positions = {
        str(item["episode_id"]): float(item["pedestal_x_m"])
        for item in block.get("assignments", ())
    }
    captures = list(manifest.get("captures") or ())
    capture_ids = [str(item.get("episode_id") or "") for item in captures]
    if set(capture_ids) != set(panel_episodes) or len(capture_ids) != len(
        set(capture_ids)
    ):
        raise ValueError("held-out collection must capture every panel episode once")
    mode_counts: Counter[str] = Counter()
    for capture in captures:
        episode_id = str(capture["episode_id"])
        observation = _resolve_inside(collection_root, str(capture["observation"]))
        sidecar = _resolve_inside(collection_root, str(capture["metadata"]))
        audit = validate_pi05_heldout_observation(observation, sidecar)
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        panel_episode = panel_episodes[episode_id]
        if audit["episode_id"] != episode_id:
            raise ValueError("held-out capture episode id mismatch")
        if metadata.get("expected_grasp_mode") != panel_episode.get("grasp_mode"):
            raise ValueError("held-out capture hidden mode differs from frozen panel")
        if metadata.get("task_text") != panel_episode.get("task_text"):
            raise ValueError("held-out capture task differs from frozen panel")
        if not math.isclose(
            float(metadata.get("pedestal_x_m", math.nan)),
            positions[episode_id],
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError("held-out capture workspace assignment mismatch")
        if capture.get("observation_sha256") != audit["observation_sha256"]:
            raise ValueError("held-out manifest observation SHA-256 mismatch")
        mode_counts[str(panel_episode["grasp_mode"])] += 1
    return {
        "status": "passed",
        "protocol": "pi05-heldout-observation-collection-audit-v1",
        "episodes": len(captures),
        "mode_counts": dict(mode_counts),
        "manifest_sha256": file_sha256(manifest_path),
        "action_arrays": 0,
        "claim_boundary": (
            "Collection integrity and isolation only; no checkpoint was selected or probed."
        ),
    }


def _resolve_inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if root not in candidate.parents:
        raise ValueError("held-out collection path escapes its root")
    return candidate


def _validate_arrays(arrays: Mapping[str, Any]) -> None:
    import numpy as np

    rgb = np.asarray(arrays["overhead_rgb"])
    depth = np.asarray(arrays["overhead_depth_m"])
    state = np.asarray(arrays["observation_state"])
    if rgb.ndim != 3 or rgb.shape[-1] != 3 or rgb.dtype != np.uint8:
        raise ValueError("held-out RGB must be HxWx3 uint8")
    if depth.shape != rgb.shape[:2] or not np.isfinite(depth).all():
        raise ValueError("held-out depth must be finite and match RGB")
    if not np.any(depth > 0.0):
        raise ValueError("held-out depth must contain positive metric values")
    if state.shape != (len(MOBILE_PI05_STATE_NAMES),) or not np.isfinite(state).all():
        raise ValueError("held-out state must be one finite 80-D vector")
    if np.any(np.abs(state[52:55]) > 1e-8):
        raise ValueError("held-out state mode channels must be zero")


def _validate_metadata(metadata: Mapping[str, Any]) -> None:
    episode_id = str(metadata.get("episode_id") or "")
    task = str(metadata.get("task_text") or "")
    expected_mode = str(metadata.get("expected_grasp_mode") or "")
    if not episode_id or not task:
        raise ValueError("held-out observation metadata requires episode id and task")
    if expected_mode not in PI05_GRASP_MODES:
        raise ValueError("held-out observation has invalid hidden expected mode")
    lower_task = task.lower()
    if any(mode.lower() in lower_task for mode in PI05_GRASP_MODES):
        raise ValueError("held-out task text leaks a grasp-mode label")

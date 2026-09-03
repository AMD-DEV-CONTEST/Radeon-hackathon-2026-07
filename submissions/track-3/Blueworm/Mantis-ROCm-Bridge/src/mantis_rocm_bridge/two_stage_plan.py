"""Two-stage plan construction and validation for Mantis stack bowls.

This module provides pure-Python (no numpy) utilities for constructing and
validating replay plans for the two-stage scripted generation system.
Plans are deterministic, conservative, hash-bound, and contain no secrets.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReplayPlanStep:
    """A frozen, hash-bound step in a replay plan.

    All numeric fields are finite scalars or lists/tuples with explicit bounds.
    The step is validated at construction time and immutable afterward.
    """

    level: int
    bowl: str
    assigned_side: str
    source_position_xyz_m: tuple[float, float, float]
    right_grasp_candidate_index: int | None
    right_grasp_candidate_tuple: tuple[float, float, float] | None
    place_xy_offset_m: tuple[float, float]
    dual_clamp_required: bool
    probe_placement_position_xyz_m: tuple[float, float, float]
    probe_placement_gate_pass: bool

    def __post_init__(self) -> None:
        """Validate step invariants at construction."""
        # Validate level is non-negative
        if not isinstance(self.level, int) or self.level < 0:
            raise ValueError(f"level must be non-negative int, got {self.level}")

        # Validate bowl is non-blank string
        if not isinstance(self.bowl, str) or not self.bowl or not self.bowl.strip():
            raise ValueError(f"bowl must be non-blank string, got {self.bowl!r}")

        # Validate side is left or right
        if self.assigned_side not in ("left", "right"):
            raise ValueError(f"assigned_side must be 'left' or 'right', got {self.assigned_side}")

        # Validate source position is 3-element tuple of finite numbers
        if not (isinstance(self.source_position_xyz_m, (list, tuple)) and len(self.source_position_xyz_m) == 3):
            raise ValueError("source_position_xyz_m must be 3-element sequence")
        for i, v in enumerate(self.source_position_xyz_m):
            if not isinstance(v, (int, float)) or not _is_finite(v):
                raise ValueError(f"source_position_xyz_m[{i}] must be finite number")

        # Validate right candidate fields match assigned_side
        if self.assigned_side == "right":
            if self.right_grasp_candidate_index is None:
                raise ValueError("right_grasp_candidate_index required for right side")
            if self.right_grasp_candidate_tuple is None:
                raise ValueError("right_grasp_candidate_tuple required for right side")
            if not isinstance(self.right_grasp_candidate_index, int) or self.right_grasp_candidate_index < 0:
                raise ValueError(f"right_grasp_candidate_index must be non-negative int, got {self.right_grasp_candidate_index}")
            if not (isinstance(self.right_grasp_candidate_tuple, (list, tuple)) and len(self.right_grasp_candidate_tuple) == 3):
                raise ValueError("right_grasp_candidate_tuple must be 3-element sequence")
            for i, v in enumerate(self.right_grasp_candidate_tuple):
                if not isinstance(v, (int, float)) or not _is_finite(v):
                    raise ValueError(f"right_grasp_candidate_tuple[{i}] must be finite number")
        else:
            # Left side: these must be None
            if self.right_grasp_candidate_index is not None:
                raise ValueError("right_grasp_candidate_index must be None for left side")
            if self.right_grasp_candidate_tuple is not None:
                raise ValueError("right_grasp_candidate_tuple must be None for left side")

        # Validate place offset is 2-element tuple of finite numbers
        if not (isinstance(self.place_xy_offset_m, (list, tuple)) and len(self.place_xy_offset_m) == 2):
            raise ValueError("place_xy_offset_m must be 2-element sequence")
        for i, v in enumerate(self.place_xy_offset_m):
            if not isinstance(v, (int, float)) or not _is_finite(v):
                raise ValueError(f"place_xy_offset_m[{i}] must be finite number")
            # Conservative bound: offsets <= 0.15 m each axis
            if abs(v) > 0.15:
                raise ValueError(f"place_xy_offset_m[{i}] must be <= 0.15 m in absolute value, got {v}")

        # Validate left zero offset
        if self.assigned_side == "left":
            if self.place_xy_offset_m != (0.0, 0.0):
                raise ValueError(f"left side must have zero offset, got {self.place_xy_offset_m}")

        # Validate exact bool fields
        if not isinstance(self.dual_clamp_required, bool):
            raise ValueError(f"dual_clamp_required must be bool, got {type(self.dual_clamp_required).__name__}")
        if not isinstance(self.probe_placement_gate_pass, bool):
            raise ValueError(f"probe_placement_gate_pass must be bool, got {type(self.probe_placement_gate_pass).__name__}")

        # Validate side/dual consistency: right side requires dual clamp, left side requires False
        if self.assigned_side == "right" and not self.dual_clamp_required:
            raise ValueError("right side must have dual_clamp_required=True")
        if self.assigned_side == "left" and self.dual_clamp_required:
            raise ValueError("left side must have dual_clamp_required=False")

        # Validate gate true
        if not self.probe_placement_gate_pass:
            raise ValueError("probe_placement_gate_pass must be True")

        # Validate probe placement position is 3-element tuple of finite numbers
        if not (isinstance(self.probe_placement_position_xyz_m, (list, tuple)) and len(self.probe_placement_position_xyz_m) == 3):
            raise ValueError("probe_placement_position_xyz_m must be 3-element sequence")
        for i, v in enumerate(self.probe_placement_position_xyz_m):
            if not isinstance(v, (int, float)) or not _is_finite(v):
                raise ValueError(f"probe_placement_position_xyz_m[{i}] must be finite number")


@dataclass(frozen=True)
class ReplayPlan:
    """A frozen, hash-bound replay plan for two-stage generation.

    The plan contains validated schema, hashes, ordered reset poses, and
    deterministic step data. It is immutable after construction and validated
    for all invariants.

    schema_version: Must be 1
    seed: Episode seed (positive integer, not 1 for probe)
    task_id: Task identifier string
    probe_source_run_id: Run ID of the probe that generated this plan
    hashes: SHA-256 hashes of critical assets
    reset_bowl_poses: Exact ordered reset bowl names and poses
    steps: Exactly 3 ordered steps, one per level
    claim_booleans: All False for probe plans
    diagnostic_only_claim_boundary: Explicit claim boundary text
    """

    schema_version: int
    seed: int
    task_id: str
    probe_source_run_id: str
    hashes: dict[str, str]
    reset_bowl_poses: list[dict[str, Any]]
    steps: tuple[ReplayPlanStep, ...]
    # Candidate-loop baseline isolation version stamp. 0 = pre-fix/unknown (a
    # plan whose right-side successful candidate > 0 may have been produced
    # from a polluted start and must be re-probed before replay); >=1 = plan
    # generated with the candidate-isolation fix, never needs re-probe for this.
    candidate_isolation_version: int = 0
    # Claim booleans - all False for probe plans
    probe_plan_pass: bool = False
    scripted_g1_pass: bool = False
    g1_claim: bool = False
    learned_policy_claim: bool = False
    rocm_claim: bool = False
    multi_seed_evidence: bool = False
    episode_success_claim: bool = False
    diagnostic_only_claim_boundary: str = ""

    def __post_init__(self) -> None:
        """Validate plan invariants at construction."""
        # Validate schema version
        if self.schema_version != 1:
            raise ValueError(f"schema_version must be 1, got {self.schema_version}")

        # Validate seed is positive integer, rejecting seed == 1 for probe
        if not isinstance(self.seed, int) or self.seed < 1:
            raise ValueError(f"seed must be positive integer, got {self.seed}")
        if self.seed == 1:
            raise ValueError(f"seed must not be 1 for probe plan, got {self.seed}")

        # Validate task_id is non-empty string
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError("task_id must be non-empty string")

        # Validate probe_source_run_id is non-empty string
        if not isinstance(self.probe_source_run_id, str) or not self.probe_source_run_id:
            raise ValueError("probe_source_run_id must be non-empty string")

        # Validate hashes dict - exactly the six frozen keys, no missing or unexpected keys
        if not isinstance(self.hashes, dict):
            raise ValueError("hashes must be dict")
        required_hashes = (
            "task",
            "scene",
            "camera",
            "port",
            "mantis_urdf",
            "bowl_urdf",
        )
        # Check for missing keys
        for key in required_hashes:
            if key not in self.hashes:
                raise ValueError(f"hashes missing required key: {key}")
        # Check for unexpected keys
        for key in self.hashes:
            if key not in required_hashes:
                raise ValueError(f"hashes has unexpected key: {key}")
        # Validate each hash value
        for key in required_hashes:
            value = self.hashes[key]
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"hashes[{key}] must be 64-character hex string (SHA-256), got {value}")
            # Validate it's valid hex
            try:
                int(value, 16)
            except ValueError:
                raise ValueError(f"hashes[{key}] must be valid hex string, got {value}")

        # Validate reset bowl poses
        if not isinstance(self.reset_bowl_poses, list):
            raise ValueError("reset_bowl_poses must be list")
        if len(self.reset_bowl_poses) != 3:
            raise ValueError(f"reset_bowl_poses must have exactly 3 entries, got {len(self.reset_bowl_poses)}")
        seen_names = set()
        for i, pose in enumerate(self.reset_bowl_poses):
            if not isinstance(pose, dict):
                raise ValueError(f"reset_bowl_poses[{i}] must be dict")
            if "name" not in pose or "position_xyz_m" not in pose or "quaternion_wxyz" not in pose:
                raise ValueError(f"reset_bowl_poses[{i}] missing required keys")
            if not isinstance(pose["name"], str) or not pose["name"]:
                raise ValueError(f"reset_bowl_poses[{i}]['name'] must be non-empty string")
            # Check uniqueness
            if pose["name"] in seen_names:
                raise ValueError(f"reset_bowl_poses[{i}] has duplicate name '{pose['name']}'")
            seen_names.add(pose["name"])
            for key in ("position_xyz_m", "quaternion_wxyz"):
                expected_len = 4 if key == "quaternion_wxyz" else 3
                if not isinstance(pose[key], (list, tuple)) or len(pose[key]) != expected_len:
                    raise ValueError(f"reset_bowl_poses[{i}]['{key}'] must be {expected_len}-element sequence")
                for j, v in enumerate(pose[key]):
                    if not isinstance(v, (int, float)) or not _is_finite(v):
                        raise ValueError(f"reset_bowl_poses[{i}]['{key}'][{j}] must be finite number")

        # Validate steps
        if not isinstance(self.steps, tuple):
            raise ValueError("steps must be tuple")
        if len(self.steps) != 3:
            raise ValueError(f"steps must have exactly 3 entries, got {len(self.steps)}")
        for i, step in enumerate(self.steps):
            if not isinstance(step, ReplayPlanStep):
                raise ValueError(f"steps[{i}] must be ReplayPlanStep")
            # Step level must match index
            if step.level != i:
                raise ValueError(f"steps[{i}].level must be {i}, got {step.level}")

        # Validate exact bool types (must come before truthiness check)
        for field_name in ("probe_plan_pass", "scripted_g1_pass", "g1_claim",
                          "learned_policy_claim", "rocm_claim", "multi_seed_evidence",
                          "episode_success_claim"):
            value = getattr(self, field_name)
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be bool, got {type(value).__name__}")

        # Validate claim booleans are all False for probe
        if any((
            self.probe_plan_pass,
            self.scripted_g1_pass,
            self.g1_claim,
            self.learned_policy_claim,
            self.rocm_claim,
            self.multi_seed_evidence,
            self.episode_success_claim,
        )):
            raise ValueError("All claim booleans must be False for probe plan")

        # Validate nonblank stripped diagnostic_only_claim_boundary
        if not isinstance(self.diagnostic_only_claim_boundary, str):
            raise ValueError(f"diagnostic_only_claim_boundary must be str, got {type(self.diagnostic_only_claim_boundary).__name__}")
        if not self.diagnostic_only_claim_boundary or not self.diagnostic_only_claim_boundary.strip():
            raise ValueError("diagnostic_only_claim_boundary must be non-blank string")

        # Validate candidate_isolation_version is a non-negative int (bool rejected)
        if isinstance(self.candidate_isolation_version, bool) or not isinstance(
            self.candidate_isolation_version, int
        ):
            raise ValueError(
                f"candidate_isolation_version must be int, got "
                f"{type(self.candidate_isolation_version).__name__}"
            )
        if self.candidate_isolation_version < 0:
            raise ValueError(
                f"candidate_isolation_version must be non-negative, got "
                f"{self.candidate_isolation_version}"
            )

        # Validate steps match reset bowl/order
        for i, step in enumerate(self.steps):
            reset_pose = self.reset_bowl_poses[i]
            # Bowl name must match
            if step.bowl != reset_pose["name"]:
                raise ValueError(f"step {i} bowl '{step.bowl}' does not match reset pose '{reset_pose['name']}'")
            # Source position must match exactly
            for j, (step_val, reset_val) in enumerate(zip(step.source_position_xyz_m, reset_pose["position_xyz_m"])):
                if step_val != reset_val:
                    raise ValueError(
                        f"step {i} source_position_xyz_m[{j}]={step_val} "
                        f"does not exactly match reset pose {reset_val}"
                    )
            # Level must match order
            if step.level != i:
                raise ValueError(f"step {i} has level {step.level}, expected {i}")

    def to_dict(self) -> dict[str, Any]:
        """Convert plan to JSON-serializable dict."""
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "task_id": self.task_id,
            "probe_source_run_id": self.probe_source_run_id,
            "hashes": self.hashes,
            "reset_bowl_poses": self.reset_bowl_poses,
            "steps": [
                {
                    "level": step.level,
                    "bowl": step.bowl,
                    "assigned_side": step.assigned_side,
                    "source_position_xyz_m": list(step.source_position_xyz_m),
                    "right_grasp_candidate_index": step.right_grasp_candidate_index,
                    "right_grasp_candidate_tuple": list(step.right_grasp_candidate_tuple) if step.right_grasp_candidate_tuple else None,
                    "place_xy_offset_m": list(step.place_xy_offset_m),
                    "dual_clamp_required": step.dual_clamp_required,
                    "probe_placement_position_xyz_m": list(step.probe_placement_position_xyz_m),
                    "probe_placement_gate_pass": step.probe_placement_gate_pass,
                }
                for step in self.steps
            ],
            "candidate_isolation_version": self.candidate_isolation_version,
            "probe_plan_pass": self.probe_plan_pass,
            "scripted_g1_pass": self.scripted_g1_pass,
            "g1_claim": self.g1_claim,
            "learned_policy_claim": self.learned_policy_claim,
            "rocm_claim": self.rocm_claim,
            "multi_seed_evidence": self.multi_seed_evidence,
            "episode_success_claim": self.episode_success_claim,
            "diagnostic_only_claim_boundary": self.diagnostic_only_claim_boundary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplayPlan:
        """Load plan from JSON dict, validating all invariants."""
        # Reconstruct steps
        steps = []
        for step_data in data["steps"]:
            steps.append(
                ReplayPlanStep(
                    level=step_data["level"],
                    bowl=step_data["bowl"],
                    assigned_side=step_data["assigned_side"],
                    source_position_xyz_m=tuple(step_data["source_position_xyz_m"]),
                    right_grasp_candidate_index=step_data["right_grasp_candidate_index"],
                    right_grasp_candidate_tuple=tuple(step_data["right_grasp_candidate_tuple"]) if step_data["right_grasp_candidate_tuple"] else None,
                    place_xy_offset_m=tuple(step_data["place_xy_offset_m"]),
                    dual_clamp_required=step_data["dual_clamp_required"],
                    probe_placement_position_xyz_m=tuple(step_data["probe_placement_position_xyz_m"]),
                    probe_placement_gate_pass=step_data["probe_placement_gate_pass"],
                )
            )
        return cls(
            schema_version=data["schema_version"],
            seed=data["seed"],
            task_id=data["task_id"],
            probe_source_run_id=data["probe_source_run_id"],
            hashes=data["hashes"],
            reset_bowl_poses=data["reset_bowl_poses"],
            steps=tuple(steps),
            probe_plan_pass=data.get("probe_plan_pass", False),
            candidate_isolation_version=data.get("candidate_isolation_version", 0),
            scripted_g1_pass=data.get("scripted_g1_pass", False),
            g1_claim=data.get("g1_claim", False),
            learned_policy_claim=data.get("learned_policy_claim", False),
            rocm_claim=data.get("rocm_claim", False),
            multi_seed_evidence=data.get("multi_seed_evidence", False),
            episode_success_claim=data.get("episode_success_claim", False),
            diagnostic_only_claim_boundary=data.get("diagnostic_only_claim_boundary", ""),
        )

    def write_atomic(self, path: Path) -> None:
        """Atomically write plan to file with guaranteed no-overwrite.

        Uses a robust atomic write pattern:
        1. Write to a unique temp file in the same directory
        2. fsync the temp file to ensure data is on stable storage
        3. Atomically publish via hard link (fails if target exists)
        4. Clean up temp file

        Raises:
            RuntimeError: If file already exists (atomic exclusive create).
            ValueError: If validation fails.
            OSError: If filesystem operations fail.
        """
        import os
        import tempfile

        plan_dict = self.to_dict()
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)

        # Check if target exists first (for better error message)
        if path.exists():
            raise RuntimeError(
                f"Replay plan file {path} already exists - refusing to overwrite prior plan"
            )

        # Create a unique temp file in the same directory as the target
        # This ensures the temp and target are on the same filesystem
        try:
            fd, temp_path = tempfile.mkstemp(dir=parent, prefix=".tmp_replay_plan_", suffix=".json")
        except OSError as exc:
            raise RuntimeError(f"Failed to create temp file in {parent}: {exc}") from exc

        try:
            # Write the plan to the temp file
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(plan_dict, handle, indent=2, sort_keys=True)
                handle.write("\n")
                # Flush to ensure data reaches the OS buffer
                handle.flush()
                # fsync to ensure data is on stable storage
                os.fsync(handle.fileno())

            # Atomic publish via hard link (fails if target exists)
            # This is the critical atomic operation
            try:
                os.link(temp_path, path)
                # fsync parent directory after publication where supported
                try:
                    parent_fd = os.open(parent, os.O_RDONLY)
                    try:
                        os.fsync(parent_fd)
                    finally:
                        os.close(parent_fd)
                except (OSError, AttributeError):
                    # Best effort - some platforms don't support directory fsync
                    pass
            except OSError as exc:
                # If link failed, check if target was created racefully
                if path.exists():
                    raise RuntimeError(
                        f"Replay plan file {path} was created racefully - refusing to overwrite"
                    ) from exc
                # Otherwise, it's a genuine filesystem error
                raise RuntimeError(f"Failed to create atomic link to {path}: {exc}") from exc

        finally:
            # Clean up temp file - safe to unlink now that target exists
            try:
                os.unlink(temp_path)
            except OSError:
                # Best effort cleanup - ignore errors
                pass

    @classmethod
    def read(cls, path: Path) -> ReplayPlan:
        """Read and validate plan from file.

        Raises:
            ValueError: If plan validation fails.
            FileNotFoundError: If file doesn't exist.
        """
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


def plan_needs_reprobe(plan: ReplayPlan) -> bool:
    """True iff ``plan`` must be re-probed before replay due to candidate isolation.

    A pre-fix plan (``candidate_isolation_version`` < 1) needs re-probe when any
    right-side step's successful grasp candidate was not the first one tried,
    because only candidate_index > 0 could have inherited a polluted/drifted
    start under the pre-fix recovery. candidate_index == 0 (tried first from a
    clean baseline) is compatible. Plans stamped with candidate_isolation_version
    >= 1 were generated with the fix and never need re-probe for this.

    Such a plan must not be trusted directly for replay; re-run probe to
    regenerate it with candidate_isolation_version >= 1.
    """
    from .candidate_isolation import plan_needs_reprobe_for_candidate_isolation

    right_indices = [
        step.right_grasp_candidate_index
        for step in plan.steps
        if step.assigned_side == "right"
    ]
    return plan_needs_reprobe_for_candidate_isolation(
        right_indices, plan.candidate_isolation_version
    )


def _is_finite(value: float) -> bool:
    """Check if value is finite (not NaN, not infinite)."""
    try:
        return isinstance(value, (int, float)) and not (value != value) and abs(value) < float("inf")
    except (TypeError, OverflowError):
        return False


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hash of file contents."""
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def validate_candidate_tuple(
    planned_tuple: tuple[float, float, float] | None,
    current_candidates: list[tuple[float, float, float]],
    candidate_index: int | None,
    assigned_side: str,
) -> None:
    """Validate that planned candidate tuple exists in current candidates.

    Args:
        planned_tuple: The (x_offset, forward_offset, z) tuple from plan.
        current_candidates: List of current candidate tuples.
        candidate_index: Planned candidate index.
        assigned_side: 'left' or 'right'.

    Raises:
        ValueError: If validation fails.
    """
    if assigned_side == "left":
        if planned_tuple is not None:
            raise ValueError("planned candidate tuple must be None for left side")
        if candidate_index is not None:
            raise ValueError("candidate index must be None for left side")
        return

    # Right side validation
    if planned_tuple is None:
        raise ValueError("planned candidate tuple required for right side")
    if candidate_index is None:
        raise ValueError("candidate index required for right side")
    if not isinstance(candidate_index, int) or candidate_index < 0:
        raise ValueError(f"candidate index must be non-negative int, got {candidate_index}")
    if candidate_index >= len(current_candidates):
        raise ValueError(f"candidate index {candidate_index} out of range for {len(current_candidates)} candidates")

    # Check exact match
    actual_tuple = current_candidates[candidate_index]
    if planned_tuple != actual_tuple:
        raise ValueError(
            f"planned candidate tuple {planned_tuple} does not match "
            f"actual tuple {actual_tuple} at index {candidate_index}"
        )


def validate_finite_offset(offset: tuple[float, float], max_abs: float = 0.15) -> None:
    """Validate that offset is finite and bounded.

    Args:
        offset: (dx, dy) offset in meters.
        max_abs: Maximum absolute value per axis (default 0.15 m).

    Raises:
        ValueError: If validation fails.
    """
    if not (isinstance(offset, (list, tuple)) and len(offset) == 2):
        raise ValueError("offset must be 2-element sequence")
    for i, v in enumerate(offset):
        if not isinstance(v, (int, float)) or not _is_finite(v):
            raise ValueError(f"offset[{i}] must be finite number")
        if abs(v) > max_abs:
            raise ValueError(f"offset[{i}] exceeds max {max_abs} m, got {v}")


def validate_ordered_poses(
    planned_poses: list[dict[str, Any]],
    actual_poses: list[dict[str, Any]],
) -> None:
    """Validate that planned reset poses exactly match actual poses.

    Args:
        planned_poses: Ordered list of planned bowl poses from plan.
        actual_poses: Ordered list of actual bowl poses from current run.

    Raises:
        ValueError: If poses don't match exactly.
    """
    if len(planned_poses) != len(actual_poses):
        raise ValueError(f"pose count mismatch: {len(planned_poses)} vs {len(actual_poses)}")

    for i, (planned, actual) in enumerate(zip(planned_poses, actual_poses)):
        if planned["name"] != actual["name"]:
            raise ValueError(f"pose[{i}] name mismatch: {planned['name']} vs {actual['name']}")

        planned_pos = planned["position_xyz_m"]
        actual_pos = actual["position_xyz_m"]
        if len(planned_pos) != 3 or len(actual_pos) != 3:
            raise ValueError(f"pose[{i}] position must be 3-element sequence")

        for j in range(3):
            if not _is_finite(planned_pos[j]) or not _is_finite(actual_pos[j]):
                raise ValueError(f"pose[{i}][{j}] must be finite")
            # Exact match required
            if planned_pos[j] != actual_pos[j]:
                raise ValueError(
                    f"pose[{i}][{j}] mismatch: planned {planned_pos[j]} vs actual {actual_pos[j]}"
                )

        # Validate quaternion (exact match required)
        planned_quat = planned["quaternion_wxyz"]
        actual_quat = actual["quaternion_wxyz"]
        if len(planned_quat) != 4 or len(actual_quat) != 4:
            raise ValueError(f"pose[{i}] quaternion must be 4-element sequence")

        for j in range(4):
            if not _is_finite(planned_quat[j]) or not _is_finite(actual_quat[j]):
                raise ValueError(f"pose[{i}] quaternion[{j}] must be finite")
            if planned_quat[j] != actual_quat[j]:
                raise ValueError(
                    f"pose[{i}] quaternion[{j}] mismatch: planned {planned_quat[j]} vs actual {actual_quat[j]}"
                )

"""Strict simulation-episode export boundary for LeRobot Mantis datasets."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import ContractError
from .episode_state import EpisodeStageTracker
from .gripper import GripperProjection, project_physical_to_virtual
from .lerobot_adapter import policy_vector_to_features

#: Frozen gripper reduction contract implemented by this export boundary.
GRIPPER_REDUCTION_CONTRACT_VERSION = 2
_STATE_GRIPPER_REDUCTION = "bounded_mean_with_residual"
_ACTION_GRIPPER_REDUCTION = "strict_symmetric_inverse"
#: Hard caps enforced at construction time (the strict check threshold lives in the contract).
_ACTION_GRIPPER_PAIR_TOLERANCE_HARD_CAP = 0.02
_GRIPPER_RANGE_TOLERANCE_HARD_CAP = 0.005


def _image_shape(image: Any) -> list[int] | None:
    shape = getattr(image, "shape", None)
    if shape is None:
        return None
    try:
        return [int(value) for value in shape]
    except (TypeError, ValueError):
        return None


def _update_image_hash(digest: Any, image: Any, camera_key: str) -> None:
    digest.update(camera_key.encode("utf-8"))
    tobytes = getattr(image, "tobytes", None)
    if not callable(tobytes):
        raise ContractError(f"{camera_key} image must provide tobytes()")
    payload = tobytes()
    if not isinstance(payload, bytes):
        raise ContractError(f"{camera_key}.tobytes() must return bytes")
    digest.update(payload)


class _GripperReductionRecorder:
    """Accumulate auditable per-frame gripper reduction diagnostics for one stream.

    Each frame records the per-side (left/right) spread and residual maximum.  The
    summary reports, per channel, the maximum spread and the maximum residual reached
    over the episode as **distinct** quantities: ``max_spread`` is paired with the
    ``frame_index`` and ``estimates`` at which that spread occurred, while
    ``max_residual`` is the largest per-frame residual maximum observed for the
    channel (tracked independently, so a later less-spread but more-residual frame
    can still raise it).  The top level exposes ``left``/``right_max_spread`` and
    ``left``/``right_max_residual`` so spread and residual are never conflated.
    """

    def __init__(
        self,
        *,
        mode: str,
        range_tolerance: float,
        action_pair_tolerance: float,
    ) -> None:
        self._mode = mode
        self._range_tolerance = range_tolerance
        self._action_pair_tolerance = action_pair_tolerance
        self._per_channel: dict[str, dict[str, Any]] = {}
        self._frames_above = 0
        self._frames: list[dict[str, Any]] = []

    def record(self, *, projection: GripperProjection, frame_index: int) -> None:
        sides: dict[str, dict[str, float]] = {}
        any_above = False
        for gripper in projection.grippers:
            spread = gripper.spread
            residual_max = max(
                abs(estimate - gripper.projected_mean) for estimate in gripper.estimates
            )
            sides[gripper.virtual_name] = {
                "spread": spread,
                "residual_max": residual_max,
            }
            current = self._per_channel.get(gripper.virtual_name)
            if current is None:
                self._per_channel[gripper.virtual_name] = {
                    "max_spread": spread,
                    "max_residual": residual_max,
                    "frame_index": frame_index,
                    "estimates": list(gripper.estimates),
                }
            else:
                # Mutate in place so an independently-tracked max_residual survives a
                # later max_spread update (the two extrema need not share a frame).
                if spread > current["max_spread"]:
                    current["max_spread"] = spread
                    current["frame_index"] = frame_index
                    current["estimates"] = list(gripper.estimates)
                if residual_max > current["max_residual"]:
                    current["max_residual"] = residual_max
            if spread > self._action_pair_tolerance:
                any_above = True
        if any_above:
            self._frames_above += 1
        self._frames.append({"frame_index": frame_index, "sides": sides})

    def summary(self) -> dict[str, Any]:
        per_channel: dict[str, Any] = {}
        for name in sorted(self._per_channel):
            data = self._per_channel[name]
            per_channel[name] = {
                "max_spread": data["max_spread"],
                "max_residual": data["max_residual"],
                "frame_index": data["frame_index"],
                "estimates": data["estimates"],
            }
        left = self._per_channel.get("left_gripper_joint", {})
        right = self._per_channel.get("right_gripper_joint", {})
        return {
            "mode": self._mode,
            "range_tolerance_normalized": self._range_tolerance,
            "action_pair_tolerance_normalized": self._action_pair_tolerance,
            "per_channel": per_channel,
            "left_max_spread": left.get("max_spread", 0.0),
            "right_max_spread": right.get("max_spread", 0.0),
            "left_max_residual": left.get("max_residual", 0.0),
            "right_max_residual": right.get("max_residual", 0.0),
            "frames_above_action_tolerance": self._frames_above,
            "frames": deepcopy(self._frames),
        }


def create_lerobot_dataset_sink(
    *,
    repo_id: str,
    root: Path,
    interface: dict[str, Any],
    use_videos: bool,
) -> Any:
    """Create a fresh LeRobot 0.4-style dataset with the frozen Mantis schema."""

    if root.exists():
        raise ContractError(f"refusing to overwrite dataset root: {root}")
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
    except ImportError as exc:
        raise ContractError("LeRobotDataset is unavailable in this Python environment") from exc
    features: dict[str, dict[str, Any]] = {
        "observation.state": {
            "dtype": "float32",
            "shape": (len(interface["state_names"]),),
            "names": list(interface["state_names"]),
        },
        "action": {
            "dtype": "float32",
            "shape": (len(interface["action_names"]),),
            "names": list(interface["action_names"]),
        },
    }
    for camera_key, shape in interface["camera_features"].items():
        features[camera_key] = {
            "dtype": "video" if use_videos else "image",
            "shape": tuple(shape),
            "names": ["height", "width", "channel"],
        }
    return LeRobotDataset.create(
        repo_id=repo_id,
        fps=int(interface["fps"]),
        features=features,
        root=root,
        robot_type=interface["robot_type"],
        use_videos=use_videos,
        image_writer_processes=0,
        image_writer_threads=8,
    )


class MantisLeRobotExportSession:
    """Stream validated simulator frames to a LeRobot sink episode by episode."""

    def __init__(
        self,
        *,
        sink: Any,
        port: dict[str, Any],
        interface: dict[str, Any],
        task: dict[str, Any],
        export_contract: dict[str, Any],
        allow_unverified_gripper: bool = False,
    ) -> None:
        if export_contract.get("schema_version") != 1:
            raise ContractError("simulation export schema_version must be 1")
        if export_contract.get("task_id") != task.get("task_id"):
            raise ContractError("simulation export and task IDs disagree")
        if export_contract.get("accepted_episode_protocol") != task.get("protocol_version"):
            raise ContractError("simulation export and task protocols disagree")
        if float(export_contract.get("fps", -1)) != float(interface.get("fps", -2)):
            raise ContractError("simulation export and LeRobot interface FPS values disagree")
        if export_contract.get("physical_state_dimension") != len(
            port["target"]["physical_joint_order"]
        ):
            raise ContractError("simulation export physical state dimension disagrees")
        if export_contract.get("physical_action_dimension") != len(
            port["target"]["physical_joint_order"]
        ):
            raise ContractError("simulation export physical action dimension disagrees")
        if int(export_contract.get("gripper_reduction_contract_version", -1)) != (
            GRIPPER_REDUCTION_CONTRACT_VERSION
        ):
            raise ContractError(
                "simulation export gripper_reduction_contract_version must be "
                f"{GRIPPER_REDUCTION_CONTRACT_VERSION}"
            )
        state_mode = export_contract.get("state_gripper_reduction")
        if state_mode != _STATE_GRIPPER_REDUCTION:
            raise ContractError(
                f"simulation export state_gripper_reduction must be {_STATE_GRIPPER_REDUCTION!r}"
            )
        action_mode = export_contract.get("action_gripper_reduction")
        if action_mode != _ACTION_GRIPPER_REDUCTION:
            raise ContractError(
                f"simulation export action_gripper_reduction must be {_ACTION_GRIPPER_REDUCTION!r}"
            )
        action_pair_tolerance = float(
            export_contract.get("action_gripper_pair_tolerance_normalized", -1)
        )
        if (
            not math.isfinite(action_pair_tolerance)
            or action_pair_tolerance < 0
            or action_pair_tolerance > _ACTION_GRIPPER_PAIR_TOLERANCE_HARD_CAP
        ):
            raise ContractError(
                "simulation export action_gripper_pair_tolerance_normalized must be "
                f"in [0, {_ACTION_GRIPPER_PAIR_TOLERANCE_HARD_CAP}]"
            )
        gripper_range_tolerance = float(
            export_contract.get("gripper_range_tolerance_normalized", -1)
        )
        if (
            not math.isfinite(gripper_range_tolerance)
            or gripper_range_tolerance < 0
            or gripper_range_tolerance > _GRIPPER_RANGE_TOLERANCE_HARD_CAP
        ):
            raise ContractError(
                "simulation export gripper_range_tolerance_normalized must be "
                f"in [0, {_GRIPPER_RANGE_TOLERANCE_HARD_CAP}]"
            )
        self._sink = sink
        self._port = deepcopy(port)
        self._interface = deepcopy(interface)
        self._task = deepcopy(task)
        self._export = deepcopy(export_contract)
        self._gripper_contract_version = GRIPPER_REDUCTION_CONTRACT_VERSION
        self._state_gripper_reduction = state_mode
        self._action_gripper_reduction = action_mode
        self._action_gripper_pair_tolerance = action_pair_tolerance
        self._gripper_range_tolerance = gripper_range_tolerance
        self._allow_unverified_gripper = allow_unverified_gripper
        self._tracker: EpisodeStageTracker | None = None
        self._seed: int | None = None
        self._generation_mode: str | None = None
        self._effective_policy_step_limit: int | None = None
        self._frame_count = 0
        self._frame_digest: Any = None
        self._state_recorder: _GripperReductionRecorder | None = None
        self._action_recorder: _GripperReductionRecorder | None = None
        self._accepted: list[dict[str, Any]] = []
        self._rejected: list[dict[str, Any]] = []
        self._finalized = False

    def begin_episode(
        self,
        *,
        seed: int,
        generation_mode: str = "online",
        effective_policy_step_limit: int | None = None,
    ) -> None:
        if self._finalized:
            raise ContractError("dataset export session is already finalized")
        if self._tracker is not None:
            raise ContractError("an export episode is already active")
        if generation_mode not in ("online", "probe", "replay"):
            raise ContractError(
                "generation_mode must be 'online', 'probe', or 'replay', got "
                f"{generation_mode!r}"
            )
        # Construct into a local first so a tracker construction failure (e.g. an
        # illegal effective_policy_step_limit, which the tracker validates) cannot
        # leave the session with half-set episode state.
        tracker = EpisodeStageTracker(
            self._task,
            seed=seed,
            effective_policy_step_limit=effective_policy_step_limit,
        )
        self._tracker = tracker
        self._seed = seed
        self._generation_mode = generation_mode
        self._effective_policy_step_limit = effective_policy_step_limit
        self._frame_count = 0
        self._frame_digest = hashlib.sha256()
        self._state_recorder = _GripperReductionRecorder(
            mode=self._state_gripper_reduction,
            range_tolerance=self._gripper_range_tolerance,
            action_pair_tolerance=self._action_gripper_pair_tolerance,
        )
        self._action_recorder = _GripperReductionRecorder(
            mode=self._action_gripper_reduction,
            range_tolerance=self._gripper_range_tolerance,
            action_pair_tolerance=self._action_gripper_pair_tolerance,
        )

    def complete_stage(
        self,
        stage: str,
        *,
        policy_step: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self._tracker is None:
            raise ContractError("no active export episode")
        self._tracker.complete_stage(stage, policy_step=policy_step, details=details)

    def fail_stage(
        self,
        stage: str,
        *,
        failure_stage: str,
        policy_step: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self._tracker is None:
            raise ContractError("no active export episode")
        self._tracker.fail_stage(
            stage,
            failure_stage=failure_stage,
            policy_step=policy_step,
            details=details,
        )

    def add_frame(
        self,
        *,
        timestamp_s: float,
        physical_state: Any,
        physical_action: Any,
        images: dict[str, Any],
    ) -> None:
        if self._tracker is None or self._frame_digest is None:
            raise ContractError("no active export episode")
        if self._state_recorder is None or self._action_recorder is None:
            raise ContractError("no active export episode")
        timestamp = float(timestamp_s)
        expected_timestamp = self._frame_count / float(self._interface["fps"])
        if not math.isfinite(timestamp) or abs(timestamp - expected_timestamp) > 1e-6:
            raise ContractError(
                f"frame {self._frame_count} timestamp must be {expected_timestamp}"
            )
        # Observation state uses the bounded symmetric projection: no pair-spread
        # rejection, but the per-finger range gate stays strict.
        state_projection = project_physical_to_virtual(
            physical_state,
            self._port,
            allow_unverified=self._allow_unverified_gripper,
            range_tolerance=self._gripper_range_tolerance,
        )
        state_features = policy_vector_to_features(
            state_projection.vector, self._interface, kind="state"
        )
        self._state_recorder.record(
            projection=state_projection, frame_index=self._frame_count
        )
        # Action projects first, then is checked for strict symmetry. Diagnostics are
        # updated before any rejection so the violation stays auditable.
        action_projection = project_physical_to_virtual(
            physical_action,
            self._port,
            allow_unverified=self._allow_unverified_gripper,
            range_tolerance=self._gripper_range_tolerance,
        )
        self._action_recorder.record(
            projection=action_projection, frame_index=self._frame_count
        )
        for gripper in action_projection.grippers:
            if gripper.spread > self._action_gripper_pair_tolerance:
                raise ContractError(
                    f"frame {self._frame_count} action gripper {gripper.virtual_name} "
                    f"spread {gripper.spread} exceeds tolerance "
                    f"{self._action_gripper_pair_tolerance}; estimates={gripper.estimates}; "
                    f"physical_names={gripper.physical_names}"
                )
        action_vector = action_projection.vector
        expected_cameras = self._interface["camera_features"]
        if set(images) != set(expected_cameras):
            missing = sorted(set(expected_cameras) - set(images))
            extra = sorted(set(images) - set(expected_cameras))
            raise ContractError(
                f"export camera mismatch: missing={missing}, extra={extra}"
            )
        for camera_key, expected_shape in expected_cameras.items():
            image = images[camera_key]
            if _image_shape(image) != expected_shape:
                raise ContractError(
                    f"{camera_key} image shape must be {expected_shape}, "
                    f"got {_image_shape(image)}"
                )
            dtype = getattr(image, "dtype", None)
            if dtype is not None and str(dtype) != "uint8":
                raise ContractError(f"{camera_key} image dtype must be uint8")

        state_vector = [state_features[name] for name in self._interface["state_names"]]
        try:
            import numpy as np
        except ImportError as exc:
            raise ContractError(
                "NumPy is required to write LeRobot numeric features"
            ) from exc
        frame = {
            "task": self._export["task_description"],
            "observation.state": np.asarray(state_vector, dtype=np.float32),
            "action": np.asarray(action_vector, dtype=np.float32),
            **images,
        }
        numeric_payload = json.dumps(
            {
                "frame_index": self._frame_count,
                "timestamp": timestamp,
                "observation.state": state_vector,
                "action": action_vector,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._frame_digest.update(numeric_payload)
        for camera_key in expected_cameras:
            _update_image_hash(self._frame_digest, images[camera_key], camera_key)
        self._sink.add_frame(frame)
        self._frame_count += 1

    def _gripper_reduction_diagnostics(self) -> dict[str, Any]:
        assert self._state_recorder is not None and self._action_recorder is not None
        return {
            "contract_version": self._gripper_contract_version,
            "state_mode": self._state_gripper_reduction,
            "action_mode": self._action_gripper_reduction,
            "range_tolerance_normalized": self._gripper_range_tolerance,
            "action_pair_tolerance_normalized": self._action_gripper_pair_tolerance,
            "state": self._state_recorder.summary(),
            "action": self._action_recorder.summary(),
        }

    def finish_episode(self, *, g1_claim: bool = False) -> dict[str, Any]:
        if self._tracker is None or self._frame_digest is None or self._seed is None:
            raise ContractError("no active export episode")
        receipt = self._tracker.receipt(
            g1_claim=g1_claim,
            generation_mode=self._generation_mode,
            effective_policy_step_limit=self._effective_policy_step_limit,
        )
        receipt["frame_count"] = self._frame_count
        receipt["frame_payload_sha256"] = self._frame_digest.hexdigest()
        receipt["export_id"] = self._export["export_id"]
        receipt["gripper_reduction_diagnostics"] = self._gripper_reduction_diagnostics()
        minimum_frames = int(self._export["minimum_frames_per_episode"])
        accepted = receipt["success"] is True and self._frame_count >= minimum_frames
        if accepted:
            episode_index = len(self._accepted)
            self._sink.save_episode()
            outcome = {
                "episode_index": episode_index,
                "seed": self._seed,
                "task_id": receipt["task_id"],
                "protocol": receipt["protocol"],
                "success": True,
                "safety_failures": receipt["safety_failures"],
                "physics_divergence": receipt["physics_divergence"],
                "frame_count": self._frame_count,
                "frame_payload_sha256": receipt["frame_payload_sha256"],
                "gripper_reduction_diagnostics": deepcopy(
                    receipt["gripper_reduction_diagnostics"]
                ),
            }
            self._accepted.append(outcome)
            receipt["dataset_episode_index"] = episode_index
            receipt["dataset_acceptance"] = "accepted"
        else:
            self._sink.clear_episode_buffer(delete_images=True)
            rejection_reasons = []
            if receipt["success"] is not True:
                rejection_reasons.append("strict_episode_not_successful")
            if self._frame_count < minimum_frames:
                rejection_reasons.append("episode_too_short")
            receipt["dataset_acceptance"] = "rejected"
            receipt["rejection_reasons"] = rejection_reasons
            self._rejected.append(deepcopy(receipt))
        self._tracker = None
        self._seed = None
        self._generation_mode = None
        self._effective_policy_step_limit = None
        self._frame_count = 0
        self._frame_digest = None
        self._state_recorder = None
        self._action_recorder = None
        return receipt

    def finalize(self) -> dict[str, Any]:
        if self._finalized:
            raise ContractError("dataset export session is already finalized")
        if self._tracker is not None:
            raise ContractError("cannot finalize dataset with an active episode")
        if not self._accepted:
            raise ContractError("refusing to finalize a dataset with zero accepted episodes")
        self._sink.finalize()
        self._finalized = True
        return {
            "schema_version": 1,
            "export_id": self._export["export_id"],
            "task_id": self._task["task_id"],
            "protocol": self._task["protocol_version"],
            "accepted_episodes": len(self._accepted),
            "rejected_episodes": len(self._rejected),
            "episodes": deepcopy(self._accepted),
            "rejections": deepcopy(self._rejected),
            "claim_boundary": self._export["claim_boundary"],
        }

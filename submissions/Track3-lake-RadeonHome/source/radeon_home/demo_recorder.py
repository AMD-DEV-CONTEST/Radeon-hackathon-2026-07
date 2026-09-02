"""Record expert demonstrations from the deterministic mobile manipulation controller.

Produces LeRobot-compatible episode files that can be used to train an ACT
or Diffusion Policy model.  Each episode is a sequence of (observation, action)
pairs captured during one successful execution of ``mjcf_mobile_pipeline.run()``.

Usage::

    python -m radeon_home.demo_recorder --task trash_to_trash_bin --episodes 50 \
        --output-dir datasets/expert_demos
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Observation / Action schemas  (LeRobot-compatible)
# ---------------------------------------------------------------------------

OBS_KEYS = [
    "observation.images.cam_high",       # 3 x 224 x 224  float32 [0,1]
    "observation.state",                 # 16-D: 7 arm + 3 base + 2 finger + 3 eef_xyz + 1 grip_width
    "action",                             # 7-D:  delta_xyz(3) + delta_yaw + delta_grip + grasp_flag + place_flag
]


@dataclass
class Episode:
    """One successful demonstration episode."""

    episode_index: int
    task_id: str
    seed: int
    frames: list[np.ndarray] = field(default_factory=list)  # HWC uint8
    states: list[np.ndarray] = field(default_factory=list)   # 16-D float32
    actions: list[np.ndarray] = field(default_factory=list)   # 7-D float32
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return len(self.frames)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_index": self.episode_index,
            "task_id": self.task_id,
            "seed": self.seed,
            "length": self.length,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Recorder — hooks into the existing PlanarFrankaController
# ---------------------------------------------------------------------------


class DemonstrationRecorder:
    """Non-invasive observation hook for the mobile manipulation controller.

    Attach to a ``PlanarFrankaController`` before starting a run, then call
    ``record()`` every control step.  The recorder extracts observation and
    action tensors from the live Genesis state without modifying the
    controller's behaviour.
    """

    def __init__(
        self,
        controller,  # PlanarFrankaController
        *,
        output_dir: Path,
        episode_index: int,
        task_id: str,
        seed: int,
        camera_resolution: tuple[int, int] = (224, 224),
    ):
        self._ctrl = controller
        self._robot = controller.robot
        self._scene = controller.scene
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._episode = Episode(episode_index=episode_index, task_id=task_id, seed=seed)
        self._prev_qpos: np.ndarray | None = None
        self._prev_hand_xyz: np.ndarray | None = None
        self._res = camera_resolution

    # ---- observation extraction -------------------------------------------

    def _extract_state(self) -> np.ndarray:
        """16-D proprioceptive state vector."""
        qpos = self._robot.get_qpos().detach().cpu().numpy().reshape(-1)
        # joint indices mirror PlanarFrankaController
        arm = qpos[[19, 20, 21, 22, 23, 24, 25]]        # joints 1-7
        base = qpos[[16, 17, 18]]                          # base_x, base_y, base_yaw
        fingers = qpos[[26, 27]]                           # finger_joint1, finger_joint2
        hand = self._ctrl.hand
        eef_xyz = hand.get_pos().detach().cpu().numpy().reshape(-1)[:3]
        grip_width = float(fingers[0] + fingers[1])
        return np.concatenate([arm, base, fingers, eef_xyz, [grip_width]]).astype(np.float32)

    def _render_camera(self, camera_name: str = "overview") -> np.ndarray:
        """Render one RGB frame from the named Genesis camera."""
        frame = self._ctrl.recorder.cameras[camera_name].render(rgb=True)[0]
        # frame is HWC uint8; center-crop to square then resize
        h, w = frame.shape[:2]
        size = min(h, w)
        top, left = (h - size) // 2, (w - size) // 2
        cropped = frame[top:top + size, left:left + size]
        # We cannot import PIL / cv2 here because they may not be installed;
        # caller frames are stored raw and resized during dataset packaging.
        return np.asarray(cropped, dtype=np.uint8)

    # ---- action derivation (delta from previous step) ---------------------

    def _derive_action(self) -> np.ndarray:
        """Compute the incremental action since the previous record call.

        Returns a 7-D vector:
          [delta_x, delta_y, delta_z, delta_yaw, delta_grip_width, grasp_flag, place_flag]
        """
        current_qpos = self._robot.get_qpos().detach().cpu().numpy().reshape(-1)
        ctrl = self._ctrl  # shorthand
        arm_now = current_qpos[[19, 20, 21, 22, 23, 24, 25]]
        base_now = current_qpos[[16, 17, 18]]
        fingers_now = current_qpos[[26, 27]]
        hand_now = ctrl.hand.get_pos().detach().cpu().numpy().reshape(-1)[:3]

        if self._prev_qpos is None:
            action = np.zeros(7, dtype=np.float32)
        else:
            delta_xyz = hand_now - self._prev_hand_xyz
            delta_yaw = base_now[2] - self._prev_qpos[17]
            delta_grip = float(fingers_now[0] + fingers_now[1]) - float(
                self._prev_qpos[26] + self._prev_qpos[27]
            )
            # heuristic grasp/place flags derived from finger state
            grasp_flag = 1.0 if float(fingers_now[0] + fingers_now[1]) < 0.02 else 0.0
            place_flag = 1.0 if (ctrl.finger_closed is False and self._prev_qpos is not None
                                 and float(self._prev_qpos[26] + self._prev_qpos[27]) < 0.02) else 0.0
            action = np.array([
                delta_xyz[0], delta_xyz[1], delta_xyz[2],
                delta_yaw,
                delta_grip,
                grasp_flag,
                place_flag,
            ], dtype=np.float32)

        self._prev_qpos = current_qpos.copy()
        self._prev_hand_xyz = hand_now.copy()
        return action

    # ---- main recording hook ----------------------------------------------

    def record(self, *, camera: str = "overview") -> None:
        """Call once per control step, after ``scene.step()``."""
        frame = self._render_camera(camera)
        state = self._extract_state()
        action = self._derive_action()

        self._episode.frames.append(frame)
        self._episode.states.append(state)
        self._episode.actions.append(action)

    def save(self) -> Path:
        """Write the episode to disk in a LeRobot-compatible layout."""
        ep = self._episode
        ep_dir = self._output_dir / f"episode_{ep.episode_index:05d}"
        ep_dir.mkdir(parents=True, exist_ok=True)

        # Save frames as individual PNGs (LeRobot convention: observation.images.cam_high)
        img_dir = ep_dir / "observation.images.cam_high"
        img_dir.mkdir(exist_ok=True)
        for t, frame in enumerate(ep.frames):
            # Use imageio for consistency with the rest of the codebase
            import imageio.v2 as imageio
            imageio.imwrite(img_dir / f"frame_{t:06d}.png", frame)

        # Save state and action as float32 .npy arrays (step-major)
        np.save(ep_dir / "observation.state.npy", np.stack(ep.states))
        np.save(ep_dir / "action.npy", np.stack(ep.actions))

        # Episode metadata
        meta_path = ep_dir / "meta.json"
        meta_path.write_text(json.dumps(ep.to_dict(), indent=2), encoding="utf-8")

        return ep_dir


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record expert demonstrations for imitation learning"
    )
    parser.add_argument(
        "--task", default="trash_to_trash_bin",
        help="Task identifier (trash_to_trash_bin, keys_to_tray, medicine_to_cup)"
    )
    parser.add_argument(
        "--episodes", type=int, default=50,
        help="Number of successful demonstrations to record"
    )
    parser.add_argument(
        "--output-dir", default="datasets/expert_demos",
        help="Output directory for recorded episodes"
    )
    parser.add_argument(
        "--seed-start", type=int, default=0,
        help="Starting seed (incremented per episode)"
    )
    return parser


def main() -> None:
    """CLI entry point — delegates to ``mjcf_mobile_pipeline.run()`` with recording hooks."""
    parser = _build_parser()
    args = parser.parse_args()

    from .mjcf_mobile_pipeline import run as pipeline_run
    from .spatial_tasks import generate_task as _generate_task

    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    recorded = 0
    seed = args.seed_start
    max_attempts = args.episodes * 3  # allow retries for failed episodes

    while recorded < args.episodes and seed < args.seed_start + max_attempts:
        task = _generate_task(args.task, seed)
        run_dir = output_root / f"run_{seed:03d}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # The pipeline run() writes result JSON — we wrap it to also record
        result = pipeline_run(
            task=args.task,
            seed=seed,
            output_dir=run_dir,
            record_demonstration=True,
            demo_output_root=output_root,
            demo_episode_index=recorded,
        )

        if result.get("transport_success"):
            recorded += 1
            manifest.append({
                "episode": recorded - 1,
                "seed": seed,
                "task": args.task,
                "steps": result.get("recorded_control_steps", 0),
                "object": result.get("physical_object", {}).get("name", args.task),
            })
        seed += 1

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps({
        "total_episodes": recorded,
        "task": args.task,
        "seeds_attempted": seed - args.seed_start,
        "episodes": manifest,
    }, indent=2), encoding="utf-8")
    print(f"Recorded {recorded}/{args.episodes} successful episodes → {output_root}")


if __name__ == "__main__":
    main()

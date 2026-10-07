"""Record scripted multi-object sorting episodes into a LeRobotDataset.

Each episode runs the full scripted sort (plum -> lemon -> banana, each into its
color-matched bowl) and records per-step (observation.state, action,
observation.images.{world,wrist}, task). Only fully-successful episodes (all
three fruits placed in their correct bowls) are committed to the dataset.

Per-frame ``task`` is updated as the scripted policy switches fruits, so a
language-conditioned policy (SmolVLA) sees the right sorting sub-goal at each
timestep.

Usage:
    uv run python franka_fruit_pick/record_sort_dataset.py --cpu --episodes 10
    uv run python franka_fruit_pick/record_sort_dataset.py --episodes 30
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from lerobot.configs.video import RGBEncoderConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset

import grasp_demo as _gd
from build_scene import build_scene
from grasp_demo import (
    TaskSpec,
    run_pick_place,
    check_success,
    _goto_interp,
    _topdown_quat,
    GRIPPER_OPEN,
    _ik,
    GraspProfile,
)
from paths import DATASETS_DIR
from scene_config import TABLE_TOP_Z
from sort_scene_config import (
    SORT_LAYOUT,
    SORT_MAPPING,
    pick_order,
    sort_task_description,
)

# --- Grasp profile overrides (see sort_demo.py for rationale) -------------
_OVERRIDE_PROFILES = {
    "018_plum": GraspProfile(yaw_offset=0.0, close_force=-35.0, center_align=True),
    "011_banana": GraspProfile(yaw_offset=-35.0, close_force=-50.0, center_align=True),
    "014_lemon": GraspProfile(yaw_offset=0.0, close_force=-60.0, center_align=True),
}
for _name, _prof in _OVERRIDE_PROFILES.items():
    _gd.GRASP_PROFILES[_name] = _prof


# --- _goto_plan with retry (see sort_demo.py for rationale) --------------
_orig_goto_plan = _gd._goto_plan


def _goto_plan_with_retry(
    bundle,
    pos,
    quat,
    *,
    finger,
    num_waypoints=150,
    settle=20,
    recorder=None,
    max_attempts=3,
):
    last_qpos = None
    dist = float("inf")
    for attempt in range(max_attempts):
        qpos = _orig_goto_plan(
            bundle,
            pos,
            quat,
            finger=finger,
            num_waypoints=num_waypoints,
            settle=settle,
            recorder=recorder,
        )
        hand = bundle.franka.get_link("hand")
        cur = hand.get_pos().cpu().numpy().reshape(-1)
        dist = float(np.linalg.norm(cur - np.asarray(pos)))
        print(
            f"    [plan attempt {attempt + 1}/{max_attempts}] target={np.asarray(pos).tolist()} hand={cur.tolist()} dist={dist:.4f}",
            flush=True,
        )
        if dist < 0.05:
            return qpos
        last_qpos = qpos
        for _ in range(10):
            bundle.franka.control_dofs_position(last_qpos)
            bundle.scene.step()
            bundle.update_wrist_cam()

    # RRTConnect failed after all retries -- fall back to _goto_interp (IK
    # interpolation). Safe for approach/descend phases where gripper is empty
    # and both start/end are at or above table level. See sort_demo.py for
    # full rationale.
    print(
        f"    [plan FAILED after {max_attempts} attempts, falling back to _goto_interp] dist={dist:.4f}",
        flush=True,
    )
    _gd._goto_interp(
        bundle,
        pos,
        quat,
        finger_cmd=finger,
        recorder=recorder,
    )
    hand = bundle.franka.get_link("hand")
    cur = hand.get_pos().cpu().numpy().reshape(-1)
    final_dist = float(np.linalg.norm(cur - np.asarray(pos)))
    print(
        f"    [interp fallback done] dist={final_dist:.4f}",
        flush=True,
    )
    return last_qpos


_gd._goto_plan = _goto_plan_with_retry


# --- _descend_vertical: keep original step-wise z descent (v9) ----------
# v7-v8 replaced _descend_vertical with _goto_interp. But v8 diagnostic showed
# _goto_interp causes lateral drift during descent, pushing fruits off the
# grasp axis. v9 reverts to the original step-wise z descent (re-solve IK each
# step, keeping the hand on a vertical line).
#
# Additionally, patch GRASP_CENTER_DROP_FRAC from 0.45 to 1.0 so fingertips
# reach the bottom of the fruit for a proper cupping grip.
_gd.GRASP_CENTER_DROP_FRAC = 1.0
_gd.PALM_CLEARANCE = 0.01

# v10: import the run_pick_place override from sort_demo (applied there)
from sort_demo import _run_pick_place_v10, _settle_grasp  # noqa: E402

_gd.run_pick_place = _run_pick_place_v10


# Home pose between picks (mirrors sort_demo._go_home) -- see comment there.
HOME_XY = (0.20, 0.00)
HOME_Z = TABLE_TOP_Z + 0.45


def _go_home(bundle, recorder=None) -> None:
    home_pos = np.array([HOME_XY[0], HOME_XY[1], HOME_Z])
    home_quat = _topdown_quat(0.0)
    # Use _goto_interp (joint-space interpolation). RRTConnect from the post-pick
    # retreat pose to home fails (yaw + lateral move crosses IK branches; verified:
    # 4 retries all failed). _goto_interp is safe because both poses are high above
    # the table (no collision) and the next descend uses _goto_interp
    # (_descend_via_interp), so the home pose's IK branch doesn't matter
    # (see sort_demo._go_home rationale).
    _gd._goto_interp(
        bundle,
        home_pos,
        home_quat,
        finger_cmd=GRIPPER_OPEN,
        recorder=recorder,
    )


CONTROL_FPS = 100  # sim dt = 0.01

JOINT_NAMES = [
    "panda_joint1",
    "panda_joint2",
    "panda_joint3",
    "panda_joint4",
    "panda_joint5",
    "panda_joint6",
    "panda_joint7",
    "panda_finger_joint1",
    "panda_finger_joint2",
]


class SortRecorder:
    """Per-step recorder for one sort episode (3 pick-and-place sub-tasks).

    Captures (state, action, world_img, wrist_img, task) at a target fps
    decimated from the 100 Hz sim. ``set_task`` swaps the active sub-goal
    label as the scripted policy moves to the next fruit.
    """

    def __init__(
        self,
        bundle,
        *,
        fps: int,
        img_wh: tuple[int, int],
        control_fps: int = CONTROL_FPS,
    ):
        self.bundle = bundle
        self.fps = fps
        self.img_w, self.img_h = img_wh
        self.steps_per_frame = control_fps / fps
        self._current_task = "sort each fruit into its color-matched bowl"
        self.reset()

    def reset(self) -> None:
        self.states: list[np.ndarray] = []
        self.actions: list[np.ndarray] = []
        self.world_imgs: list[np.ndarray] = []
        self.wrist_imgs: list[np.ndarray] = []
        self.tasks: list[str] = []
        self._accum = self.steps_per_frame  # capture the very first step

    def set_task(self, task: str) -> None:
        self._current_task = task

    def __len__(self) -> int:
        return len(self.states)

    @staticmethod
    def _to_np(x) -> np.ndarray:
        if hasattr(x, "detach"):
            x = x.detach().cpu().numpy()
        return np.asarray(x)

    def _resize(self, img) -> np.ndarray:
        img = self._to_np(img)
        if (img.shape[1], img.shape[0]) != (self.img_w, self.img_h):
            img = cv2.resize(
                img, (self.img_w, self.img_h), interpolation=cv2.INTER_AREA
            )
        return np.ascontiguousarray(img, dtype=np.uint8)

    def on_step(self, action) -> None:
        self._accum += 1.0
        if self._accum < self.steps_per_frame:
            return
        self._accum -= self.steps_per_frame

        state = (
            self._to_np(self.bundle.franka.get_qpos()).reshape(-1).astype(np.float32)
        )
        action = self._to_np(action).reshape(-1).astype(np.float32)
        world = self._resize(self.bundle.world_cam.render(rgb=True)[0])
        wrist = self._resize(self.bundle.wrist_cam.render(rgb=True)[0])

        self.states.append(state)
        self.actions.append(action)
        self.world_imgs.append(world)
        self.wrist_imgs.append(wrist)
        self.tasks.append(self._current_task)

    def flush_to(self, dataset: LeRobotDataset) -> None:
        for state, action, world, wrist, task in zip(
            self.states, self.actions, self.world_imgs, self.wrist_imgs, self.tasks
        ):
            dataset.add_frame(
                {
                    "observation.state": state,
                    "action": action,
                    "observation.images.world": world,
                    "observation.images.wrist": wrist,
                    "task": task,
                }
            )
        dataset.save_episode()


def build_features(img_wh: tuple[int, int]) -> dict:
    w, h = img_wh
    vec = {"dtype": "float32", "shape": (len(JOINT_NAMES),), "names": JOINT_NAMES}
    img = {
        "dtype": "video",
        "shape": (h, w, 3),
        "names": ["height", "width", "channel"],
    }
    return {
        "observation.state": dict(vec),
        "action": dict(vec),
        "observation.images.world": dict(img),
        "observation.images.wrist": dict(img),
    }


def run_sort_episode_per_fruit(
    bundle, dataset, *, fps: int, img_wh: tuple[int, int]
) -> int:
    """Run one scripted sort attempt. Commit each successful fruit as its own
    LeRobot episode (so a failed fruit doesn't waste the successful one's frames).

    Returns the number of episodes committed (0, 1, or 2 for plum+banana).
    """
    committed = 0
    first_pick = True
    for fruit in pick_order():
        # Reset to home BETWEEN picks (see sort_demo.run_sort_episode rationale:
        # skip on the first pick because RRTConnect from FRANKA_QPOS to HOME
        # fails; the starter grasp_demo goes directly from FRANKA_QPOS to
        # pregrasp, which is the known-good planning pattern).
        if not first_pick:
            _go_home(bundle)
        first_pick = False
        # Fresh recorder per fruit: only this fruit's frames are committed, so a
        # failed fruit's noisy frames never enter the dataset.
        recorder = SortRecorder(bundle, fps=fps, img_wh=img_wh)
        container = SORT_MAPPING[fruit]
        recorder.set_task(sort_task_description(fruit))
        task = TaskSpec(
            pick_object=fruit,
            place_target=container,
            success_tol=0.06,
        )
        try:
            # Debug: log fruit position before pick
            fruit_entity = bundle.ycb[fruit]
            fruit_pos_before = fruit_entity.get_pos().cpu().numpy().reshape(-1)
            print(
                f"    [DEBUG {fruit}] before pick: pos={fruit_pos_before.tolist()}",
                flush=True,
            )

            success, _ = run_pick_place(
                bundle, task, save_frames=False, recorder=recorder
            )
        except Exception as e:
            print(f"  [{fruit} error] {e}")
            success = False

        # Debug: log fruit position after pick-and-place + check_success details
        fruit_entity = bundle.ycb[fruit]
        fruit_pos_after = fruit_entity.get_pos().cpu().numpy().reshape(-1)
        container_entity = bundle.ycb[container]
        container_pos = container_entity.get_pos().cpu().numpy().reshape(-1)
        print(
            f"    [DEBUG {fruit}] after pick: fruit_pos={fruit_pos_after.tolist()} "
            f"container_pos={container_pos.tolist()} ok={success}",
            flush=True,
        )
        if not success:
            # Log check_success details
            try:
                from grasp_demo import _resolve_place, _entity_aabb, _BOWL_RIM_MARGIN

                place_xy, place_ref_z, place_ent = _resolve_place(
                    bundle, task.place_target
                )
                horizontal = float(np.linalg.norm(fruit_pos_after[:2] - place_xy))
                if place_ent is not None:
                    bowl_aabb = _entity_aabb(place_ent)
                    rim_z = float(bowl_aabb[1, 2])
                    rim_radius = 0.5 * float(
                        min(
                            bowl_aabb[1, 0] - bowl_aabb[0, 0],
                            bowl_aabb[1, 1] - bowl_aabb[0, 1],
                        )
                    )
                    obj_bottom_z = float(_entity_aabb(fruit_entity)[0, 2])
                    within = horizontal < min(task.success_tol, rim_radius)
                    inside = obj_bottom_z < rim_z - _BOWL_RIM_MARGIN
                    print(
                        f"    [DEBUG {fruit}] check_success: horizontal={horizontal:.4f} "
                        f"rim_z={rim_z:.4f} rim_radius={rim_radius:.4f} "
                        f"obj_bottom_z={obj_bottom_z:.4f} within={within} inside={inside}",
                        flush=True,
                    )
            except Exception as e:
                print(f"    [DEBUG {fruit}] check_success debug error: {e}", flush=True)
        if success and len(recorder) > 0:
            recorder.flush_to(dataset)
            committed += 1
            print(f"  [{fruit} OK] sub-episode committed ({len(recorder)} frames)")
        else:
            print(
                f"  [{fruit} skip] not committed (ok={success}, frames={len(recorder)})"
            )
    return committed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record scripted sort episodes into a LeRobotDataset."
    )
    parser.add_argument(
        "-c", "--cpu", action="store_true", default=False, help="Force CPU sim."
    )
    parser.add_argument(
        "--episodes", type=int, default=10, help="Target successful episodes to record."
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=30,
        help="Max total attempts before giving up.",
    )
    parser.add_argument(
        "--fps", type=int, default=30, help="Dataset fps (decimated from 100 Hz sim)."
    )
    parser.add_argument(
        "--img-wh", type=int, nargs=2, default=[224, 224], help="Image width height."
    )
    parser.add_argument(
        "--dataset-name",
        type=str,
        default="sort_fruit",
        help="Dataset name (under datasets/).",
    )
    parser.add_argument(
        "--repo-id", type=str, default="local/sort_fruit", help="LeRobot repo id."
    )
    args = parser.parse_args()

    img_wh = tuple(args.img_wh)
    features = build_features(img_wh)

    dataset_dir = DATASETS_DIR / args.dataset_name
    dataset_dir.mkdir(parents=True, exist_ok=True)

    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        fps=args.fps,
        features=features,
        image_writer_processes=0,
        image_writer_threads=2,
        video_backend="pyav",
    )

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)

    successful = 0
    attempts = 0
    while successful < args.episodes and attempts < args.max_attempts:
        attempts += 1
        print(
            f"\n=== Attempt {attempts} (committed so far: {successful}/{args.episodes}) ==="
        )

        # Fresh scene per attempt (Genesis scenes are not cheap to reset
        # in-place; rebuilding guarantees a clean physics state for each episode).
        bundle = build_scene(layout=SORT_LAYOUT, add_world_cam=True, add_wrist_cam=True)

        try:
            committed = run_sort_episode_per_fruit(
                bundle,
                dataset,
                fps=args.fps,
                img_wh=img_wh,
            )
        except Exception as e:
            print(f"  [episode error] {e}")
            committed = 0

        successful += committed
        if committed == 0:
            print(f"  [skip] no sub-episodes committed this attempt")

    print(f"\n=== Dataset written: {dataset_dir} ===")
    print(f"Committed episodes: {successful}/{attempts} attempts")


if __name__ == "__main__":
    main()

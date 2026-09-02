"""Run and record the official-MJCF Franka reference baseline on Radeon GPU."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


UPSTREAM_URL = "https://github.com/wangxunx/franka_fruit_pick_demo"
UPSTREAM_COMMIT = "64ae838"


def _reference_candidates(explicit: Path | None) -> list[Path]:
    candidates = []
    if explicit is not None:
        candidates.append(explicit)
    configured = os.environ.get("RADEONHOME_FRANKA_REFERENCE")
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            Path("/persistent/projects/reference-franka"),
            Path(__file__).resolve().parents[2]
            / "reference"
            / "franka_fruit_pick_demo",
        ]
    )
    return candidates


def resolve_reference_root(explicit: Path | None = None) -> Path:
    for candidate in _reference_candidates(explicit):
        if (candidate / "franka_fruit_pick" / "grasp_demo.py").is_file():
            return candidate.resolve()
    searched = ", ".join(str(path) for path in _reference_candidates(explicit))
    raise FileNotFoundError(
        "franka_fruit_pick_demo was not found. Clone "
        f"{UPSTREAM_URL} and pass --reference-root. Searched: {searched}"
    )


class SimulationVideoRecorder:
    """Capture frames from the running simulation at a fixed control-step stride."""

    def __init__(self, bundle, *, stride: int = 8) -> None:
        self.bundle = bundle
        self.stride = stride
        self.step_count = 0
        self.frames = []

    def on_step(self, _action) -> None:
        self.step_count += 1
        if self.step_count % self.stride:
            return
        camera = self.bundle.video_cam or self.bundle.world_cam
        self.frames.append(camera.render(rgb=True)[0])


def run(args: argparse.Namespace) -> dict:
    reference_root = resolve_reference_root(args.reference_root)
    sys.path.insert(0, str(reference_root))

    import genesis as gs
    import imageio.v2 as imageio
    from franka_fruit_pick.build_scene import build_scene
    from franka_fruit_pick.grasp_demo import (
        TaskSpec,
        _parse_place,
        run_pick_place,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    gs.init(backend=gs.gpu, seed=args.seed)
    bundle = build_scene(
        show_viewer=False,
        n_envs=1,
        add_world_cam=True,
        add_wrist_cam=True,
        add_video_cam=True,
    )
    recorder = SimulationVideoRecorder(bundle, stride=args.video_stride)
    task = TaskSpec(
        pick_object=args.pick,
        place_target=_parse_place(args.place),
        success_tol=args.tolerance,
    )
    initial_xyz = (
        bundle.ycb[args.pick].get_pos().detach().cpu().numpy().reshape(-1).tolist()
    )
    success, key_frames = run_pick_place(
        bundle, task, save_frames=True, recorder=recorder
    )
    final_xyz = (
        bundle.ycb[args.pick].get_pos().detach().cpu().numpy().reshape(-1).tolist()
    )

    key_frame_files = []
    for index, (tag, frame) in enumerate(key_frames):
        filename = f"{index:02d}_{tag}.png"
        imageio.imwrite(args.output_dir / filename, frame)
        key_frame_files.append(filename)
    video_name = "official_mjcf_pick_place.mp4"
    imageio.mimsave(
        args.output_dir / video_name,
        recorder.frames,
        fps=max(1, round(100 / args.video_stride)),
    )

    result = {
        "backend": "gpu",
        "seed": args.seed,
        "robot_asset": "official_franka_mjcf",
        "pick_object": args.pick,
        "place_target": args.place,
        "initial_object_xyz": initial_xyz,
        "final_object_xyz": final_xyz,
        "success": bool(success),
        "recorded_control_steps": recorder.step_count,
        "recorded_video_frames": len(recorder.frames),
        "video_stride": args.video_stride,
        "upstream": {
            "url": UPSTREAM_URL,
            "tested_commit": UPSTREAM_COMMIT,
            "local_root": str(reference_root),
        },
    }
    result_name = "official_mjcf_result.json"
    (args.output_dir / result_name).write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    artifacts = {
        "provenance": "Rendered directly from this Genesis simulation run",
        "synthetic_or_reconstructed": False,
        "key_frames": key_frame_files,
        "full_run_video": video_name,
        "structured_result": result_name,
        "upstream_credit": UPSTREAM_URL,
        "upstream_commit": UPSTREAM_COMMIT,
    }
    (args.output_dir / "artifact_manifest.json").write_text(
        json.dumps(artifacts, indent=2), encoding="utf-8"
    )
    print(json.dumps({**result, "artifacts": artifacts}, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record the official-MJCF Franka physical grasp baseline"
    )
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pick", default="014_lemon")
    parser.add_argument("--place", default="024_bowl")
    parser.add_argument("--tolerance", type=float, default=0.06)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--video-stride", type=int, default=8)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()

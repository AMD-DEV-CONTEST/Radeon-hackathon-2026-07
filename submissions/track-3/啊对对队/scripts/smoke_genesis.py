from __future__ import annotations

import argparse
import json
import time

import numpy as np
import torch

import genesis as gs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Headless Genesis Franka and depth-camera smoke test"
    )
    parser.add_argument("--steps", type=int, default=80)
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("--steps must be positive")

    if args.backend == "rocm" and getattr(torch.version, "hip", None) is None:
        raise RuntimeError("ROCm mode requires a PyTorch HIP build")
    if args.backend == "cuda" and (
        getattr(torch.version, "cuda", None) is None
        or getattr(torch.version, "hip", None) is not None
    ):
        raise RuntimeError("CUDA mode requires an NVIDIA PyTorch CUDA build")
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch cannot access a GPU")
    if args.backend == "rocm" and torch.cuda.device_count() != 1:
        raise RuntimeError("Exactly one Radeon GPU must be visible")

    gs.init(backend=gs.gpu, precision="32")
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.01),
        rigid_options=gs.options.RigidOptions(box_box_detection=True),
        show_viewer=False,
    )

    plane = scene.add_entity(gs.morphs.Plane())
    franka = scene.add_entity(
        gs.morphs.MJCF(file="xml/franka_emika_panda/panda.xml")
    )
    scene.add_entity(
        gs.morphs.Box(size=(0.08, 0.06, 0.05), pos=(0.65, 0.0, 0.025))
    )
    depth_camera = scene.add_sensor(
        gs.sensors.DepthCamera(
            pattern=gs.sensors.DepthCameraPattern(
                res=(96, 72),
                fov_horizontal=60.0,
            ),
            entity_idx=plane.idx,
            link_idx_local=0,
            pos_offset=(-1.3, 0.0, 1.25),
            euler_offset=(0.0, 45.0, 0.0),
            max_range=5.0,
            return_world_frame=True,
        )
    )
    scene.build()

    arm_dofs = np.arange(7)
    finger_dofs = np.arange(7, 9)
    franka.set_dofs_kp([100.0, 100.0], finger_dofs)
    franka.set_dofs_kv([10.0, 10.0], finger_dofs)
    franka.set_qpos(
        np.array(
            [-1.0124, 1.5559, 1.3662, -1.6878, -1.5799, 1.7757, 1.4602, 0.04, 0.04]
        )
    )
    scene.step()

    hand = franka.get_link("hand")
    pregrasp = franka.inverse_kinematics(
        link=hand,
        pos=np.array([0.65, 0.0, 0.16]),
        quat=np.array([0, 1, 0, 0]),
    )
    franka.control_dofs_position(pregrasp[:-2], arm_dofs)
    franka.control_dofs_position(np.array([0.04, 0.04]), finger_dofs)

    torch.cuda.synchronize()
    started = time.perf_counter()
    for _ in range(args.steps):
        scene.step()
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started

    depth = depth_camera.read_image()
    finite_hits = int((torch.isfinite(depth) & (depth < 5.0)).sum().item())
    report = {
        "device": torch.cuda.get_device_name(0),
        "rocm": torch.version.hip,
        "cuda": torch.version.cuda,
        "backend": args.backend,
        "steps": args.steps,
        "elapsed_seconds": round(elapsed, 6),
        "simulation_steps_per_second": round(args.steps / elapsed, 2),
        "depth_shape": list(depth.shape),
        "depth_finite_hits": finite_hits,
        "ik_solution_size": int(pregrasp.shape[-1]),
    }
    print(json.dumps(report, indent=2))

    if finite_hits == 0:
        raise RuntimeError("Depth camera returned no finite scene hits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

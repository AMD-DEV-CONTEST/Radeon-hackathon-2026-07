"""Record a trained policy walking, for the demo video.

Rendering is the one part of this project that needs the offscreen GL context
Genesis always builds, so it is kept out of the training path entirely: train
headless, render afterwards, from a checkpoint.

Usage: render.py <checkpoint> [out.mp4] [seconds] [vx] [vy] [wz]
"""
from __future__ import annotations

import sys

import genesis as gs
import torch

from chaal.env import Go2LocomotionEnv
from chaal.eval import load_policy

ckpt = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "clip.mp4"
seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0
cmd = [float(x) for x in (sys.argv[4:7] or (1.0, 0.0, 0.0))]

gs.init(backend=gs.amdgpu, logging_level="warning")

env = Go2LocomotionEnv(num_envs=1, add_camera=True)
policy = load_policy(ckpt, env)

obs, _ = env.reset()
env.commands[:] = torch.tensor(cmd, device=env.device)

# Genesis 1.3.0 takes the filename and fps up front; stop_recording() takes
# no arguments. fps must divide 1/dt or it is silently reduced.
env.camera.start_recording(save_to_filename=out, fps=int(1 / env.task.dt))
steps = int(seconds / env.task.dt)
with torch.no_grad():
    for _ in range(steps):
        action = policy(obs)
        obs, _, _, _ = env.step(action)
        # Hold the command fixed: the point of the clip is one clear gait, not
        # the resampling the training env does.
        env.commands[:] = torch.tensor(cmd, device=env.device)
        pos = env.base_pos[0].tolist()
        env.camera.set_pose(
            pos=(pos[0] + 2.0, pos[1] - 2.0, pos[2] + 0.8),
            lookat=(pos[0], pos[1], pos[2]),
        )
        env.camera.render()

env.camera.stop_recording()
print(f"wrote {out}  ({steps} frames, command {cmd})")
print("CHAAL_DONE")

"""Render every clip the demo video needs, from one scene.

A Genesis scene costs about a minute of kernel compilation, so building one per
clip would waste most of the runtime. One env, one policy, several recordings.

Usage: render_clips.py <checkpoint> [seconds]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import genesis as gs
import torch

from chaal.env import Go2LocomotionEnv
from chaal.eval import load_policy

ckpt = sys.argv[1]
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0

CLIPS = [
    ("walk-forward.mp4", (1.0, 0.0, 0.0), "forward at 1.0 m/s"),
    ("walk-turn.mp4", (0.5, 0.0, 1.0), "forward and turning at 1.0 rad/s"),
    ("walk-sideways.mp4", (0.0, 0.8, 0.0), "sideways at 0.8 m/s"),
    ("walk-reverse.mp4", (-0.8, 0.0, 0.0), "backwards at 0.8 m/s"),
]

gs.init(backend=gs.amdgpu, logging_level="warning")
env = Go2LocomotionEnv(num_envs=1, add_camera=True)
policy = load_policy(ckpt, env)

steps = int(seconds / env.task.dt)
fps = int(1 / env.task.dt)
results: list[dict] = []

for name, cmd, label in CLIPS:
    obs, _ = env.reset()
    command = torch.tensor(cmd, device=env.device)
    env.commands[:] = command

    env.camera.start_recording(save_to_filename=name, fps=fps)
    tracked = 0.0
    with torch.no_grad():
        for _ in range(steps):
            obs, _, _, _ = env.step(policy(obs))
            # Hold the command: the clip should show one clear gait, not the
            # resampling the training environment does every 4 seconds.
            env.commands[:] = command
            tracked += float(torch.norm(env.commands[0, :2] - env.base_lin_vel[0, :2]))
            pos = env.base_pos[0].tolist()
            env.camera.set_pose(
                pos=(pos[0] + 2.0, pos[1] - 2.0, pos[2] + 0.8),
                lookat=(pos[0], pos[1], pos[2]),
            )
            env.camera.render()
    env.camera.stop_recording()
    err = tracked / steps
    results.append({"file": name, "command": list(cmd), "label": label,
                    "seconds": seconds, "mean_tracking_error_ms": round(err, 4)})
    print(f"{name:<20} {label:<34} mean tracking error {err:.3f} m/s", flush=True)

# The video captions are generated from this file rather than typed into the
# assembly script, so a caption cannot claim a number the clip did not produce.
out = Path("bench-results/clips.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"checkpoint": ckpt, "clips": results}, indent=2) + "\n")
print(f"wrote {out}")
print("CHAAL_DONE")

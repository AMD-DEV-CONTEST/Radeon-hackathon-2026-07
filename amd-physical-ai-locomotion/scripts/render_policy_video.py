#!/usr/bin/env python3
"""Render a demo video driven by the TRAINED PPO policy (checkpoints/latest.pkl).

Unlike make_demo_video_full.py (open-loop scripted gaits), this rolls out the
learned joystick policy: each segment just feeds a different velocity command
[vx, vy, vyaw] and the same network produces forward / turn / sidestep — the
motion is natural because it was learned, not hand-authored.

Runs on CPU (the AMD GPU is blocked by the ROCm profiler race, see
docs/ROCM_BUG_REPORT.md). Reuses render_3d / title_card / concat from the
scripted-demo script so the output style matches.

Usage (on the instance, after training has written a checkpoint):
    cd /workspace/demo
    MUJOCO_GL=egl python3 scripts/render_policy_video.py                 # uses latest.pkl
    MUJOCO_GL=egl python3 scripts/render_policy_video.py checkpoints/go1_38000000.pkl
"""
import sys
import pickle
import functools
from pathlib import Path

import numpy as np
import jax
import mujoco
import subprocess

from mujoco_playground import registry
from mujoco_playground.config import locomotion_params
from brax.training.agents.ppo import networks as ppo_networks
from brax.training.acme import running_statistics

# Reuse rendering + video assembly from the scripted-demo module.
import make_demo_video_full as demo

ENV = "Go1JoystickFlatTerrain"
OUT = Path("assets/demo_policy.mp4")
CKPT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("checkpoints/latest.pkl")

# Each segment: key, HUD label, [vx, vy, vyaw] command, #steps, camera opts.
# Commands stay inside the training range (vx +-1.5, vy +-0.8, vyaw +-1.2).
CMD_MAX = (1.5, 0.8, 1.2)  # training command range: |vx|,|vy|,|vyaw|


def _phase(i, nsteps, keys, ramp=0.06):
    """Interpolate the command through waypoints instead of stepping.

    `keys` is a list of (fraction, [vx,vy,vyaw]); the command linearly ramps
    between consecutive waypoints over the last `ramp` of the gap. The policy
    was trained on smoothly-resampled commands, so hard square-wave steps make
    it freeze in place (confirmed: stepped sprint path=0.23m vs sin-driven
    zigzag path=12m). Smooth transitions keep the "hard move" look while
    staying in the policy's comfort zone.
    """
    frac = i / max(nsteps - 1, 1)
    bounds = []
    acc = 0.0
    for width, cmd in keys:
        bounds.append((acc, acc + width, np.array(cmd, dtype=float)))
        acc += width
    for lo, hi, cmd in bounds:
        if frac <= hi:
            # ramp in from the previous waypoint over the first `ramp` of window
            prev = None
            for plo, phi, pcmd in bounds:
                if phi <= lo + 1e-9:
                    prev = pcmd
            if prev is not None and frac < lo + ramp:
                t = (frac - lo) / ramp
                return list(prev + (cmd - prev) * t)
            return list(cmd)
    return list(bounds[-1][2])


def sprint_stop(i, nsteps):
    # full-speed dash, ease to stop, dash again — accel/decel transitions
    return _phase(i, nsteps, [
        (0.35, [1.5, 0.0, 0.0]),   # sprint
        (0.15, [0.0, 0.0, 0.0]),   # stop
        (0.35, [1.5, 0.0, 0.0]),   # sprint again
        (0.15, [0.0, 0.0, 0.0]),   # stop
    ])


def spin_fast(i, nsteps):
    # high-speed banked circling: forward + max yaw one way, then reverse.
    # Pure in-place yaw barely rotates this policy (turnL only reached 67deg,
    # path 0.65m), so we add forward speed -> tight fast loops that actually
    # move and look like a show-off manoeuvre.
    return _phase(i, nsteps, [
        (0.5, [1.0, 0.0,  1.2]),
        (0.5, [1.0, 0.0, -1.2]),
    ])


def zigzag(i, nsteps):
    # forward while rapidly switching turn direction -> weaving S-path
    import math
    vyaw = 1.2 * math.sin(2 * math.pi * (i / nsteps) * 3.0)  # 3 full weaves
    return [1.0, 0.0, vyaw]


def figure8(i, nsteps):
    # true figure-8: hold a constant turn one way for a full loop, then hold
    # the opposite turn for the second loop. A sine yaw (like zigzag) reverses
    # every half period and never closes a loop -> looked like weaving, so we
    # sustain each turn direction instead. _phase ramps the sign flip smoothly.
    return _phase(i, nsteps, [
        (0.5, [1.1, 0.0,  1.1]),   # first loop (left)
        (0.5, [1.1, 0.0, -1.1]),   # second loop (right) -> closed 8
    ])


def strafe_switch(i, nsteps):
    # sprint forward, then hard sidestep left, then hard sidestep right
    return _phase(i, nsteps, [
        (0.34, [1.3,  0.0, 0.0]),
        (0.33, [0.3,  0.8, 0.0]),
        (0.33, [0.3, -0.8, 0.0]),
    ])


# Each segment: key, HUD label, command (fixed list OR callable), #steps, camera.
SEGMENTS = [
    ("stand",   "Stand (zero command)", [0.0,  0.0,  0.0], 240,
     dict(track=True,  azimuth=45)),
    # --- baseline locomotion (tracked camera; policy translates several metres) ---
    ("forward", "Walk forward",         [1.0,  0.0,  0.0], 500,
     dict(track=True, azimuth=90, distance=3.2)),
    ("turnL",   "Turn left in place",   [0.0,  0.0,  1.0], 400,
     dict(track=True,  azimuth=45)),
    # --- HARD moves: time-varying commands the policy must transition through ---
    ("sprint",  "Sprint -> hard stop -> sprint", sprint_stop, 640,
     dict(track=True, azimuth=90, distance=3.6)),
    ("spin",    "High-speed banked circling",    spin_fast,   560,
     dict(track=True, azimuth=45, distance=4.0)),
    ("zigzag",  "Weaving S-path (fast turn switch)", zigzag,   640,
     dict(track=True, azimuth=70, distance=3.8)),
    ("figure8", "Figure-8 (forward + alt turns)", figure8,    720,
     dict(track=True, azimuth=70, distance=4.2)),
    ("strafe",  "Sprint -> strafe L -> strafe R", strafe_switch, 600,
     dict(track=True, azimuth=60, distance=3.8)),
]


def load_policy(env, ckpt_path):
    """Rebuild the PPO network used in training and bind the saved params.

    CRITICAL: training used normalize_observations=True, so params[0] is a
    RunningStatisticsState and the actor was trained on NORMALIZED obs. The net
    must be rebuilt with the same preprocess_observations_fn or the policy sees
    raw-scale obs and topples after ~50 steps. (Confirmed via probe_norm.py:
    without normalization FELL@53, with it survives 400+ steps.)
    """
    ppo_params = locomotion_params.brax_ppo_config(ENV)
    nf = dict(ppo_params).get("network_factory", {})
    net = ppo_networks.make_ppo_networks(
        env.observation_size, env.action_size,
        preprocess_observations_fn=running_statistics.normalize, **nf)
    make_policy = ppo_networks.make_inference_fn(net)
    with open(ckpt_path, "rb") as f:
        params = pickle.load(f)
    # deterministic=True -> use the mean action, no exploration noise
    return make_policy(params, deterministic=True)


def rollout_policy(env, policy, command, nsteps):
    """Roll the learned policy; collect qpos snaps.

    `command` is either a fixed [vx, vy, vyaw] or a callable (i, nsteps) ->
    [vx, vy, vyaw] for time-varying "hard" moves (sprint+stop, figure-8,
    rapid turn switching). The callable lets one segment chain several
    commands so the policy has to transition between behaviours on the fly.
    """
    jit_reset = jax.jit(env.reset)
    jit_step = jax.jit(env.step)
    inference = jax.jit(policy)

    rng = jax.random.PRNGKey(0)
    state = jit_reset(rng)
    is_sched = callable(command)

    def force_cmd(obs, cmd):
        # The actor network consumes obs["state"], whose LAST 3 dims are the
        # joystick command (see joystick.py _get_obs layout). The env keeps
        # re-sampling its own command internally every step, so instead of
        # fighting that, we overwrite those 3 dims with our command right
        # before inference. Physics only depends on the action the policy
        # returns, so this fully controls the rollout.
        s = obs["state"]
        return {**obs, "state": s.at[-3:].set(cmd)}

    snaps = []
    q0 = np.asarray(state.data.qpos)
    yaw0 = _yaw(q0)
    path_len = 0.0        # total distance travelled along the ground path
    peak_disp = 0.0       # farthest the trunk ever got from the start point
    n_switch = 0          # how many times the commanded vector changed
    prev_c = None
    prev_xy = q0[:2].copy()
    for i in range(nsteps):
        c = command(i, nsteps) if is_sched else command
        if prev_c is None or np.any(np.abs(np.array(c) - np.array(prev_c)) > 1e-6):
            n_switch += 1
        prev_c = c
        cmd = jax.numpy.array(c, dtype=jax.numpy.float32)
        act_rng, rng = jax.random.split(rng)
        act, _ = inference(force_cmd(state.obs, cmd), act_rng)
        state = jit_step(state, act)
        qpos = np.asarray(state.data.qpos)
        xy = qpos[:2]
        path_len += float(np.linalg.norm(xy - prev_xy))
        peak_disp = max(peak_disp, float(np.linalg.norm(xy - q0[:2])))
        prev_xy = xy.copy()
        snaps.append((qpos.copy(), None))
    qn = snaps[-1][0]
    st = dict(dx=float(qn[0] - q0[0]), dy=float(qn[1] - q0[1]),
              dyaw=float(np.degrees(_yaw(qn) - yaw0)),
              min_h=float(min(s[0][2] for s in snaps)),
              path=path_len, peak=peak_disp, switches=n_switch)
    return snaps, st


def _yaw(qpos):
    w, x, y, z = qpos[3], qpos[4], qpos[5], qpos[6]
    return np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


# render_3d reads snaps as [(qpos, xpos)]; xpos is unused for track modes, but
# fixed-camera mode calls mj_forward per frame so xpos isn't needed there either.
def render_seg(model, snaps, label, cam):
    # patch the HUD wording for this run: trained policy, not scripted gait
    return demo.render_3d(model, snaps, label, **cam)


def main():
    if not CKPT.exists():
        sys.exit(f"[render] checkpoint not found: {CKPT}\n"
                 f"         train first, or pass a path to an existing .pkl")
    print(f"[render] checkpoint: {CKPT}")

    cfg = registry.get_default_config(ENV)
    cfg.impl = "jax"
    env = registry.load(ENV, config=cfg)
    model = env.mj_model

    # make the HUD say 'trained PPO policy' instead of 'scripted gait'
    demo._hud = _patched_hud

    policy = load_policy(env, CKPT)

    segs = []
    for key, label, cmd, nsteps, cam in SEGMENTS:
        desc = "schedule:" + cmd.__name__ if callable(cmd) else str(cmd)
        print(f"[render] segment '{key}' cmd={desc} — {nsteps} steps ...")
        snaps, st = rollout_policy(env, policy, cmd, nsteps)
        print(f"         dx={st['dx']:+.2f}m dy={st['dy']:+.2f}m "
              f"yaw={st['dyaw']:+.0f}deg min_trunk_h={st['min_h']:.3f}m")
        print(f"         path={st['path']:.2f}m peak={st['peak']:.2f}m "
              f"cmd_switches={st['switches']}")
        frames = render_seg(model, snaps, label, cam)
        segs.append((key, label, demo.save_segment(frames, "pol_" + key)))

    flist = [demo.title_card(
        "Unitree Go1 — TRAINED PPO policy\nReal MuJoCo physics · AMD Radeon (CPU fallback)", 4)]
    for key, label, path in segs:
        flist.append(demo.title_card(label, 2))
        flist.append(path)
    flist.append(demo.title_card(
        "GPU training blocked by a ROCm profiler race\nTrained on CPU — see docs/ROCM_BUG_REPORT.md", 4))

    tmp_txt = Path("/tmp/concat_policy.txt")
    tmp_txt.write_text("".join(f"file '{p}'\n" for p in flist))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_bin = "ffmpeg"
    subprocess.run([ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
                    "-i", str(tmp_txt), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(OUT)], check=True)
    print(f"✅ {OUT}  ({OUT.stat().st_size // 1024} KB)")
    print("   Upload to YouTube/Bilibili for the PR submission.")


def _patched_hud(img_arr, label, note=None):
    from PIL import Image, ImageDraw
    img = Image.fromarray(img_arr)
    draw = ImageDraw.Draw(img)
    f = demo._font(15)
    draw.text((10, 10), f"Unitree Go1 - trained PPO policy, real MuJoCo physics - {label}",
              fill=(20, 20, 60), font=f)
    if note:
        draw.text((10, 32), note, fill=(120, 60, 60), font=f)
    return np.array(img)


if __name__ == "__main__":
    main()

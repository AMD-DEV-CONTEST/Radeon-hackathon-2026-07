"""Start noise-free at a chosen reference frame and compare a zero-action
baseline against the policy.

An earlier version (render_track.py) set info["motion_idx"] straight after
reset, but the robot's qpos and qvel were still at whatever frame RSI had
picked. State and reference index disagreed and the episode ended after one
step. This builds the initial state exactly from the requested frame instead.

Usage:
  MUJOCO_GL=egl python eval_track.py --params <ckpt> --motion <npz> [--video out.mp4]
"""

import argparse
import subprocess
from pathlib import Path

import jax
import jax.numpy as jp
import mujoco
import numpy as np

if not hasattr(jax, "device_put_replicated"):
    def _dpr(x, devices):
        n = len(devices)
        st = jax.tree_util.tree_map(lambda y: jp.stack([jp.asarray(y)] * n), x)
        return jax.device_put(st, devices[0]) if n == 1 else st
    jax.device_put_replicated = _dpr

from brax.training.acme import running_statistics  # noqa: E402
from brax.training.agents.ppo import networks as ppo_networks  # noqa: E402
from mujoco import mjx  # noqa: E402
from mujoco_playground._src import mjx_env  # noqa: E402
from orbax import checkpoint as ocp  # noqa: E402

import g1_track  # noqa: E402
from g1_track import quat_rotate_inv  # noqa: E402


def front_azimuth(root_quat, offset=45.0):
    """Camera azimuth, in degrees, for a three-quarter front view derived from
    the root quaternion.

    A hardcoded azimuth breaks whenever the motion faces a different way — in
    this project it once filmed an entire clip from behind.
    """
    import numpy as _np
    w, x, y, z = root_quat
    # Direction of the body +x axis in world coordinates.
    fwd = _np.array([1 - 2 * (y * y + z * z),
                     2 * (x * y + w * z),
                     2 * (x * z - w * y)])
    facing = _np.degrees(_np.arctan2(fwd[1], fwd[0]))
    return facing + 180.0 + offset


ap = argparse.ArgumentParser()
ap.add_argument("--params", default=None)
ap.add_argument("--motion", required=True)
ap.add_argument("--video", default=None)
ap.add_argument("--start", type=int, default=0)
ap.add_argument("--fps", type=int, default=25)
# Side-by-side, so the file ends up 2*res wide. 540 gives 1080p.
ap.add_argument("--res", type=int, default=640,
                help="pixels per pane (square)")
args = ap.parse_args()

env = g1_track.G1Track(args.motion)
mj = env.mj_model
PEL = g1_track.BODY_NAMES.index("pelvis")


def state_at(idx):
    """Build the initial state exactly from a reference frame, without RSI noise."""
    ref = env._ref_at(idx)
    ang_b = quat_rotate_inv(ref["root_quat"], ref["body_angvel"][PEL])
    qpos = jp.concatenate([ref["root_pos"], ref["root_quat"], ref["joint_pos"]])
    qvel = jp.concatenate([ref["body_linvel"][PEL], ang_b, ref["joint_vel"]])
    data = mjx_env.make_data(
        mj, qpos=qpos, qvel=qvel, ctrl=ref["joint_pos"],
        impl=env.mjx_model.impl.value,
        naconmax=env._config.naconmax, njmax=env._config.njmax)
    data = mjx.forward(env.mjx_model, data)
    info = {"rng": jax.random.PRNGKey(0), "step": jp.int32(0),
            "motion_idx": jp.int32(idx), "last_act": jp.zeros(env.action_size)}
    metrics = {k: jp.zeros(()) for k in
               ["err_anchor_pos", "err_anchor_ori", "err_body_pos", "err_body_ori",
                "err_joint_pos", "r_anchor_pos", "r_anchor_ori", "r_body_pos",
                "r_body_ori", "r_body_lin_vel", "r_body_ang_vel"]}
    obs = env._get_obs(data, info)
    return mjx_env.State(data, obs, jp.zeros(()), jp.zeros(()), metrics, info)


step = jax.jit(env.step)

policy = None
if args.params:
    dummy = state_at(0)
    net = ppo_networks.make_ppo_networks(
        observation_size={k: v.shape for k, v in dummy.obs.items()},
        action_size=env.action_size,
        preprocess_observations_fn=running_statistics.normalize,
        policy_hidden_layer_sizes=(512, 256, 128),
        value_hidden_layer_sizes=(512, 256, 128),
        policy_obs_key="state", value_obs_key="privileged_state")
    raw = ocp.PyTreeCheckpointer().restore(Path(args.params).absolute())
    items = [raw[k] for k in sorted(raw.keys())] if isinstance(raw, dict) else list(raw)
    n0 = items[0]
    if isinstance(n0, dict):
        cnt = n0["count"]
        if isinstance(cnt, dict):
            cnt = jp.float32(float(cnt.get("hi", 0)) + float(cnt.get("lo", 0)))
        n0 = running_statistics.RunningStatisticsState(
            count=cnt, mean=n0["mean"], summed_variance=n0["summed_variance"],
            std=n0["std"])
    policy = jax.jit(ppo_networks.make_inference_fn(net)((n0, items[1]),
                                                        deterministic=True))


def rollout(mode):
    st = state_at(args.start)
    qs, errs = [], []
    total = env._T - 1 - args.start
    n = 0
    for t in range(total):
        if mode == "policy":
            a, _ = policy(st.obs, jax.random.PRNGKey(0))
        else:
            a = jp.zeros(env.action_size)
        st = step(st, a)
        qs.append(np.asarray(st.data.qpos).copy())
        errs.append(float(st.metrics["err_body_pos"]))
        n = t + 1
        if float(st.done) > 0:
            break
    return n, total, float(np.mean(errs)), qs


print(f"\n{'Mode':<14} {'Motion completed':>20} {'Body pos error':>16}")
print("-" * 48)
results = {}
for mode in (["zero"] + (["policy"] if policy else [])):
    n, total, e, qs = rollout(mode)
    results[mode] = qs
    label = "Zero-action" if mode == "zero" else "Policy"
    print(f"{label:<14} {n:>7}/{total} ({n/total*100:5.1f}%) {e:>16.4f} m")

# ---------------- rendering ----------------
if args.video:
    qs = results.get("policy", results["zero"])
    W = H = args.res
    mj.vis.global_.offwidth = max(mj.vis.global_.offwidth, W)
    mj.vis.global_.offheight = max(mj.vis.global_.offheight, H)
    r = mujoco.Renderer(mj, height=H, width=W)
    d = mujoco.MjData(mj)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    cam.distance, cam.elevation = 3.0, -8
    cam.azimuth = front_azimuth(np.asarray(env._ref_root_quat[0]))

    def frame(q):
        d.qpos[:] = q
        d.qvel[:] = 0
        mujoco.mj_forward(mj, d)
        cam.lookat[:] = [q[0], q[1], 0.8]
        r.update_scene(d, camera=cam)
        return r.render().astype(np.uint8)

    Path(args.video).parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt",
         "rgb24", "-s", f"{W*2}x{H}", "-r", str(args.fps), "-i", "-",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", args.video],
        stdin=subprocess.PIPE)
    skip = max(1, int(round(50 / args.fps)))
    for k in range(0, len(qs), skip):
        idx = min(args.start + k + 1, env._T - 1)
        ref_q = np.concatenate([np.asarray(env._ref_root_pos[idx]),
                                np.asarray(env._ref_root_quat[idx]),
                                np.asarray(env._ref_joint_pos[idx])])
        proc.stdin.write(np.hstack([frame(ref_q), frame(qs[k])]).tobytes())
    proc.stdin.close()
    proc.wait()
    # Close the renderer while the interpreter is still whole. Leaving it
    # to __del__ runs the EGL teardown after module globals have been
    # cleared, which prints 'Exception ignored ... TypeError: NoneType
    # object is not callable' — alarming in a log, and harmless only if
    # you already know that.
    r.close()
    print(f"\nOK  {args.video}   left = reference, right = policy")

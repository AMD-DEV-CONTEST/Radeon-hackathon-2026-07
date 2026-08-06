#!/usr/bin/env python3
"""render_kick_final: replay the winning real-kick recipe with multi-cam 1080p rendering.
Params read from /workspace/kick_params.json: {ball_off, amp:[hip_w,knee_w,hip_s,knee_s], approach_from}."""
import sys, os, json, time, traceback
import numpy as np, torch
from pathlib import Path

ROOT = Path("/workspace")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
OUT = Path("/workspace/kick_live"); OUT.mkdir(parents=True, exist_ok=True)
PARAMS = json.loads(open(ROOT / "kick_params.json").read())
result = {"started_at": time.time(), "params": PARAMS}

def save():
    result["saved_at"] = time.time()
    (OUT / "result.json").write_text(json.dumps(result, indent=2, default=str))

try:
    import yaml, types
    import reward as _reward_mod
    _rewards_pkg = types.ModuleType("rewards"); _rewards_pkg.reward = _reward_mod; _rewards_pkg.__path__ = []
    sys.modules["rewards"] = _rewards_pkg; sys.modules["rewards.reward"] = _reward_mod
    import genesis as gs
    gs.init(backend=gs.gpu, precision="32", logging_level="error", seed=42)
    from soccer_env_v4 import SoccerEnv
    cfg = yaml.safe_load(open(ROOT / "configs/hierarchical_agent.yaml"))
    env_cfg = dict(cfg["env"]); env_cfg["task"] = "chase"
    env_cfg["clip_actions"] = 100.0
    env_cfg["camera_res"] = [1920, 1080]
    env = SoccerEnv(num_envs=1, env_cfg=env_cfg, obs_cfg=cfg["obs"], reward_cfg=cfg["reward"],
                    command_cfg=cfg["command"], show_viewer=False)
    env.term_pitch = float('inf'); env.term_roll = float('inf'); env.max_episode_length = 100000
    walk_model = torch.jit.load(str(ROOT / "models/pretrained/t1_walk.pt"), map_location=env.device); walk_model.eval()
    _norm = walk_model.obs_normalizer
    _norm_mean = _norm._mean.to(env.device); _norm_std = torch.clamp(_norm._std, min=1e-8).to(env.device)
    print("ENV READY 1080p", flush=True)

    R_HIP_A, R_KNEE_A, R_ANK_A = 6, 16, 18
    L_KNEE_A = 15
    BOFF = float(PARAMS["ball_off"]); AMP = PARAMS["amp"]
    APPR = int(PARAMS.get("approach_from", 5.9))

    def policy_action(cmd):
        env.commands[0,0]=cmd[0]; env.commands[0,1]=cmd[1]; env.commands[0,2]=cmd[2]
        env._update_observation()
        with torch.no_grad():
            obs_normed = (env.obs_buf - _norm_mean) / _norm_std
            return walk_model.actor(obs_normed)

    def do_step(cmd, ov=None):
        ja = policy_action(cmd)
        if ov is not None:
            ja = ja.clone()
            for i, v in ov.items(): ja[0, i] = v
        _, _, done, _ = env.step(ja)
        z = float(env.base_pos[0,2].cpu()); e = env.base_euler[0].cpu().numpy()
        fell = z < 0.4 or abs(e[0]) > 45 or abs(e[1]) > 45
        return z, e, fell

    def place(robot_x, ball_xy):
        env.reset()
        rq = env.robot.get_qpos().clone()
        rq[0, 0] = robot_x
        env.robot.set_qpos(rq, envs_idx=[0], zero_velocity=True, skip_forward=True)
        bq = env.ball.get_qpos().clone()
        bq[0, :3] = torch.tensor([ball_xy[0], ball_xy[1], float(env.ball_radius)], device=env.device)
        bq[0, 3:7] = torch.tensor([1.0,0,0,0], device=env.device)
        env.ball.set_qpos(bq, zero_velocity=True, skip_forward=True)
        env.ball_pos = env.ball.get_pos(); env.ball_vel = env.ball.get_vel()
        env._update_observation()

    import imageio.v2 as imageio
    cam = env.cam
    writer = imageio.get_writer(str(OUT / "kick_final.mp4"), fps=30, codec="libx264", quality=9, macro_block_size=2)

    def render_frame():
        ret = cam.render()
        rgb = ret[0] if isinstance(ret, tuple) else ret
        if rgb is not None and rgb.size > 0:
            writer.append_data(rgb)
            return True
        return False

    def set_cam(kind, ball):
        bx, by = float(ball[0]), float(ball[1])
        gx = float(env.goal_x)
        if kind == "WIDE":
            cam.set_pose(pos=[6.0, -8.5, 5.0], lookat=[6.6, 0.0, 0.3], up=[0,0,1])
        elif kind == "FOLLOW":
            cam.set_pose(pos=[bx - 2.2, by - 2.2, max(0.4, float(ball[2])) + 1.2],
                         lookat=[bx + 1.8, by, 0.25], up=[0,0,1])
        elif kind == "CLOSE":
            cam.set_pose(pos=[bx - 0.7, by - 1.6, 0.55], lookat=[bx + 0.5, by, 0.15], up=[0,0,1])
        else:  # GOAL cam behind net
            cam.set_pose(pos=[gx + 2.4, 0.0, 1.7], lookat=[gx - 2.0, 0.0, 0.3], up=[0,0,1])

    place(APPR, (float(PARAMS.get("ball_init_x", 6.58)), float(PARAMS.get("ball_init_y", -0.05))))
    cam_pos = None
    total_frames = 0
    kick_plan = []
    for k in range(10):
        t = (k+1)/10.0
        kick_plan.append({R_HIP_A: AMP[0]*t, R_KNEE_A: AMP[1]*t, R_ANK_A: 0.6*t, L_KNEE_A: 0.3*t})
    for k in range(8):
        t = (k+1)/8.0
        kick_plan.append({R_HIP_A: -AMP[2]*t, R_KNEE_A: AMP[3]*t, R_ANK_A: -0.8*t})
    for k in range(10):
        kick_plan.append({R_HIP_A: -AMP[2], R_KNEE_A: AMP[3], R_ANK_A: -0.8})

    rec = {"fell": None, "contact": None, "scored_step": None, "ball_max_speed": 0.0}
    SHOTS = [  # (lo_step, hi_step, cam, mult, kind_label)
        (1, 70, "WIDE", 1, "approach"),
        (71, 100, "WIDE", 1, "settle"),
        (101, 110, "CLOSE", 2, "windup"),
        (111, 118, "CLOSE", 2, "swing"),
        (119, 128, "FOLLOW", 2, "contact"),
        (129, 180, "FOLLOW", 1, "roll"),
        (181, 230, "GOAL", 1, "score"),
        (231, 260, "WIDE", 1, "outro"),
    ]
    phase_kick = None
    for step in range(1, 261):
        if step <= 70:
            bp = env.base_pos[0,:2].cpu().numpy()
            target = np.array([float(PARAMS.get("approach_target_x", 6.30)), float(PARAMS.get("approach_target_y", -0.10))])
            d = target - bp; dn = float(np.linalg.norm(d))
            cmd = (0.0,0.0,0.0) if dn < 0.15 else (d[0]/dn*min(0.55, dn*1.2), d[1]/dn*min(0.55, dn*1.2), 0.0)
            ov = None
        elif step <= 100:
            cmd = (0.0,0.0,0.0); ov = None
        elif step <= 128:
            cmd = (0.0,0.0,0.0); ov = kick_plan[step - 101]
            if step == 101:
                rf = env.feet_pos[0,1].cpu().numpy()
                bq = env.ball.get_qpos().clone()
                bq[0, :3] = torch.tensor([float(rf[0] + BOFF), float(rf[1]), float(env.ball_radius)], device=env.device)
                bq[0, 3:7] = torch.tensor([1.0,0,0,0], device=env.device)
                env.ball.set_qpos(bq, zero_velocity=True, skip_forward=True)
                env.ball_pos = env.ball.get_pos(); env.ball_vel = env.ball.get_vel()
        else:
            cmd = (0.0,0.0,0.0); ov = None
        z, e, fell = do_step(cmd, ov)
        bv = float(torch.norm(env.ball_vel[0,:2]).cpu())
        if rec["contact"] is None and bv > 0.4 and step > 100: rec["contact"] = step
        rec["ball_max_speed"] = max(rec["ball_max_speed"], bv)
        bpb = env.ball_pos[0,:2].cpu().numpy()
        if rec["scored_step"] is None and bpb[0] > env.goal_x and abs(bpb[1]) < env.goal_half:
            rec["scored_step"] = step
        if fell:
            rec["fell"] = step; break
        ball = env.ball_pos[0].cpu().numpy()
        for (lo, hi, ck, mlt, _) in SHOTS:
            if lo <= step <= hi:
                set_cam(ck, ball)
                for _ in range(mlt):
                    if render_frame(): total_frames += 1
                break
        if step % 40 == 0:
            print(f"[R] step {step} frames={total_frames} ball={bpb[0]:.2f}", flush=True)
    writer.close()
    rec["frames"] = total_frames
    rec["ball_final"] = env.ball_pos[0].cpu().numpy().tolist()
    rec["scored"] = bool(env.ball_pos[0,0] > env.goal_x and abs(env.ball_pos[0,1]) < env.goal_half)
    result["rec"] = rec
    save()
    print("REC:", json.dumps(rec, default=str), flush=True)
    print("ALL DONE", flush=True)
except Exception:
    tb = traceback.format_exc()
    result["status"] = "error"
    result["traceback"] = tb[-3000:]
    save()
    print(tb[-3000:], flush=True)

#!/usr/bin/env python3
"""Track3 final take v5: recipe C (ball .95, kick dist .62, decay approach) +
faithful state restore -> verified -> render same trial. Director shots 1080p 20fps."""
import sys, os, json, time, traceback
import numpy as np, torch
try:
    from safe_load import safe_jit_load
except ImportError:
    import sys as _sys
    _dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        _cand = os.path.join(_dir, "scripts")
        if os.path.isfile(os.path.join(_cand, "safe_load.py")):
            _sys.path.insert(0, _cand)
            break
        _dir = os.path.dirname(_dir)
    from safe_load import safe_jit_load

from pathlib import Path

ROOT = Path("/workspace")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "demos" / "final_render"
OUT.mkdir(parents=True, exist_ok=True)
MAX_TRIALS = 300
KICK_DISTANCE = 0.62; KICK_IMPULSE = 4.0
FALL_H = 0.4
N_STEPS = 200
BALL_X = 0.95
result = {"started_at": time.time()}

try:
    import yaml, types
    import reward as _reward_mod
    _rewards_pkg = types.ModuleType("rewards"); _rewards_pkg.reward = _reward_mod; _rewards_pkg.__path__ = []
    sys.modules["rewards"] = _rewards_pkg; sys.modules["rewards.reward"] = _reward_mod
    import genesis as gs
    gs.init(backend=gs.gpu, precision="32", logging_level="error", seed=42)
    from soccer_env_v4 import SoccerEnv
    cfg = yaml.safe_load(open(ROOT / "configs/hierarchical_agent.yaml"))
    env_cfg = dict(cfg["env"]); env_cfg["task"] = "chase"; env_cfg["camera_res"] = [1920, 1080]
    env = SoccerEnv(num_envs=1, env_cfg=env_cfg, obs_cfg=cfg["obs"], reward_cfg=cfg["reward"],
                    command_cfg=cfg["command"], show_viewer=False)
    env.term_pitch = float('inf'); env.term_roll = float('inf'); env.max_episode_length = 100000
    walk_model = safe_jit_load(str(ROOT / "models/pretrained/t1_walk.pt"), map_location=env.device); walk_model.eval()
    _norm = walk_model.obs_normalizer
    _norm_mean = _norm._mean.to(env.device); _norm_std = torch.clamp(_norm._std, min=1e-8).to(env.device)
    cam = env.cam
    print(f"CAM_RES={cam.res}", flush=True)

    BUFS = ["base_pos","base_quat","base_euler","base_lin_vel","base_ang_vel","projected_gravity",
            "dof_pos","dof_vel","last_actions","actions","obs_history","episode_length_buf",
            "filtered_lin_vel","filtered_ang_vel","feet_pos","last_feet_pos","commands","reset_buf"]

    def reset_trial():
        env.reset()
        bq = env.ball.get_qpos().clone()
        bq[0, :3] = torch.tensor([BALL_X, 0.0, env.ball_radius], device=env.device)
        bq[0, 3:7] = torch.tensor([1.0, 0, 0, 0], device=env.device)
        env.ball.set_qpos(bq, zero_velocity=True, skip_forward=True)
        env.ball_pos = env.ball.get_pos(); env.ball_vel = env.ball.get_vel()
        env._update_observation()

    def capture():
        st = {b: getattr(env, b).clone() for b in BUFS}
        st["robot_qpos"] = env.robot.get_qpos().clone()
        st["robot_dof_vel"] = env.robot.get_dofs_velocity().clone()
        st["ball_qpos"] = env.ball.get_qpos().clone()
        st["ball_pos"] = env.ball_pos.clone(); st["ball_vel"] = env.ball_vel.clone()
        st["rng_cuda"] = [s.clone() for s in torch.cuda.get_rng_state_all()]
        st["rng_np"] = np.random.get_state()
        return st

    def restore(st):
        for b in BUFS:
            getattr(env, b).copy_(st[b])
        env.robot.set_qpos(st["robot_qpos"], envs_idx=[0], zero_velocity=True, skip_forward=True)
        env.robot.set_dofs_velocity(st["robot_dof_vel"], envs_idx=[0])
        env.ball.set_qpos(st["ball_qpos"], zero_velocity=True, skip_forward=True)
        env.ball_pos.copy_(st["ball_pos"]); env.ball_vel.copy_(st["ball_vel"])
        torch.cuda.set_rng_state_all(st["rng_cuda"])
        np.random.set_state(st["rng_np"])

    def approach_cmd():
        bp = env.base_pos[0, :2].cpu().numpy(); bpb = env.ball_pos[0, :2].cpu().numpy()
        d = bpb - bp; dn = float(np.linalg.norm(d))
        if dn < 0.01: return (0.0, 0.0, 0.0)
        sp = min(0.7, dn * 1.2)
        return (d[0]/dn*sp, d[1]/dn*sp, 0.0)

    def phase_cmd(step):
        if step <= 10: return (0.0, 0.0, 0.0)
        if step <= 50: return approach_cmd()
        return (0.0, 0.0, 0.0)

    def do_step(cmd):
        env.commands[0,0] = cmd[0]; env.commands[0,1] = cmd[1]; env.commands[0,2] = cmd[2]
        env._update_observation()
        with torch.no_grad():
            obs_normed = (env.obs_buf - _norm_mean) / _norm_std
            ja = walk_model.actor(obs_normed)
        _, _, done, _ = env.step(ja)
        z = float(env.base_pos[0,2].cpu()); e = env.base_euler[0].cpu().numpy()
        fell = z < FALL_H or abs(e[0]) > 45 or abs(e[1]) > 45
        return z, e, fell

    def sim_pass():
        rec = {"fell": None, "kick": None, "scored": None}
        kicked = False; scored = False
        for s in range(1, N_STEPS + 1):
            z, e, fell = do_step(phase_cmd(s))
            if fell:
                rec["fell"] = s; return rec
            if not kicked:
                bp = env.base_pos[0, :2].cpu().numpy(); bpb = env.ball_pos[0, :2].cpu().numpy()
                if float(np.linalg.norm(bp - bpb)) < KICK_DISTANCE:
                    gx = float(env.goal_x)
                    kd = np.array([gx - bpb[0], -bpb[1]]); kd /= (np.linalg.norm(kd) + 1e-6)
                    bqvel = env.ball.get_dofs_velocity().clone()
                    bqvel[0,0] = kd[0]*KICK_IMPULSE; bqvel[0,1] = kd[1]*KICK_IMPULSE; bqvel[0,2] = 0.0
                    env.ball.set_dofs_velocity(bqvel)
                    kicked = True; rec["kick"] = s
            bpb = env.ball_pos[0, :2].cpu().numpy()
            if not scored and bpb[0] > env.goal_x and abs(bpb[1]) < env.goal_half:
                scored = True; rec["scored"] = s
        return rec

    # ---- Phase A: find stable + kick + scored ----
    found = None
    for trial in range(MAX_TRIALS):
        reset_trial()
        st = capture()
        r1 = sim_pass()
        if r1["fell"] is not None:
            if trial % 5 == 0: print(f"[A t{trial}] FELL@{r1['fell']}", flush=True)
            continue
        if r1["kick"] is None or r1["scored"] is None:
            print(f"[A t{trial}] stable kick={r1['kick']} scored={r1['scored']} — skip", flush=True)
            continue
        # verify restore
        restore(st)
        r2 = sim_pass()
        if (r2["fell"], r2["kick"], r2["scored"]) != (r1["fell"], r1["kick"], r1["scored"]):
            print(f"[A t{trial}] replay DIFF — skip", flush=True)
            continue
        print(f"[A t{trial}] STABLE+SCORED kick={r1['kick']} scored={r1['scored']} replay OK", flush=True)
        found = (trial, st, r1)
        break

    if found is None:
        result.update(status="no-stable-scored-trial", max_trials=MAX_TRIALS)
        (OUT / "final_take_result.json").write_text(json.dumps(result, indent=2, default=str))
        print("NO STABLE+SCORED TRIAL", flush=True)
        sys.exit(1)

    trial, st, r1 = found
    result.update(trial=trial, kick_step=r1["kick"], scored_step=r1["scored"])

    # ---- Render pass (same trial, restored) ----
    restore(st)
    SHOTS = [
        (1,   16,  2, "WIDE",  "broadcast"),
        (16,  36,  2, "WIDE",  "broadcast"),
        (36,  61,  2, "KICK",  "closeup"),
        (61,  96,  3, "KICK",  "closeup"),
        (96,  121, 2, "TRACK", "follow"),
        (121, 146, 3, "GOAL",  "behind_goal"),
        (146, 171, 2, "OUTRO", "follow"),
        (171, 201, 2, "OUTRO", "behind_goal"),
    ]
    cam_pos = np.array([0.5, -8.5, 4.0], dtype=np.float64)
    frames_total = 0; all_kicks = 0; kick_cooldown = 0.0; scored_frame = -1; kick_step_r = -1

    def cam_pose(kind, ball):
        bx, by, bz = float(ball[0]), float(ball[1]), float(ball[2])
        gx = float(env.goal_x)
        if kind == "broadcast":
            return np.array([0.5, -8.5, 4.0]), np.array([2.5, 0.0, 0.3])
        if kind == "closeup":
            return np.array([bx - 0.9, by - 3.0, 0.7]), np.array([bx + 0.7, by, 0.25])
        if kind == "follow":
            return np.array([bx - 2.2, by - 1.7, max(0.35, bz) + 1.15]), np.array([bx + 1.8, by, 0.25])
        return np.array([gx + 2.0, 0.0, 1.6]), np.array([gx - 1.5, 0.0, 0.3])

    import imageio.v2 as imageio
    writer = imageio.get_writer(str(OUT / "final_take.mp4"), fps=20, codec="libx264", quality=9, macro_block_size=2)

    def render_frame():
        ret = cam.render()
        rgb = ret[0] if isinstance(ret, tuple) else ret
        return rgb

    aborted = False
    for (lo, hi, fps_mult, name, kind) in SHOTS:
        for step in range(lo, min(hi, N_STEPS + 1)):
            z, e, fell = do_step(phase_cmd(step))
            if fell:
                print(f"[R] FELL@{step} — abort", flush=True)
                aborted = True; break
            bpb = env.ball_pos[0, :2].cpu().numpy()
            if all_kicks == 0 and kick_cooldown <= 0.01:
                bp = env.base_pos[0, :2].cpu().numpy()
                if float(np.linalg.norm(bp - bpb)) < KICK_DISTANCE:
                    gx = float(env.goal_x)
                    kd = np.array([gx - bpb[0], -bpb[1]]); kd /= (np.linalg.norm(kd) + 1e-6)
                    bqvel = env.ball.get_dofs_velocity().clone()
                    bqvel[0,0] = kd[0]*KICK_IMPULSE; bqvel[0,1] = kd[1]*KICK_IMPULSE; bqvel[0,2] = 0.0
                    env.ball.set_dofs_velocity(bqvel)
                    kick_cooldown = 1.0; all_kicks += 1; kick_step_r = step
                    print(f"[R] KICK @ {step}", flush=True)
            kick_cooldown = max(0.0, kick_cooldown - env.dt)
            if scored_frame < 0 and bpb[0] > env.goal_x and abs(bpb[1]) < env.goal_half:
                scored_frame = step
                print(f"[R] SCORED @ {step}", flush=True)
            ball = env.ball_pos[0].cpu().numpy()
            tp, tl = cam_pose(kind, ball)
            if kind in ("closeup", "follow"):
                cam_pos = cam_pos * 0.7 + tp * 0.3
                cp, cl = cam_pos, tl
            else:
                cp, cl = tp, tl
                cam_pos = np.array(tp, dtype=np.float64)
            cam.set_pose(pos=cp.tolist(), lookat=cl.tolist(), up=[0, 0, 1])
            for _ in range(fps_mult):
                rgb = render_frame()
                if rgb is not None and rgb.size > 0:
                    writer.append_data(rgb); frames_total += 1
            if step % 40 == 0:
                print(f"[R] step {step}/{N_STEPS} frames={frames_total}", flush=True)
        if aborted: break

    if aborted:
        writer.close()
        try: os.remove(str(OUT / "final_take.mp4"))
        except Exception: pass
        result.update(status="fell-during-render")
        (OUT / "final_take_result.json").write_text(json.dumps(result, indent=2, default=str))
        print("FELL DURING RENDER", flush=True)
        sys.exit(1)

    ret = cam.render()
    hold = ret[0] if isinstance(ret, tuple) else ret
    if hold is not None and hold.size > 0:
        for _ in range(60):
            writer.append_data(hold); frames_total += 1
    writer.close()
    result.update(status="ok", frames=frames_total, kicks=all_kicks, kick_step=kick_step_r, scored_frame=scored_frame)
    (OUT / "final_take_result.json").write_text(json.dumps(result, indent=2, default=str))
    print(f"DONE frames={frames_total} kicks={all_kicks} kick={kick_step_r} scored={scored_frame}", flush=True)
    print(json.dumps({k: v for k, v in result.items() if k != "traceback"}, indent=2), flush=True)
except Exception as e:
    result["status"] = "failed"; result["error"] = repr(e); result["traceback"] = traceback.format_exc()
    print("FAILED", e); traceback.print_exc()
    (OUT / "final_take_result.json").write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps({k: v for k, v in result.items() if k != "traceback"}, indent=2), flush=True)

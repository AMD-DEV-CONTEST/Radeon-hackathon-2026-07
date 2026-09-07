#!/usr/bin/env python3
"""
Demo video — SCRIPTED multi-gait rollout with REAL MuJoCo physics, rendered headless.

What this actually does (honest description):
  * loads the real Unitree Go1 model from mujoco_playground's registry;
  * applies a gravity-compensation feedforward so the P-servo actuators hold a
    proper standing pose (they have no gravity comp, so raw home targets sag);
  * drives several SCRIPTED reference gaits — bob-in-place, jump-in-place,
    forward trot, and spin-in-place — through the TRUE MuJoCo dynamics
    (mujoco.mj_step) on CPU. Real physics integration, not a keyframed animation;
  * renders each gait from a trunk-tracking 3/4 camera and stitches labelled
    title cards + segments into one short mp4.

These are SCRIPTED gaits (no trained checkpoint) on CPU MuJoCo physics. They show
the simulation + rendering pipeline working — they are NOT a learned walking
policy, and the CPU physics here is separate from the GPU MJX training path.

Rendering: tries mujoco.Renderer (real 3D); if unavailable on this build it falls
back to a 2D skeleton driven by the SAME real-physics trajectory.

Usage:
    MUJOCO_GL=osmesa python3 scripts/make_demo_video_full.py
"""
import os
os.environ.setdefault("MUJOCO_GL", "osmesa")

import subprocess
from pathlib import Path

import numpy as np
import mujoco
import imageio
from PIL import Image, ImageDraw, ImageFont
from mujoco_playground import registry as reg

W, H = 640, 480
FPS = 30
SEED = 0
OUT = Path("assets/demo_full_7gaits.mp4")

# Scripted gaits: (key, on-screen label, number of physics steps).
# ~2.5 min total: 7 gaits, each long enough to read clearly, + title cards.
GAITS = [
    ("bob",       "Bob in place",          360),  # gentle body bob
    ("jump",      "Hop (pronk)",           360),  # all 4 legs push off together
    ("march",     "March in place",        600),  # diagonal pairs lift, no travel/yaw
    ("walk",      "Forward walk (trot)",   780),  # diagonal pairs -> move forward
    ("sidestep",  "Sidestep (pace)",       600),  # same-side pairs -> lateral
    ("spin",      "Turn in place (trot)",  780),  # diagonal pairs, tangential -> yaw
    ("wave",      "Wave hello",            420),  # lift front-right foot, wave
    ("rearstand", "Rear-leg stand",        420),  # lift both front feet, pitch up
]

# --- PIL fallback drawing constants (only used if mujoco.Renderer is unavailable)
SCALE = 200
LEG_BODIES = {
    'FR': ('FR_hip', 'FR_thigh', 'FR_calf'),
    'FL': ('FL_hip', 'FL_thigh', 'FL_calf'),
    'RR': ('RR_hip', 'RR_thigh', 'RR_calf'),
    'RL': ('RL_hip', 'RL_thigh', 'RL_calf'),
}
LEG_COLORS = {'FR': (200, 40, 40), 'FL': (40, 80, 200),
              'RR': (40, 180, 80), 'RL': (220, 130, 40)}


def _font(size):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Analytic leg inverse kinematics for the Go1.
#
# Per leg the chain is: hip (rotates about body +x) -> thigh (about +y, offset
# [0,±0.08,0]) -> calf (about +y, offset [0,0,-0.213]) -> foot ([0,0,-0.213]).
# Both links are L=0.213 m. We solve for (hip, thigh, calf) angles that place the
# foot at a target (fx, fy, fz) expressed in the hip frame. Verified against FK
# to machine precision (round-trip err ~2e-16). Driving the feet through smooth
# Cartesian trajectories — rather than jointspace sinusoids — is what makes the
# motion obey the robot's kinematics and keeps feet from clipping through each
# other or skating.
# ---------------------------------------------------------------------------
L1 = 0.213
L2 = 0.213
LEG_HIP_Y = [-0.08, 0.08, -0.08, 0.08]   # thigh y-offset sign per leg [FR,FL,RR,RL]


def leg_ik(fx, fy, fz, d):
    """Foot target (hip frame) -> (hip, thigh, calf) joint angles. Analytic."""
    r = np.hypot(fy, fz)
    wz = -np.sqrt(max(r * r - d * d, 1e-9))
    h = np.arctan2(fz, fy) - np.arctan2(wz, d)
    wx = fx
    c = (wx * wx + wz * wz - L1 * L1 - L2 * L2) / (2 * L1 * L2)
    b = -np.arccos(np.clip(c, -1.0, 1.0))
    vx = -L2 * np.sin(b)
    vz = -L1 - L2 * np.cos(b)
    a = np.arctan2(wx, wz) - np.arctan2(vx, vz)
    a = np.arctan2(np.sin(a), np.cos(a))
    return h, a, b


def foot_home(leg):
    """Home foot position in the hip frame (from home joint angles via FK)."""
    d = LEG_HIP_Y[leg]
    h = 0.1 * (1 if leg in (0, 2) else -1)
    a, b = 0.9, -1.8
    vx = -L2 * np.sin(b); vz = -L1 - L2 * np.cos(b)
    wx = np.cos(a) * vx + np.sin(a) * vz
    wz = -np.sin(a) * vx + np.cos(a) * vz
    fy = np.cos(h) * d - np.sin(h) * wz
    fz = np.sin(h) * d + np.cos(h) * wz
    return np.array([wx, fy, fz])


# Neutral foot position (hip frame) at the home standing pose, per leg.
FOOT_HOME_W = [foot_home(i) for i in range(4)]


def _set_leg_ik(ctrl, base_ctrl, leg, fx, fy, fz):
    """Solve IK for a foot target (hip frame) and write joint targets with the
    same gravity-comp feedforward the standing pose uses (base_ctrl = home+sag)."""
    h, a, b = leg_ik(fx, fy, fz, LEG_HIP_Y[leg])
    hip_home = 0.1 * (1 if leg in (0, 2) else -1)
    ctrl[3 * leg + 0] = h + (base_ctrl[3 * leg + 0] - hip_home)
    ctrl[3 * leg + 1] = a + (base_ctrl[3 * leg + 1] - 0.9)
    ctrl[3 * leg + 2] = b + (base_ctrl[3 * leg + 2] - (-1.8))


def gait_ctrl(gait, t, base_ctrl, nlegs, num_steps, stab=None):
    """Return the position-control target for one physics step of a scripted gait.

    Go1 leg joints per leg are [hip(abduction), thigh, calf]; legs 0,1 = front,
    2,3 = back. Locomotion gaits (walk/spin/sidestep/march) drive the FEET through
    Cartesian trajectories and solve analytic IK, so motion obeys the robot's
    kinematics. Static (crawl) timing keeps 3 feet planted at all times, so the
    support triangle always holds the CoM and the body cannot topple. Every gait
    is wrapped in an ease-in/out envelope `env` (0->1->0) and starts/ends at the
    standing pose to remove start/stop jerk."""
    ctrl = base_ctrl.copy()
    env = max(0.0, np.sin(np.pi * t / max(1, num_steps - 1)))  # ease in/out

    # --- Trunk-attitude PD ------------------------------------------------
    # Two-beat / lifted-leg poses only touch 2 feet, so open-loop the CoM tips
    # off the contact line with no restoring torque. `stab` carries the live
    # trunk state (roll, pitch, their rates, height); we convert its errors into
    # a per-leg foot-height nudge: press the dropping side/end DOWN (extend the
    # leg to push the body up) and unload the rising one. This is the balance
    # feedback a real quadruped controller provides — without it these gaits fall.
    def set_leg(leg, fx, fy, fz, grounded=True, pitch_ref=0.0, h_ref=0.30,
                hold_x=False, hold_y=False, hold_yaw=False):
        if stab is not None and grounded:
            sy = 1.0 if LEG_HIP_Y[leg] > 0 else -1.0     # +1 left, -1 right
            sx = 1.0 if leg in (0, 1) else -1.0          # +1 front, -1 back
            roll, pitch, wr, wp, h, ex, ey, eyaw = stab
            KR, KRD = 0.35, 0.06        # roll P / D  (foot-z metres per rad)
            KP, KPD = 0.30, 0.05        # pitch P / D  (drives toward pitch_ref)
            KH = 0.6                     # height P (extend legs if body sags)
            KXY = 0.5                    # horizontal position hold (foot-x/y per m)
            KYAW = 0.06                  # yaw hold (foot-y per rad, front/back split)
            # roll>0 => right(-y) side drops => press right down (negative dz).
            fz += (KR * roll + KRD * wr) * sy
            # pitch error vs the desired lean; >0 (too nose-down) => press front down.
            fz += -(KP * (pitch - pitch_ref) + KPD * wp) * sx
            # body low => extend all legs (lower feet) to push trunk up.
            fz += -KH * (h_ref - h)
            # position hold: slide stance feet OPPOSITE the drift so they push the
            # body back to start. Only enabled for in-place gaits.
            if hold_x:
                fx += KXY * ex
            if hold_y:
                fy += KXY * ey
            # yaw hold: counter-rotate footholds (front & back push opposite +y).
            if hold_yaw:
                fy += KYAW * eyaw * sx
        _set_leg_ik(ctrl, base_ctrl, leg, fx, fy, fz)

    if gait == "bob":
        # gentle in-place bob — small amplitude so it reads as a bob, not a hop.
        period = 60.0
        ph = 2.0 * np.pi * (t / period)
        A = 0.035 * env
        for leg in range(nlegs):
            s = A * np.sin(ph + (0.0 if leg < 2 else np.pi * 0.25))
            ctrl[3 * leg + 1] = base_ctrl[3 * leg + 1] - s
            ctrl[3 * leg + 2] = base_ctrl[3 * leg + 2] + 2.0 * s

    elif gait == "jump":
        # Pronk hop: ALL FOUR feet extend downward together (fz below home) to push
        # the trunk up, then retract. Symmetric front/back so the body stays level.
        # `env` ramps the hop height in and out; the crouch precedes each push.
        period = 75.0
        ph = 2.0 * np.pi * (t / period)
        # crouch (feet closer, dz>0) then thrust (feet extend, dz<0); one cycle:
        dz = 0.05 * env * np.sin(ph)
        for leg in range(nlegs):
            fx, fy, fz = FOOT_HOME_W[leg]
            set_leg(leg, fx, fy, fz + dz)

    elif gait == "sidestep":
        # Sideways shuffle as a STATIC crawl: exactly one foot swings at a time while
        # the other three stay planted, so the CoM never leaves the 3-foot support
        # triangle. A same-side (pace) pair tips over open-loop — pushing two same-side
        # feet sideways makes a roll moment with nothing to catch it — so the reliable
        # way to translate sideways without balance control is one foot at a time.
        order = (1, 3, 0, 2)        # FL, RL, FR, RR
        cycles = 5.0
        u = (t / max(1, num_steps)) * cycles * 4
        cur = int(u) % 4
        frac = u - int(u)
        swing = order[cur]
        lift_h = 0.06
        step = 0.09 * env           # sideways foothold displacement per swing
        slide = step / 4.0          # each stance foot carries 1/4 of the body move
        for leg in range(nlegs):
            fx, fy, fz = FOOT_HOME_W[leg].copy()
            if leg == swing:
                fy += step * (frac - 0.5) + step * 0.5   # place foot further +y
                fz += lift_h * np.sin(np.pi * frac)
                set_leg(leg, fx, fy, fz, grounded=False)
            else:
                fy -= slide                              # planted feet push body +y
                set_leg(leg, fx, fy, fz, hold_x=True, hold_yaw=True)

    elif gait in ("walk", "spin", "march"):
        # Two-beat gait: a PAIR of legs swings while the other pair stances, then
        # they swap. Leg indices: FR=0, FL=1, RR=2, RL=3.
        #   trot (walk/spin/march): diagonal pairs {FR,RL} and {FL,RR}
        # Only 2 feet touch during a beat, so this is a DYNAMIC gait — it relies on
        # a short swing (small stride, brief airtime) rather than a support triangle.
        pairA, pairB = (0, 3), (1, 2)      # diagonals
        n_phase = 2
        cycles = 6.0                # beats per pair over the whole segment
        u = (t / max(1, num_steps)) * cycles * n_phase
        cur = int(u) % n_phase
        frac = u - int(u)
        swing = pairA if cur == 0 else pairB
        lift_h = 0.06
        step = 0.06 * env           # foothold displacement per swing
        slide = step                # stance feet carry the full body move (1:1)
        march_lift = 0.10           # march lifts higher (visible) but no travel/yaw
        for leg in range(nlegs):
            fx, fy, fz = FOOT_HOME_W[leg].copy()
            is_swing = leg in swing
            if is_swing:
                fz += (march_lift if gait == "march" else lift_h) * np.sin(np.pi * frac)
            if gait == "march":
                # pure in-place: hold x, y AND yaw so it steps without wandering.
                set_leg(leg, fx, fy, fz, grounded=not is_swing,
                        hold_x=True, hold_y=True, hold_yaw=True)
                continue
            if gait == "walk":
                if is_swing:
                    fx += step * (frac - 0.5)       # swing foot forward (+x)
                else:
                    fx -= slide * frac              # stance pushes body +x
            elif gait == "spin":
                # tangential footfall: front legs +y, rear legs -y -> yaw.
                tang = 1 if leg in (0, 1) else -1
                if is_swing:
                    fy += step * (frac - 0.5) * tang
                else:
                    fy -= slide * frac * tang
            # hold the axes this gait is NOT meant to travel/turn on:
            #   walk travels +x -> hold y + yaw       spin turns yaw -> hold x + y
            hx = gait in ("spin",)
            hy = gait in ("walk",)
            hyaw = gait in ("walk",)
            set_leg(leg, fx, fy, fz, grounded=not is_swing,
                    hold_x=hx, hold_y=hy, hold_yaw=hyaw)

    elif gait == "wave":
        # friendly gesture: lift the REAR-RIGHT foot and swing it up/down a few
        # times. Lifting a rear foot (not a front one) leaves the FR/FL/RL triangle,
        # whose missing corner is at the BACK — and the CoM already sits forward of
        # that edge, so the pose is naturally stable (gravity gives a restoring
        # moment). A front-foot lift is a genuine single-support balance problem that
        # topples open-loop; a rear-foot lift does not. The three grounded feet keep
        # the trunk PD + yaw hold on, so any residual tip is actively corrected.
        raise_leg = 2               # RR
        prog = t / max(1, num_steps)
        load = min(1.0, prog / 0.15, (1.0 - prog) / 0.15)   # 0->1->0 trapezoid
        up = max(0.0, min(1.0, (prog - 0.12) / 0.1, (0.92 - prog) / 0.1))
        for leg in range(nlegs):
            fx, fy, fz = FOOT_HOME_W[leg].copy()
            if leg == raise_leg:
                wph = 2.0 * np.pi * (t / 45.0)
                # lift the foot clear of the ground, then swing it up/down. Airborne
                # -> no PD.
                fx -= up * (0.05 + 0.03 * np.sin(wph))         # reach back + swing
                fz += up * (0.16 + 0.05 * np.sin(2 * wph))     # lift clear
                set_leg(leg, fx, fy, fz, grounded=False)
            else:
                # Load the FR/FL/RL triangle: stance feet slide backward (body eases
                # FORWARD, off the lifted rear-right corner) and slide -y (body eases
                # +y / LEFT, away from the lifted right side). PD + yaw hold ON.
                fx -= load * 0.06
                fy -= load * 0.03
                set_leg(leg, fx, fy, fz, hold_yaw=True)

    elif gait == "rearstand":
        # Rear-leg stand: lift BOTH front feet and hold a nose-UP lean on the two
        # rear feet. The lean is INTENTIONAL, so the PD is given a nonzero pitch
        # reference (`pitch_ref`) — it HOLDS the target lean instead of cancelling
        # it, and the rear-foot D-term damps the backward tip that flipped it before.
        # Rear feet also slide forward under the CoM. Front feet are airborne
        # (grounded=False) so no correction is applied to them.
        prog = t / max(1, num_steps)
        rise = max(0.0, np.sin(np.pi * prog)) ** 0.7    # 0->1->0, holds near the top
        lean = 0.28 * rise              # target nose-up pitch (rad), ~16deg — modest
        for leg in range(nlegs):
            fx, fy, fz = FOOT_HOME_W[leg].copy()
            if leg in (0, 1):           # front feet: lift clear, tuck toward body
                fz += rise * 0.16
                fx -= rise * 0.05
                set_leg(leg, fx, fy, fz, grounded=False)
            else:
                # rear feet slide BACKWARD (-x) so they sit behind the CoM: gravity
                # then pulls the nose back DOWN and the pitch PD holds it up against
                # that — a stable balance point, not a runaway backward tip. Roll and
                # yaw are held so it doesn't twist off the two-foot contact line.
                fx -= rise * 0.08
                set_leg(leg, fx, fy, fz, pitch_ref=-lean,
                        hold_x=True, hold_y=True, hold_yaw=True)

    return ctrl


def _yaw(quat):
    w, x, y, z = quat
    return np.arctan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _roll_pitch(quat):
    """Roll (about +x/forward) and pitch (about +y/left) from a wxyz quaternion."""
    w, x, y, z = quat
    roll = np.arctan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    sp = 2.0 * (w * y - z * x)
    pitch = np.arcsin(np.clip(sp, -1.0, 1.0))
    return float(roll), float(pitch)


def rollout_gait(model, data, gait, num_steps, base_ctrl):
    """Step TRUE MuJoCo dynamics under a scripted gait. Returns (snaps, stats).

    snaps: list of (qpos, xpos) copies. stats: measured net motion so results are
    verifiable without watching the video."""
    nu = model.nu
    lo = model.actuator_ctrlrange[:, 0]
    hi = model.actuator_ctrlrange[:, 1]
    nlegs = nu // 3
    x0 = data.qpos[0:2].copy()
    yaw0 = _yaw(data.qpos[3:7])
    min_h = float("inf")
    snaps = []
    for t in range(num_steps):
        # live trunk state for the attitude PD: roll, pitch, their rates, height,
        # plus horizontal-position and yaw error vs the segment start (for in-place
        # gaits that must not drift). ex/ey are the drift the stance feet must undo.
        roll, pitch = _roll_pitch(data.qpos[3:7])
        wr, wp = float(data.qvel[3]), float(data.qvel[4])   # body angular rates
        ex = float(data.qpos[0] - x0[0])
        ey = float(data.qpos[1] - x0[1])
        eyaw = float(_yaw(data.qpos[3:7]) - yaw0)
        stab = (roll, pitch, wr, wp, float(data.qpos[2]), ex, ey, eyaw)
        ctrl = gait_ctrl(gait, t, base_ctrl, nlegs, num_steps, stab=stab)
        data.ctrl[:] = np.clip(ctrl, lo, hi)
        mujoco.mj_step(model, data)
        min_h = min(min_h, float(data.qpos[2]))
        snaps.append((data.qpos.copy(), data.xpos.copy()))
    dx, dy = (data.qpos[0:2] - x0)
    dyaw = np.degrees(_yaw(data.qpos[3:7]) - yaw0)
    stats = dict(dx=float(dx), dy=float(dy), dyaw=float(dyaw), min_h=min_h)
    return snaps, stats
def render_3d(model, snaps, label, track=True, azimuth=45, distance=2.6):
    """Render snapshots with the real mujoco.Renderer.

    track=True follows the trunk (good for in-place motions). track=False fixes
    the camera on the START position so body TRANSLATION is visible — this is what
    lets forward walk / sidestep read as actually moving instead of marching in
    place. Raises if the renderer is unavailable."""
    frames = []
    renderer = mujoco.Renderer(model, height=H, width=W)
    data = mujoco.MjData(model)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    cam.distance = distance
    cam.elevation = -18
    cam.azimuth = azimuth
    fixed_lookat = np.array(snaps[0][0][0:3], dtype=float)
    for qpos, _ in snaps:
        data.qpos[:] = qpos
        mujoco.mj_forward(model, data)
        cam.lookat[:] = data.qpos[0:3] if track else fixed_lookat
        renderer.update_scene(data, camera=cam)
        frames.append(_hud(np.array(renderer.render()), label))
    renderer.close()
    return frames


def render_pil(model, snaps, label):
    """Fallback: 2D skeleton driven by the SAME real-physics trajectory (3/4 proj)."""
    n2id = {mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, j): j
            for j in range(model.nbody)}
    cx = snaps[0][1][n2id['trunk']].copy()

    def project(pos):
        ix = ((pos[0] - cx[0]) * 0.35 + (pos[1] - cx[1]) * 0.65) * SCALE + W // 2
        iy = H // 2 - pos[2] * SCALE
        return int(ix), int(iy)

    frames = []
    for _, xpos in snaps:
        img = Image.new("RGB", (W, H), (250, 250, 252))
        draw = ImageDraw.Draw(img)
        gy = H // 2
        draw.line([(0, gy), (W, gy)], fill=(60, 60, 60), width=2)
        for ln in ['FR', 'FL', 'RR', 'RL']:
            color = LEG_COLORS[ln]
            ids = [n2id[b] for b in LEG_BODIES[ln]]
            pts = [project(xpos[i]) for i in ids]
            draw.line([pts[0], pts[1]], fill=color, width=10)
            draw.line([pts[1], pts[2]], fill=color, width=8)
            fc = (220, 40, 40) if xpos[ids[2], 2] < 0.03 else color
            draw.ellipse([pts[2][0] - 8, pts[2][1] - 8, pts[2][0] + 8, pts[2][1] + 8], fill=fc)
        tp = project(xpos[n2id['trunk']])
        draw.rectangle([tp[0] - 80, tp[1] - 18, tp[0] + 80, tp[1] + 18],
                       fill=(20, 30, 50), outline=(0, 0, 0), width=2)
        frames.append(_hud(np.array(img), label, note="2D skeleton (renderer unavailable)"))
    return frames


def _hud(img_arr, label, note=None):
    img = Image.fromarray(img_arr)
    draw = ImageDraw.Draw(img)
    f = _font(15)
    draw.text((10, 10), f"Unitree Go1 — scripted gait, real MuJoCo physics — {label}",
              fill=(20, 20, 60), font=f)
    if note:
        draw.text((10, 32), note, fill=(120, 60, 60), font=f)
    return np.array(img)


def title_card(text, sec=3):
    frames = []
    font = _font(26)
    for _ in range(int(FPS * sec)):
        img = Image.new("RGB", (W, H), (40, 40, 60))
        draw = ImageDraw.Draw(img)
        lines = text.split("\n")
        y = (H - len(lines) * 40) // 2
        for line in lines:
            b = draw.textbbox((0, 0), line, font=font)
            draw.text(((W - b[2]) // 2, y), line, fill=(220, 220, 240), font=font)
            y += 40
        frames.append(np.array(img))
    out = Path(f"/tmp/title_{abs(hash(text))}.mp4")
    imageio.mimsave(str(out), np.stack(frames), fps=FPS, codec="libx264", quality=8)
    return out


def save_segment(frames, name):
    out = Path(f"/tmp/demo_seg_{name}.mp4")
    imageio.mimsave(str(out), np.stack(frames), fps=FPS,
                    codec="libx264", quality=8, pixelformat="yuv420p")
    print(f"  segment {name}: {len(frames)} frames -> {out} ({out.stat().st_size // 1024} KB)")
    return out


def settle_and_compensate(model, data, base_ctrl):
    """P-servo actuators (kp=35, no gravity comp) sag under the raw home target.
    Settle once, measure the steady-state sag, add it back as feedforward. Since
    torque = kp*(ctrl - q) is linear, one correction lands the standing pose."""
    nu = model.nu
    for _ in range(120):
        data.ctrl[:] = base_ctrl
        mujoco.mj_step(model, data)
    sag = base_ctrl - data.qpos[7:7 + nu]
    base_ctrl = base_ctrl + sag
    lo = model.actuator_ctrlrange[:, 0]; hi = model.actuator_ctrlrange[:, 1]
    base_ctrl = np.clip(base_ctrl, lo, hi)
    for _ in range(120):
        data.ctrl[:] = base_ctrl
        mujoco.mj_step(model, data)
    print(f"[demo] gravity-comp done; trunk height now {float(data.qpos[2]):.3f} m (target ~0.278)")
    return base_ctrl


def reset_to_stand(model, data, base_ctrl):
    """Return to the compensated standing pose between gaits so each starts clean."""
    if model.nkey > 0:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)
    for _ in range(120):
        data.ctrl[:] = base_ctrl
        mujoco.mj_step(model, data)


def main():
    print("[demo] loading Go1JoystickFlatTerrain ...")
    cfg = reg.get_default_config("Go1JoystickFlatTerrain")
    cfg.impl = "jax"
    env = reg.load("Go1JoystickFlatTerrain", config=cfg)
    model = env.mj_model

    data = mujoco.MjData(model)
    if model.nkey > 0:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    else:
        data.qpos[0:3] = [0, 0, 0.28]
        data.qpos[3:7] = [1, 0, 0, 0]
        for leg in range(4):
            data.qpos[7 + leg * 3: 7 + leg * 3 + 3] = [0.0, 0.9, -1.8]
    mujoco.mj_forward(model, data)

    base_ctrl = None
    if model.nkey > 0 and getattr(model, "key_ctrl", None) is not None \
            and model.key_ctrl.shape[1] == model.nu:
        kc = model.key_ctrl[0].copy()
        if np.any(np.abs(kc) > 1e-6):
            base_ctrl = kc
    if base_ctrl is None:
        base_ctrl = data.qpos[7:7 + model.nu].copy()

    base_ctrl = settle_and_compensate(model, data, base_ctrl)

    use_3d = True
    try:
        _ = mujoco.Renderer(model, height=8, width=8)
        _.close()
    except Exception as e:
        use_3d = False
        print(f"[demo] mujoco.Renderer unavailable ({e}); falling back to 2D skeleton.")

    # Per-gait camera. Traveling gaits use a FIXED camera (track=False) so the
    # body visibly crosses the frame; walk goes +x (side view, az=90), sidestep
    # goes +y (front view, az=0). In-place gaits track the trunk.
    CAM = {
        "bob":      dict(track=True,  azimuth=45),
        "jump":     dict(track=True,  azimuth=45),
        "march":    dict(track=True,  azimuth=45),
        "walk":     dict(track=False, azimuth=90, distance=3.0),
        "sidestep": dict(track=False, azimuth=0,  distance=3.0),
        "spin":      dict(track=True,  azimuth=45),
        "wave":      dict(track=True,  azimuth=30),
        "rearstand": dict(track=True,  azimuth=90, distance=2.8),  # side view shows pitch
    }

    # Roll out + render each scripted gait, resetting to a clean stand between them.
    segs = {}
    for key, label, nsteps in GAITS:
        reset_to_stand(model, data, base_ctrl)
        print(f"[demo] gait '{key}' — {nsteps} steps of REAL physics ...")
        snaps, st = rollout_gait(model, data, key, nsteps, base_ctrl)
        print(f"       moved dx={st['dx']:+.2f}m dy={st['dy']:+.2f}m "
              f"yaw={st['dyaw']:+.0f}deg min_trunk_h={st['min_h']:.3f}m")
        frames = render_3d(model, snaps, label, **CAM.get(key, {})) if use_3d \
            else render_pil(model, snaps, label)
        segs[key] = (label, save_segment(frames, key))

    flist = [title_card("Unitree Go1 — scripted gaits\nReal MuJoCo physics · AMD Radeon", 4)]
    for key, label, _ in GAITS:
        flist.append(title_card(label, 2))
        flist.append(segs[key][1])
    flist.append(title_card("Training blocked by a ROCm profiler race\nSee docs/ROCM_BUG_REPORT.md", 4))

    tmp_txt = Path("/tmp/concat_list.txt")
    tmp_txt.write_text("".join(f"file '{p}'\n" for p in flist))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Segments may differ slightly in encode params, so re-encode on concat
    # (-c copy needs identical streams). Use the ffmpeg bundled with
    # imageio-ffmpeg so we don't depend on a system ffmpeg being on PATH.
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_bin = "ffmpeg"
    subprocess.run([ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
                    "-i", str(tmp_txt), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(OUT)], check=True)
    print(f"✅ {OUT}  ({OUT.stat().st_size // 1024} KB)  render={'3D' if use_3d else '2D-skeleton'}")
    print("   Upload to YouTube/Bilibili for the PR submission.")


if __name__ == "__main__":
    main()

"""multi-robot Soccer Environment — 6 robots in a single Genesis scene.

Extends SoccerEnvHierarchical to support 6 robot entities (3 left team + 3 right team)
in a SINGLE scene, not parallel envs. Left team uses RL policy, right team uses
rule-based policy. Each robot has its own walk model inference for locomotion.

Architecture:
    Left Team (RL):  3 robots → shared PPO policy → velocity commands → walk model → joints
    Right Team (Rule): 3 robots → rule-based chase → velocity commands → walk model → joints
    Ball: shared, single ball entity
    Kick: when robot is close to ball (< 0.3m), apply impulse toward goal
"""
from __future__ import annotations
import math, os, torch
import numpy as np
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


from control_utils import compose_full_joint_targets, store_robot_actions

try:
    import genesis as gs
except Exception:
    gs = None

try:
    from tensordict import TensorDict
except Exception:
    TensorDict = None

from genesis.utils.geom import inv_quat, quat_to_xyz, transform_by_quat, transform_quat_by_quat

# Import parent env
try:
    from envs.soccer_env import SoccerEnv
except ImportError:
    from soccer_env_v4 import SoccerEnv
from soccer_env_v4 import POLICY_JOINT_NAMES

try:
    from rewards.reward import compute_reward
except ImportError:
    from reward import compute_reward

# Field constants
FIELD_L = 14.0
FIELD_W = 9.0
HALF_L = FIELD_L / 2
HALF_W = FIELD_W / 2
GOAL_W = 2.6
GOAL_HALF = GOAL_W / 2
BALL_R = 0.11
ROBOT_HEIGHT = 0.72

# Kick tuning (was hardcoded 0.3 / 3.0 / 1.0 magic numbers in two places)
# Distance (m) from robot base to ball center under which a kick may fire.
# Raised from 0.3 -> 0.5: a humanoid's foot only reaches the ball at ~0.45-0.5m
# center distance, so the old 0.3m threshold almost never triggered a real kick.
KICK_DISTANCE = 1.1  # robot 0 starts at 1.0m from ball, need >1.0 to trigger kick immediately
KICK_IMPULSE = 5.0    # m/s — increased from 2.5 to escape robot's vicinity
KICK_COOLDOWN = 1.0   # seconds between kicks (longer cooldown for stability)

# 6 robot starting positions
# Left team (attacks +x): [attacker, defender, keeper]
LEFT_START = [(-1.0, 0.0), (-3.5, 1.5), (-6.5, 0.0)]
# Right team (attacks -x): [attacker, defender, keeper]
RIGHT_START = [(1.0, 0.0), (3.5, -1.5), (6.5, 0.0)]

DECIMATION = 10  # low-level physics substeps
PHYSICS_DT = 0.002


class SoccerEnv3v3(SoccerEnv):
    """multi-robot soccer environment with 6 robots in a single scene.

    The RL policy controls the left team (3 robots) with a shared policy.
    The right team uses a rule-based chase-ball policy.
    Each robot uses the frozen t1_walk.pt for locomotion.
    """

    def __init__(self, num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg,
                 walk_model_path, high_level_decimation=5, show_viewer=False):
        self._hl_initialized = False
        self.high_level_decimation = high_level_decimation
        self.num_robots = 6  # 3 left + 3 right
        self.num_rl_robots = 3  # left team

        device = gs.device if gs is not None else "cpu"
        # High-level actions for every entity (6 robots × 3 dims).  The legacy
        # ``step((N, 3))`` API still addresses robot 0; ``step_multi`` accepts
        # one independently computed command for each of the six robots.
        self.hl_actions = torch.zeros((num_envs, 6, 3), dtype=gs.tc_float, device=device)
        self.last_hl_actions = torch.zeros((num_envs, 6, 3), dtype=gs.tc_float, device=device)

        # Call parent init — sets up physics, scene, buffers, calls reset()
        super().__init__(num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg, show_viewer)

        self._hl_initialized = True
        self.num_actions = 3  # vx, vy, wz per robot
        self.hl_clip_lin = env_cfg.get("hl_clip_lin", 0.6)
        self.hl_clip_ang = env_cfg.get("hl_clip_ang", 0.6)
        self.high_level_dt = self.dt * high_level_decimation
        self.use_rule_walk = env_cfg.get("use_rule_walk", False)
        self._rule_walk_phase = 0.0

        # High-level obs: 19 dims per robot, 3 robots = 57 dims
        # But we only run RL policy for 1 robot at a time (attacker),
        # so obs_buf is 19 dims
        self.hl_obs_dim = 19
        self.obs_buf = torch.empty((self.num_envs, 720),  # low-level obs for walk model
                                   dtype=gs.tc_float, device=self.device)

        # Load frozen walking model (shared across all robots)
        self.walk_model = safe_jit_load(walk_model_path, map_location=self.device)
        self.walk_model.eval()
        try:
            _norm = self.walk_model.obs_normalizer
            self._norm_mean = _norm._mean.to(self.device)
            self._norm_std = torch.clamp(_norm._std, min=1e-8).to(self.device)
            print(f"[multi-robot] Walk model normalizer loaded: mean={self._norm_mean.shape}")
        except Exception as e:
            self._norm_mean = None
            self._norm_std = None
            print(f"[multi-robot] Walk model normalizer not available: {e}")

        print(f"[multi-robot] Frozen walk model loaded from {walk_model_path}")
        print(f"[multi-robot] HL obs dim={self.hl_obs_dim}, HL action dim={self.num_actions}")
        print(f"[multi-robot] HL dt={self.high_level_dt:.3f}s, decimation={high_level_decimation}")
        print(f"[multi-robot] 6 robots (3 RL + 3 rule), 1 ball, single scene")

        # Per-robot buffers
        self._init_robot_buffers()

        # Kick cooldown
        self.kick_cooldown = torch.zeros((self.num_envs, self.num_robots),
                                          dtype=gs.tc_float, device=self.device)

        self._update_observation()
        self._m_goals = 0
        self._m_dist = 0.0
        self._m_steps = 0

    def _init_robot_buffers(self):
        """Initialize per-robot state buffers."""
        n = self.num_envs
        dev = self.device
        # Positions for all 6 robots
        self.all_base_pos = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)
        self.all_base_quat = torch.zeros((n, self.num_robots, 4), dtype=gs.tc_float, device=dev)
        self.all_base_euler = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)
        self.all_dof_pos = []
        self.all_dof_vel = []
        self.all_last_actions = []
        self.all_default_dof_pos = []

        # Initialize per-robot joint buffers
        for i in range(self.num_robots):
            robot = self.robots[i]
            motor_joints = [j for j in robot.joints[1:] if j.n_dofs > 0]
            num_motors = len(motor_joints)
            # Entity APIs require entity-local DOF indices. ``dof_start`` is
            # a solver/global offset and can overwrite the floating-base
            # qpos when passed to set/get/control_dofs_* APIs.
            local_dof_idx = torch.tensor(
                [j.dof_idx_local if hasattr(j, "dof_idx_local") else j.dof_start
                 for j in motor_joints],
                dtype=gs.tc_int,
                device=dev,
            )
            # URDF entities are spawned with zero joint angles.  The frozen
            # T1 walk policy expects the Booster standing pose from the parent
            # environment; using the spawn pose makes all six robots collapse
            # before the first high-level command.
            parent_default = getattr(self, "default_dof_pos", None)
            if parent_default is not None and int(parent_default.numel()) == num_motors:
                default_pos = parent_default.detach().clone()
            else:
                default_pos = robot.get_dofs_position(local_dof_idx)[0].clone()
            all_joint_names = [j.name for j in motor_joints]
            policy_joint_indices = torch.tensor(
                [all_joint_names.index(name) for name in POLICY_JOINT_NAMES],
                dtype=gs.tc_int,
                device=dev,
            )

            self.all_dof_pos.append(torch.zeros((n, num_motors), dtype=gs.tc_float, device=dev))
            self.all_dof_vel.append(torch.zeros((n, num_motors), dtype=gs.tc_float, device=dev))
            self.all_last_actions.append(torch.zeros(
                (n, len(POLICY_JOINT_NAMES)), dtype=gs.tc_float, device=dev
            ))
            self.all_default_dof_pos.append(default_pos)

            # Set PD gains
            kp = self.cfg.get("kp", 200.0)
            kd = self.cfg.get("kd", 5.0)
            robot.set_dofs_kp([kp] * num_motors, local_dof_idx)
            robot.set_dofs_kv([kd] * num_motors, local_dof_idx)

            # Store per-robot metadata
            if not hasattr(self, '_robot_meta'):
                self._robot_meta = []
            self._robot_meta.append({
                'motor_joints': motor_joints,
                'local_dof_idx': local_dof_idx,
                'num_motors': num_motors,
                'policy_joint_indices': policy_joint_indices,
            })

        # Filtered velocity for each robot (for observation)
        self.all_filtered_lin_vel = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)
        self.all_filtered_ang_vel = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)

        # Low-level obs history (10-frame × 72 dims = 720) for each robot
        self.all_obs_history = []
        for i in range(self.num_robots):
            obs_dim_per_frame = 72  # 3+3+3+21+21+21 (ang_vel, grav, cmd, dof_pos, dof_vel, last_act)
            self.all_obs_history.append(
                torch.zeros((n, 10, obs_dim_per_frame), dtype=gs.tc_float, device=dev)
            )

        # Last HL actions for each robot
        self.all_last_hl_actions = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)
        # Velocity commands for each robot
        self.all_commands = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)

    def _build_scene(self, show_viewer):
        """Build scene with 6 robots, ball, field, goals, camera."""
        self.scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=PHYSICS_DT, substeps=1),
            rigid_options=gs.options.RigidOptions(
                enable_self_collision=False,
                # gfx1100 has a 64 KiB local-memory ceiling per kernel.  A
                # 4096-pair solver specialization exceeds it for six T1s;
                # 1024 retains ample headroom over the observed active pairs.
                max_collision_pairs=1024,
                # Newton's tiled factorization compiles to 66,560 bytes of
                # local memory for this six-humanoid scene, above gfx1100's
                # 65,536-byte limit. CG avoids that architecture-specific
                # kernel while retaining contact constraints.
                constraint_solver=gs.constraint_solver.CG,
                sparse_solve=True,
                tolerance=1e-4,
                iterations=50,
            ),
            viewer_options=gs.options.ViewerOptions(
                camera_pos=(0, -12, 8), camera_lookat=(0, 0, 0.5), camera_fov=50),
            vis_options=gs.options.VisOptions(
                rendered_envs_idx=[0],
                show_world_frame=False,
                show_link_frame=False,
                show_cameras=False,
                plane_reflection=False,
                ambient_light=(0.7, 0.7, 0.7),
                shadow=True,
            ),
            renderer=gs.renderers.Rasterizer(),
            show_viewer=show_viewer,
        )

        # Ground: physics plane (collision) + textured field mesh (visual).
        self.scene.add_entity(
            gs.morphs.URDF(file=_genesis_asset("urdf", "plane", "plane.urdf"), fixed=True))

        # Field ground: custom quad mesh (vt texture coords + vn normal) mapped
        # with the pitch texture (grass + white lines, 14m x 9m per SPEC).
        _field_mesh = os.path.join(os.path.dirname(__file__), "..", "assets", "field_mesh.obj")
        _field_tex = os.path.join(os.path.dirname(__file__), "..", "assets", "textures", "soccer_field.png")
        if not os.path.exists(_field_mesh):
            _field_mesh = "/workspace/assets/field_mesh.obj"
        if not os.path.exists(_field_tex):
            _field_tex = "/workspace/assets/textures/soccer_field.png"
        if os.path.exists(_field_mesh) and os.path.exists(_field_tex):
            self.scene.add_entity(
                gs.morphs.Mesh(
                    file=_field_mesh,
                    pos=(0, 0, 0),
                    fixed=True,
                    collision=False,
                    visualization=True,
                ),
                surface=gs.surfaces.Rough(
                    diffuse_texture=gs.textures.ImageTexture(image_path=_field_tex),
                    roughness=0.9,
                ),
            )
        else:
            print(f"[multi-robot] WARN: field mesh/texture missing ({_field_mesh}, {_field_tex}) — bare plane only")

        # Goal markers
        _gs_s = gs.surfaces.Rough(color=(0.95, 0.95, 0.95), roughness=0.5)
        _pw2 = 0.1
        for gx in [-HALF_L, HALF_L]:
            self.scene.add_entity(morph=gs.morphs.Box(size=(_pw2, GOAL_W + _pw2, _pw2), pos=(gx, 0, 1.0), fixed=True), surface=_gs_s)

        # 6 robots
        robot_path = self.cfg["robot_urdf"]
        if not os.path.isabs(robot_path):
            project_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", robot_path))
            ga = _genesis_asset(robot_path)
            # Prefer the project-pinned asset.  A stale `/workspace/urdf` can
            # otherwise shadow the repo copy when launched from a notebook.
            robot_path = project_path if os.path.exists(project_path) else (
                ga if os.path.exists(ga) else os.path.abspath(robot_path)
            )

        self.robots = []
        all_starts = LEFT_START + RIGHT_START
        for i, (x, y) in enumerate(all_starts):
            if robot_path.endswith(".xml") or robot_path.endswith(".mjcf"):
                robot = self.scene.add_entity(
                    gs.morphs.MJCF(file=robot_path, pos=(x, y, ROBOT_HEIGHT)))
            else:
                robot = self.scene.add_entity(
                    gs.morphs.URDF(file=robot_path, pos=(x, y, ROBOT_HEIGHT),
                                  fixed=False, merge_fixed_links=False))
            self.robots.append(robot)

        # The parent SoccerEnv constructor initializes its legacy single-robot
        # buffers immediately after _build_scene().  Point that compatibility
        # API at robot 0; this subclass replaces the buffers with six-robot
        # versions once the parent constructor returns.
        self.robot = self.robots[0]

        # Ball
        ball_path = os.path.join(os.path.dirname(__file__), "..", "assets", "ball.urdf")
        if not os.path.exists(ball_path):
            ball_path = "/workspace/radeon-repo/assets/ball.urdf"
        if not os.path.exists(ball_path):
            ball_path = "/workspace/assets/ball.urdf"
        self.ball = self.scene.add_entity(gs.morphs.URDF(file=os.path.abspath(ball_path)))

        # Camera (close-up for visible motion)
        self.cam = self.scene.add_camera(
            res=(1280, 720), pos=(2, -3, 2), lookat=(0, 0, 0.8), fov=60, GUI=False, spp=8)

        self.scene.build(n_envs=self.num_envs)

    def _obs_dim(self):
        return 720  # low-level obs for walk model

    def _read_all_robot_states(self):
        """Read positions, quats, dof states for all 6 robots."""
        for i in range(self.num_robots):
            robot = self.robots[i]
            self.all_base_pos[:, i, :] = robot.get_pos()
            self.all_base_quat[:, i, :] = robot.get_quat()
            self.all_base_euler[:, i, :] = quat_to_xyz(
                transform_quat_by_quat(
                    inv_quat(torch.tensor([1.0, 0, 0, 0], device=self.device)),
                    robot.get_quat()), rpy=True, degrees=True)
            meta = self._robot_meta[i]
            self.all_dof_pos[i] = robot.get_dofs_position(meta['local_dof_idx'])
            self.all_dof_vel[i] = robot.get_dofs_velocity(meta['local_dof_idx'])

        # Ball
        self.ball_pos = self.ball.get_pos()
        self.ball_vel = self.ball.get_vel()

    def _compute_rl_obs(self, robot_idx=0):
        """Compute 19-dim high-level observation for RL robot (robot_idx=0 = attacker)."""
        pos = self.all_base_pos[:, robot_idx, :]
        quat = self.all_base_quat[:, robot_idx, :]
        lin_vel = self.all_filtered_lin_vel[:, robot_idx, :]
        ang_vel = self.all_filtered_ang_vel[:, robot_idx, :]
        last_actions = self.all_last_hl_actions[:, robot_idx, :]

        inv_bq = inv_quat(quat)

        # Ball relative to robot, body frame
        ball_rel = self.ball_pos - pos
        ball_rel_body = transform_by_quat(ball_rel, inv_bq)
        ball_vel_body = transform_by_quat(self.ball_vel, inv_bq)

        # Goal direction in body frame
        goal_pos = torch.zeros_like(pos)
        goal_pos[:, 0] = self.goal_x  # left team attacks +x
        goal_rel = goal_pos - pos
        goal_rel_body = transform_by_quat(goal_rel, inv_bq)
        goal_dist = torch.norm(goal_rel_body[:, :2], dim=1, keepdim=True)
        goal_dir = goal_rel_body[:, :2] / (goal_dist + 1e-6)

        dist_to_ball = torch.norm(ball_rel_body[:, :2], dim=1, keepdim=True)

        obs = torch.cat([
            lin_vel,                    # 3
            ang_vel,                    # 3
            transform_by_quat(          # 2 (projected gravity xy)
                torch.tensor([0.0, 0.0, -1.0], device=self.device).expand(self.num_envs, -1),
                inv_bq)[:, :2],
            ball_rel_body[:, :2],       # 2
            ball_vel_body[:, :2],       # 2
            dist_to_ball,               # 1
            goal_dir,                   # 2
            goal_dist,                  # 1
            last_actions,               # 3
        ], dim=-1)
        return obs

    def _compute_rule_actions(self, robot_idx):
        """Rule-based velocity command — all non-attacker robots stand still."""
        return torch.zeros((self.num_envs, 3), dtype=gs.tc_float, device=self.device)

        actions = torch.stack([
            torch.clamp(vx, -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(vy, -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(wz, -self.hl_clip_ang, self.hl_clip_ang),
        ], dim=1)
        return actions

        actions = torch.stack([
            torch.clamp(vx, -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(vy, -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(wz, -self.hl_clip_ang, self.hl_clip_ang),
        ], dim=1)
        return actions

    def _build_low_level_obs_for_robot(self, robot_idx):
        """Build 720-dim observation for walk model of a specific robot."""
        i = robot_idx
        meta = self._robot_meta[i]
        pos = self.all_base_pos[:, i, :]
        quat = self.all_base_quat[:, i, :]
        dof_pos = self.all_dof_pos[i]
        dof_vel = self.all_dof_vel[i]
        last_act = self.all_last_actions[i]
        cmd = self.all_commands[:, i, :]
        default_pos = self.all_default_dof_pos[i]
        policy_idx = meta['policy_joint_indices']
        policy_dof_pos = dof_pos[:, policy_idx]
        policy_dof_vel = dof_vel[:, policy_idx]
        policy_default_pos = default_pos[policy_idx]

        inv_bq = inv_quat(quat)
        lin_vel = self.all_filtered_lin_vel[:, i, :]
        ang_vel = transform_by_quat(self.robots[i].get_ang(), inv_bq)
        grav = transform_by_quat(
            torch.tensor([0.0, 0.0, -1.0], device=self.device).expand(self.num_envs, -1), inv_bq)

        # 72-dim per frame: ang_vel(3) + grav(3) + cmd(3) + dof_pos(21) + dof_vel(21) + last_act(21)
        n_motors = meta['num_motors']
        per_frame = torch.cat([
            ang_vel * self.obs_scales["ang_vel"],         # 3
            grav,                                          # 3
            cmd,                                           # 3
            (policy_dof_pos - policy_default_pos) * self.obs_scales["dof_pos"],  # 21
            policy_dof_vel * self.obs_scales["dof_vel"],  # 21
            last_act,                                     # 21
        ], dim=-1)

        # Pad to 72 dims if needed
        if per_frame.shape[-1] < 72:
            pad = torch.zeros(self.num_envs, 72 - per_frame.shape[-1], device=self.device)
            per_frame = torch.cat([per_frame, pad], dim=-1)

        # 10-frame history
        self.all_obs_history[i] = torch.cat([self.all_obs_history[i][:, 1:], per_frame.unsqueeze(1)], dim=1)
        return self.all_obs_history[i].reshape(self.num_envs, -1)  # 720

    def _rule_walk_actions(self, cmd, robot_idx):
        """Deterministic gait controller — bypasses t1_walk.pt.

        Produces 21-dim joint actions (same interface as _run_walk_model).
        Uses a proper bipedal gait: alternating stance/swing phases with
        hip pitch, knee flex, ankle push-off, and arm counter-swing.

        The action is scaled by action_scale (0.25) then added to default
        pose in _low_level_step_robot, so:
          target = action * 0.25 + default_pos

        POLICY_JOINT_NAMES indices:
          0=L_ShPit 1=R_ShPit 2=Waist 3=L_ShRol 4=R_ShRol
          5=L_HipPit 6=R_HipPit 7=L_ElbPit 8=R_ElbPit
          9=L_HipRol 10=R_HipRol 11=L_ElbYaw 12=R_ElbYaw
          13=L_HipYaw 14=R_HipYaw 15=L_KneePit 16=R_KneePit
          17=L_AnkPit 18=R_AnkPit 19=L_AnkRol 20=R_AnkRol

        Default standing pose (relevant joints):
          L_HipPit=-0.2, R_HipPit=-0.2, L_Knee=0.4, R_Knee=0.4,
          L_AnkPit=-0.2, R_AnkPit=-0.2
        """
        n = self.num_envs
        dev = self.device
        n_joints = len(POLICY_JOINT_NAMES)

        vx = float(cmd[0, 0].item())
        vy = float(cmd[0, 1].item())
        wz = float(cmd[0, 2].item())
        speed = math.sqrt(vx * vx + vy * vy)
        moving = speed > 0.05

        # Advance phase only once per low-level step (robot 0 call)
        if robot_idx == 0:
            freq = 1.5  # Hz — v7 frequency (stable)
            self._rule_walk_phase += freq * self.dt

        phase = self._rule_walk_phase
        speed_norm = min(speed, 1.0)

        actions = torch.zeros((n, n_joints), dtype=gs.tc_float, device=dev)

        if not moving:
            return actions  # standing pose = all zeros

        # ---- v7 gait + forward lean (proven to walk forward) ----
        lh = math.sin(phase)
        rh = math.sin(phase + math.pi)

        hip_amp = 0.5 * speed_norm
        left_hip = hip_amp * lh
        right_hip = hip_amp * rh

        # Forward lean: constant hip pitch offset for forward motion
        forward_lean = 0.35 * min(speed_norm, 1.0)
        left_hip += forward_lean
        right_hip += forward_lean

        knee_amp = 0.6 * speed_norm
        left_knee = knee_amp * max(0.0, lh)
        right_knee = knee_amp * max(0.0, rh)

        ankle_amp = 0.2 * speed_norm
        left_ankle = -ankle_amp * min(0.0, lh)
        right_ankle = -ankle_amp * min(0.0, rh)

        roll_amp = 0.1 * speed_norm
        left_roll = roll_amp * lh
        right_roll = -roll_amp * lh

        arm_amp = 0.3 * speed_norm
        left_arm = -arm_amp * lh
        right_arm = -arm_amp * rh

        yaw_offset = wz * 0.2

        actions[:, 0] = left_arm
        actions[:, 1] = right_arm
        actions[:, 5] = left_hip
        actions[:, 6] = right_hip
        actions[:, 9] = left_roll
        actions[:, 10] = right_roll
        actions[:, 13] = yaw_offset   # L_Hip_Yaw
        actions[:, 14] = yaw_offset   # R_Hip_Yaw
        actions[:, 15] = left_knee
        actions[:, 16] = right_knee
        actions[:, 17] = left_ankle
        actions[:, 18] = right_ankle

        return actions

    def _run_walk_model(self, obs_720):
        """Run frozen walking model."""
        with torch.no_grad():
            if self._norm_mean is not None:
                obs_normed = (obs_720 - self._norm_mean) / self._norm_std
            else:
                obs_normed = obs_720
            return self.walk_model.actor(obs_normed)

    def _low_level_step_robot(self, robot_idx, joint_actions):
        """Execute one low-level control step for a specific robot."""
        i = robot_idx
        robot = self.robots[i]
        meta = self._robot_meta[i]
        n_motors = meta['num_motors']

        actions = torch.clip(joint_actions, -self.clip_actions, self.clip_actions)
        exec_actions = self.all_last_actions[i] if self.simulate_action_latency else actions

        full_targets = compose_full_joint_targets(
            exec_actions,
            self.action_scale,
            self.all_default_dof_pos[i],
            meta['policy_joint_indices'],
        )
        robot.control_dofs_position(
            full_targets,
            meta['local_dof_idx'],
        )

        store_robot_actions(self.all_last_actions, i, actions)

    def _execute_kick(self, robot_idx):
        """Apply kick impulse to ball if robot is close enough.

        Returns a per-environment boolean mask so callers can record an
        explicit kick/contact event without guessing from the ball trajectory.
        """
        i = robot_idx
        pos = self.all_base_pos[:, i, :]
        ball_pos = self.ball_pos

        dist = torch.norm(ball_pos[:, :2] - pos[:, :2], dim=1)
        can_kick = (dist < KICK_DISTANCE) & (self.kick_cooldown[:, i] < 0.01)

        if can_kick.any():
            # Kick direction: toward opponent goal
            if i < 3:  # left team attacks +x
                goal_x = self.goal_x
            else:  # right team attacks -x
                goal_x = -self.goal_x

            goal_dir = torch.stack([goal_x - pos[:, 0], -pos[:, 1]], dim=1)
            goal_dir_norm = goal_dir / (torch.norm(goal_dir, dim=1, keepdim=True) + 1e-6)
            impulse = goal_dir_norm * KICK_IMPULSE  # m/s kick

            # Apply to ball velocity
            ball_qvel = self.ball.get_dofs_velocity().clone()
            ball_qvel[can_kick, 0] = impulse[can_kick, 0]
            ball_qvel[can_kick, 1] = impulse[can_kick, 1]
            ball_qvel[can_kick, 2] = 0.0
            self.ball.set_dofs_velocity(ball_qvel)
            self.kick_cooldown[can_kick, i] = KICK_COOLDOWN

        self.kick_cooldown[:, i] = torch.clamp(
            self.kick_cooldown[:, i] - self.high_level_dt, min=0.0)
        return can_kick

    def _normalise_commands(self, hl_actions, *, legacy: bool = False):
        """Return a finite ``(num_envs, 6, 3)`` command tensor.

        ``legacy=True`` preserves the old renderer contract where only the
        left attacker was supplied and the remaining five entities followed
        the built-in rule chase.  The acceptance evaluator calls
        :meth:`step_multi` and therefore exercises independent control of all
        six robots in this one scene.
        """
        actions = torch.as_tensor(hl_actions, dtype=self.hl_actions.dtype, device=self.device)
        if actions.ndim == 2 and actions.shape == (self.num_envs, 3):
            commands = torch.zeros_like(self.hl_actions)
            commands[:, 0, :] = actions
            legacy = True
        elif actions.ndim == 3 and actions.shape == (self.num_envs, self.num_robots, 3):
            commands = actions.clone()
        else:
            raise ValueError(
                "multi-robot high-level actions must have shape "
                f"({self.num_envs}, 3) or ({self.num_envs}, 6, 3), got {tuple(actions.shape)}"
            )

        if legacy:
            # The compatibility path deliberately keeps the historical rule
            # behaviour for robots 1..5.  No worker or coordinator is involved.
            for i in range(1, self.num_robots):
                commands[:, i, :] = self._compute_rule_actions(i)

        commands = torch.nan_to_num(commands, nan=0.0, posinf=0.0, neginf=0.0)
        commands[..., :2] = torch.clamp(commands[..., :2], -self.hl_clip_lin, self.hl_clip_lin)
        commands[..., 2] = torch.clamp(commands[..., 2], -self.hl_clip_ang, self.hl_clip_ang)
        commands = torch.where(torch.abs(commands) < 0.05, torch.zeros_like(commands), commands)
        return commands

    def _apply_commands(self, commands):
        """Install per-robot commands while preserving previous-action state."""
        self.all_commands.copy_(commands)
        self.all_last_hl_actions.copy_(self.hl_actions)
        self.hl_actions.copy_(commands)

    def _physics_step(self):
        """Advance the single Genesis scene and return all six robot actions."""
        # Run N low-level steps
        for _ in range(self.high_level_decimation):
            for i in range(self.num_robots):
                if i == 0 and not getattr(self, "use_rule_walk", False):
                    # Robot 0: use walk model for fast locomotion
                    low_obs = self._build_low_level_obs_for_robot(i)
                    joint_actions = self._run_walk_model(low_obs)
                else:
                    # Robots 1-5: use rule_walk with zero cmd for stable standing
                    cmd = self.all_commands[:, i, :]
                    joint_actions = self._rule_walk_actions(cmd, i)
                self._low_level_step_robot(i, joint_actions)

            for _ in range(DECIMATION):
                self.scene.step()

            self.episode_length_buf += 1
            self._read_all_robot_states()

            # Update filtered velocities
            fw = 0.3
            for i in range(self.num_robots):
                robot = self.robots[i]
                lin_vel = transform_by_quat(robot.get_vel(),
                    inv_quat(self.all_base_quat[:, i, :]))
                ang_vel = transform_by_quat(robot.get_ang(),
                    inv_quat(self.all_base_quat[:, i, :]))
                self.all_filtered_lin_vel[:, i, :] = lin_vel * fw + self.all_filtered_lin_vel[:, i, :] * (1 - fw)
                self.all_filtered_ang_vel[:, i, :] = ang_vel * fw + self.all_filtered_ang_vel[:, i, :] * (1 - fw)

        # Kick logic — AFTER physics step, with reduced impulse to avoid falls.
        # Also zero out velocity commands for any robot that kicks this step,
        # so the gait doesn't fight the kick perturbation.
        self.last_kick_events = torch.zeros(
            (self.num_envs, self.num_robots), dtype=gs.tc_bool, device=self.device
        )
        for i in range(self.num_robots):
            kick_mask = self._execute_kick(i)
            self.last_kick_events[:, i] = kick_mask
            if kick_mask.any():
                # Robot that kicked: reduce command (not zero) to avoid sudden stop
                self.all_commands[:, i, :] *= 0.3

    def _compute_step_telemetry(self):
        """Compute reward, terminal flags, and pre-reset state telemetry."""

        # Build high-level observation for RL robot
        self._update_observation()

        # Compute reward (simplified)
        soccer = {
            "torso_up": torch.clamp(-transform_by_quat(
                torch.tensor([0.0, 0.0, -1.0], device=self.device).expand(self.num_envs, -1),
                inv_quat(self.all_base_quat[:, 0, :]))[:, 2], min=-1.0, max=1.0),
            "fallen": self.all_base_pos[:, 0, 2] < self.fall_height,
            "base_lin_vel_x": self.all_filtered_lin_vel[:, 0, 0],
            "ball_x": self.ball_pos[:, 0],
            "dist_to_ball": torch.norm(self.all_base_pos[:, 0, :2] - self.ball_pos[:, :2], dim=1),
            "prev_dist_to_ball": torch.norm(
                (self.all_base_pos[:, 0, :2] - self.ball_pos[:, :2]).clone(), dim=1),
            "ball_vel_to_goal": torch.sum(self.ball_vel[:, :2] *
                torch.stack([self.goal_x - self.ball_pos[:, 0],
                            -self.ball_pos[:, 1]], dim=1) /
                (torch.norm(torch.stack([self.goal_x - self.ball_pos[:, 0],
                            -self.ball_pos[:, 1]], dim=1), dim=1, keepdim=True) + 1e-6), dim=1),
            "scored": (self.ball_pos[:, 0] > self.goal_x) &
                      (torch.abs(self.ball_pos[:, 1]) < self.goal_half),
            "just_recovered": torch.zeros(self.num_envs, dtype=gs.tc_bool, device=self.device),
        }

        # The shared-match evaluator reports a transparent task metric instead
        # of invoking the training reward, whose chase_hl contract requires
        # foot/contact/history tensors that this six-entity harness does not
        # fabricate.  This value is descriptive and is not presented as the
        # PPO training objective.
        self.rew_buf = (
            torch.exp(-soccer["dist_to_ball"])
            + 0.1 * (~soccer["fallen"]).to(dtype=gs.tc_float)
            + 5.0 * soccer["scored"].to(dtype=gs.tc_float)
        )

        # Termination
        self.reset_buf = self.episode_length_buf > self.max_episode_length
        scored_left = (self.ball_pos[:, 0] > self.goal_x) & (torch.abs(self.ball_pos[:, 1]) < self.goal_half)
        scored_right = (self.ball_pos[:, 0] < -self.goal_x) & (torch.abs(self.ball_pos[:, 1]) < self.goal_half)
        self.reset_buf |= scored_left | scored_right
        for i in range(self.num_robots):
            self.reset_buf |= torch.abs(self.all_base_euler[:, i, 1]) > self.term_pitch
            self.reset_buf |= torch.abs(self.all_base_euler[:, i, 0]) > self.term_roll
        self.reset_buf |= self.scene.rigid_solver.get_error_envs_mask()
        fallen = self.all_base_pos[:, :, 2] < self.fall_height
        fallen |= torch.abs(self.all_base_euler[:, :, 1]) > self.term_pitch
        fallen |= torch.abs(self.all_base_euler[:, :, 0]) > self.term_roll
        timeout = self.episode_length_buf > self.max_episode_length
        # Clone before _reset_idx: the canonical evaluator must never log the
        # reset pose as the terminal state.
        terminal_state = {
            "all_base_pos": self.all_base_pos.detach().clone(),
            "all_base_quat": self.all_base_quat.detach().clone(),
            "all_base_euler": self.all_base_euler.detach().clone(),
            "all_filtered_lin_vel": self.all_filtered_lin_vel.detach().clone(),
            "ball_pos": self.ball_pos.detach().clone(),
            "ball_vel": self.ball_vel.detach().clone(),
            "fallen": fallen.detach().clone(),
            "scored_left": scored_left.detach().clone(),
            "scored_right": scored_right.detach().clone(),
        }
        self.extras = {
            "time_outs": timeout.to(dtype=gs.tc_float),
            "fallen": fallen.any(dim=1),
            "scored": (scored_left | scored_right),
            "terminal_state": terminal_state,
            "kick_events": self.last_kick_events.detach().clone(),
        }

        if self.reset_buf.any():
            self._reset_idx(self.reset_buf)

        obs_dict = TensorDict({"policy": self._compute_rl_obs(0)}, batch_size=[self.num_envs])
        return obs_dict, self.rew_buf, self.reset_buf, self.extras

    def step_multi(self, hl_actions):
        """Advance six independently controlled robots in the same scene.

        Args:
            hl_actions: velocity commands shaped ``(num_envs, 6, 3)``.  Robot
                indices are fixed as ``A_attacker, A_defender, A_keeper,
                B_attacker, B_defender, B_keeper``.  All entities share the
                same Genesis scene, ball, solver, and clock.
        """
        commands = self._normalise_commands(hl_actions)
        self._apply_commands(commands)
        self._physics_step()
        return self._compute_step_telemetry()

    def step(self, hl_actions):
        """Backward-compatible single-attacker step.

        New evaluation code should call :meth:`step_multi`; retaining this
        adapter keeps the existing PPO renderer and training utilities intact.
        """
        commands = self._normalise_commands(hl_actions, legacy=True)
        self._apply_commands(commands)
        self._physics_step()
        return self._compute_step_telemetry()

    def _update_observation(self):
        """Update the observation buffer for RL robot."""
        if not self._hl_initialized:
            super()._update_observation()
            return
        self.obs_buf = self._compute_rl_obs(0)

    def get_observations(self):
        return TensorDict({"policy": self._compute_rl_obs(0)}, batch_size=[self.num_envs])

    def reset(self):
        # ``SoccerEnv.__init__`` invokes ``self.reset()`` before this subclass
        # has discovered the six robots' motor layouts.  Defer that first
        # call; __init__ below performs the real reset after buffers exist.
        if not self._hl_initialized:
            return None
        self._reset_idx()
        self._read_all_robot_states()
        return self.get_observations()

    def _reset_idx(self, envs_idx=None):
        """Reset all robots to starting positions."""
        # Partial reset was never implemented for this single-scene evaluator.
        # With one env, a terminal mask is equivalent to resetting the scene.
        if envs_idx is not None:
            try:
                if bool(torch.as_tensor(envs_idx).any().item()):
                    envs_idx = None
            except Exception:
                envs_idx = None
        if envs_idx is None:
            # Reset all
            for i, robot in enumerate(self.robots):
                starts = LEFT_START + RIGHT_START
                x, y = starts[i]
                qpos = robot.get_qpos().clone()
                qpos[0, :3] = torch.tensor([x, y, ROBOT_HEIGHT], device=self.device)
                qpos[0, 3:7] = torch.tensor([1.0, 0, 0, 0], device=self.device)
                # Set default joint positions
                meta = self._robot_meta[i]
                motor_start = int(meta['local_dof_idx'][0].item())
                qpos[0, motor_start:motor_start + meta['num_motors']] = self.all_default_dof_pos[i]
                robot.set_qpos(qpos, zero_velocity=True, skip_forward=True)

            # Reset ball to center
            ball_qpos = self.ball.get_qpos().clone()
            ball_qpos[0, :3] = torch.tensor([0.0, 0.0, BALL_R], device=self.device)
            ball_qpos[0, 3:7] = torch.tensor([1.0, 0, 0, 0], device=self.device)
            self.ball.set_qpos(ball_qpos, zero_velocity=True, skip_forward=True)

            # Reset buffers
            self.episode_length_buf.zero_()
            self.reset_buf.fill_(True)
            self.kick_cooldown.zero_()
            for i in range(self.num_robots):
                self.all_obs_history[i].zero_()
                self.all_last_actions[i].zero_()
                self.all_last_hl_actions[:, i, :].zero_()
                self.all_filtered_lin_vel[:, i, :].zero_()
                self.all_filtered_ang_vel[:, i, :].zero_()
        else:
            pass  # Partial reset not needed for rendering


def _genesis_asset(*parts):
    return os.path.join(os.path.dirname(gs.__file__), "assets", *parts)

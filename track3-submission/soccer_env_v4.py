"""Genesis humanoid-soccer environment — EXACT alignment with booster_deploy t1_walk.pt.

Observation format (must match pre-trained model exactly):
  Per frame (72 dims):
    ang_vel(3) + projected_gravity(3) + commands(3) + dof_pos(21) + dof_vel(21) + last_action(21)
  10-frame history → 720 input dims (NO ball info in RL obs)

  Ball info is handled by the upper rule layer, NOT the RL policy.

Action: 21 dims (policy joints only, excludes head)
  action_scale = 0.25 (from booster_deploy T1WalkControllerCfg)

PD gains: from booster_deploy T1WalkControllerCfg (per-joint, not uniform)
"""
from __future__ import annotations
import math, os, torch

try:
    import genesis as gs
except Exception:
    gs = None

try:
    from tensordict import TensorDict
except Exception:
    TensorDict = None

from genesis.utils.geom import inv_quat, quat_to_xyz, transform_by_quat, transform_quat_by_quat


def torch_rand_float(low, high, shape, device):
    return (high - low) * torch.rand(shape, device=device) + low


def gs_rand(lower, upper, batch_shape):
    assert lower.shape == upper.shape
    return (upper - lower) * torch.rand(size=(*batch_shape, *lower.shape), dtype=gs.tc_float, device=gs.device) + lower


def _genesis_asset(*parts):
    return os.path.join(os.path.dirname(gs.__file__), "assets", *parts)


# ═══════════════════════════════════════════════════════════════════
# EXACT alignment with booster_deploy/tasks/locomotion/locomotion.py
# ═══════════════════════════════════════════════════════════════════

# 21 policy joints (same order as booster_deploy T1WalkControllerCfg.policy_joint_names)
POLICY_JOINT_NAMES = [
    "Left_Shoulder_Pitch", "Right_Shoulder_Pitch", "Waist",
    "Left_Shoulder_Roll", "Right_Shoulder_Roll",
    "Left_Hip_Pitch", "Right_Hip_Pitch",
    "Left_Elbow_Pitch", "Right_Elbow_Pitch",
    "Left_Hip_Roll", "Right_Hip_Roll",
    "Left_Elbow_Yaw", "Right_Elbow_Yaw",
    "Left_Hip_Yaw", "Right_Hip_Yaw",
    "Left_Knee_Pitch", "Right_Knee_Pitch",
    "Left_Ankle_Pitch", "Right_Ankle_Pitch",
    "Left_Ankle_Roll", "Right_Ankle_Roll",
]

# PD gains: EXACT from booster_deploy T1WalkControllerCfg
# 23 joints: [head_yaw, head_pitch, L_shoulder_pitch, L_shoulder_roll, L_elbow_pitch, L_elbow_yaw,
#             R_shoulder_pitch, R_shoulder_roll, R_elbow_pitch, R_elbow_yaw, waist,
#             L_hip_pitch, L_hip_roll, L_hip_yaw, L_knee_pitch, L_ankle_pitch, L_ankle_roll,
#             R_hip_pitch, R_hip_roll, R_hip_yaw, R_knee_pitch, R_ankle_pitch, R_ankle_roll]
KP_23 = [4.0, 4.0,
         50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0,
         200.0,
         200.0, 200.0, 200.0, 200.0, 50.0, 50.0,
         200.0, 200.0, 200.0, 200.0, 50.0, 50.0]

KD_23 = [1.0, 1.0,
         1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
         5.0,
         5.0, 5.0, 5.0, 5.0, 2.0, 2.0,
         5.0, 5.0, 5.0, 5.0, 2.0, 2.0]

# Default standing pose: EXACT from booster_deploy T1WalkControllerCfg
DEFAULT_POS_23 = [0, 0,
                  0.2, -1.3, 0, -0.5,
                  0.2, 1.3, 0, 0.5,
                  0.0,
                  -0.2, 0, 0, 0.4, -0.2, 0.0,
                  -0.2, 0, 0, 0.4, -0.2, 0.0]

# MuJoCo physics params from booster_deploy
PHYSICS_DT = 0.002
DECIMATION = 10  # control dt = 0.002 * 10 = 0.02
INIT_POS = [0.0, 0.0, 0.7]  # Trunk link initial height for URDF loading
INIT_QUAT = [1.0, 0.0, 0.0, 0.0]


class SoccerEnv:
    def __init__(self, num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg, show_viewer=False):
        if gs is None:
            raise RuntimeError("Genesis not available.")
        self.num_envs = num_envs
        self.device = gs.device
        self.cfg = env_cfg
        self.obs_cfg = obs_cfg
        self.reward_cfg = reward_cfg
        self.command_cfg = command_cfg
        self.task = env_cfg.get("task", "chase")
        self.distill_logger = None

        # Use booster_deploy physics params
        self.dt = PHYSICS_DT * DECIMATION  # 0.02
        self.substeps = DECIMATION  # 10 substeps per control step
        self.max_episode_length = math.ceil(env_cfg["episode_length_s"] / self.dt)
        self.action_scale = 0.25  # EXACT from booster_deploy
        self.clip_actions = env_cfg.get("clip_actions", 100.0)
        self.simulate_action_latency = env_cfg.get("simulate_action_latency", True)

        # Soccer field geometry
        self.ball_radius = env_cfg["ball_radius"]
        self.field_x, self.field_y = env_cfg["field"]
        self.goal_half = env_cfg["goal_width"] / 2.0
        self.goal_x = self.field_x / 2.0
        self.circle_radius = env_cfg.get("circle_radius", 1.5)
        self.fall_height = env_cfg.get("fall_height", 0.4)
        self.term_pitch = env_cfg.get("termination_pitch_deg", 30)
        self.term_roll = env_cfg.get("termination_roll_deg", 30)

        self.obs_history_length = 10  # EXACT from booster_deploy
        self.obs_scales = obs_cfg["obs_scales"]
        self.reward_scales = reward_cfg

        self._build_scene(show_viewer)

        # ---- auto-discover motor DOFs (23 total) ----
        self.motor_joints = [j for j in self.robot.joints[1:] if j.n_dofs > 0]
        self.motors_dof_idx = torch.tensor([j.dof_start for j in self.motor_joints], dtype=gs.tc_int, device=self.device)
        self.base_dof_start = int(self.motors_dof_idx[0].item())
        self.num_motors = len(self.motor_joints)  # 23

        # Build policy joint mapping: indices into the 23 motor joints
        all_joint_names = [j.name for j in self.motor_joints]
        self.policy_joint_indices = torch.tensor(
            [all_joint_names.index(n) for n in POLICY_JOINT_NAMES],
            dtype=gs.tc_int, device=self.device
        )
        # num_actions = 21 (PPO network output size, matches pre-trained model)
        self.num_actions = len(POLICY_JOINT_NAMES)

        # Default standing pose
        self.default_dof_pos = torch.tensor(DEFAULT_POS_23, dtype=gs.tc_float, device=self.device)
        self.policy_default_pos = self.default_dof_pos[self.policy_joint_indices].clone()

        # PD gains: set per-joint using booster_deploy values
        self.robot.set_dofs_kp(KP_23, self.motors_dof_idx)
        self.robot.set_dofs_kv(KD_23, self.motors_dof_idx)

        self.actions_dof_idx = torch.argsort(self.motors_dof_idx)

        # ---- buffers ----
        # EXACT obs format: 72 per frame × 10 history = 720 (NO ball info)
        self.obs_dim_per_frame = 3 + 3 + 3 + self.num_actions + self.num_actions + self.num_actions  # 72
        self.obs_history = torch.zeros((self.num_envs, self.obs_history_length, self.obs_dim_per_frame),
                                       dtype=gs.tc_float, device=self.device)

        # Action buffer: 21 policy actions
        self.actions = torch.zeros((self.num_envs, self.num_actions), dtype=gs.tc_float, device=self.device)
        self.last_actions = torch.zeros_like(self.actions)

        # State buffers (23 motors for physics, 21 for policy)
        self.base_pos = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.base_quat = torch.empty((self.num_envs, 4), dtype=gs.tc_float, device=self.device)
        self.base_euler = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.base_lin_vel = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.base_ang_vel = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.projected_gravity = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.dof_pos = torch.empty((self.num_envs, self.num_motors), dtype=gs.tc_float, device=self.device)
        self.dof_vel = torch.empty((self.num_envs, self.num_motors), dtype=gs.tc_float, device=self.device)
        self.last_dof_vel = torch.zeros_like(self.dof_pos)

        # Ball state (for reward, NOT in RL observation)
        self.ball_pos = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.ball_vel = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.prev_dist_to_ball = torch.empty((self.num_envs,), dtype=gs.tc_float, device=self.device)
        self.prev_ball_goal_dist = torch.empty((self.num_envs,), dtype=gs.tc_float, device=self.device)

        # Init pos/quat (use booster_deploy values)
        self.init_base_pos = torch.tensor([0.0, 0.0, 0.7], dtype=gs.tc_float, device=self.device)  # Trunk link height
        self.init_base_quat = torch.tensor(INIT_QUAT, dtype=gs.tc_float, device=self.device)
        self.inv_base_init_quat = inv_quat(self.init_base_quat)
        self.global_gravity = torch.tensor([0.0, 0.0, -1.0], dtype=gs.tc_float, device=self.device)
        self.init_projected_gravity = transform_by_quat(self.global_gravity, self.inv_base_init_quat)

        # Build init qpos
        qpos_template = self.robot.get_qpos()[0].clone()
        # Set floating base position (first 3 values = x, y, z)
        qpos_template[0] = 0.0  # x
        qpos_template[1] = 0.0  # y
        qpos_template[2] = INIT_POS[2]  # z = 0.7
        qpos_template[self.base_dof_start:self.base_dof_start + self.num_motors] = self.default_dof_pos
        self.init_qpos = qpos_template.unsqueeze(0).expand(self.num_envs, -1).clone()

        # Reward/reset buffers
        self.rew_buf = torch.empty((self.num_envs,), dtype=gs.tc_float, device=self.device)
        self.reset_buf = torch.ones((self.num_envs,), dtype=gs.tc_bool, device=self.device)
        self.episode_length_buf = torch.empty((self.num_envs,), dtype=gs.tc_int, device=self.device)
        self.extras = dict()

        # Velocity commands (same as booster_deploy)
        self.commands = torch.zeros(self.num_envs, 3, dtype=gs.tc_float, device=self.device)
        self.cmd_resample_time = torch.zeros(self.num_envs, dtype=gs.tc_int, device=self.device)

        # Feet tracking
        self.feet_pos = torch.zeros(self.num_envs, 2, 3, dtype=gs.tc_float, device=self.device)
        self.last_feet_pos = torch.zeros_like(self.feet_pos)
        self.feet_contact = torch.zeros(self.num_envs, 2, dtype=gs.tc_bool, device=self.device)
        self.filtered_lin_vel = torch.zeros(self.num_envs, 3, dtype=gs.tc_float, device=self.device)
        self.filtered_ang_vel = torch.zeros(self.num_envs, 3, dtype=gs.tc_float, device=self.device)
        self.fallen_prev = torch.zeros((self.num_envs,), dtype=gs.tc_bool, device=self.device)

        # Shot tracking
        self.shot_prev_vel = torch.zeros((self.num_envs,), dtype=gs.tc_float, device=self.device)
        self.shots_taken = 0
        self.shots_on_target = 0
        self.goals_scored = 0

        # obs_buf: exactly 720 dims (NO ball info — matches pre-trained model)
        self.obs_buf = torch.empty((self.num_envs, 720), dtype=gs.tc_float, device=self.device)

        self.reset()

    def _build_scene(self, show_viewer):
        self.scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=PHYSICS_DT, substeps=1),
            rigid_options=gs.options.RigidOptions(enable_self_collision=True, tolerance=1e-5, max_collision_pairs=512),
            viewer_options=gs.options.ViewerOptions(camera_pos=(6, 6, 4), camera_lookat=(0, 0, 0.5), camera_fov=40),
            vis_options=gs.options.VisOptions(
                rendered_envs_idx=[0],
                show_world_frame=False,
                show_link_frame=False,
                show_cameras=False,
                plane_reflection=True,
                ambient_light=(0.7, 0.7, 0.7),
                shadow=True,
            ),
            renderer=gs.renderers.Rasterizer(),
            show_viewer=show_viewer,
        )

        # Ground
        self.scene.add_entity(gs.morphs.URDF(file=_genesis_asset("urdf", "plane", "plane.urdf"), fixed=True))

        # Soccer field (only for single-env rendering)
        if self.num_envs == 1:
            import math as _m
            _FL = self.field_x; _FW = self.field_y; _HL = _FL / 2; _HW = _FW / 2
            _LH = 0.005; _LW = 0.12; _GW = self.goal_half * 2; _GH = 1.0; _PR = 0.05; _CR = self.circle_radius

            # Green field surface
            _field_surface = gs.surfaces.Rough(color=(0.12, 0.45, 0.15), roughness=0.9)
            self.scene.add_entity(
                morph=gs.morphs.Plane(pos=(0, 0, 0.001), plane_size=(_FL, _FW), fixed=True),
                surface=_field_surface,
            )

            # White field lines as thin Boxes
            _w = gs.surfaces.Rough(color=(1, 1, 1), roughness=0.8)
            _z = _LH / 2 + 0.002

            # Boundary lines (4 sides)
            self.scene.add_entity(morph=gs.morphs.Box(size=(_FL, _LW, _LH), pos=(0, -_HW, _z), fixed=True), surface=_w)
            self.scene.add_entity(morph=gs.morphs.Box(size=(_FL, _LW, _LH), pos=(0,  _HW, _z), fixed=True), surface=_w)
            self.scene.add_entity(morph=gs.morphs.Box(size=(_LW, _FW, _LH), pos=(-_HL, 0, _z), fixed=True), surface=_w)
            self.scene.add_entity(morph=gs.morphs.Box(size=(_LW, _FW, _LH), pos=( _HL, 0, _z), fixed=True), surface=_w)

            # Halfway line
            self.scene.add_entity(morph=gs.morphs.Box(size=(_LW, _FW, _LH), pos=(0, 0, _z), fixed=True), surface=_w)

            # Center circle (128 segments with overlap for solid smooth circle)
            _NSEG = 128
            _seg_len = 2 * _m.pi * _CR / _NSEG + _LW  # overlap by full line width
            for _i in range(_NSEG):
                _a = 2 * _m.pi * _i / _NSEG
                self.scene.add_entity(
                    morph=gs.morphs.Box(size=(_seg_len, _LW, _LH),
                                        pos=(_CR * _m.cos(_a), _CR * _m.sin(_a), _z),
                                        euler=(0, 0, _m.degrees(_a)), fixed=True),
                    surface=_w)

            # Center spot
            self.scene.add_entity(morph=gs.morphs.Box(size=(0.08, 0.08, _LH), pos=(0, 0, _z), fixed=True), surface=_w)

            # Penalty areas (both sides)
            _PA_DEPTH = 2.0   # penalty area depth
            _PA_HALF = 2.5    # penalty area half-width
            for _sx in [-_HL, _HL]:
                _pa_x = _sx + (_PA_DEPTH / 2) * (1 if _sx < 0 else -1)
                # 3 lines per penalty area: back, left, right
                self.scene.add_entity(morph=gs.morphs.Box(size=(_LW, _PA_HALF * 2, _LH), pos=(_pa_x, 0, _z), fixed=True), surface=_w)
                self.scene.add_entity(morph=gs.morphs.Box(size=(_PA_DEPTH, _LW, _LH), pos=(_pa_x - _PA_DEPTH/2 * (1 if _sx < 0 else -1), -_PA_HALF, _z), fixed=True), surface=_w)
                self.scene.add_entity(morph=gs.morphs.Box(size=(_PA_DEPTH, _LW, _LH), pos=(_pa_x - _PA_DEPTH/2 * (1 if _sx < 0 else -1),  _PA_HALF, _z), fixed=True), surface=_w)

            # Goal areas (smaller boxes inside penalty areas)
            _GA_DEPTH = 1.0
            _GA_HALF = 1.5
            for _sx in [-_HL, _HL]:
                _ga_x = _sx + (_GA_DEPTH / 2) * (1 if _sx < 0 else -1)
                self.scene.add_entity(morph=gs.morphs.Box(size=(_LW, _GA_HALF * 2, _LH), pos=(_ga_x, 0, _z), fixed=True), surface=_w)
                self.scene.add_entity(morph=gs.morphs.Box(size=(_GA_DEPTH, _LW, _LH), pos=(_ga_x - _GA_DEPTH/2 * (1 if _sx < 0 else -1), -_GA_HALF, _z), fixed=True), surface=_w)
                self.scene.add_entity(morph=gs.morphs.Box(size=(_GA_DEPTH, _LW, _LH), pos=(_ga_x - _GA_DEPTH/2 * (1 if _sx < 0 else -1),  _GA_HALF, _z), fixed=True), surface=_w)

            # Penalty spots
            for _sx in [-_HL + 1.5, _HL - 1.5]:
                self.scene.add_entity(morph=gs.morphs.Box(size=(0.08, 0.08, _LH), pos=(_sx, 0, _z), fixed=True), surface=_w)

            # Goal posts (white)
            _gs_s = gs.surfaces.Rough(color=(0.95, 0.95, 0.95), roughness=0.5)
            _hg = _GW / 2; _pw2 = _PR * 2
            for _gx in [-_HL, _HL]:
                self.scene.add_entity(morph=gs.morphs.Box(size=(_pw2, _pw2, _GH), pos=(_gx, -_hg, _GH / 2), fixed=True), surface=_gs_s)
                self.scene.add_entity(morph=gs.morphs.Box(size=(_pw2, _pw2, _GH), pos=(_gx, _hg, _GH / 2), fixed=True), surface=_gs_s)
                self.scene.add_entity(morph=gs.morphs.Box(size=(_pw2, _GW + _pw2, _pw2), pos=(_gx, 0, _GH), fixed=True), surface=_gs_s)

        # Robot — use booster_deploy init height (0.6m)
        robot_path = self.cfg["robot_urdf"]
        if not os.path.isabs(robot_path):
            ga = _genesis_asset(robot_path)
            robot_path = ga if os.path.exists(ga) else os.path.abspath(robot_path)
        if robot_path.endswith(".xml") or robot_path.endswith(".mjcf"):
            self.robot = self.scene.add_entity(gs.morphs.MJCF(file=robot_path, pos=INIT_POS, quat=INIT_QUAT))
        else:
            self.robot = self.scene.add_entity(gs.morphs.URDF(file=robot_path, pos=INIT_POS, quat=INIT_QUAT, fixed=False, merge_fixed_links=False))

        # Ball
        ball_path = os.path.join(os.path.dirname(__file__), "..", "assets", "ball.urdf")
        self.ball = self.scene.add_entity(gs.morphs.URDF(file=os.path.abspath(ball_path)))

        # Camera
        self.scene.add_camera(res=(960, 540), pos=(6, -8, 4), lookat=(0, 0, 0.5), fov=50, GUI=False)
        self.scene.build(n_envs=self.num_envs)

    def _obs_dim(self):
        return 720  # EXACT: 10 × 72, matches pre-trained model

    def get_stats(self):
        return {"shots_taken": self.shots_taken, "shots_on_target": self.shots_on_target,
                "goals_scored": self.goals_scored}

    def reset(self):
        self._reset_idx()
        self._update_observation()
        return self.get_observations()

    def step(self, actions):
        # actions: (num_envs, 21) — matches pre-trained model output
        self.actions = torch.clip(actions, -self.clip_actions, self.clip_actions)
        exec_actions = self.last_actions if self.simulate_action_latency else self.actions

        # Map 21 policy actions → 23 motor targets (head keeps default)
        target_dof_pos = self.default_dof_pos.unsqueeze(0).expand(self.num_envs, -1).clone()
        policy_targets = exec_actions * self.action_scale + self.policy_default_pos.unsqueeze(0)
        target_dof_pos[:, self.policy_joint_indices] = policy_targets

        self.robot.control_dofs_position(
            target_dof_pos[:, self.actions_dof_idx],
            slice(self.base_dof_start, self.base_dof_start + self.num_motors),
        )

        # Run DECIMATION substeps (booster_deploy convention)
        for _ in range(DECIMATION):
            self.scene.step()

        self.episode_length_buf += 1
        self._read_state()

        # Compute reward
        soccer = self._soccer_state()
        from rewards.reward import compute_reward
        w = dict(self.reward_scales)
        w["_ball_radius"] = self.ball_radius
        w["dt"] = self.dt
        for _k in list(w.keys()):
            if isinstance(w[_k], (int, float)) and _k not in ["_ball_radius", "dt", "tracking_sigma", "swing_period", "only_positive_rewards"]:
                w[_k] *= self.dt
        self.rew_buf = compute_reward(soccer, self.actions, w, self.task)

        self._resample_ball_if_needed()
        self.reset_buf = self.episode_length_buf > self.max_episode_length
        self.reset_buf |= torch.abs(self.base_euler[:, 1]) > self.term_pitch
        self.reset_buf |= torch.abs(self.base_euler[:, 0]) > self.term_roll
        self.reset_buf |= self.scene.rigid_solver.get_error_envs_mask()
        self.extras["time_outs"] = (self.episode_length_buf > self.max_episode_length).to(dtype=gs.tc_float)

        self._reset_idx(self.reset_buf)
        self._update_observation()
        self.last_actions.copy_(self.actions)
        self.last_dof_vel.copy_(self.dof_vel)
        self.fallen_prev.copy_(soccer["fallen"])
        return self.get_observations(), self.rew_buf, self.reset_buf, self.extras

    def get_observations(self):
        return TensorDict({"policy": self.obs_buf}, batch_size=[self.num_envs])

    def _read_state(self):
        # Read from Trunk link (link index 1), not robot.get_pos() which returns world link
        trunk = self.robot.links[1]
        self.base_pos = trunk.get_pos()
        self.base_quat = trunk.get_quat()
        self.base_euler = quat_to_xyz(transform_quat_by_quat(self.inv_base_init_quat, self.base_quat), rpy=True, degrees=True)
        inv_bq = inv_quat(self.base_quat)
        self.base_lin_vel = transform_by_quat(self.robot.get_vel(), inv_bq)
        self.base_ang_vel = transform_by_quat(self.robot.get_ang(), inv_bq)
        self.projected_gravity = transform_by_quat(self.global_gravity, inv_bq)
        self.dof_pos = self.robot.get_dofs_position(self.motors_dof_idx)
        self.dof_vel = self.robot.get_dofs_velocity(self.motors_dof_idx)
        self.ball_pos = self.ball.get_pos()
        self.ball_vel = self.ball.get_vel()

        fw = 0.1
        self.filtered_lin_vel[:] = self.base_lin_vel * fw + self.filtered_lin_vel * (1.0 - fw)
        self.filtered_ang_vel[:] = self.base_ang_vel * fw + self.filtered_ang_vel * (1.0 - fw)

        self.last_feet_pos.copy_(self.feet_pos)
        for _i, _n in enumerate(["left_foot_link", "right_foot_link"]):
            try:
                _link = self.robot.get_link(_n)
                self.feet_pos[:, _i, :] = _link.get_pos()
                self.feet_contact[:, _i] = self.feet_pos[:, _i, 2] < 0.06
            except Exception:
                self.feet_contact[:, _i] = False

    def _soccer_state(self):
        torso_up = torch.clamp(-self.projected_gravity[:, 2], min=-1.0, max=1.0)
        fallen = (self.base_pos[:, 2] < self.fall_height) | (torch.abs(self.base_euler[:, 1]) > 45) | (torch.abs(self.base_euler[:, 0]) > 45)
        dist_to_ball = torch.norm(self.base_pos[:, :2] - self.ball_pos[:, :2], dim=1)
        inv_bq = inv_quat(self.base_quat)
        ball_rel = self.ball_pos - self.base_pos
        ball_rel_body = transform_by_quat(ball_rel, inv_bq)
        goal_dir = torch.stack([self.goal_x - self.ball_pos[:, 0], -self.ball_pos[:, 1], torch.zeros_like(self.ball_pos[:, 0])], dim=1)
        goal_dir = goal_dir / (torch.norm(goal_dir, dim=1, keepdim=True) + 1e-6)
        ball_vel_to_goal = torch.sum(self.ball_vel[:, :2] * goal_dir[:, :2], dim=1)
        ball_goal_dist = torch.hypot(self.goal_x - self.ball_pos[:, 0], self.ball_pos[:, 1])
        feet_ball_xy = self.feet_pos[:, :, :2] - self.ball_pos.unsqueeze(1)[:, :, :2]
        min_foot_dist = torch.norm(feet_ball_xy, dim=2).min(dim=1).values
        scored = (self.ball_pos[:, 0] > self.goal_x) & (torch.abs(self.ball_pos[:, 1]) < self.goal_half)
        just_recovered = self.fallen_prev & (~fallen)

        shooting_now = (ball_vel_to_goal > 1.0) & (self.shot_prev_vel < 1.0)
        # Vectorized counters — 3 GPU syncs total instead of 2*num_envs syncs.
        # (The old per-env python loops scaled linearly with num_envs and would
        #  bottleneck training at 1024+ envs. Statistics are identical.)
        self.shots_taken += int(shooting_now.sum())
        self.shots_on_target += int((shooting_now & (self.ball_pos[:, 1].abs() < self.goal_half)).sum())
        self.goals_scored += int((scored & (self.shot_prev_vel > 0.5)).sum())
        self.shot_prev_vel.copy_(ball_vel_to_goal)

        return {
            "torso_up": torso_up, "fallen": fallen,
            "base_lin_vel_x": self.filtered_lin_vel[:, 0],
            "base_lin_vel_y_y": self.filtered_lin_vel[:, 1],
            "base_lin_vel_z": self.filtered_lin_vel[:, 2],
            "base_ang_vel_z": self.filtered_ang_vel[:, 2],
            "base_ang_vel_xy": self.base_ang_vel[:, :2],
            "projected_gravity_xy": self.projected_gravity[:, :2],
            "ball_x": self.ball_pos[:, 0],
            "dist_to_ball": dist_to_ball,
            "prev_dist_to_ball": self.prev_dist_to_ball,
            "ball_goal_dist": ball_goal_dist,
            "prev_ball_goal_dist": self.prev_ball_goal_dist,
            "min_foot_dist": min_foot_dist,
            "ball_vel_to_goal": ball_vel_to_goal,
            "scored": scored, "just_recovered": just_recovered,
            "commands": self.commands,
            "gait_process": torch.zeros(self.num_envs, device=self.device),
            "gait_frequency": torch.ones(self.num_envs, device=self.device),
            "goal_dir_body": goal_dir[:, :2],
            "ball_rel_body": ball_rel_body[:, :2],
            "feet_contact": self.feet_contact,
            "feet_pos": self.feet_pos, "last_feet_pos": self.last_feet_pos,
            "episode_length_buf": self.episode_length_buf,
            "last_actions": self.last_actions,
            "last_dof_vel": self.last_dof_vel[:, self.policy_joint_indices],
            "dof_vel": self.dof_vel[:, self.policy_joint_indices],
        }

    def _resample_ball_if_needed(self):
        self.prev_dist_to_ball = torch.norm(self.base_pos[:, :2] - self.ball_pos[:, :2], dim=1).clone()
        self.prev_ball_goal_dist = torch.hypot(self.goal_x - self.ball_pos[:, 0], self.ball_pos[:, 1]).clone()

    def _reset_idx(self, envs_idx=None):
        self.robot.set_qpos(self.init_qpos, envs_idx=envs_idx, zero_velocity=True, skip_forward=True)
        ball_qpos = self._sample_ball_qpos()
        self.ball.set_qpos(ball_qpos, envs_idx=envs_idx, zero_velocity=True, skip_forward=True)

        if envs_idx is None:
            self.base_pos.copy_(self.init_base_pos)
            self.base_quat.copy_(self.init_base_quat)
            self.projected_gravity.copy_(self.init_projected_gravity)
            self.dof_pos.copy_(self.default_dof_pos.unsqueeze(0).expand(self.num_envs, -1))
            self.base_lin_vel.zero_(); self.base_ang_vel.zero_(); self.dof_vel.zero_()
            self.actions.zero_(); self.last_actions.zero_(); self.last_dof_vel.zero_()
            self.obs_history.zero_(); self.episode_length_buf.zero_()
            self.reset_buf.fill_(True); self.fallen_prev.zero_()
        else:
            torch.where(envs_idx[:, None], self.init_base_pos, self.base_pos, out=self.base_pos)
            torch.where(envs_idx[:, None], self.init_base_quat, self.base_quat, out=self.base_quat)
            torch.where(envs_idx[:, None], self.init_projected_gravity, self.projected_gravity, out=self.projected_gravity)
            torch.where(envs_idx[:, None], self.default_dof_pos.unsqueeze(0).expand(self.num_envs, -1), self.dof_pos, out=self.dof_pos)
            self.base_lin_vel.masked_fill_(envs_idx[:, None], 0.0)
            self.base_ang_vel.masked_fill_(envs_idx[:, None], 0.0)
            self.dof_vel.masked_fill_(envs_idx[:, None], 0.0)
            self.actions.masked_fill_(envs_idx[:, None], 0.0)
            self.last_actions.masked_fill_(envs_idx[:, None], 0.0)
            self.last_dof_vel.masked_fill_(envs_idx[:, None], 0.0)
            self.episode_length_buf.masked_fill_(envs_idx, 0)
            self.reset_buf.masked_fill_(envs_idx, True)
            self.fallen_prev.masked_fill_(envs_idx, False)

        self._read_state()
        self.prev_dist_to_ball = torch.norm(self.base_pos[:, :2] - self.ball_pos[:, :2], dim=1).clone()
        self.prev_ball_goal_dist = torch.hypot(self.goal_x - self.ball_pos[:, 0], self.ball_pos[:, 1]).clone()
        self._resample_commands(envs_idx)

    def _sample_ball_qpos(self):
        lo = torch.tensor([-self.field_x / 2 + 0.5, -self.goal_half, self.ball_radius], device=self.device)
        hi = torch.tensor([self.goal_x - 1.0, self.goal_half, self.ball_radius], device=self.device)
        pos = gs_rand(lo, hi, (self.num_envs,))
        quat = torch.zeros((self.num_envs, 4), device=self.device)
        quat[:, 0] = 1.0
        return torch.cat([pos, quat], dim=1)

    def _resample_commands(self, envs_idx):
        if envs_idx is None:
            n = self.num_envs
            self.commands[:, 0] = torch_rand_float(-1.0, 1.0, (n,), device=self.device)
            self.commands[:, 1] = torch_rand_float(-1.0, 1.0, (n,), device=self.device)
            self.commands[:, 2] = torch_rand_float(-1.0, 1.0, (n,), device=self.device)
            self.cmd_resample_time[:] = self.episode_length_buf + torch.randint(
                int(8.0 / self.dt), int(12.0 / self.dt), (n,), device=self.device).to(dtype=gs.tc_int)
        else:
            n = envs_idx.sum().item()
            if n > 0:
                _idx = envs_idx.nonzero(as_tuple=False).flatten()
                self.commands[_idx, 0] = torch_rand_float(-1.0, 1.0, (n,), device=self.device)
                self.commands[_idx, 1] = torch_rand_float(-1.0, 1.0, (n,), device=self.device)
                self.commands[_idx, 2] = torch_rand_float(-1.0, 1.0, (n,), device=self.device)
                self.cmd_resample_time[_idx] = self.episode_length_buf[_idx] + torch.randint(
                    int(8.0 / self.dt), int(12.0 / self.dt), (n,), device=self.device).to(dtype=gs.tc_int)
        _need = self.episode_length_buf >= self.cmd_resample_time
        if _need.any():
            _idx = _need.nonzero(as_tuple=False).flatten()
            _n = len(_idx)
            self.commands[_idx, 0] = torch_rand_float(-1.0, 1.0, (_n,), device=self.device)
            self.commands[_idx, 1] = torch_rand_float(-1.0, 1.0, (_n,), device=self.device)
            self.commands[_idx, 2] = torch_rand_float(-1.0, 1.0, (_n,), device=self.device)
            self.cmd_resample_time[_idx] += torch.randint(
                int(8.0 / self.dt), int(12.0 / self.dt), (_n,), device=self.device).to(dtype=gs.tc_int)

    def _update_observation(self):
        """Build observation EXACTLY matching booster_deploy format.

        Per frame (72 dims):
          ang_vel(3) + projected_gravity(3) + commands(3) +
          dof_pos(21) + dof_vel(21) + last_action(21)

        10-frame history → 720 dims total.
        NO ball info — ball is handled by rule layer, not RL policy.

        CRITICAL: obs_scales MUST be applied to match the pre-trained
        normalizer, which was trained on SCALED obs from booster_deploy.
        """
        # Extract policy joint subset from full 23-joint state
        policy_dof_pos = self.dof_pos[:, self.policy_joint_indices]
        policy_dof_vel = self.dof_vel[:, self.policy_joint_indices]

        # Apply obs_scales (must match booster_deploy training convention)
        s_ang_vel = self.obs_scales.get("ang_vel", 0.25)
        s_dof_pos = self.obs_scales.get("dof_pos", 1.0)
        s_dof_vel = self.obs_scales.get("dof_vel", 0.05)

        base_obs = torch.cat([
            self.base_ang_vel * s_ang_vel,                                           # 3
            self.projected_gravity,                                                   # 3
            self.commands,                                                           # 3
            (policy_dof_pos - self.policy_default_pos.unsqueeze(0)) * s_dof_pos,     # 21
            policy_dof_vel * s_dof_vel,                                              # 21
            self.last_actions,                                                        # 21
        ], dim=-1)  # Total: 72

        # Update history: shift left, append new frame
        self.obs_history = torch.cat([self.obs_history[:, 1:], base_obs.unsqueeze(1)], dim=1)

        # Flatten: (num_envs, 720)
        self.obs_buf = self.obs_history.reshape(self.num_envs, -1)

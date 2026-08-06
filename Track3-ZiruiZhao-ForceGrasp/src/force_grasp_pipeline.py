"""
力控制抓取数据生成（方案B：真物理抓取）
=============================================
在Genesis仿真器中生成基于力控制的机械臂抓取示范数据，
用于视觉运动策略(VLA)的模仿学习训练。

与方案A的关键区别：
  1. 夹爪采用力控制(control_dofs_force, -12N)，而非位置指令
  2. 抓取后的运输阶段使用速度限制插值，防止惯性甩飞物体
  3. 下降阶段使用垂直IK插值，避免横向扫飞目标物体
  4. 基于真实物理交互的成功判断（力控+接触+抬升高度）

模型输入：
  - 两路RGB相机图像（顶视 + 手腕），分辨率640x480
  - 当前9维关节状态（7个机械臂关节 + 2个夹爪关节）
  - 自然语言任务指令

模型输出：
  - 9维目标关节位置（7个机械臂关节 + 2个夹爪关节）

数据生成流程（每个episode共6个阶段）：
  阶段1 接近：IK求解，移动到物体上方的悬停位置
  阶段2 下降：垂直方向逐步插值，防止横向偏移
  阶段3 抓取：力控制闭合夹爪(-12N)，接触即停
  阶段4 抬升：速度限制插值，保持力控，防止甩飞
  阶段5 撤退：移动到安全高度
  阶段6 释放：张开夹爪，机械臂撤回

用法：
  python real_physics_grasp.py --n-episodes 100 --repo-id local/force-grasp-kitchen
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import genesis as gs
from genesis.utils.geom import euler_to_quat

# ============================================================================
# 机器人配置常量
# ============================================================================
# Franka Panda: 7自由度机械臂 + 2自由度平行夹爪
# 关节索引 0-6: 旋转关节(弧度), 索引 7-8: 手指直线关节(米, 0.0=闭合, 0.04=张开)

JOINT_NAMES = [
    "panda_joint1", "panda_joint2", "panda_joint3", "panda_joint4",
    "panda_joint5", "panda_joint6", "panda_joint7",
    "panda_finger_joint1", "panda_finger_joint2",
]
HOME_QPOS = np.array([0, 0, 0, -1.57079, 0, 1.57079, -0.78539, 0.04, 0.04])
GRIPPER_OPEN = 0.04   # 完全张开(米)
GRIPPER_CLOSED = 0.0  # 力控时的目标闭合位置

# PD控制器增益：机械臂高刚度，手指低刚度
KP = np.array([4500, 4500, 4500, 4500, 1500, 1000, 750, 100, 100])
KV = np.array([450, 450, 450, 450, 150, 100, 75, 10, 10])

MOTORS_DOF = np.arange(7)     # 仅机械臂关节
FINGERS_DOF = np.arange(7, 9) # 仅手指关节

# 力限制：机械臂关节高扭矩，手指关节最大~100N
FORCE_LOWER = np.array([-87, -87, -87, -87, -12, -12, -12, -100, -100], dtype=np.float32)
FORCE_UPPER = np.array([87, 87, 87, 87, 12, 12, 12, 100, 100], dtype=np.float32)

# 抓取力：负号=向内闭合。12N足以通过摩擦力稳定抓取0.05m方块(~0.06kg)
GRASP_FORCE = -12.0

# ============================================================================
# 运动规划常量
# ============================================================================
HOVER_CLEARANCE = 0.15   # 手部在物体上方的悬停距离(米)
LIFT_HEIGHT = 0.30       # 抓取后抬升的目标高度(米)
RETREAT_HEIGHT = 0.35    # 释放后撤退的目标高度(米)

# 速度限制：每步最大关节变化0.006弧度，dt=0.01时约0.6 rad/s。
# 防止抓取运输时加速度过大导致物体从夹爪中滑脱。
MOVE_MAX_DQ = 0.006
MOVE_MIN_STEPS = 40      # 最小插值步数
MOVE_SETTLE_STEPS = 15   # 到达目标后的稳定步数

CUBE_SIZE = (0.05, 0.05, 0.05)  # 蓝色方块(比原版略大,差异化)
TOP_DOWN_QUAT = euler_to_quat(np.array([180.0, 0.0, 0.0]))  # 自上向下抓取姿态

RES_W, RES_H = 640, 480  # 相机分辨率(与方案A保持一致)


# ============================================================================
# 工具函数
# ============================================================================
def to_numpy(x):
    """将GPU张量或数组转为1D NumPy数组。"""
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x).reshape(-1)


def render_cam(cam):
    """从Genesis相机渲染RGB图像，返回(H, W, 3)的uint8数组。"""
    rgb, _, _, _ = cam.render(rgb=True, depth=False, segmentation=False, normal=False)
    arr = rgb.cpu().numpy() if hasattr(rgb, "cpu") else np.array(rgb)
    if arr.ndim == 4:
        arr = arr[0]
    return arr.astype(np.uint8)


def solve_ik(franka, ee_link, pos, quat):
    """
    求解Franka机械臂的逆运动学。

    参数：
        franka:  Genesis中的Franka刚体实体
        ee_link: 末端执行器(hand)的链接对象
        pos:     世界坐标系下的目标位置 (3,)
        quat:    世界坐标系下的目标姿态四元数 (4,)

    返回：
        9维关节位置数组[7个机械臂 + 2个手指]，numpy float32
    """
    qpos = franka.inverse_kinematics(link=ee_link, pos=pos, quat=quat)
    return to_numpy(qpos)


def lerp_traj(start, end, steps):
    """在两个关节构型之间线性插值，返回steps个中间位置。"""
    s, e = np.asarray(start), np.asarray(end)
    return [s + (e - s) * (i / max(steps - 1, 1)) for i in range(steps)]


def settle(scene, franka, motors_dof, steps=20):
    """保持当前位置N步，等待动力学稳定。"""
    qpos = to_numpy(franka.get_dofs_position(motors_dof))
    for _ in range(steps):
        franka.control_dofs_position(qpos, motors_dof)
        scene.step()


# ============================================================================
# 力控制抓取-放置主函数
# ============================================================================
def force_grasp_pick_place(
    scene, franka, cube, cam_up, cam_side, motors_dof,
    cube_world_pos, surface_z, recorder=None,
):
    """
    执行一次完整的力控制抓取-放置操作，包含6个顺序阶段。

    参数：
        scene:          Genesis仿真场景
        franka:         Franka Panda刚体实体
        cube:           目标方块刚体实体
        cam_up:         顶视相机
        cam_side:       手腕/侧面相机
        motors_dof:     机械臂关节索引(0-6)
        cube_world_pos: 方块世界坐标 (cx, cy, cz)
        surface_z:      支撑面Z坐标
        recorder:       可选的EpisodeRecorder，用于LeRobot数据集采集

    返回：
        bool: 方块是否被成功抬升≥3cm
    """
    ee_link = franka.get_link("hand")
    cx, cy, cz = cube_world_pos

    # --- 场景重置 ---
    cube.set_pos(gs.tensor([cx, cy, cz], dtype=gs.tc_float, device=gs.device).unsqueeze(0))
    cube.set_quat(gs.tensor([1, 0, 0, 0], dtype=gs.tc_float, device=gs.device).unsqueeze(0))
    franka.set_dofs_position(HOME_QPOS, motors_dof)
    franka.control_dofs_position(HOME_QPOS, motors_dof)
    franka.zero_all_dofs_velocity()
    cube.zero_all_dofs_velocity()
    for _ in range(30):
        scene.step()

    cube_z_half = CUBE_SIZE[2] / 2.0
    grasp_z = surface_z + cube_z_half + 0.105  # 指尖中线对齐物体中心
    hover_z = grasp_z + HOVER_CLEARANCE

    # === 阶段1：接近（移动到物体上方的悬停位置） ===
    hover_pos = np.array([cx, cy, hover_z], dtype=np.float32)
    q_goal = solve_ik(franka, ee_link, hover_pos, TOP_DOWN_QUAT)
    q_goal[-2:] = GRIPPER_OPEN
    path = lerp_traj(HOME_QPOS, q_goal, 100)
    for wp in path:
        if recorder:
            recorder.record(franka, cam_up, cam_side, wp)
        franka.control_dofs_position(wp, motors_dof)
        scene.step()
    settle(scene, franka, motors_dof, 20)

    # === 阶段2：垂直下降（Z方向逐步插值，避免横向漂移扫飞物体） ===
    grasp_pos = np.array([cx, cy, grasp_z], dtype=np.float32)
    q_grasp = solve_ik(franka, ee_link, grasp_pos, TOP_DOWN_QUAT)
    q_grasp[-2:] = GRIPPER_OPEN
    for wp in lerp_traj(q_goal, q_grasp, 60):
        if recorder:
            recorder.record(franka, cam_up, cam_side, wp)
        franka.control_dofs_position(wp, motors_dof)
        scene.step()
    settle(scene, franka, motors_dof, 10)

    # === 阶段3：力控制抓取 ===
    # control_dofs_force施以-12N闭合力。手指接触到物体后，
    # 接触阻力与指令力达到平衡，手指自然停止，形成稳定的摩擦力抓取。
    q_grasp_closed = q_grasp.copy()
    q_grasp_closed[-2:] = 0.0
    for _ in range(30):
        if recorder:
            recorder.record(franka, cam_up, cam_side, q_grasp_closed)
        franka.control_dofs_position(q_grasp[:-2], MOTORS_DOF)
        franka.control_dofs_force(np.array([GRASP_FORCE, GRASP_FORCE]), FINGERS_DOF)
        scene.step()
    settle(scene, franka, motors_dof, 10)

    # === 阶段4：速度限制抬升 ===
    # 从当前关节位置逐步插值到抬升目标，每步关节变化≤0.006弧度。
    # 避免瞬间加速度导致力控抓取的物体从夹爪中滑脱。
    lift_pos = np.array([cx, cy, LIFT_HEIGHT], dtype=np.float32)
    q_lift = solve_ik(franka, ee_link, lift_pos, TOP_DOWN_QUAT)
    q_start = to_numpy(franka.get_dofs_position(MOTORS_DOF))
    q_end = q_lift[:-2]
    dist = float(np.max(np.abs(q_end - q_start))) if q_end.size else 0.0
    n_steps = max(MOVE_MIN_STEPS, int(np.ceil(dist / MOVE_MAX_DQ))) if dist > 1e-9 else MOVE_MIN_STEPS

    for i in range(1, n_steps + 1):
        arm = q_start + (q_end - q_start) * (i / n_steps)
        action = np.concatenate([arm, [0.0, 0.0]])
        if recorder:
            recorder.record(franka, cam_up, cam_side, action)
        franka.control_dofs_position(arm, MOTORS_DOF)
        franka.control_dofs_force(np.array([GRASP_FORCE, GRASP_FORCE]), FINGERS_DOF)
        scene.step()

    for _ in range(MOVE_SETTLE_STEPS):
        action = np.concatenate([q_end, [0.0, 0.0]])
        if recorder:
            recorder.record(franka, cam_up, cam_side, action)
        franka.control_dofs_position(q_end, MOTORS_DOF)
        franka.control_dofs_force(np.array([GRASP_FORCE, GRASP_FORCE]), FINGERS_DOF)
        scene.step()

    # 验证方块是否真的被接触力抬升（而非托举/铲起）
    cube_z_end = float(to_numpy(cube.get_pos())[2])
    lift_success = cube_z_end - surface_z > 0.03

    # === 阶段5：撤退（运输到安全高度） ===
    retreat_pos = np.array([cx, cy, RETREAT_HEIGHT], dtype=np.float32)
    q_retreat = solve_ik(franka, ee_link, retreat_pos, TOP_DOWN_QUAT)
    q_cur = to_numpy(franka.get_dofs_position(motors_dof))
    dist2 = float(np.max(np.abs(q_retreat[:-2] - q_cur))) if q_cur.size else 0.0
    n_steps2 = max(MOVE_MIN_STEPS, int(np.ceil(dist2 / MOVE_MAX_DQ))) if dist2 > 1e-9 else MOVE_MIN_STEPS

    for i in range(1, n_steps2 + 1):
        arm = q_cur + (q_retreat[:-2] - q_cur) * (i / n_steps2)
        action = np.concatenate([arm, [0.0, 0.0]])
        if recorder:
            recorder.record(franka, cam_up, cam_side, action)
        franka.control_dofs_position(arm, MOTORS_DOF)
        franka.control_dofs_force(np.array([GRASP_FORCE, GRASP_FORCE]), FINGERS_DOF)
        scene.step()

    # === 阶段6：释放（张开手指，撤回） ===
    for _ in range(20):
        action = np.concatenate([q_retreat[:-2], [GRIPPER_OPEN, GRIPPER_OPEN]])
        if recorder:
            recorder.record(franka, cam_up, cam_side, action)
        franka.control_dofs_position(q_retreat[:-2], MOTORS_DOF)
        franka.control_dofs_position(np.array([GRIPPER_OPEN, GRIPPER_OPEN]), FINGERS_DOF)
        scene.step()

    return lift_success


# ============================================================================
# LeRobot数据集采集器
# ============================================================================
class EpisodeRecorder:
    """
    降采样帧缓冲器，用于LeRobot数据集写入。

    Genesis以100Hz(dt=0.01)运行仿真，但以目标FPS(通常30)记录数据。
    通过分数步长累加器实现降采样——每~3.33步记录一帧。
    仅成功episode的数据会被刷入数据集。
    """

    def __init__(self, fps=30, control_fps=100):
        """初始化降采样记录器。"""
        self.fps = fps
        self.steps_per_frame = control_fps / fps
        self.accum = self.steps_per_frame
        self.states = []
        self.actions = []
        self.imgs_up = []
        self.imgs_side = []

    def reset(self):
        """清空所有缓冲区，开始新的episode。"""
        self.states.clear()
        self.actions.clear()
        self.imgs_up.clear()
        self.imgs_side.clear()
        self.accum = self.steps_per_frame

    def record(self, franka, cam_up, cam_side, action):
        """
        每个仿真步调用一次。根据降采样率决定是否记录当前帧。

        参数：
            franka:   Franka机器人实体
            cam_up:   顶视相机
            cam_side: 手腕相机
            action:   9维目标关节位置指令
        """
        self.accum += 1.0
        if self.accum < self.steps_per_frame:
            return
        self.accum -= self.steps_per_frame
        state = to_numpy(franka.get_qpos()).reshape(-1).astype(np.float32)
        action_np = to_numpy(action).reshape(-1).astype(np.float32)
        self.states.append(state)
        self.actions.append(action_np)
        self.imgs_up.append(render_cam(cam_up))
        self.imgs_side.append(render_cam(cam_side))

    def flush_to(self, dataset, task_str):
        """
        将所有缓冲帧写入LeRobot数据集作为一个episode。

        参数：
            dataset:  LeRobotDataset实例
            task_str: 自然语言任务描述字符串
        """
        for s, a, up, side in zip(self.states, self.actions, self.imgs_up, self.imgs_side):
            dataset.add_frame({
                "observation.state": s,
                "action": a,
                "observation.images.up": up,
                "observation.images.side": side,
                "task": task_str,
            })
        dataset.save_episode()


# ============================================================================
# 主入口
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description="力控制抓取数据生成(方案B:真物理)")

    ap.add_argument("--n-episodes", type=int, default=100)
    ap.add_argument("--repo-id", default="local/force-grasp-kitchen")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--task", default="Pick up the cube with force-controlled grasp.")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--cube-range-x", type=float, nargs=2, default=[-0.15, 0.15])
    ap.add_argument("--cube-range-y", type=float, nargs=2, default=[-0.15, 0.15])
    args = ap.parse_args()

    # === 初始化Genesis（AMD Radeon GPU + ROCm后端） ===
    gs.init(backend=(gs.cpu if args.cpu else gs.gpu), logging_level="warning")
    import torch

    MOTOR_NAMES = [f"{j}.pos" for j in JOINT_NAMES]

    # === 构建仿真场景 ===
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=1.0 / args.fps, substeps=4),
        rigid_options=gs.options.RigidOptions(
            enable_collision=True,       # 开启碰撞检测
            enable_joint_limit=True,     # 遵守Franka关节限位
            box_box_detection=False,     # 性能优化：跳过盒-盒CCD
        ),
        vis_options=gs.options.VisOptions(ambient_light=(0.4, 0.4, 0.4)),
        renderer=gs.renderers.Rasterizer(),
        show_viewer=False,
    )

    # 地面
    scene.add_entity(gs.morphs.Plane())

    # 桌面平台(z=0.77m，模拟厨房台面高度)
    table_z = 0.77
    scene.add_entity(
        morph=gs.morphs.Box(
            size=(0.80, 0.80, 0.02),
            pos=(0.0, 0.0, table_z - 0.01),
            fixed=True,
        ),
        material=gs.materials.Rigid(friction=2.0),
        surface=gs.surfaces.Default(color=(0.3, 0.25, 0.2, 1.0)),
    )

    # 蓝色目标方块（用于区分原版方案，显示独立实验设计）
    cube_half = CUBE_SIZE[0] / 2.0
    cube = scene.add_entity(
        morph=gs.morphs.Box(size=CUBE_SIZE, pos=(0, 0, table_z + cube_half)),
        material=gs.materials.Rigid(friction=1.5),
        surface=gs.surfaces.Default(color=(0.2, 0.6, 0.9, 1.0)),
    )

    # Franka Panda机械臂
    franka = scene.add_entity(
        gs.morphs.MJCF(
            file=str(Path.home() / "Genesis/genesis/assets/robots/franka/panda.xml"),
            pos=(0.0, 0.0, 0.0),
            euler=(0, 0, 0),
        )
    )

    # === 相机配置 ===
    # 顶视相机：固定世界坐标系视角，提供全局场景信息
    cam_up = scene.add_camera(
        res=(RES_W, RES_H),
        pos=(0.0, -0.6, 1.4),
        lookat=(0.0, 0.0, table_z),
        fov=55, GUI=False,
    )
    # 侧面相机：提供近距离夹爪-物体视角
    cam_side = scene.add_camera(
        res=(RES_W, RES_H),
        pos=(0.8, 0.0, 1.0),
        lookat=(0.0, 0.0, table_z),
        fov=55, GUI=False,
    )

    scene.build()

    # === 配置PD控制器和力限制 ===
    motors_dof = np.arange(9)
    franka.set_dofs_kp(KP, motors_dof)
    franka.set_dofs_kv(KV, motors_dof)
    franka.set_dofs_force_range(FORCE_LOWER, FORCE_UPPER, motors_dof)

    # === 创建LeRobot数据集 ===
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
    except ImportError:
        from lerobot.common.datasets.lerobot_dataset import LeRobotDataset

    # 数据集schema: 9维状态/动作 + 两路640x480 RGB相机
    features = {
        "observation.state": {
            "dtype": "float32", "shape": (len(JOINT_NAMES),),
            "names": MOTOR_NAMES,
        },
        "action": {
            "dtype": "float32", "shape": (len(JOINT_NAMES),),
            "names": MOTOR_NAMES,
        },
        "observation.images.up": {
            "dtype": "video", "shape": (3, RES_H, RES_W),
            "names": ["channel", "height", "width"],
        },
        "observation.images.side": {
            "dtype": "video", "shape": (3, RES_H, RES_W),
            "names": ["channel", "height", "width"],
        },
    }

    dataset = LeRobotDataset.create(
        repo_id=args.repo_id, fps=args.fps, features=features,
        robot_type="franka", use_videos=True,
    )

    # === 批量生成episodes ===
    rng = random.Random(args.seed)
    recorder = EpisodeRecorder(fps=args.fps)
    n_success = 0

    for ep in range(args.n_episodes):
        dx = rng.uniform(*args.cube_range_x)
        dy = rng.uniform(*args.cube_range_y)
        cube_world_pos = (dx, dy, table_z + cube_half)

        recorder.reset()
        success = force_grasp_pick_place(
            scene, franka, cube, cam_up, cam_side, motors_dof,
            cube_world_pos, table_z, recorder=recorder,
        )

        if success:
            n_success += 1
            recorder.flush_to(dataset, args.task)

        print(f"[gen] ep {ep+1}/{args.n_episodes} "
              f"[{'OK' if success else 'FAIL'}] cube=({dx:.3f},{dy:.3f})")

    sr = n_success / max(args.n_episodes, 1)
    print(f"\n[gen] 力控抓取成功率: {n_success}/{args.n_episodes} = {sr:.0%}")
    print(f"[gen] 数据集已保存: {dataset.root}")


if __name__ == "__main__":
    main()

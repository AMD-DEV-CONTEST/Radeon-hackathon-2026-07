"""
G1-D OpenPI 推理 Client — 关节空间直接控制

架构: 本脚本运行在本地 PC，通过 WebSocket 请求 OpenPI policy server 获取预测动作，
      通过 DDS 直接下发双臂关节指令，通过 ZMQ 从 Jetson 获取图像。

数据流:
  1. ImageClient(ZMQ) 获取相机图像 + DDS 获取双臂关节角/夹爪状态
  2. 组装 16-dim joint state 观测 (left_arm[7]+right_arm[7]+grippers[2]，与训练一致)
  3. WebSocket → OpenPI policy server 推理
  4. Server 输出反归一化后的绝对关节角 (Unnormalize → AbsoluteActions)
  5. 直接下发关节角控制双臂 + 夹爪

依赖:
  - openpi_client (OpenPI 官方轻量客户端)
  - unitree_lerobot (DDS/ZMQ 机器人通信)
  - unitree_sdk2py (DDS 底层)
"""

import argparse
import collections
import json
import logging
import os
import time

import cv2
import numpy as np
import pyarrow.parquet as pq

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 16-dim 布局 (与训练/数据集一致): left_arm[0:7] + right_arm[7:14] + left_grip[14] + right_grip[15]
IDX_LEFT_GRIP = 14
IDX_RIGHT_GRIP = 15

# ═══════════════════════════════════════════════════════════════════════════════
# 数据集加载
# ═══════════════════════════════════════════════════════════════════════════════


def load_first_frame_joint(dataset_path: str, episode_index: int = 0) -> np.ndarray:
    """从 LeRobot v2.1 格式数据集中加载指定 episode 第一帧的 joint 状态 (16-dim)。

    数据集目录结构:
        dataset_path/
        ├── meta/info.json
        └── data/chunk-000/episode_000000.parquet

    Args:
        dataset_path: 数据集根目录
        episode_index: 使用哪个 episode 的第一帧作为初始位姿

    Returns:
        (16,) float32 array — 第一帧 observation.state
    """
    info_path = os.path.join(dataset_path, "meta", "info.json")
    if not os.path.exists(info_path):
        raise FileNotFoundError(f"找不到数据集 info.json: {info_path}")

    with open(info_path, "r") as f:
        info = json.load(f)

    chunks_size = info.get("chunks_size", 1000)
    data_path_template = info.get(
        "data_path", "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet"
    )

    chunk_index = episode_index // chunks_size
    relative_path = data_path_template.format(
        episode_index=episode_index,
        episode_chunk=chunk_index,
        chunk_index=chunk_index,
    )
    parquet_path = os.path.join(dataset_path, relative_path)

    if not os.path.exists(parquet_path):
        raise FileNotFoundError(f"找不到 parquet 文件: {parquet_path}")

    table = pq.read_table(parquet_path)
    obs_state_col = table.column("observation.state")
    first_frame = np.array(obs_state_col[0].as_py(), dtype=np.float32)

    if first_frame.shape[0] != 16:
        raise ValueError(f"期望 16-dim joint state，实际: {first_frame.shape}")

    logger.info(
        f"数据集第一帧 joint state: "
        f"L_arm=[{first_frame[0]:.3f},...,{first_frame[6]:.3f}] "
        f"R_arm=[{first_frame[7]:.3f},...,{first_frame[13]:.3f}] "
        f"L_grip={first_frame[IDX_LEFT_GRIP]:.3f} "
        f"R_grip={first_frame[IDX_RIGHT_GRIP]:.3f}"
    )
    return first_frame


# ═══════════════════════════════════════════════════════════════════════════════
# 机器人初始化
# ═══════════════════════════════════════════════════════════════════════════════


def initialize_robot(
    init_state_16d: np.ndarray,
    arm_ctrl,
    arm_ik,
    left_gripper_val,
    right_gripper_val,
):
    """将双臂和夹爪初始化到指定的 joint 位姿（直接关节控制，无需 IK）。

    Args:
        init_state_16d: (16,) 目标关节状态
        arm_ctrl: ArmController 实例
        arm_ik: ArmIK 实例 (用于求解 tau)
        left_gripper_val: multiprocessing.Value — 左夹爪控制值
        right_gripper_val: multiprocessing.Value — 右夹爪控制值

    Returns:
        (init_left_gripper, init_right_gripper) 初始夹爪值
    """
    state = np.asarray(init_state_16d, dtype=np.float64).ravel()

    # 拆分 16-dim → arm_q[14] + gripper[2]
    arm_q = np.concatenate([state[:7], state[7:14]])
    left_gripper = float(state[IDX_LEFT_GRIP])
    right_gripper = float(state[IDX_RIGHT_GRIP])

    tau = arm_ik.solve_tau(arm_q)
    arm_ctrl.ctrl_dual_arm(arm_q, tau)
    logger.info(f"双臂正在运动到初始位姿: q={np.array2string(arm_q, precision=4)}")

    left_gripper_val.value = left_gripper
    right_gripper_val.value = right_gripper
    logger.info(f"夹爪初始化: L={left_gripper:.3f}, R={right_gripper:.3f}")

    time.sleep(2.0)
    logger.info("初始化完成，双臂和夹爪已到位。")
    return left_gripper, right_gripper


# ═══════════════════════════════════════════════════════════════════════════════
# 观测获取
# ═══════════════════════════════════════════════════════════════════════════════


def get_observation(image_client, cam_config, arm_ctrl, left_grip_val, right_grip_val):
    """获取 3 路相机图像 + 16-dim joint state。

    Returns:
        obs: dict with keys for OpenPI server
        arm_q: (14,) current arm joint angles
    """
    images = {}
    arm_q = None

    # 1. ZMQ 获取相机图像
    if cam_config.get("head_camera", {}).get("enable_zmq", True):
        head_img = image_client.get_head_frame()
        if head_img is not None and hasattr(head_img, "bgr") and head_img.bgr is not None:
            w = cam_config["head_camera"]["image_shape"][1]
            # 裁剪双目左半部分作为 cam_left_high (对应 G1DJointInputs 的 base_0_rgb)
            rgb = cv2.cvtColor(head_img.bgr[:, : w // 2], cv2.COLOR_BGR2RGB)
            images["cam_left_high"] = rgb

    if cam_config.get("left_wrist_camera", {}).get("enable_zmq", True):
        left_wrist = image_client.get_left_wrist_frame()
        if left_wrist is not None and hasattr(left_wrist, "bgr") and left_wrist.bgr is not None:
            images["cam_left_wrist"] = cv2.cvtColor(left_wrist.bgr, cv2.COLOR_BGR2RGB)

    if cam_config.get("right_wrist_camera", {}).get("enable_zmq", True):
        right_wrist = image_client.get_right_wrist_frame()
        if right_wrist is not None and hasattr(right_wrist, "bgr") and right_wrist.bgr is not None:
            images["cam_right_wrist"] = cv2.cvtColor(right_wrist.bgr, cv2.COLOR_BGR2RGB)

    # 2. DDS 获取双臂关节角
    arm_q = arm_ctrl.get_current_dual_arm_q()  # (14,)

    # 3. 组装 16-dim state
    if arm_q is not None:
        arm_q = np.asarray(arm_q, dtype=np.float32).ravel()
        state = np.concatenate([
            arm_q[:7],                        # left_arm[7]
            arm_q[7:14],                      # right_arm[7]
            [left_grip_val.value],            # left_gripper
            [right_grip_val.value],           # right_gripper
        ]).astype(np.float32)
    else:
        state = None

    return images, state, arm_q


# ═══════════════════════════════════════════════════════════════════════════════
# 动作执行
# ═══════════════════════════════════════════════════════════════════════════════


def execute_action(
    abs_action_16d: np.ndarray,
    arm_ctrl,
    arm_ik,
    left_gripper_val,
    right_gripper_val,
):
    """执行 16-dim 绝对关节角动作。

    Args:
        abs_action_16d: (16,) absolute target joint positions
    """
    action = np.asarray(abs_action_16d, dtype=np.float64).ravel()

    # 拆分 16-dim → arm_q[14] + gripper[2]
    arm_q = np.concatenate([action[:7], action[7:14]])
    left_gripper = float(action[IDX_LEFT_GRIP])
    right_gripper = float(action[IDX_RIGHT_GRIP])

    tau = arm_ik.solve_tau(arm_q)
    arm_ctrl.ctrl_dual_arm(arm_q, tau)

    left_gripper_val.value = left_gripper
    right_gripper_val.value = right_gripper


# ═══════════════════════════════════════════════════════════════════════════════
# 图像压缩传输 (云端 wss 推理)
# ═══════════════════════════════════════════════════════════════════════════════

_IMAGE_DEFAULT_MAX_SIZE = 224


def _resize_with_pad_rgb(image: np.ndarray, height: int, width: int) -> np.ndarray:
    """Resize HWC uint8 RGB with letterbox padding (matches server resize_with_pad)."""
    image = np.asarray(image)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"Expected HWC RGB image, got shape {image.shape}")

    cur_height, cur_width = image.shape[:2]
    ratio = max(cur_width / width, cur_height / height)
    resized_height = int(cur_height / ratio)
    resized_width = int(cur_width / ratio)
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)

    pad_h0 = (height - resized_height) // 2
    pad_w0 = (width - resized_width) // 2
    pad_h1 = height - resized_height - pad_h0
    pad_w1 = width - resized_width - pad_w0
    return cv2.copyMakeBorder(
        resized, pad_h0, pad_h1, pad_w0, pad_w1, cv2.BORDER_CONSTANT, value=0
    )


def _encode_rgb_jpeg(image: np.ndarray, quality: int = 80) -> bytes:
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    ok, encoded = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return encoded.tobytes()


def prepare_images_for_transport(
    images: dict[str, np.ndarray],
    *,
    transport: str = "raw",
    jpeg_quality: int = 80,
    max_size: int = 0,
) -> dict[str, np.ndarray | bytes]:
    """Prepare camera images before sending to the policy server."""
    if transport == "raw":
        if max_size <= 0:
            return images
        return {
            key: _resize_with_pad_rgb(img, max_size, max_size)
            for key, img in images.items()
        }

    if transport != "jpeg":
        raise ValueError(f"Unsupported image transport: {transport}")

    target = max_size if max_size > 0 else _IMAGE_DEFAULT_MAX_SIZE
    prepared: dict[str, np.ndarray | bytes] = {}
    for key, img in images.items():
        resized = _resize_with_pad_rgb(img, target, target)
        prepared[key] = _encode_rgb_jpeg(resized, quality=jpeg_quality)
    return prepared


def estimate_payload_bytes(images: dict[str, np.ndarray | bytes]) -> int:
    total = 0
    for value in images.values():
        if isinstance(value, (bytes, bytearray, memoryview)):
            total += len(value)
        else:
            total += int(np.asarray(value).nbytes)
    return total


# ═══════════════════════════════════════════════════════════════════════════════
# 推理 Client (WebSocket)
# ═══════════════════════════════════════════════════════════════════════════════


def _server_uri(host: str, port: int) -> str:
    if host.startswith("ws"):
        return host
    return f"ws://{host}:{port}"


class OpenPIClient:
    """封装与 OpenPI WebSocket policy server 的通信 (使用官方 WebsocketClientPolicy)。"""

    def __init__(self, host: str = "localhost", port: int = 8000, infer_timeout: float = 600):
        from openpi_client import websocket_client_policy

        connect_kwargs = {
            "ping_interval": 30,
            "ping_timeout": infer_timeout,
            "open_timeout": 30,
        }
        if host.startswith("ws"):
            self._policy = websocket_client_policy.WebsocketClientPolicy(host=host, **connect_kwargs)
        else:
            self._policy = websocket_client_policy.WebsocketClientPolicy(
                host=host, port=port, **connect_kwargs
            )
        metadata = self._policy.get_server_metadata()
        logger.info(f"已连接 OpenPI Server, metadata: {metadata}")
        self._action_plan = collections.deque()

    def infer(self, obs: dict) -> dict:
        """发送观测，返回 action chunk 与 server timing。"""
        result = self._policy.infer(obs)
        return {
            "actions": np.asarray(result["actions"], dtype=np.float32),
            "policy_timing": result.get("policy_timing", {}),
            "server_timing": result.get("server_timing", {}),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Rerun 可视化 (LeRobot display_data 模式)
# ═══════════════════════════════════════════════════════════════════════════════


def is_headless() -> bool:
    """Detect if running without GUI (no pynput / no X display)."""
    try:
        import pynput  # noqa: F401
        return False
    except Exception:
        return True


def init_rerun(display_data: bool, viewer_ip: str | None, viewer_port: str | None) -> bool:
    """Initialize Rerun viewer. Returns True if logging is enabled."""
    if not display_data:
        return False

    if is_headless() and not viewer_ip:
        logger.warning(
            "Headless environment, skipping Rerun. "
            "Use --viewer_ip/--viewer_port for remote viewer."
        )
        return False

    import rerun as rr

    batch_size = os.getenv("RERUN_FLUSH_NUM_BYTES", "8000")
    os.environ["RERUN_FLUSH_NUM_BYTES"] = batch_size

    rr.init("g1d_openpi_control_loop")

    if viewer_ip:
        if not viewer_port:
            raise ValueError(
                "Viewer IP & Port are required for remote viewer. "
                "Set via --viewer_ip/--viewer_port or disable --display_data."
            )
        logger.info(f"Connecting Rerun viewer at {viewer_ip}:{viewer_port}")
        rr.connect_tcp(f"{viewer_ip}:{viewer_port}")
    else:
        memory_limit = os.getenv("LEROBOT_RERUN_MEMORY_LIMIT", "10%")
        rr.spawn(memory_limit=memory_limit)

    logger.info("Rerun visualization enabled")
    return True


def log_control_step(
    step_idx: int,
    images: dict,
    state_16d: np.ndarray,
    action: np.ndarray,
    infer_ms: float | None = None,
) -> None:
    """Log one control step to Rerun (LeRobot control loop + visualize_dataset style)."""
    import rerun as rr

    rr.set_time_sequence("step", step_idx)

    for key, img in images.items():
        rr.log(key, rr.Image(img), static=True)

    for dim_idx, val in enumerate(state_16d):
        rr.log(f"state/{dim_idx}", rr.Scalar(float(val)))

    for dim_idx, val in enumerate(action):
        rr.log(f"action/{dim_idx}", rr.Scalar(float(val)))

    if infer_ms is not None:
        rr.log("timing/infer_ms", rr.Scalar(infer_ms))


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="G1-D OpenPI inference client (Joint Space)")
    parser.add_argument("--server_host", type=str, default="localhost",
                        help="OpenPI WebSocket server host")
    parser.add_argument("--server_port", type=int, default=8000,
                        help="OpenPI WebSocket server port")
    parser.add_argument(
        "--infer_timeout",
        type=float,
        default=600,
        help="WebSocket ping/推理超时（秒，云端首次推理可能 >30s）",
    )
    parser.add_argument(
        "--image_transport",
        type=str,
        default="auto",
        choices=["auto", "raw", "jpeg"],
        help="图像传输格式：auto=远程 wss 用 jpeg，本地 raw",
    )
    parser.add_argument(
        "--jpeg_quality",
        type=int,
        default=80,
        help="JPEG 压缩质量 (1-100，仅 image_transport=jpeg 时生效)",
    )
    parser.add_argument(
        "--image_max_size",
        type=int,
        default=224,
        help="传输前缩放边长 (letterbox)；0 表示不缩放。jpeg 模式默认 224",
    )
    parser.add_argument("--image_host", type=str, default="192.168.123.164",
                        help="Jetson image server IP")
    parser.add_argument("--instruction", type=str, default="fold the towel",
                        help="Task instruction for the model")
    parser.add_argument("--frequency", type=float, default=30.0,
                        help="Control loop frequency (Hz)")
    parser.add_argument("--arm", type=str, default="G1_29",
                        choices=["G1_29", "G1_23"])
    parser.add_argument("--ee", type=str, default="dex1",
                        choices=["dex1", "dex3"])
    parser.add_argument("--dataset_path", type=str, default="",
                        help="LeRobot v2.1 数据集路径，用于获取第一帧作为初始位姿")
    parser.add_argument("--episode_index", type=int, default=0,
                        help="使用数据集中哪个 episode 的第一帧初始化")
    parser.add_argument(
        "--display_data",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Display cameras and joint data in Rerun viewer (LeRobot display_data)",
    )
    parser.add_argument(
        "--viewer_ip",
        type=str,
        default=None,
        help="Remote Rerun viewer IP (connect_tcp mode)",
    )
    parser.add_argument(
        "--viewer_port",
        type=str,
        default=None,
        help="Remote Rerun viewer port (connect_tcp mode)",
    )
    args = parser.parse_args()

    if args.image_transport == "auto":
        args.image_transport = "jpeg" if args.server_host.startswith("ws") else "raw"
    if args.image_transport == "jpeg" and args.image_max_size <= 0:
        args.image_max_size = 224

    # ── 初始化 OpenPI WebSocket Client ───────────────────────────
    server_uri = _server_uri(args.server_host, args.server_port)
    logger.info(f"连接 OpenPI Server: {server_uri}")
    pi_client = OpenPIClient(
        host=args.server_host,
        port=args.server_port,
        infer_timeout=args.infer_timeout,
    )

    # ── 初始化机器人接口 ──────────────────────────────────────────
    from multiprocessing import Array, Lock, Value
    from unitree_lerobot.eval_robot.image_server.image_client import ImageClient
    from unitree_lerobot.eval_robot.robot_control.robot_arm import G1_29_ArmController
    from unitree_lerobot.eval_robot.robot_control.robot_arm_ik import G1_29_ArmIK
    from unitree_lerobot.eval_robot.robot_control.robot_hand_unitree import Dex1_1_Gripper_Controller

    logger.info("初始化 ImageClient...")
    image_client = ImageClient(host=args.image_host, request_bgr=True)
    cam_config = image_client.get_cam_config()
    logger.info(f"相机配置: {list(cam_config.keys())}")

    logger.info("初始化 ArmController + ArmIK...")
    arm_ctrl = G1_29_ArmController(motion_mode=False, simulation_mode=False)
    arm_ik = G1_29_ArmIK()

    logger.info("初始化 Gripper (Dex1)...")
    left_gripper_val = Value("d", 0.0, lock=True)
    right_gripper_val = Value("d", 0.0, lock=True)
    data_lock = Lock()
    state_arr = Array("d", 2, lock=False)
    action_arr = Array("d", 2, lock=False)
    ee_ctrl = Dex1_1_Gripper_Controller(
        left_gripper_val,
        right_gripper_val,
        data_lock,
        state_arr,
        action_arr,
        simulation_mode=False,
    )

    # ── 加载数据集初始位姿 ──────────────────────────────────────────
    init_state_16d = None
    if args.dataset_path:
        init_state_16d = load_first_frame_joint(args.dataset_path, args.episode_index)

    # ── 获取当前机器人状态 ────────────────────────────────────────
    logger.info("获取当前机器人状态...")
    current_arm_q = arm_ctrl.get_current_dual_arm_q()
    if current_arm_q is not None:
        logger.info(f"当前关节角: {np.array2string(np.asarray(current_arm_q), precision=4)}")

    print("\n" + "=" * 60)
    print("  G1-D OpenPI 推理 Client — Joint Space")
    print("=" * 60)
    print(f"  Server        : {server_uri}")
    print(f"  Image Host    : {args.image_host}")
    print(f"  Instruction   : {args.instruction}")
    print(f"  Frequency     : {args.frequency} Hz")
    print(f"  Display Data  : {args.display_data}")
    if args.viewer_ip:
        print(f"  Rerun Viewer  : {args.viewer_ip}:{args.viewer_port}")
    if init_state_16d is not None:
        print(f"  Init from     : {args.dataset_path} (episode {args.episode_index})")
    else:
        print(f"  Init from     : 当前位姿 (未指定 --dataset_path)")
    print(
        f"  Image Transport: {args.image_transport}"
        + (f" (quality={args.jpeg_quality}, max={args.image_max_size})" if args.image_transport == "jpeg" else "")
    )
    print("=" * 60)
    print("\n  操作说明:")
    print("    1. 按 's' + Enter: 初始化机器人到数据集第一帧位姿，然后开始推理")
    print("    2. Ctrl+C 停止推理")
    print()

    user_input = input("输入 's' 开始: ").strip().lower()
    if user_input != "s":
        logger.info("用户取消，退出。")
        image_client.close()
        return

    # ── 初始化机器人到数据集第一帧位姿 ────────────────────────────
    if init_state_16d is not None:
        initialize_robot(
            init_state_16d, arm_ctrl, arm_ik, left_gripper_val, right_gripper_val
        )
    else:
        logger.info("未指定数据集，跳过归位，使用当前位姿开始推理。")

    # ── 相机预热 ──────────────────────────────────────────────────
    logger.info("预热相机...")
    for _ in range(30):
        images, _, _ = get_observation(
            image_client, cam_config, arm_ctrl, left_gripper_val, right_gripper_val
        )
        if "cam_left_high" in images:
            break
        time.sleep(0.03)
    logger.info(f"相机就绪，可用视角: {list(images.keys())}")

    rerun_enabled = init_rerun(args.display_data, args.viewer_ip, args.viewer_port)

    # ── 推理主循环 ────────────────────────────────────────────────
    logger.info(f"开始推理循环 @ {args.frequency} Hz")
    action_plan = collections.deque()
    step_idx = 0
    pending_infer_ms: float | None = None

    try:
        while True:
            loop_start = time.perf_counter()

            # 1. 获取观测
            images, state_16d, current_arm_q = get_observation(
                image_client, cam_config, arm_ctrl,
                left_gripper_val, right_gripper_val,
            )

            if state_16d is None or current_arm_q is None:
                logger.warning("无法获取关节角，跳过本帧")
                time.sleep(1.0 / args.frequency)
                continue

            # 2. 若 action_plan 为空，请求新的 action chunk
            if not action_plan:
                if "cam_left_high" not in images:
                    logger.warning("主相机图像缺失，等待...")
                    time.sleep(1.0 / args.frequency)
                    continue

                # 构造 OpenPI 观测 (G1DJointInputs 期望的嵌套 dict 格式)
                # 推理时不经过 RepackTransform，直接发送 state/images/prompt
                # 不传 actions：模型推理不依赖输入 actions，且可避免 DeltaActions 触发
                obs = {
                    "state": state_16d.astype(np.float32),
                    "images": {},
                    "prompt": args.instruction,
                }
                # cam_left_high → 模型主视图 base_0_rgb
                if "cam_left_high" in images:
                    obs["images"]["cam_left_high"] = images["cam_left_high"]
                if "cam_left_wrist" in images:
                    obs["images"]["cam_left_wrist"] = images["cam_left_wrist"]
                if "cam_right_wrist" in images:
                    obs["images"]["cam_right_wrist"] = images["cam_right_wrist"]

                obs["images"] = prepare_images_for_transport(
                    obs["images"],
                    transport=args.image_transport,
                    jpeg_quality=args.jpeg_quality,
                    max_size=args.image_max_size,
                )
                payload_bytes = estimate_payload_bytes(obs["images"])

                try:
                    t0 = time.perf_counter()
                    infer_result = pi_client.infer(obs)
                    t1 = time.perf_counter()
                    pending_infer_ms = (t1 - t0) * 1000
                    actions = infer_result["actions"]
                    policy_ms = infer_result.get("policy_timing", {}).get("infer_ms")
                    for i in range(len(actions)):
                        action_plan.append(actions[i])
                    timing_detail = (
                        f", policy={policy_ms:.0f}ms" if isinstance(policy_ms, (int, float)) else ""
                    )
                    logger.info(
                        f"[step {step_idx}] 获取 {len(actions)} 帧动作 "
                        f"(client={pending_infer_ms:.0f}ms{timing_detail}, "
                        f"payload={payload_bytes / 1024:.0f}KB)"
                    )
                except Exception as e:
                    logger.error(f"推理请求失败: {e}")
                    time.sleep(0.5)
                    continue

            # 3. 取一帧绝对关节角 (Server 已完成 Unnormalize → AbsoluteActions)
            action = action_plan.popleft()

            # 4. 执行动作
            execute_action(action, arm_ctrl, arm_ik,
                           left_gripper_val, right_gripper_val)

            if rerun_enabled:
                log_control_step(
                    step_idx,
                    images,
                    state_16d,
                    action,
                    infer_ms=pending_infer_ms,
                )
                pending_infer_ms = None

            step_idx += 1

            # 5. 频率控制
            elapsed = time.perf_counter() - loop_start
            sleep_time = max(0, (1.0 / args.frequency) - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("用户中断，停止推理。")
    finally:
        image_client.close()
        logger.info("资源已释放，退出。")


if __name__ == "__main__":
    main()

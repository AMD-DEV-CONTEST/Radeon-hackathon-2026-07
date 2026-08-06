"""LeKiwi runtime — official LeRobot host/client architecture.

LeKiwi is a mobile manipulator with one Feetech STS3215 serial bus:

* arm motors: IDs 1-6
* omni-base motors: IDs 7-9

The normal wireless setup runs ``lekiwi_host`` on the robot's Raspberry Pi
and uses LeRobot's ZMQ client from this Local Agent (commands on 5555,
observations/cameras on 5556). A wired build can still be launched by the
LeKiwi API, but this runtime intentionally does not fake a Damiao/CAN driver.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from .._protocol import CameraSource, RuntimeInfo

logger = logging.getLogger(__name__)

LEKIWI_STATE_NAMES = [
    "arm_shoulder_pan.pos",
    "arm_shoulder_lift.pos",
    "arm_elbow_flex.pos",
    "arm_wrist_flex.pos",
    "arm_wrist_roll.pos",
    "arm_gripper.pos",
    "x.vel",
    "y.vel",
    "theta.vel",
]

LEKIWI_MOTOR_IDS: Dict[str, int] = {
    "arm_shoulder_pan": 1,
    "arm_shoulder_lift": 2,
    "arm_elbow_flex": 3,
    "arm_wrist_flex": 4,
    "arm_wrist_roll": 5,
    "arm_gripper": 6,
    "base_left_wheel": 7,
    "base_back_wheel": 8,
    "base_right_wheel": 9,
}

DEFAULT_REMOTE_IP = os.environ.get("LEKIWI_REMOTE_IP", "192.168.1.50")
DEFAULT_CMD_PORT = int(os.environ.get("LEKIWI_CMD_PORT", "5555"))
DEFAULT_OBSERVATION_PORT = int(os.environ.get("LEKIWI_OBSERVATION_PORT", "5556"))

LEKIWI_INFO = RuntimeInfo(
    runtime_id="lekiwi",
    robot_type="lekiwi_client",
    display_name="LeKiwi (Kiwi omni base + SO-101 arm)",
    joint_count=len(LEKIWI_STATE_NAMES),
    joint_names=LEKIWI_STATE_NAMES,
    urdf_url="/api/urdf/lekiwi/lekiwi.urdf?v=official-cad-1",
    supports_telemetry=False,
    camera_sources=[
        CameraSource(
            camera_id="front",
            display_name="Workspace camera",
            device_type="ip",
            default_device=f"tcp://{DEFAULT_REMOTE_IP}:{DEFAULT_OBSERVATION_PORT}",
        ),
        CameraSource(
            camera_id="wrist",
            display_name="Wrist camera",
            device_type="ip",
            default_device=f"tcp://{DEFAULT_REMOTE_IP}:{DEFAULT_OBSERVATION_PORT}",
        ),
    ],
)


def _make_client(remote_ip: str, cmd_port: int, observation_port: int) -> Any:
    """Create the official LeRobot ZMQ client lazily.

    Importing here keeps the catalog usable on machines that have not yet
    installed the LeKiwi optional dependencies.
    """
    try:
        from lerobot.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig
    except ImportError as exc:  # pragma: no cover - depends on optional hardware env
        raise RuntimeError(
            "LeRobot LeKiwi client is unavailable. Install a current "
            "`lerobot[feetech]` build with LeKiwi support."
        ) from exc

    config = LeKiwiClientConfig(
        remote_ip=remote_ip,
        port_zmq_cmd=cmd_port,
        port_zmq_observations=observation_port,
        id="botversex-lekiwi",
    )
    return LeKiwiClient(config)


class LeKiwiReader:
    """Read arm pose, body velocity and camera observations from LeKiwi Host."""

    def __init__(
        self,
        remote_ip: str = DEFAULT_REMOTE_IP,
        cmd_port: int = DEFAULT_CMD_PORT,
        observation_port: int = DEFAULT_OBSERVATION_PORT,
        device_id: Optional[str] = None,
        **_: Any,
    ) -> None:
        self.remote_ip = remote_ip
        self.cmd_port = cmd_port
        self.observation_port = observation_port
        self.device_id = device_id
        self.is_connected = False
        self._client: Any = None
        self._last_observation: Dict[str, Any] = {}

    def connect(self) -> bool:
        try:
            self._client = _make_client(
                self.remote_ip, self.cmd_port, self.observation_port
            )
            self._client.connect()
            self.is_connected = bool(self._client.is_connected)
        except Exception as exc:
            logger.info("LeKiwi Host connection failed: %s", exc)
            self._client = None
            self.is_connected = False
        return self.is_connected

    def _read(self) -> Dict[str, Any]:
        if not self.is_connected or self._client is None:
            return {}
        try:
            observation = self._client.get_observation()
            if observation:
                self._last_observation = dict(observation)
        except Exception as exc:
            logger.debug("LeKiwi observation read failed: %s", exc)
        return self._last_observation

    def read_positions(self) -> Optional[List[float]]:
        observation = self._read()
        if not observation:
            return None
        values: List[float] = []
        for name in LEKIWI_STATE_NAMES:
            raw = observation.get(name, 0.0)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = 0.0
            # Official LeKiwi defaults to degrees for arm positions. Runtime
            # readers expose radians consistently to the generic 3D state view.
            if name.endswith(".pos") and name != "arm_gripper.pos":
                value = math.radians(value)
            values.append(value)
        return values

    def read_telemetry(self) -> Dict[str, Optional[List[Optional[float]]]]:
        # The official host/client protocol currently exposes state + images,
        # not motor temperature/current telemetry.
        return {}

    def read_state_snapshot(self) -> dict:
        positions = self.read_positions()
        return {
            "type": "robot_state",
            "robot_id": self.device_id or "lekiwi-001",
            "runtime_id": "lekiwi",
            "timestamp": time.time(),
            "connected": self.is_connected,
            "transport": {
                "kind": "lekiwi_zmq",
                "remote_ip": self.remote_ip,
                "command_port": self.cmd_port,
                "observation_port": self.observation_port,
            },
            "joints": dict(zip(LEKIWI_STATE_NAMES, positions)) if positions else {},
            "stream_interval_s": 0.1,
        }

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                logger.debug("LeKiwi client disconnect failed", exc_info=True)
        self._client = None
        self.is_connected = False


class LeKiwiWriter:
    """Send official LeKiwi action dictionaries over the ZMQ client."""

    def __init__(
        self,
        remote_ip: str = DEFAULT_REMOTE_IP,
        cmd_port: int = DEFAULT_CMD_PORT,
        observation_port: int = DEFAULT_OBSERVATION_PORT,
        device_id: Optional[str] = None,
        **_: Any,
    ) -> None:
        self.remote_ip = remote_ip
        self.cmd_port = cmd_port
        self.observation_port = observation_port
        self.device_id = device_id
        self.is_connected = False
        self.torque_enabled = False
        self._client: Any = None

    def connect(self) -> bool:
        try:
            self._client = _make_client(
                self.remote_ip, self.cmd_port, self.observation_port
            )
            self._client.connect()
            self.is_connected = bool(self._client.is_connected)
            self.torque_enabled = self.is_connected
        except Exception as exc:
            logger.info("LeKiwi writer connection failed: %s", exc)
            self._client = None
            self.is_connected = False
            self.torque_enabled = False
        return self.is_connected

    def preflight(self) -> Tuple[bool, str]:
        try:
            import zmq  # noqa: F401
            from lerobot.robots.lekiwi import LeKiwiClient  # noqa: F401
        except ImportError:
            return False, "缺少 LeRobot LeKiwi/ZMQ 依赖，请安装 lerobot[feetech] 与 pyzmq"
        if not self.remote_ip:
            return False, "请先填写 LeKiwi（树莓派/Orin）的局域网 IP"
        return True, f"准备连接 LeKiwi Host {self.remote_ip}:{self.cmd_port}"

    def enable_torque(self) -> bool:
        # Torque ownership lives on LeKiwi Host. Connecting the official client
        # is the enable gate; no unsupported remote register write is invented.
        self.torque_enabled = self.is_connected
        return self.torque_enabled

    def disable_torque(self) -> None:
        # First stop the mobile base, then disconnect. The host watchdog also
        # stops motion after 500 ms without commands.
        if self._client is not None and self.is_connected:
            try:
                self._client.send_action({"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0})
            except Exception:
                logger.debug("LeKiwi zero-velocity command failed", exc_info=True)
        self.disconnect()

    def write_positions(self, joints_rad: Dict[str, float]) -> int:
        if not self.torque_enabled or self._client is None:
            return 0
        action: Dict[str, float] = {}
        for name, value in joints_rad.items():
            if name not in LEKIWI_STATE_NAMES:
                continue
            value = float(value)
            if name.endswith(".pos") and name != "arm_gripper.pos":
                value = math.degrees(value)
            action[name] = value
        if not action:
            return 0
        try:
            self._client.send_action(action)
            return len(action)
        except Exception as exc:
            logger.warning("LeKiwi action send failed: %s", exc)
            return 0

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                logger.debug("LeKiwi client disconnect failed", exc_info=True)
        self._client = None
        self.is_connected = False
        self.torque_enabled = False


class LeKiwiRuntime:
    info = LEKIWI_INFO

    @staticmethod
    def create_reader(**kwargs: Any) -> LeKiwiReader:
        return LeKiwiReader(**kwargs)

    @staticmethod
    def create_writer(**kwargs: Any) -> LeKiwiWriter:
        return LeKiwiWriter(**kwargs)

    @staticmethod
    def joint_names() -> List[str]:
        return list(LEKIWI_STATE_NAMES)

    @staticmethod
    def motor_ids() -> Dict[str, int]:
        return dict(LEKIWI_MOTOR_IDS)


from .._protocol import register_runtime as _register

_register("lekiwi", LeKiwiRuntime)

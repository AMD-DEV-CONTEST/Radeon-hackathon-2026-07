"""SO-101 Runtime — first (and default) BotverseX runtime.

Thin adapter wrapping `sender.reader.LeaderArmReader` and
`sender.writer.FollowerArmWriter` behind the `RuntimeReader` /
`RuntimeWriter` protocols.

The reader/writer underneath use **lerobot-standard calibration**
loaded from ~/.cache/huggingface/lerobot/calibration/... — so this
adapter just plumbs through `device_id` without knowing about the
old custom JSON format.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .._protocol import CameraSource, RuntimeInfo
from sender.reader import LeaderArmReader
from sender.writer import FollowerArmWriter, MockArmWriter


SO101_JOINT_NAMES = ["1", "2", "3", "4", "5", "6"]

SO101_INFO = RuntimeInfo(
    runtime_id="so101",
    robot_type="so101",
    display_name="SO-101 (Feetech STS3215 × 6)",
    joint_count=6,
    joint_names=SO101_JOINT_NAMES,
    urdf_url="/api/urdf/so101.urdf",
    supports_telemetry=True,
    camera_sources=[
        CameraSource(
            camera_id="cam_main",
            display_name="Workspace Camera",
            device_type="usb",
            default_device="0",
            width=640,
            height=480,
            fps=30,
        ),
    ],
)


class SO101Reader:
    """RuntimeReader adapter for the Feetech leader arm."""

    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        device_id: Optional[str] = None,
        read_telemetry: bool = True,
    ) -> None:
        self._inner = LeaderArmReader(
            port=port, device_id=device_id, read_telemetry=read_telemetry,
        )

    @property
    def is_connected(self) -> bool:
        return self._inner.is_connected

    def connect(self) -> bool:
        return self._inner.connect()

    def read_positions(self) -> Optional[Dict[str, float]]:
        """Returns a dict mapping motor name → normalized position, or None."""
        frame = self._inner.read()
        return frame.positions_normalized or None

    def read_telemetry(self) -> Dict[str, Dict[str, Optional[float]]]:
        frame = self._inner.read()
        return {
            "temperatures_c": frame.temperatures_c,
            "currents_a": frame.currents_a,
            "voltages_v": frame.voltages_v,
        }

    def disconnect(self) -> None:
        self._inner.disconnect()


class SO101Writer:
    """RuntimeWriter adapter for the Feetech follower arm."""

    def __init__(
        self,
        port: str,
        device_id: Optional[str] = None,
        warmup_seconds: float = 0.4,
    ) -> None:
        self._inner = FollowerArmWriter(
            port=port,
            device_id=device_id,
            warmup_seconds=warmup_seconds,
        )

    @property
    def is_connected(self) -> bool:
        return self._inner.is_connected

    @property
    def torque_enabled(self) -> bool:
        return self._inner.torque_enabled

    def connect(self) -> bool:
        return self._inner.connect()

    def preflight(self) -> Tuple[bool, str]:
        return self._inner.preflight()

    def enable_torque(self) -> bool:
        return self._inner.enable_torque()

    def disable_torque(self) -> None:
        self._inner.disable_torque()

    def write_positions(self, normalized: Dict[str, float]) -> int:
        return self._inner.write_positions(normalized)

    def disconnect(self) -> None:
        self._inner.disconnect()


class SO101MockWriter:
    """RuntimeWriter mock for dry-run / smoke tests."""

    def __init__(self, name: str = "so101_mock") -> None:
        self._inner = MockArmWriter(name=name)

    @property
    def is_connected(self) -> bool:
        return self._inner.is_connected

    @property
    def torque_enabled(self) -> bool:
        return self._inner.torque_enabled

    def connect(self) -> bool:
        return self._inner.connect()

    def preflight(self) -> Tuple[bool, str]:
        return self._inner.preflight()

    def enable_torque(self) -> bool:
        return self._inner.enable_torque()

    def disable_torque(self) -> None:
        self._inner.disable_torque()

    def write_positions(self, normalized: Dict[str, float]) -> int:
        return self._inner.write_positions(normalized)

    def disconnect(self) -> None:
        self._inner.disconnect()


class SO101Runtime:
    """Convenience factory grouping reader + writer + info for SO-101."""

    info = SO101_INFO

    @staticmethod
    def create_reader(port: str = "/dev/ttyACM0", **kwargs) -> SO101Reader:
        return SO101Reader(port=port, **kwargs)

    @staticmethod
    def create_writer(port: str = "/dev/ttyACM1", **kwargs) -> SO101Writer:
        return SO101Writer(port=port, **kwargs)

    @staticmethod
    def create_mock_writer(**kwargs) -> SO101MockWriter:
        return SO101MockWriter(**kwargs)


from .._protocol import register_runtime as _register
_register("so101", SO101Runtime)

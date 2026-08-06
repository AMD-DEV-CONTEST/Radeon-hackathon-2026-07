"""B601-RS Runtime — thin adapter; teleop/record via official LeRobot CLI."""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from .._protocol import CameraSource, RuntimeInfo, register_runtime

B601_JOINT_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_yaw",
    "wrist_roll",
    "gripper",
]

B601_RS_INFO = RuntimeInfo(
    runtime_id="b601_rs",
    robot_type="b601_rs",
    display_name="reBot B601-RS (RobStride × 7 + Star Arm 102 主臂)",
    joint_count=7,
    joint_names=B601_JOINT_NAMES,
    urdf_url="/api/urdf/b601_rs/b601_rs.urdf",
    supports_telemetry=True,
    camera_sources=[
        CameraSource(
            camera_id="front",
            display_name="Front Camera",
            device_type="usb",
            default_device="0",
            width=640,
            height=480,
            fps=30,
        ),
        CameraSource(
            camera_id="side",
            display_name="Side Camera",
            device_type="usb",
            default_device="2",
            width=640,
            height=480,
            fps=30,
        ),
    ],
)


class B601StateReader:
    """Minimal state reader for robots.py generic GET/WS endpoints."""

    def read_state_snapshot(self) -> dict:
        from api.b601 import get_b601_runtime_state

        return asyncio.run(get_b601_runtime_state())


class B601RSRuntime:
    """Factory grouping metadata for B601-RS. Control via /api/b601/* CLI wrappers."""

    info = B601_RS_INFO

    @staticmethod
    def create_reader() -> B601StateReader:
        return B601StateReader()

    @staticmethod
    def create_writer():
        raise NotImplementedError("B601 write path uses LeRobot CLI via /api/b601/*")

    @staticmethod
    def default_leader_port() -> str:
        import os
        from pathlib import Path

        for candidate in (
            "/dev/leader_stararm102",
            os.environ.get("BOTVERSEX_B601_LEADER", ""),
            "/dev/ttyUSB0",
        ):
            if candidate and Path(candidate).exists():
                return candidate
        return "/dev/leader_stararm102"

    @staticmethod
    def default_can() -> str:
        import os

        return os.environ.get("BOTVERSEX_B601_CAN", "can0")

    @staticmethod
    def joint_names() -> List[str]:
        return list(B601_JOINT_NAMES)


register_runtime("b601_rs", B601RSRuntime)

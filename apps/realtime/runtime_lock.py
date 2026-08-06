"""B601 runtime / CAN mutex — teleop, record, kinematics, gravity comp, ROS2 are exclusive."""
from __future__ import annotations

import asyncio
from enum import Enum
from typing import Optional


class RuntimeMode(str, Enum):
    IDLE = "idle"
    TELEOP = "teleop"
    RECORD = "record"
    CALIBRATE = "calibrate"
    INFERENCE = "inference"
    KINEMATICS = "kinematics"
    GRAVITY_COMP = "gravity_comp"
    ROS2 = "ros2"


_MODE_LABELS: dict[RuntimeMode, str] = {
    RuntimeMode.IDLE: "空闲",
    RuntimeMode.TELEOP: "遥操",
    RuntimeMode.RECORD: "录制",
    RuntimeMode.CALIBRATE: "标定",
    RuntimeMode.INFERENCE: "策略推理",
    RuntimeMode.KINEMATICS: "运动学控制",
    RuntimeMode.GRAVITY_COMP: "重力补偿",
    RuntimeMode.ROS2: "ROS2",
}


class RuntimeLockBusy(Exception):
    def __init__(self, holder: RuntimeMode, detail: str) -> None:
        self.holder = holder
        self.detail = detail
        super().__init__(detail)


class RuntimeLock:
    def __init__(self) -> None:
        self._async_lock = asyncio.Lock()
        self._mode: RuntimeMode = RuntimeMode.IDLE
        self._owner: str = ""

    @property
    def mode(self) -> RuntimeMode:
        return self._mode

    @property
    def owner(self) -> str:
        return self._owner

    def status_dict(self) -> dict[str, str]:
        return {
            "runtime_mode": self._mode.value,
            "runtime_owner": self._owner,
        }

    def is_busy(self) -> bool:
        return self._mode != RuntimeMode.IDLE

    def conflict_message(self, requested: RuntimeMode) -> str:
        label = _MODE_LABELS.get(self._mode, self._mode.value)
        req = _MODE_LABELS.get(requested, requested.value)
        return f"当前处于「{label}」模式，无法启动「{req}」。请先停止当前任务。"

    async def acquire(self, mode: RuntimeMode, owner: str = "") -> None:
        async with self._async_lock:
            if self._mode != RuntimeMode.IDLE and self._mode != mode:
                raise RuntimeLockBusy(self._mode, self.conflict_message(mode))
            self._mode = mode
            self._owner = owner or mode.value

    async def release(self, mode: Optional[RuntimeMode] = None) -> None:
        async with self._async_lock:
            if mode is not None and self._mode != mode:
                return
            self._mode = RuntimeMode.IDLE
            self._owner = ""

    async def force_release(self) -> None:
        async with self._async_lock:
            self._mode = RuntimeMode.IDLE
            self._owner = ""


b601_runtime_lock = RuntimeLock()

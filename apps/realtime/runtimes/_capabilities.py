"""Robot capability protocol — shared vocabulary for manifest + UI filtering."""
from __future__ import annotations

from enum import Enum


class RobotCapability(str, Enum):
    TELEOP = "teleop"
    RECORD = "record"
    CALIBRATE = "calibrate"
    INFERENCE = "inference"
    JOINTS_LIVE = "joints_live"
    CAMERA = "camera"
    SOUND = "sound"
    CONVERSATION = "conv"
    BIMANUAL = "bimanual"
    KINEMATICS = "kinematics"
    GRAVITY_COMP = "gravity_comp"
    ROS2 = "ros2"


SO101_CAPS = {
    RobotCapability.TELEOP,
    RobotCapability.RECORD,
    RobotCapability.CALIBRATE,
    RobotCapability.INFERENCE,
    RobotCapability.JOINTS_LIVE,
    RobotCapability.CAMERA,
}

REACHY_CAPS = {
    RobotCapability.RECORD,
    RobotCapability.SOUND,
    RobotCapability.CONVERSATION,
    RobotCapability.CAMERA,
    RobotCapability.JOINTS_LIVE,
}

B601_CAPS = {
    RobotCapability.TELEOP,
    RobotCapability.RECORD,
    RobotCapability.CALIBRATE,
    RobotCapability.INFERENCE,
    RobotCapability.JOINTS_LIVE,
    RobotCapability.CAMERA,
    RobotCapability.KINEMATICS,
    RobotCapability.GRAVITY_COMP,
    RobotCapability.ROS2,
}

# T2-3: RUNTIME_CAPABILITIES dict 和 capability_tags() 函数已删除 — 从未被任何代码 import，
# 前端直接读 manifest 里的 capability_tags 数组。capability 常量集合（SO101_CAPS 等）保留，
# 供 T2-2 通用工作台面板注册表未来使用。

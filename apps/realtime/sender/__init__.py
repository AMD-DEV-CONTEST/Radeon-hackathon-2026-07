"""apps.realtime.sender — leader/follower Feetech sender, lerobot-calibrated.

Modules:
  lerobot_calibration   loads lerobot-standard calibration JSON into
                        MotorCalibration dicts, builds Motor entries with
                        the correct MotorNormMode per motor.
  joint_angles          normalized ↔ radian conversion using URDF limits
                        as the shared leader/follower contract.
  reader                FeetechMotorsBus wrapper for the leader arm;
                        returns normalized positions + telemetry.
  writer                FeetechMotorsBus wrapper for the follower arm;
                        takes normalized goals, handles torque gating,
                        preflight, warmup ramp.
  sender                async WS loop pushing leader frames to /ws/teleop.
  follower              async WS loop consuming /ws/ui and driving the
                        follower writer.

CLI:
  python -m sender --mode leader   --com_port /dev/ttyACM1 --device-id ethan_leader
  python -m sender --mode follower --com_port /dev/ttyACM0 --device-id ethan_follower
"""

from .lerobot_calibration import (
    SO101_MOTOR_NAMES,
    SO101_MOTOR_IDS,
    build_motors_dict,
    calibration_path,
    list_available,
    load_motor_calibration,
    resolve_and_load,
    resolve_device_id,
)
from .joint_angles import (
    JOINT_LIMITS_RAD,
    MOTOR_ID_TO_NAME,
    MOTOR_NAME_TO_ID,
    normalized_to_rad,
    rad_to_normalized,
)
from .reader import LeaderArmReader, TelemetryFrame
from .sender import BotclawSender
from .writer import BaseArmWriter, FollowerArmWriter, MockArmWriter

__all__ = [
    "SO101_MOTOR_NAMES",
    "SO101_MOTOR_IDS",
    "build_motors_dict",
    "calibration_path",
    "list_available",
    "load_motor_calibration",
    "resolve_and_load",
    "resolve_device_id",
    "JOINT_LIMITS_RAD",
    "MOTOR_ID_TO_NAME",
    "MOTOR_NAME_TO_ID",
    "normalized_to_rad",
    "rad_to_normalized",
    "LeaderArmReader",
    "TelemetryFrame",
    "BotclawSender",
    "BaseArmWriter",
    "FollowerArmWriter",
    "MockArmWriter",
]

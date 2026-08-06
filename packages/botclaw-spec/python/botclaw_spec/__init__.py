"""
BotClaw contract spec — Python (Pydantic v2) models (v0.1).

Kept in lock-step with:
  - schemas/*.schema.json (authoritative JSON Schema)
  - ts/index.ts (TypeScript types)

Change propagation: schema first -> Python here -> TypeScript last.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


BOTCLAW_SPEC_VERSION: str = "0.4.0"

JointName = Literal["1", "2", "3", "4", "5", "6"]
JOINT_NAMES: tuple[JointName, ...] = ("1", "2", "3", "4", "5", "6")


class _StrictModel(BaseModel):
    """Base with JSON Schema-aligned defaults."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------- JointUpdate ----------


class JointUpdateMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    fps: Optional[float] = Field(default=None, ge=0)
    source: Optional[str] = None


class JointMap(BaseModel):
    """Joint angles keyed by 1..6 (so101 ordering)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    j1: float = Field(alias="1")
    j2: float = Field(alias="2")
    j3: float = Field(alias="3")
    j4: float = Field(alias="4")
    j5: float = Field(alias="5")
    j6: float = Field(alias="6")

    def to_dict(self) -> dict[str, float]:
        return {
            "1": self.j1,
            "2": self.j2,
            "3": self.j3,
            "4": self.j4,
            "5": self.j5,
            "6": self.j6,
        }


class JointUpdate(BaseModel):
    """v0.4 起放开 extra=ignore, 方便 sender 在同一帧捎带硬件遥测 (temp/current/voltage).

    RobotState WS 会收集这些透传字段, 但 joint_update 广播本身只保留 joints/servo_values.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    type: Literal["joint_update"] = "joint_update"
    robot_id: str = Field(min_length=1)
    timestamp: float
    joints: JointMap
    servo_values: Optional[dict[str, int]] = None
    meta: Optional[JointUpdateMeta] = None
    # v0.4: optional telemetry - sender 能拿到啥就传啥
    temperatures_c: Optional[dict[str, float]] = None
    currents_a: Optional[dict[str, float]] = None
    voltages_v: Optional[dict[str, float]] = None


# ---------- RobotState ----------


class JointLimit(_StrictModel):
    lo: float
    hi: float


class RobotSafety(_StrictModel):
    """M4.3 RobotState 扩展: 安全闸和硬件保护状态."""

    model_config = ConfigDict(extra="allow")

    estop: bool = False
    clamped: Optional[list[str]] = None
    max_delta_rad: Optional[float] = None


class RobotState(_StrictModel):
    """M4.3: 机械臂运行态的定时快照, 非事件驱动.

    joints/servo_values 是"上一帧观测", 其他字段描述设备/连接/安全态.
    所有硬件字段 (temperatures/currents/voltages) 均为 optional, 上游可只填自己拿得到的项.
    """

    # v0.4 新增: 让后续可平滑加字段而不破坏旧客户端
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: Literal["robot_state"] = "robot_state"
    robot_id: str = Field(min_length=1)
    timestamp: float
    joints: Optional[dict[str, Optional[float]]] = None
    servo_values: Optional[dict[str, Optional[int]]] = None

    # 连接 / 录制
    teleop_connected: bool
    ui_clients: int = Field(ge=0)
    is_recording: bool
    buffer_size: Optional[int] = Field(default=None, ge=0)

    # v0.4 新增 - 硬件遥测 (可缺省)
    temperatures_c: Optional[dict[str, Optional[float]]] = None
    currents_a: Optional[dict[str, Optional[float]]] = None
    voltages_v: Optional[dict[str, Optional[float]]] = None

    # v0.4 新增 - 硬件/软件限位 + 安全
    limits_rad: Optional[dict[str, JointLimit]] = None
    safety: Optional[RobotSafety] = None

    # v0.4 新增 - 实际观测帧率
    fps_observed: Optional[float] = Field(default=None, ge=0)


# ---------- DeviceCapabilities ----------


RobotModel = Literal["so101", "so100", "reachy_mini", "reachy_mini_lite", "openclaw", "generic"]
ControlMode = Literal["leader_follower", "keyboard", "vr", "replay", "telemetry", "inference"]


class CameraSource(_StrictModel):
    """Runtime camera descriptor aligned with apps/realtime/runtimes/_protocol.py."""

    camera_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    device_type: Literal["usb", "realsense", "ip"] = "usb"
    default_device: Optional[str] = None
    width: int = Field(default=640, ge=1)
    height: int = Field(default=480, ge=1)
    fps: int = Field(default=30, ge=1)


class DeviceCapabilities(_StrictModel):
    robot_id: str = Field(min_length=1)
    robot_model: RobotModel
    display_name: Optional[str] = None
    joint_count: int = Field(ge=1)
    joint_names: list[str] = Field(min_length=1)
    control_modes: list[ControlMode] = Field(min_length=1)
    max_fps: float = Field(ge=1)
    urdf_url: Optional[str] = None
    has_gripper: Optional[bool] = None
    supports_telemetry: bool = False
    camera_sources: list[CameraSource] = Field(default_factory=list)


# ---------- Skill ----------


ParamType = Literal["string", "number", "bool", "enum"]
TrainBackend = Literal["local", "qualia", "none"]
CompatibilityLevel = Literal["A+", "A", "B", "C", "D"]


class SkillParamSchema(_StrictModel):
    """UI/API validation schema for a single skill parameter."""

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    type: ParamType
    default: Optional[Any] = None
    min: Optional[float] = None
    max: Optional[float] = None
    options: Optional[list[str | int | float | bool]] = None
    required: bool = False


class SkillCompatibility(_StrictModel):
    """Optional engineering-grade compatibility metadata for v0.9."""

    level: Optional[CompatibilityLevel] = None
    verified_runtimes: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class Skill(_StrictModel):
    """BotClaw v0.9 skill registry entry.

    This intentionally matches apps/api/app/data/skills_seed.json so the file
    registry can be validated as the first real BotClaw protocol consumer.
    """

    skill_id: str = Field(min_length=1)
    verb: str = Field(min_length=1)
    robot_type: str = Field(min_length=1)
    compatible_types: list[str] = Field(default_factory=list)
    params_schema: list[SkillParamSchema] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    joint_count: Optional[int] = Field(default=None, ge=1)
    train_backend: TrainBackend = "local"
    hf_model_id: Optional[str] = None
    hf_dataset_id: Optional[str] = None
    min_episodes: int = Field(default=20, ge=1)
    episode_duration_s: float = Field(default=30, ge=1)
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    author: Optional[str] = None
    version: str = "0.1.0"
    created_at: Optional[datetime] = None
    compatibility: Optional[SkillCompatibility] = None


# ---------- DatasetEpisode ----------


class DatasetEpisodeArtifacts(_StrictModel):
    # `json` is a BaseModel method; expose via alias to keep JSON key stable.
    json_path: Optional[str] = Field(default=None, alias="json")
    parquet: Optional[str] = None
    video: Optional[str] = None


class JointStats(_StrictModel):
    min: float
    max: float
    mean: float
    std: float
    range: float
    jitter: float


class DatasetStats(_StrictModel):
    """非严格: 扫描端可能追加字段, 解析端保持向前兼容."""
    model_config = {"extra": "allow"}

    frame_count: Optional[int] = None
    duration_s: Optional[float] = None
    fps_nominal: Optional[float] = None
    fps_observed_mean: Optional[float] = None
    fps_observed_std: Optional[float] = None
    joints: Optional[dict[str, JointStats]] = None


class DatasetEpisode(_StrictModel):
    spec_version: Optional[str] = None
    id: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    recorded_at: datetime
    duration_sec: Optional[float] = Field(default=None, ge=0)
    frame_count: int = Field(ge=0)
    fps: float = Field(ge=0)
    fps_nominal: Optional[float] = Field(default=None, ge=0)
    source: Optional[str] = None
    artifacts: DatasetEpisodeArtifacts
    tags: Optional[list[str]] = None
    # v0.2: 整数 0-100 (原 v0.1 是 0..1 float 占位).
    quality_score: Optional[int] = Field(default=None, ge=0, le=100)
    flags: Optional[list[str]] = None
    stats: Optional[DatasetStats] = None


# ---------- TrainingJob ----------


TrainingJobStatus = Literal[
    "queued", "running", "succeeded", "failed", "cancelled"
]


class TrainingJob(_StrictModel):
    id: str = Field(min_length=1)
    status: TrainingJobStatus
    algorithm: str
    dataset_ids: list[str] = Field(min_length=1)
    hyperparameters: Optional[dict[str, Any]] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    metrics: Optional[dict[str, float]] = None
    artifact_url: Optional[str] = None
    error_message: Optional[str] = None
    progress: Optional[float] = Field(default=None, ge=0, le=1)


# ---------- Model (v0.3) ----------


class ModelArtifact(_StrictModel):
    """已训练好的模型 checkpoint + metrics. 对齐 apps/realtime/models/<key>/model.json."""
    model_key: str = Field(min_length=1)
    name: Optional[str] = None
    algo: str = Field(min_length=1)
    dataset_id: Optional[str] = None
    checkpoint: str = "checkpoint.pt"
    input_dim: Optional[int] = None
    output_dim: Optional[int] = None
    prediction_mode: Optional[Literal["delta", "absolute"]] = "delta"
    hparams: Optional[dict[str, Any]] = None
    metrics: Optional[dict[str, Any]] = None


# ---------- CompareFrame (v0.3) ----------


class CompareFrame(_StrictModel):
    """推断 WS 每帧同时带 ground truth + prediction + per-joint error.

    对齐 apps/realtime/api/inference.py 中 /ws/compare/* 的推送形状.
    """
    type: Literal["compare_frame"] = "compare_frame"
    frame_index: int = Field(ge=0)
    gt: "JointMap"
    pred: "JointMap"
    error: "JointMap"
    step_rmse: float = Field(ge=0)
    latency_ms: Optional[float] = Field(default=None, ge=0)


__all__ = [
    "BOTCLAW_SPEC_VERSION",
    "JOINT_NAMES",
    "JointName",
    "JointMap",
    "JointUpdate",
    "JointUpdateMeta",
    "RobotState",
    "RobotSafety",
    "JointLimit",
    "RobotModel",
    "ControlMode",
    "CameraSource",
    "DeviceCapabilities",
    "ParamType",
    "TrainBackend",
    "CompatibilityLevel",
    "SkillParamSchema",
    "SkillCompatibility",
    "Skill",
    "DatasetEpisode",
    "DatasetEpisodeArtifacts",
    "DatasetStats",
    "JointStats",
    "TrainingJob",
    "TrainingJobStatus",
    "ModelArtifact",
    "CompareFrame",
]

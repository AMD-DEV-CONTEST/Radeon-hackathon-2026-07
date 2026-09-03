"""AutoFlow 核心数据模型。

这些模型是整个系统的契约，贯穿 planner -> capture -> compiler -> replay 全链路。
- TaskPlan:   LLM 生成的结构化任务计划 (含语义标注)
- Recording:  录制原始数据 (动作 + 帧 + UI树)
- Bundle:     编译后的确定性程序 (Resolution Ladder 素材 + 验证条件)
- RunResult:  单次执行结果
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# TaskPlan 相关
# --------------------------------------------------------------------------- #

class ActionType(str, Enum):
    CLICK = "click"
    TYPE = "type"
    PRESS = "press"
    WAIT = "wait"
    HOTKEY = "hotkey"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TargetEvidence(BaseModel):
    """Planner 提供的目标语义提示，供首次执行和编译器使用。"""

    semantic_hint: str = ""
    expected_text: Optional[str] = None
    expected_location: Optional[str] = None


class PlanStep(BaseModel):
    """TaskPlan 中的单个步骤 (LLM 输出)。"""

    step_index: int
    action: ActionType
    description: str
    target_evidence: TargetEvidence = Field(default_factory=TargetEvidence)
    parameters: dict[str, Any] = Field(default_factory=dict)
    postcondition: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    reversible: bool = True
    # 首次执行后的实际结果 (供编译器使用)
    actual_result: Optional[dict[str, Any]] = None


class TaskPlan(BaseModel):
    """结构化任务计划。"""

    task_id: str
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    global_verification: Optional[dict[str, Any]] = None
    context: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Recording 相关
# --------------------------------------------------------------------------- #

class RecordingEvent(BaseModel):
    """录制中的单个事件 (动作 / 截图 / UI树节点)。"""

    timestamp: str = Field(default_factory=_now)
    kind: Literal["action", "frame", "ui_tree", "ocr"] = "action"
    data: dict[str, Any] = Field(default_factory=dict)


class Recording(BaseModel):
    """一次录制的完整原始数据。"""

    recording_id: str
    app_name: str = ""
    backend: Literal["web", "desktop", "mock"] = "web"
    started_at: str = Field(default_factory=_now)
    events: list[RecordingEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_event(self, kind: str, data: dict[str, Any]) -> None:
        self.events.append(
            RecordingEvent(kind=kind, data=data)  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------- #
# Bundle 相关
# --------------------------------------------------------------------------- #

class EvidenceType(str, Enum):
    STRUCTURAL = "structural"    # UIA / DOM selector
    TEMPLATE = "template"        # 局部截图模板
    OCR = "ocr"                  # 控件文字
    GEOMETRY = "geometry"        # 几何相对定位
    GROUNDING = "grounding"      # (可选) grounding 模型


class StepEvidence(BaseModel):
    """单步的定位证据集合 (Resolution Ladder 素材)。"""

    structural: Optional[dict[str, Any]] = None
    template: Optional[dict[str, Any]] = None
    ocr: Optional[dict[str, Any]] = None
    geometry: Optional[dict[str, Any]] = None
    grounding: Optional[dict[str, Any]] = None


class BundleStep(BaseModel):
    """编译后的确定性步骤。"""

    index: int
    action: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    evidence: StepEvidence = Field(default_factory=StepEvidence)
    resolution_ladder: list[EvidenceType] = Field(default_factory=list)
    postcondition: Optional[dict[str, Any]] = None
    risk: dict[str, Any] = Field(default_factory=lambda: {"level": "low", "reversible": True})
    identity_check: Optional[dict[str, Any]] = None
    # 参数化槽位: {slot_name: default}
    slots: dict[str, Any] = Field(default_factory=dict)


class Bundle(BaseModel):
    """确定性程序 (编译产物)。"""

    task_id: str
    goal: str
    version: int = 1
    created_at: str = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    steps: list[BundleStep] = Field(default_factory=list)
    effect_oracle: Optional[dict[str, Any]] = None
    halt_policy: dict[str, Any] = Field(
        default_factory=lambda: {
            "on_identity_fail": "halt",
            "on_effect_fail": "halt",
            "max_heal_attempts": 3,
        }
    )


# --------------------------------------------------------------------------- #
# 执行结果
# --------------------------------------------------------------------------- #

class StepResult(BaseModel):
    index: int
    status: Literal["success", "halt"]
    evidence_used: Optional[EvidenceType] = None
    reason: str = ""
    duration_ms: int = 0


class RunResult(BaseModel):
    """单次执行的完整结果。"""

    run_id: str
    task_id: str
    status: Literal["success", "halted", "effect_failed"]
    started_at: str = Field(default_factory=_now)
    duration_ms: int = 0
    steps: list[StepResult] = Field(default_factory=list)
    halt_report: Optional[dict[str, Any]] = None
    receipt: Optional[str] = None  # 隐私安全凭证

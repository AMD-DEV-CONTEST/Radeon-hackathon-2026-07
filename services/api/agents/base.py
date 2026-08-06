from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SkillStep(BaseModel):
    id: str
    skill: str
    description: str
    params: dict[str, Any] = {}
    depends_on: list[str] = []
    status: StepStatus = StepStatus.PENDING
    output: dict[str, Any] | None = None
    error: str | None = None


class Plan(BaseModel):
    goal: str
    style_id: str = "realistic_3d"
    output_mode: str = "fullcolor_3d"
    user_prompt: str = ""
    postprocess_params: dict[str, Any] = {}
    steps: list[SkillStep] = []
    reasoning: str = ""

    def to_display_plan(self) -> list[dict[str, Any]]:
        return [step.model_dump() for step in self.steps]


class AgentContext(BaseModel):
    job_id: str | None = None
    user_input: str = ""
    image_path: str | None = None
    current_plan: Plan | None = None
    history: list[dict[str, Any]] = []

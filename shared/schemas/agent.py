from typing import Any
from pydantic import BaseModel


class SkillStepResponse(BaseModel):
    id: str
    skill: str
    description: str
    params: dict[str, Any]
    depends_on: list[str]
    status: str
    output: dict[str, Any] | None
    error: str | None


class PlanResponse(BaseModel):
    goal: str
    style_id: str
    output_mode: str
    user_prompt: str
    postprocess_params: dict[str, Any]
    steps: list[SkillStepResponse]
    reasoning: str


class AgentPlanRequest(BaseModel):
    user_input: str
    image_path: str | None = None


class AgentChatRequest(BaseModel):
    message: str
    plan: PlanResponse | None = None


class AgentChatResponse(BaseModel):
    action: str
    params: dict[str, Any]
    response: str


class AgentExecuteRequest(BaseModel):
    plan: PlanResponse
    input_image_path: str


class AgentExecuteResponse(BaseModel):
    job_id: str
    status: str

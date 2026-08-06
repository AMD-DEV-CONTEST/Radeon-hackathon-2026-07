from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from agents.director import director
from agents.base import Plan
from agents.memory import agent_memory
from jobs.tasks import generate_asset_task
from models import get_db, GenerationJob, JobStatus
from shared.schemas.agent import (
    AgentPlanRequest,
    AgentExecuteRequest,
    AgentChatRequest,
    PlanResponse,
    AgentChatResponse,
    AgentExecuteResponse,
)
from shared.schemas.job import JobResponse

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/plan", response_model=PlanResponse)
def agent_plan(payload: AgentPlanRequest):
    plan = director.plan(payload.user_input, payload.image_path)
    # Save user preference for style if a default memory namespace is implied
    if plan.style_id:
        agent_memory.set("last_style_id", plan.style_id)
    return PlanResponse(**plan.model_dump())


@router.post("/execute", response_model=AgentExecuteResponse)
def agent_execute(payload: AgentExecuteRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    plan = Plan(**payload.plan.model_dump())

    # Create job record first so the UI can poll it immediately
    job = GenerationJob(
        status=JobStatus.PENDING.value,
        input_image_path=payload.input_image_path,
        style=plan.style_id,
        prompt=plan.user_prompt,
        output_mode=plan.output_mode,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch the long-running generation in the background so the HTTP
    # response returns immediately (required when Celery runs in eager mode).
    background_tasks.add_task(
        generate_asset_task.delay,
        plan.model_dump(),
        payload.input_image_path,
        job.id,
    )

    return AgentExecuteResponse(job_id=job.id, status=JobStatus.PENDING.value)


@router.post("/chat", response_model=AgentChatResponse)
def agent_chat(payload: AgentChatRequest):
    plan_obj = Plan(**payload.plan.model_dump()) if payload.plan else None
    result = director.chat(payload.message, plan_obj)
    return AgentChatResponse(**result)


@router.get("/memory/style")
def get_last_style():
    return {"last_style_id": agent_memory.get("last_style_id")}

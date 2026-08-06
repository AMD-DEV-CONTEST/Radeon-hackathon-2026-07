from pathlib import Path
from typing import Any

from agents.base import Plan, AgentContext
from agents.styles import get_style
from models import SessionLocal, GenerationJob, JobStatus
from storage import result_path
from pipelines.generate_3d import run_generate_3d_pipeline
from pipelines.generate_relief import run_generate_relief_pipeline


def create_job_from_plan(plan: Plan, input_image_path: str) -> GenerationJob:
    db = SessionLocal()
    try:
        job = GenerationJob(
            status=JobStatus.PENDING.value,
            input_image_path=input_image_path,
            style=plan.style_id,
            prompt=plan.user_prompt,
            output_mode=plan.output_mode,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


def run_plan(plan: Plan, input_image_path: str, job_id: str | None = None) -> str:
    """Execute a plan and return the job_id.

    For now this directly dispatches to the 3D or 2.5D pipeline.
    Future iterations can run individual skill steps for finer control.
    """
    if job_id is None:
        job = create_job_from_plan(plan, input_image_path)
        job_id = job.id

    style = get_style(plan.style_id)

    if plan.output_mode == "relief_2d5":
        run_generate_relief_pipeline(
            job_id=job_id,
            input_image_path=input_image_path,
            style=plan.style_id,
            prompt=plan.user_prompt,
            postprocess_params=style.postprocess_params | plan.postprocess_params,
        )
    else:
        run_generate_3d_pipeline(
            job_id=job_id,
            input_image_path=input_image_path,
            style=plan.style_id,
            prompt=plan.user_prompt,
            postprocess_params=style.postprocess_params | plan.postprocess_params,
        )

    return job_id


class Director3D:
    """High-level agent director: plan -> dispatch -> observe -> chat."""

    def __init__(self):
        self.context = AgentContext()

    def plan(self, user_input: str, image_path: str | None = None) -> Plan:
        from agents.planner import plan_from_request
        plan = plan_from_request(user_input)
        self.context = AgentContext(
            user_input=user_input,
            image_path=image_path,
            current_plan=plan,
        )
        return plan

    def execute(self, plan: Plan, image_path: str) -> str:
        return run_plan(plan, image_path)

    def chat(self, message: str, current_plan: Plan | None = None) -> dict[str, Any]:
        from agents.chat import parse_chat_message
        return parse_chat_message(message, current_plan)


director = Director3D()

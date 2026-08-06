from celery_app import celery_app
from pipelines.generate_3d import run_generate_3d_pipeline
from agents.base import Plan
from agents.director import run_plan


@celery_app.task(bind=True, max_retries=1, default_retry_delay=10)
def generate_3d_task(self, job_id: str, input_image_path: str, style: str, prompt: str):
    self.update_state(state="STARTED", meta={"job_id": job_id})
    run_generate_3d_pipeline(
        job_id=job_id,
        input_image_path=input_image_path,
        style=style,
        prompt=prompt,
    )
    return {"job_id": job_id, "status": "completed"}


@celery_app.task(bind=True, max_retries=1, default_retry_delay=10)
def generate_asset_task(self, plan_dict: dict, input_image_path: str, job_id: str | None = None):
    """Agent-driven generation task that dispatches to 3D or 2.5D pipeline."""
    plan = Plan(**plan_dict)
    self.update_state(state="STARTED", meta={"job_id": job_id, "plan": plan_dict})
    final_job_id = run_plan(plan, input_image_path, job_id=job_id)
    return {"job_id": final_job_id, "status": "completed"}


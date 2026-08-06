from threading import Thread

from fastapi import APIRouter, HTTPException, Request

from StoryCanvasAI.backend.models.schemas import (
    StoryRequest,
)

router = APIRouter()

# This will be assigned from app.py
pipeline = None


# ----------------------------------------------------
# Background worker
# ----------------------------------------------------
def run_pipeline(job_manager, job_id, pipeline, prompt, pages):
    print("========== THREAD STARTED ==========")

    try:
        print("Updating job...")
        job_manager.update(
            job_id,
            status="Generating Story",
            progress=5,
        )

        print("Calling pipeline.generate()")

        story = pipeline.generate(
            user_prompt=prompt,
            pages=pages,
        )

        print("Pipeline finished")

        job_manager.update(
            job_id,
            status="Completed",
            progress=100,
            story=story,
        )

        print("Job completed")

    except Exception as e:
        import traceback
        traceback.print_exc()

        print("THREAD ERROR:", e)

        job_manager.update(
            job_id,
            status="Failed",
            error=str(e),
        )
# ----------------------------------------------------
# Health
# ----------------------------------------------------
@router.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "StoryCanvas AI Backend"
    }


# ----------------------------------------------------
# Generate Story (Starts Background Job)
# ----------------------------------------------------
@router.post("/generate")
def generate_story(request: Request,body: StoryRequest,):
    global pipeline

    if pipeline is None:
        raise HTTPException(
            status_code=500,
            detail="Pipeline not initialized."
        )

    job_manager = request.app.state.job_manager

    # Create new job
    job_id = job_manager.create_job()
    print("Creating background thread...")
    # Start background thread
    Thread(
        target=run_pipeline,
        args=(
            job_manager,
            job_id,
            pipeline,
            body.prompt,
            body.pages,
        ),
        daemon=True,
    ).start()
    print("Thread started")
    return {
        "status": "started",
        "job_id": job_id,
    }

@router.get("/status/{job_id}")
def get_status(
    job_id: str,
    request: Request,
):

    job_manager = request.app.state.job_manager

    job = job_manager.get(job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    return {
        "status": job["status"],
        "progress": job["progress"],
        "error": job["error"],
    }

@router.get("/story/{job_id}")
def get_story(
    job_id: str,
    request: Request,
):

    job_manager = request.app.state.job_manager

    job = job_manager.get(job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    if job["story"] is None:

        return {
            "status": job["status"],
            "progress": job["progress"],
        }

    return {
        "status": "completed",
        "story": job["story"],
    }
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from app.core.config import STORAGE_ROOT
from app.core.security import require_demo_auth
from app.schemas.project import ProjectCreate, ResultEdit, ReviewRequest
from app.services.mock import generate_results, make_result
from app.services.store import store
from app.services.uploads import validate_and_store

logger = logging.getLogger("brandpilot.api")
router = APIRouter()

@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "brandpilot-backend", "mode": "mock"}

@router.get("/system-info")
def system_info(_: None = Depends(require_demo_auth)) -> dict:
    return {"gpu_connected": False, "rocm_available": False, "inference_mode": "mock", "device": None, "message": "AMD Radeon inference has not been connected yet."}

@router.post("/projects", status_code=201)
def create_project(payload: ProjectCreate, _: None = Depends(require_demo_auth)) -> dict:
    project = store.create(payload)
    logger.info("project_created", extra={"project_id": project["project_id"]})
    return project

@router.get("/projects/{project_id}")
def get_project(project_id: str, _: None = Depends(require_demo_auth)) -> dict:
    return store.get(project_id)

@router.post("/projects/{project_id}/assets", status_code=201)
async def upload_asset(
    project_id: str,
    file: UploadFile = File(...),
    _: None = Depends(require_demo_auth),
) -> dict:
    project = store.get(project_id)
    asset = await validate_and_store(file, STORAGE_ROOT / "projects" / project["project_id"] / "assets")
    project["asset"] = asset
    project["status"] = "asset_uploaded"
    store.save(project)
    return asset


@router.get("/projects/{project_id}/assets/{storage_name}")
def get_asset(
    project_id: str,
    storage_name: str,
    _: None = Depends(require_demo_auth),
) -> FileResponse:
    project = store.get(project_id)
    asset = project.get("asset")
    if not asset or storage_name != asset.get("storage_name"):
        raise HTTPException(status_code=404, detail="Asset not found")
    asset_dir = (STORAGE_ROOT / "projects" / project_id / "assets").resolve()
    path = (asset_dir / storage_name).resolve()
    if path.parent != asset_dir or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(path, media_type=asset["content_type"])

@router.post("/projects/{project_id}/generate")
def generate(project_id: str, _: None = Depends(require_demo_auth)) -> dict:
    project = store.get(project_id)
    if not project.get("asset"):
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Upload a product asset before generation")
    project["results"] = generate_results(project)
    project["status"] = "completed"
    project["generation_state"] = "completed"
    store.save(project)
    return {"mode": "mock", "gpu_connected": False, "rocm_available": False, "project_id": project_id, "status": "completed", "results": project["results"]}

@router.post("/projects/{project_id}/results/{result_id}/review")
def review(
    project_id: str,
    result_id: str,
    payload: ReviewRequest,
    _: None = Depends(require_demo_auth),
) -> dict:
    project = store.get(project_id)
    result = store.find_result(project, result_id)
    result["human_review_status"] = payload.status
    result["review_note"] = payload.note
    result["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    project["review_state"] = "in_progress"
    store.save(project)
    return result

@router.patch("/projects/{project_id}/results/{result_id}")
def edit_result(
    project_id: str,
    result_id: str,
    payload: ResultEdit,
    _: None = Depends(require_demo_auth),
) -> dict:
    project = store.get(project_id)
    result = store.find_result(project, result_id)
    for key, value in payload.model_dump(exclude_none=True).items():
        result[key] = value
    store.save(project)
    return result

@router.post("/projects/{project_id}/results/{result_id}/regenerate")
def regenerate(
    project_id: str,
    result_id: str,
    _: None = Depends(require_demo_auth),
) -> dict:
    project = store.get(project_id)
    current = store.find_result(project, result_id)
    replacement = make_result(current["style"], current["output_format"], current.get("revision", 1) + 1)
    project["results"] = [replacement if item["result_id"] == result_id else item for item in project["results"]]
    store.save(project)
    return replacement

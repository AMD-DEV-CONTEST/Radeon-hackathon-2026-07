import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4
from fastapi import HTTPException
from app.core.config import STORAGE_ROOT
from app.schemas.project import ProjectCreate

INTERRUPTIBLE_GENERATION_STATES = {
    "queued",
    "loading_model",
    "preprocessing",
    "generating",
    "saving",
}


class ProjectStore:
    def __init__(self, root: Path = STORAGE_ROOT):
        self.root = root
        self.projects = root / "projects"
        self.projects.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    @staticmethod
    def validate_id(value: str) -> str:
        try:
            return str(UUID(value))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc

    def path(self, project_id: str) -> Path:
        return self.projects / self.validate_id(project_id) / "project.json"

    def create(self, config: ProjectCreate) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        project_id = str(uuid4())
        data = {"project_id": project_id, "status": "created", "created_at": now, "updated_at": now, "configuration": config.model_dump(), "asset": None, "generation_state": "pending", "review_state": "pending", "results": []}
        self.save(data)
        return data

    def get(self, project_id: str) -> dict:
        path = self.path(project_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Project not found")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=500, detail="Project storage is unavailable") from exc

    def save(self, data: dict) -> dict:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        path = self.projects / data["project_id"] / "project.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temporary.replace(path)
        return data

    def find_result(self, project: dict, result_id: str) -> dict:
        for result in project["results"]:
            if result["result_id"] == result_id:
                return result
        raise HTTPException(status_code=404, detail="Result not found")

    def recover_interrupted_jobs(self) -> int:
        """Mark jobs left active by a previous process as safely interrupted."""
        recovered = 0
        for project_path in self.projects.glob("*/project.json"):
            try:
                project = json.loads(project_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if project.get("generation_state") not in INTERRUPTIBLE_GENERATION_STATES:
                continue
            project["generation_state"] = "interrupted"
            project["status"] = "interrupted"
            project["active_rocm_job_id"] = None
            project["last_generation_failure"] = (
                "The previous experimental generation was interrupted by a backend restart."
            )
            self.save(project)
            recovered += 1
        return recovered


store = ProjectStore()

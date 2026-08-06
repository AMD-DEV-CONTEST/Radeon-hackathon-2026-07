import shutil
from pathlib import Path
from fastapi import UploadFile

from config import settings


def ensure_dirs():
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.result_dir.mkdir(parents=True, exist_ok=True)


def save_upload(file: UploadFile, job_id: str) -> Path:
    ensure_dirs()
    target_dir = settings.upload_dir / job_id
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / (file.filename or "input.jpg")
    with dest.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return dest


def result_path(job_id: str, filename: str) -> Path:
    target_dir = settings.result_dir / job_id
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / filename

from __future__ import annotations

from pathlib import Path

from ...config import AppPaths

DATABASE_FILE_NAME = "xenix.db"


def database_path(paths: AppPaths) -> Path:
    return paths.state / DATABASE_FILE_NAME


def artifact_models_root(paths: AppPaths) -> Path:
    return paths.artifacts / "models"


def artifact_datasets_root(paths: AppPaths) -> Path:
    return paths.artifacts / "datasets"


def artifact_training_root(paths: AppPaths) -> Path:
    return paths.artifacts / "training"


def artifact_apply_root(paths: AppPaths) -> Path:
    return paths.artifacts / "apply"


def knowledge_root(paths: AppPaths) -> Path:
    return paths.artifacts / "knowledge"


def knowledge_objects_root(paths: AppPaths) -> Path:
    return knowledge_root(paths) / "objects"


def knowledge_staging_root(paths: AppPaths) -> Path:
    return knowledge_root(paths) / "staging"


def knowledge_indexes_root(paths: AppPaths) -> Path:
    return knowledge_root(paths) / "indexes"


def knowledge_tasks_root(paths: AppPaths) -> Path:
    return knowledge_root(paths) / "tasks"


def knowledge_import_task_root(paths: AppPaths, import_id: str) -> Path:
    return knowledge_tasks_root(paths) / "imports" / import_id


def knowledge_import_result_path(paths: AppPaths, import_id: str) -> Path:
    return knowledge_import_task_root(paths, import_id) / "result.json"


def knowledge_import_logs_path(paths: AppPaths, import_id: str) -> Path:
    return knowledge_import_task_root(paths, import_id) / "logs.jsonl"


def ml_task_parent_root(paths: AppPaths) -> Path:
    return paths.artifacts / "ml-tasks"


def ml_task_root(paths: AppPaths, ml_task_id: str) -> Path:
    return ml_task_parent_root(paths) / ml_task_id


def task_input_dir(paths: AppPaths, ml_task_id: str) -> Path:
    return ml_task_root(paths, ml_task_id) / "input"


def task_output_dir(paths: AppPaths, ml_task_id: str) -> Path:
    return ml_task_root(paths, ml_task_id) / "output"


def task_models_dir(paths: AppPaths, ml_task_id: str) -> Path:
    return ml_task_root(paths, ml_task_id) / "models"


def task_request_path(paths: AppPaths, ml_task_id: str) -> Path:
    return ml_task_root(paths, ml_task_id) / "request.json"


def task_result_path(paths: AppPaths, ml_task_id: str) -> Path:
    return ml_task_root(paths, ml_task_id) / "result.json"


def task_logs_path(paths: AppPaths, ml_task_id: str) -> Path:
    return ml_task_root(paths, ml_task_id) / "logs.jsonl"


def dataset_model_dir(paths: AppPaths, dataset_id: str) -> Path:
    return artifact_models_root(paths) / "datasets" / dataset_id


def dataset_apply_dir(paths: AppPaths, dataset_id: str) -> Path:
    return artifact_apply_root(paths) / "datasets" / dataset_id


def ensure_storage_layout(paths: AppPaths) -> None:
    for directory in (
        artifact_datasets_root(paths),
        artifact_models_root(paths),
        artifact_training_root(paths),
        artifact_apply_root(paths),
        ml_task_parent_root(paths),
        knowledge_objects_root(paths),
        knowledge_indexes_root(paths),
        knowledge_staging_root(paths),
        knowledge_tasks_root(paths),
    ):
        directory.mkdir(parents=True, exist_ok=True)

from __future__ import annotations

import json
import traceback
from pathlib import Path

from ..contracts import (
    ApplyTaskRequest,
    EvaluateTaskRequest,
    FitTaskRequest,
    HyperparameterTuningTaskRequest,
    TaskLogEntry,
)
from ..registry import get_model_service


def run_fit_task(task_dir_str: str) -> None:
    task_dir = Path(task_dir_str)
    request = FitTaskRequest.model_validate_json(task_request_path_from_dir(task_dir).read_text(encoding="utf-8"))
    logger = TaskFileLogger(task_dir)
    logger.info(f"Starting fit for model '{request.manual_training.model_key}'.")
    service = get_model_service(request.manual_training.model_key)
    try:
        result = service.fit(request, task_dir)
        write_result(task_dir, result.model_dump(mode="json"))
        logger.info("Fit completed successfully.")
    except Exception as exc:  # pragma: no cover - subprocess safety
        logger.error(f"Fit failed: {exc}")
        write_result(
            task_dir,
            {
                "task_id": request.task_id,
                "evaluation_kind": request.evaluation_kind.value,
                "evaluation_policy": request.evaluation_policy.model_dump(mode="json"),
                "error_summary": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise


def run_hyperparameter_tuning_task(task_dir_str: str) -> None:
    task_dir = Path(task_dir_str)
    request = HyperparameterTuningTaskRequest.model_validate_json(
        task_request_path_from_dir(task_dir).read_text(encoding="utf-8")
    )
    logger = TaskFileLogger(task_dir)
    logger.info(f"Starting tuning for model '{request.hyperparameter_tuning.model_key}'.")
    service = get_model_service(request.hyperparameter_tuning.model_key)
    try:
        result = service.tune(request, task_dir)
        write_result(task_dir, result.model_dump(mode="json"))
        logger.info("Tuning completed successfully.")
    except Exception as exc:  # pragma: no cover - subprocess safety
        logger.error(f"Tuning failed: {exc}")
        write_result(
            task_dir,
            {
                "task_id": request.task_id,
                "evaluation_kind": request.evaluation_kind.value,
                "evaluation_policy": request.evaluation_policy.model_dump(mode="json"),
                "error_summary": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise


def run_evaluate_task(task_dir_str: str) -> None:
    task_dir = Path(task_dir_str)
    request = EvaluateTaskRequest.model_validate_json(
        task_request_path_from_dir(task_dir).read_text(encoding="utf-8")
    )
    logger = TaskFileLogger(task_dir)
    logger.info(f"Starting evaluation for model '{request.evaluate_model.model_key}'.")
    service = get_model_service(request.evaluate_model.model_key)
    try:
        result = service.evaluate(request, task_dir)
        write_result(task_dir, result.model_dump(mode="json"))
        logger.info("Evaluation completed successfully.")
    except Exception as exc:  # pragma: no cover - subprocess safety
        logger.error(f"Evaluation failed: {exc}")
        write_result(
            task_dir,
            {
                "task_id": request.task_id,
                "evaluation_kind": request.evaluation_kind.value,
                "evaluation_policy": request.evaluation_policy.model_dump(mode="json"),
                "error_summary": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise


def run_apply_task(task_dir_str: str) -> None:
    task_dir = Path(task_dir_str)
    request = ApplyTaskRequest.model_validate_json(
        task_request_path_from_dir(task_dir).read_text(encoding="utf-8")
    )
    logger = TaskFileLogger(task_dir)
    logger.info(f"Starting apply for model '{request.apply_model.model_key}'.")
    service = get_model_service(request.apply_model.model_key)
    try:
        result = service.apply(request, task_dir)
        write_result(task_dir, result.model_dump(mode="json"))
        logger.info("Apply completed successfully.")
    except Exception as exc:  # pragma: no cover - subprocess safety
        logger.error(f"Apply failed: {exc}")
        write_result(
            task_dir,
            {
                "task_id": request.task_id,
                "trained_model_id": request.apply_model.trained_model_id,
                "model_key": request.apply_model.model_key,
                "error_summary": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise


def task_request_path_from_dir(task_dir: Path) -> Path:
    return task_dir / "request.json"


def task_result_path_from_dir(task_dir: Path) -> Path:
    return task_dir / "result.json"


def task_logs_path_from_dir(task_dir: Path) -> Path:
    return task_dir / "logs.jsonl"


def write_result(task_dir: Path, payload: dict[str, object]) -> None:
    task_result_path_from_dir(task_dir).write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


class TaskFileLogger:
    def __init__(self, task_dir: Path) -> None:
        self._path = task_logs_path_from_dir(task_dir)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)

    def _write(self, level: str, message: str) -> None:
        entry = TaskLogEntry(level=level, message=message)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json())
            handle.write("\n")

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_SAVE_LABEL_DATETIME_FORMAT = "%Y-%m-%d %H:%M"
_SAVE_FILE_DATETIME_FORMAT = "%Y%m%d-%H%M%S"
_SLUG_PATTERN = re.compile(r"[^\w]+", re.UNICODE)


class TrainedModelContextPayload(BaseModel):
    run_name: str
    dataset_name: str
    dataset_file_name: str
    evaluation_kind: str | None = None
    model_family: str | None = None
    model_task_kind: str | None = None
    train_role_bindings: list[dict[str, Any]] = Field(default_factory=list)
    apply_role_schema: dict[str, Any] = Field(default_factory=dict)
    result_contract: dict[str, Any] = Field(default_factory=dict)
    dataset_row_count: int
    dataset_column_count: int
    preview_columns: list[str] = Field(default_factory=list)
    preview_rows: list[list[str]] = Field(default_factory=list)


class TrainedModelMetadata(BaseModel):
    schema_version: int = 4
    model_key: str
    evaluation_kind: str | None = None
    model_family: str | None = None
    model_task_kind: str | None = None
    model_display_name: str
    display_name: str
    saved_name: str
    artifact_file_name: str
    save_note: str
    training_operation: str
    source_run_name: str
    source_dataset_name: str
    source_dataset_file_name: str
    train_role_bindings: list[dict[str, Any]] = Field(default_factory=list)
    apply_role_schema: dict[str, Any] = Field(default_factory=dict)
    result_contract: dict[str, Any] = Field(default_factory=dict)
    dataset_row_count: int = 0
    dataset_column_count: int = 0
    preview_columns: list[str] = Field(default_factory=list)
    preview_rows: list[list[str]] = Field(default_factory=list)
    training_params: dict[str, Any] = Field(default_factory=dict)
    best_params: dict[str, Any] = Field(default_factory=dict)
    tuning_grid: dict[str, list[Any]] = Field(default_factory=dict)
    evaluation_model_training_scope: str | None = None
    apply_model_training_scope: str | None = None
    evaluation_ml_task_id: str | None = None
    evaluation_primary_metric_name: str | None = None
    evaluation_primary_metric_value: float | None = None
    evaluation_metrics: dict[str, float] = Field(default_factory=dict)
    evaluation_details: dict[str, Any] = Field(default_factory=dict)


def parse_trained_model_metadata(payload: dict[str, Any] | None) -> TrainedModelMetadata | None:
    if not isinstance(payload, dict) or not payload:
        return None
    try:
        return TrainedModelMetadata.model_validate(payload)
    except Exception:
        return None


def build_saved_name(
    run_name: str,
    model_display_name: str,
    created_at: datetime,
) -> str:
    timestamp = created_at.strftime(_SAVE_LABEL_DATETIME_FORMAT)
    return f"{run_name} · {model_display_name} · {timestamp}"


def build_artifact_file_name(
    run_name: str,
    model_display_name: str,
    created_at: datetime,
    ml_task_id: str,
) -> str:
    run_slug = _slugify(run_name)
    model_slug = _slugify(model_display_name)
    timestamp = created_at.strftime(_SAVE_FILE_DATETIME_FORMAT)
    task_suffix = ml_task_id[:8]
    return f"{run_slug}-{model_slug}-{timestamp}-{task_suffix}.joblib"


def build_save_note(model_display_name: str) -> str:
    return (
        f"The saved {model_display_name} model remains available for comparison, "
        "apply reuse, and later review."
    )


def with_evaluation(
    metadata: TrainedModelMetadata,
    evaluation: Any,
    *,
    evaluation_ml_task_id: str | None = None,
) -> TrainedModelMetadata:
    update = {
        "schema_version": max(metadata.schema_version, 4),
        "evaluation_primary_metric_name": evaluation.primary_metric_name,
        "evaluation_primary_metric_value": float(evaluation.primary_metric_value),
        "evaluation_metrics": {
            str(metric_name): float(metric_value)
            for metric_name, metric_value in evaluation.metrics.items()
        },
        "evaluation_details": dict(getattr(evaluation, "details", {}) or {}),
    }
    if evaluation_ml_task_id:
        update["evaluation_ml_task_id"] = evaluation_ml_task_id
    return metadata.model_copy(update=update)


def with_evaluation_task(
    metadata: TrainedModelMetadata,
    evaluation_ml_task_id: str,
) -> TrainedModelMetadata:
    return metadata.model_copy(update={"evaluation_ml_task_id": evaluation_ml_task_id})


def artifact_file_name_from_path(artifact_path: str) -> str:
    return Path(artifact_path).name


def _slugify(value: str) -> str:
    normalized = _SLUG_PATTERN.sub("-", value.strip().lower()).strip("-_")
    return normalized or "model"

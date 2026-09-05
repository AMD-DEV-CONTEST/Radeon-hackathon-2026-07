from __future__ import annotations

import json
import queue
import shutil
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import duckdb
from opentelemetry import context as otel_context
from sqlalchemy.orm import sessionmaker
from sqlmodel import Field, SQLModel

from ..config import AppPaths
from ..exceptions import InvalidStateTransitionError, NotFoundError, ValidationError
from ..observability import extract_context, inject_context, record_counter, record_histogram, start_span
from .ml.contracts import (
    ApplyTaskResult,
    EvaluateTaskResult,
    FitTaskRequest,
    FitTaskResult,
    HyperparameterTuningTaskRequest,
    HyperparameterTuningTaskResult,
    TaskLogEntry,
    TrainedModelContextPayload,
)
from .ml.execution import MLWorkerRunner
from .ml.worker_pool import MLWorkerPool
from .ml.worker_settings import MLWorkerSettingsService
from .storage.layout import (
    dataset_apply_dir,
    dataset_model_dir,
    ml_task_root,
    task_input_dir,
    task_logs_path,
    task_output_dir,
    task_models_dir,
    task_request_path,
    task_result_path,
)
from .trained_model_metadata import (
    TrainedModelMetadata,
    artifact_file_name_from_path,
    build_artifact_file_name,
    build_save_note,
    build_saved_name,
)
from .storage.models import (
    DatasetRow,
    DatasetSourceFormat,
    MLTaskArtifactKind,
    MLTaskArtifactRow,
    MLTaskRow,
    MLTaskStatus,
    MLTaskType,
    TrainedModelRow,
)
from .storage.repositories import (
    DatasetRepository,
    MLTaskRepository,
    ProjectRepository,
    TrainedModelRepository,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_model_catalog_entry(model_key: str):
    from .ml.registry import get_model_catalog_entry

    return get_model_catalog_entry(model_key)


ALLOWED_TRANSITIONS: dict[MLTaskStatus, set[MLTaskStatus]] = {
    MLTaskStatus.PENDING: {MLTaskStatus.RUNNING, MLTaskStatus.CANCELLED},
    MLTaskStatus.RUNNING: {
        MLTaskStatus.SUCCEEDED,
        MLTaskStatus.FAILED,
        MLTaskStatus.CANCELLED,
    },
}


class CreateMLTaskInput(SQLModel):
    project_id: str
    dataset_id: str | None = None
    task_type: MLTaskType
    request_payload: dict[str, Any] = Field(default_factory=dict)


class StartMLTaskInput(SQLModel):
    ml_task_id: str


class MLTaskArtifactInput(SQLModel):
    artifact_kind: MLTaskArtifactKind
    absolute_path: str
    ready_to_open: bool = True


class CompleteMLTaskInput(SQLModel):
    ml_task_id: str
    result_payload: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[MLTaskArtifactInput] = Field(default_factory=list)


class FailMLTaskInput(SQLModel):
    ml_task_id: str
    error_summary: str


class CancelMLTaskInput(SQLModel):
    ml_task_id: str


class MLTaskService:
    def __init__(
        self,
        session_factory: sessionmaker,
        paths: AppPaths,
        worker_runner: MLWorkerRunner | None = None,
        worker_settings_service: MLWorkerSettingsService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._paths = paths
        self._projects = ProjectRepository()
        self._datasets = DatasetRepository()
        self._ml_tasks = MLTaskRepository()
        self._trained_models = TrainedModelRepository()
        self._worker_runner = worker_runner or MLWorkerPool(
            worker_settings_service or MLWorkerSettingsService(paths)
        )
        self._queue: queue.Queue[str] = queue.Queue()
        self._callbacks: list[Callable[[MLTaskRow], None]] = []
        self._dispatcher_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._submitted_ids: set[str] = set()
        self._trace_carriers: dict[str, dict[str, str]] = {}
        self._dispatch_semaphore = threading.BoundedSemaphore(
            max(1, int(getattr(self._worker_runner, "max_dispatch_threads", 1)))
        )

    def register_completion_listener(self, callback: Callable[[MLTaskRow], None]) -> None:
        self._callbacks.append(callback)

    def create_ml_task(self, input_data: CreateMLTaskInput) -> MLTaskRow:
        if not isinstance(input_data.request_payload, Mapping):
            raise ValidationError("ML task request payload must be a dictionary.")

        now = _utc_now()
        row = MLTaskRow(
            project_id=input_data.project_id,
            dataset_id=input_data.dataset_id,
            task_type=input_data.task_type,
            status=MLTaskStatus.PENDING,
            request_payload=dict(input_data.request_payload),
            created_at=now,
            updated_at=now,
        )

        with self._session_factory() as session:
            project = self._projects.get(session, input_data.project_id)
            if project is None:
                raise NotFoundError(f"Project '{input_data.project_id}' was not found.")

            if input_data.dataset_id is not None:
                dataset = self._datasets.get(session, input_data.dataset_id)
                if dataset is None:
                    raise NotFoundError(f"Dataset '{input_data.dataset_id}' was not found.")
                if dataset.project_id != project.id:
                    raise ValidationError("ML task dataset does not belong to the provided project.")

            self._ml_tasks.create(session, row)
            session.commit()
            self._record_task(row)
            return row

    def submit_ml_task(self, ml_task_id: str) -> None:
        task = self.get_ml_task(ml_task_id)
        if task.status is not MLTaskStatus.PENDING:
            raise InvalidStateTransitionError(
                f"ML task '{ml_task_id}' must be pending before it can be submitted."
            )

        root = ml_task_root(self._paths, ml_task_id)
        root.mkdir(parents=True, exist_ok=True)
        task_input_dir(self._paths, ml_task_id).mkdir(parents=True, exist_ok=True)
        task_output_dir(self._paths, ml_task_id).mkdir(parents=True, exist_ok=True)
        task_models_dir(self._paths, ml_task_id).mkdir(parents=True, exist_ok=True)
        task_request_path(self._paths, ml_task_id).write_text(
            json.dumps(task.request_payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

        with self._lock:
            if ml_task_id in self._submitted_ids:
                return
            self._submitted_ids.add(ml_task_id)
            self._trace_carriers[ml_task_id] = inject_context({})
            self._queue.put(ml_task_id)
            self._ensure_dispatcher_locked()

    def start_ml_task(self, input_data: StartMLTaskInput) -> MLTaskRow:
        with self._session_factory() as session:
            row = self._ml_tasks.get(session, input_data.ml_task_id)
            if row is None:
                raise NotFoundError(f"ML task '{input_data.ml_task_id}' was not found.")

            self._require_transition(row.status, MLTaskStatus.RUNNING)
            now = _utc_now()
            updated = self._ml_tasks.update_status(
                session,
                row.id,
                row.status,
                MLTaskStatus.RUNNING,
                now,
            )
            session.commit()

        ml_task_root(self._paths, input_data.ml_task_id).mkdir(parents=True, exist_ok=True)
        self._record_task(updated)
        return updated

    def complete_ml_task(self, input_data: CompleteMLTaskInput) -> MLTaskRow:
        with self._session_factory() as session:
            row = self._ml_tasks.get(session, input_data.ml_task_id)
            if row is None:
                raise NotFoundError(f"ML task '{input_data.ml_task_id}' was not found.")

            self._require_transition(row.status, MLTaskStatus.SUCCEEDED)
            completed = self._complete_row(session, row, input_data.result_payload, input_data.artifacts)
            session.commit()
            self._record_task(completed)
            return completed

    def fail_ml_task(self, input_data: FailMLTaskInput) -> MLTaskRow:
        error_summary = input_data.error_summary.strip()
        if not error_summary:
            raise ValidationError("ML task failure summary cannot be empty.")

        with self._session_factory() as session:
            row = self._ml_tasks.get(session, input_data.ml_task_id)
            if row is None:
                raise NotFoundError(f"ML task '{input_data.ml_task_id}' was not found.")

            self._require_transition(row.status, MLTaskStatus.FAILED)
            failed = self._ml_tasks.fail(session, row.id, error_summary, _utc_now())
            session.commit()
            self._record_task(failed, error_type="MLTaskFailure")
            return failed

    def cancel_ml_task(self, input_data: CancelMLTaskInput) -> MLTaskRow:
        with self._session_factory() as session:
            row = self._ml_tasks.get(session, input_data.ml_task_id)
            if row is None:
                raise NotFoundError(f"ML task '{input_data.ml_task_id}' was not found.")

            self._require_transition(row.status, MLTaskStatus.CANCELLED)
            cancelled = self._ml_tasks.cancel(session, row.id, _utc_now())
            session.commit()
            self._record_task(cancelled)
            return cancelled

    def list_dataset_ml_tasks(self, dataset_id: str) -> list[MLTaskRow]:
        with self._session_factory() as session:
            return self._ml_tasks.list_by_dataset(session, dataset_id)

    def get_ml_task(self, ml_task_id: str) -> MLTaskRow:
        with self._session_factory() as session:
            row = self._ml_tasks.get(session, ml_task_id)
            if row is None:
                raise NotFoundError(f"ML task '{ml_task_id}' was not found.")
            return row

    def list_ml_task_artifacts(self, ml_task_id: str) -> list[MLTaskArtifactRow]:
        with self._session_factory() as session:
            return self._ml_tasks.list_artifacts(session, ml_task_id)

    def read_task_logs(self, ml_task_id: str) -> list[TaskLogEntry]:
        path = task_logs_path(self._paths, ml_task_id)
        if not path.exists():
            return []
        return [
            TaskLogEntry.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _ensure_dispatcher_locked(self) -> None:
        if self._dispatcher_thread is not None and self._dispatcher_thread.is_alive():
            return
        self._dispatcher_thread = threading.Thread(
            target=self._dispatch_loop,
            name="xenix-ml-dispatcher",
            daemon=True,
        )
        self._dispatcher_thread.start()

    def _dispatch_loop(self) -> None:
        while True:
            ml_task_id = self._queue.get()
            self._dispatch_semaphore.acquire()
            threading.Thread(
                target=self._run_queued_task,
                args=(ml_task_id,),
                name=f"xenix-ml-task-{ml_task_id[:8]}",
                daemon=True,
            ).start()

    def _run_queued_task(self, ml_task_id: str) -> None:
        from .runtime_activity import activity_coordinator

        carrier = self._trace_carriers.pop(ml_task_id, {})
        token = otel_context.attach(extract_context(carrier)) if carrier else None
        try:
            with activity_coordinator.work(f"ml:{ml_task_id}"):
                finished_task = self._run_task(ml_task_id)
                if finished_task is not None:
                    self._notify_callbacks(finished_task)
        finally:
            if token is not None:
                otel_context.detach(token)
            with self._lock:
                self._submitted_ids.discard(ml_task_id)
            self._queue.task_done()
            self._dispatch_semaphore.release()

    def _run_task(self, ml_task_id: str) -> MLTaskRow | None:
        task = self.get_ml_task(ml_task_id)
        if task.status is not MLTaskStatus.PENDING:
            return task

        task_started_at = perf_counter()
        try:
            with start_span("ml.task", self._task_attributes(task)):
                running_task = self.start_ml_task(StartMLTaskInput(ml_task_id=ml_task_id))
                return_code = self._worker_runner.run(
                    self._resolve_entrypoint(running_task.task_type),
                    ml_task_root(self._paths, ml_task_id),
                    cancel_requested=lambda: self.get_ml_task(ml_task_id).status is MLTaskStatus.CANCELLED,
                )
                current = self.get_ml_task(ml_task_id)
                if current.status is MLTaskStatus.CANCELLED:
                    self._record_task_duration(current, task_started_at)
                    return current
                if return_code == 0:
                    completed = self._finalize_success(ml_task_id)
                    self._record_task_duration(completed, task_started_at)
                    return completed
                failed = self._finalize_failure(ml_task_id, return_code)
                self._record_task_duration(failed, task_started_at)
                return failed
        except Exception as exc:
            current = self.get_ml_task(ml_task_id)
            if current.status is MLTaskStatus.RUNNING:
                failed = self.fail_ml_task(
                    FailMLTaskInput(ml_task_id=ml_task_id, error_summary=str(exc))
                )
                self._record_task_duration(failed, task_started_at)
                return failed
            return current

    def _resolve_entrypoint(self, task_type: MLTaskType) -> Callable[[str], None]:
        from .ml.operations import (
            run_apply_task,
            run_evaluate_task,
            run_fit_task,
            run_hyperparameter_tuning_task,
        )

        if task_type is MLTaskType.FIT:
            return run_fit_task
        if task_type is MLTaskType.HYPERPARAMETER_TUNING:
            return run_hyperparameter_tuning_task
        if task_type is MLTaskType.EVALUATE:
            return run_evaluate_task
        if task_type is MLTaskType.APPLY:
            return run_apply_task
        raise ValidationError(f"ML task type '{task_type.value}' is not executable in this workflow.")

    def _finalize_success(self, ml_task_id: str) -> MLTaskRow:
        with self._session_factory() as session:
            row = self._ml_tasks.get(session, ml_task_id)
            if row is None:
                raise NotFoundError(f"ML task '{ml_task_id}' was not found.")
            if row.task_type is MLTaskType.FIT:
                result_payload, artifacts = self._finalize_fit_task(session, row)
            elif row.task_type is MLTaskType.HYPERPARAMETER_TUNING:
                result_payload, artifacts = self._finalize_tuning_task(session, row)
            elif row.task_type is MLTaskType.EVALUATE:
                result_payload, artifacts = self._finalize_evaluate_task(row)
            elif row.task_type is MLTaskType.APPLY:
                result_payload, artifacts = self._finalize_apply_task(session, row)
            else:
                raise ValidationError(f"ML task type '{row.task_type.value}' cannot be finalized.")

            completed = self._complete_row(session, row, result_payload, artifacts)
            session.commit()
            return completed

    def _finalize_fit_task(
        self,
        session: Any,
        row: MLTaskRow,
    ) -> tuple[dict[str, Any], list[MLTaskArtifactInput]]:
        request = FitTaskRequest.model_validate(row.request_payload)
        trained_model_context = self._resolve_trained_model_context(session, row, request.trained_model_context)
        result = FitTaskResult.model_validate_json(task_result_path(self._paths, row.id).read_text(encoding="utf-8"))
        if result.error_summary:
            raise ValidationError(result.error_summary)
        evaluation_model_path = Path(result.model_artifact_path)
        final_model_path = Path(result.final_model_artifact_path) if result.final_model_artifact_path else evaluation_model_path
        holdout_path = Path(result.holdout_artifact_path) if result.holdout_artifact_path else None
        export_path = Path(result.export_artifact_path) if result.export_artifact_path else None
        self._require_existing_path(evaluation_model_path)
        self._require_existing_path(final_model_path)
        if holdout_path is not None:
            self._require_existing_path(holdout_path)
        if export_path is not None:
            self._require_existing_path(export_path)
        catalog_entry = _get_model_catalog_entry(result.model_key)
        model_display_name = catalog_entry.display_name
        artifact_file_name = build_artifact_file_name(
            trained_model_context.run_name,
            model_display_name,
            row.created_at,
            row.id,
        )
        canonical_path = self._copy_canonical_model(row, artifact_file_name, final_model_path)
        metadata = TrainedModelMetadata(
            model_key=result.model_key,
            evaluation_kind=trained_model_context.evaluation_kind or catalog_entry.evaluation_kind.value,
            model_family=trained_model_context.model_family or catalog_entry.model_family.value,
            model_task_kind=trained_model_context.model_task_kind or catalog_entry.model_task_kind.value,
            model_display_name=model_display_name,
            display_name=model_display_name,
            saved_name=build_saved_name(
                trained_model_context.run_name,
                model_display_name,
                row.created_at,
            ),
            artifact_file_name=artifact_file_name_from_path(str(canonical_path)),
            save_note=build_save_note(model_display_name),
            training_operation=row.task_type.value,
            source_run_name=trained_model_context.run_name,
            source_dataset_name=trained_model_context.dataset_name,
            source_dataset_file_name=trained_model_context.dataset_file_name,
            train_role_bindings=[dict(binding) for binding in trained_model_context.train_role_bindings],
            apply_role_schema=dict(trained_model_context.apply_role_schema),
            result_contract=dict(trained_model_context.result_contract),
            dataset_row_count=trained_model_context.dataset_row_count,
            dataset_column_count=trained_model_context.dataset_column_count,
            preview_columns=list(trained_model_context.preview_columns),
            preview_rows=[list(row_values) for row_values in trained_model_context.preview_rows],
            training_params=dict(result.params),
            evaluation_model_training_scope="holdout_train_split" if result.final_model_artifact_path else None,
            apply_model_training_scope="all_eligible_rows" if result.final_model_artifact_path else None,
        )
        trained_model = self._trained_models.create(
            session,
            TrainedModelRow(
                dataset_id=row.dataset_id,
                ml_task_id=row.id,
                model_key=result.model_key,
                problem_kind=catalog_entry.problem_kind,
                artifact_path=str(canonical_path),
                metadata_payload=metadata.model_dump(mode="json"),
            ),
        )
        payload = result.model_dump(mode="json")
        payload["trained_model_id"] = trained_model.id
        payload["canonical_model_artifact_path"] = str(canonical_path)
        payload["evaluation_model_artifact_path"] = str(evaluation_model_path)
        artifacts = [
            MLTaskArtifactInput(artifact_kind=MLTaskArtifactKind.MODEL, absolute_path=str(canonical_path)),
        ]
        if holdout_path is not None:
            artifacts.append(
                MLTaskArtifactInput(
                    artifact_kind=MLTaskArtifactKind.HOLDOUT_DATA,
                    absolute_path=str(holdout_path),
                    ready_to_open=False,
                )
            )
        if export_path is not None:
            artifacts.append(
                MLTaskArtifactInput(
                    artifact_kind=MLTaskArtifactKind.EXPORT_FILE,
                    absolute_path=str(export_path),
                )
            )
        return payload, artifacts

    def _finalize_tuning_task(
        self,
        session: Any,
        row: MLTaskRow,
    ) -> tuple[dict[str, Any], list[MLTaskArtifactInput]]:
        request = HyperparameterTuningTaskRequest.model_validate(row.request_payload)
        trained_model_context = self._resolve_trained_model_context(session, row, request.trained_model_context)
        result = HyperparameterTuningTaskResult.model_validate_json(
            task_result_path(self._paths, row.id).read_text(encoding="utf-8")
        )
        if result.error_summary:
            raise ValidationError(result.error_summary)
        evaluation_model_path = Path(result.model_artifact_path)
        final_model_path = Path(result.final_model_artifact_path) if result.final_model_artifact_path else evaluation_model_path
        holdout_path = Path(result.holdout_artifact_path) if result.holdout_artifact_path else None
        export_path = Path(result.export_artifact_path) if result.export_artifact_path else None
        self._require_existing_path(evaluation_model_path)
        self._require_existing_path(final_model_path)
        if holdout_path is not None:
            self._require_existing_path(holdout_path)
        if export_path is not None:
            self._require_existing_path(export_path)
        catalog_entry = _get_model_catalog_entry(result.model_key)
        model_display_name = catalog_entry.display_name
        artifact_file_name = build_artifact_file_name(
            trained_model_context.run_name,
            model_display_name,
            row.created_at,
            row.id,
        )
        canonical_path = self._copy_canonical_model(row, artifact_file_name, final_model_path)
        metadata = TrainedModelMetadata(
            model_key=result.model_key,
            evaluation_kind=trained_model_context.evaluation_kind or catalog_entry.evaluation_kind.value,
            model_family=trained_model_context.model_family or catalog_entry.model_family.value,
            model_task_kind=trained_model_context.model_task_kind or catalog_entry.model_task_kind.value,
            model_display_name=model_display_name,
            display_name=model_display_name,
            saved_name=build_saved_name(
                trained_model_context.run_name,
                model_display_name,
                row.created_at,
            ),
            artifact_file_name=artifact_file_name_from_path(str(canonical_path)),
            save_note=build_save_note(model_display_name),
            training_operation=row.task_type.value,
            source_run_name=trained_model_context.run_name,
            source_dataset_name=trained_model_context.dataset_name,
            source_dataset_file_name=trained_model_context.dataset_file_name,
            train_role_bindings=[dict(binding) for binding in trained_model_context.train_role_bindings],
            apply_role_schema=dict(trained_model_context.apply_role_schema),
            result_contract=dict(trained_model_context.result_contract),
            dataset_row_count=trained_model_context.dataset_row_count,
            dataset_column_count=trained_model_context.dataset_column_count,
            preview_columns=list(trained_model_context.preview_columns),
            preview_rows=[list(row_values) for row_values in trained_model_context.preview_rows],
            best_params=dict(result.best_params),
            tuning_grid={
                str(key): list(values)
                for key, values in request.hyperparameter_tuning.param_grid.items()
            },
            evaluation_model_training_scope="holdout_train_split" if result.final_model_artifact_path else None,
            apply_model_training_scope="all_eligible_rows" if result.final_model_artifact_path else None,
        )
        trained_model = self._trained_models.create(
            session,
            TrainedModelRow(
                dataset_id=row.dataset_id,
                ml_task_id=row.id,
                model_key=result.model_key,
                problem_kind=catalog_entry.problem_kind,
                artifact_path=str(canonical_path),
                metadata_payload=metadata.model_dump(mode="json"),
            ),
        )
        payload = result.model_dump(mode="json")
        payload["trained_model_id"] = trained_model.id
        payload["canonical_model_artifact_path"] = str(canonical_path)
        payload["evaluation_model_artifact_path"] = str(evaluation_model_path)
        artifacts = [
            MLTaskArtifactInput(artifact_kind=MLTaskArtifactKind.MODEL, absolute_path=str(canonical_path)),
        ]
        if holdout_path is not None:
            artifacts.append(
                MLTaskArtifactInput(
                    artifact_kind=MLTaskArtifactKind.HOLDOUT_DATA,
                    absolute_path=str(holdout_path),
                    ready_to_open=False,
                )
            )
        if export_path is not None:
            artifacts.append(
                MLTaskArtifactInput(
                    artifact_kind=MLTaskArtifactKind.EXPORT_FILE,
                    absolute_path=str(export_path),
                )
            )
        return payload, artifacts

    def _finalize_evaluate_task(self, row: MLTaskRow) -> tuple[dict[str, Any], list[MLTaskArtifactInput]]:
        result = EvaluateTaskResult.model_validate_json(
            task_result_path(self._paths, row.id).read_text(encoding="utf-8")
        )
        if result.error_summary:
            raise ValidationError(result.error_summary)
        return result.model_dump(mode="json"), []

    def _finalize_apply_task(
        self,
        session: Any,
        row: MLTaskRow,
    ) -> tuple[dict[str, Any], list[MLTaskArtifactInput]]:
        result = ApplyTaskResult.model_validate_json(
            task_result_path(self._paths, row.id).read_text(encoding="utf-8")
        )
        if result.error_summary:
            raise ValidationError(result.error_summary)

        output_path = Path(result.output_file_path)
        self._require_existing_path(output_path)
        canonical_path = self._copy_canonical_apply_output(row, output_path)
        dataset = self._datasets.get(session, row.dataset_id) if row.dataset_id is not None else None
        if dataset is None:
            raise NotFoundError(f"Dataset '{row.dataset_id}' was not found.")
        result_dataset_id = uuid4().hex
        result_dataset_path = self._materialize_apply_result_dataset(
            source_csv_path=canonical_path,
            dataset_id=result_dataset_id,
        )
        dataset_row = DatasetRow(
            id=result_dataset_id,
            project_id=row.project_id,
            name=f"{dataset.name} apply results",
            source_path=str(result_dataset_path),
            source_format=DatasetSourceFormat.PARQUET,
            copied_from=None,
            copied_at=None,
            derived_from_dataset_id=row.dataset_id,
            ml_task_id=row.id,
        )
        self._datasets.create(session, dataset_row)
        payload = result.model_dump(mode="json")
        payload["canonical_output_path"] = str(canonical_path)
        payload["result_dataset_id"] = dataset_row.id
        payload["row_count"] = result.summary.row_count
        payload["input_file_count"] = result.summary.input_file_count
        payload["prediction_column_name"] = result.summary.prediction_column_name
        artifacts = [
            MLTaskArtifactInput(
                artifact_kind=MLTaskArtifactKind.APPLY_RESULT,
                absolute_path=str(canonical_path),
                ready_to_open=True,
            )
        ]
        return payload, artifacts

    def _materialize_apply_result_dataset(self, *, source_csv_path: Path, dataset_id: str) -> Path:
        output_dir = self._paths.state / "datasets" / "derived"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{dataset_id}.parquet"
        duckdb.connect(database=":memory:").execute(
            "COPY (SELECT * FROM read_csv_auto("
            f"{self._sql_string(str(source_csv_path))})) "
            f"TO {self._sql_string(str(output_path))} (FORMAT PARQUET)"
        )
        return output_path

    def _sql_string(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _finalize_failure(self, ml_task_id: str, return_code: int) -> MLTaskRow:
        result_path = task_result_path(self._paths, ml_task_id)
        error_summary = f"Worker process exited with code {return_code}."
        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(payload.get("error_summary"), str) and payload["error_summary"].strip():
                    error_summary = payload["error_summary"].strip()
            except json.JSONDecodeError:
                pass
        return self.fail_ml_task(FailMLTaskInput(ml_task_id=ml_task_id, error_summary=error_summary))

    def _complete_row(
        self,
        session: Any,
        row: MLTaskRow,
        result_payload: Mapping[str, Any],
        artifacts: list[MLTaskArtifactInput],
    ) -> MLTaskRow:
        persisted_artifacts: list[MLTaskArtifactRow] = []
        for artifact in artifacts:
            artifact_path = Path(artifact.absolute_path)
            self._require_existing_path(artifact_path)
            persisted_artifacts.append(
                MLTaskArtifactRow(
                    ml_task_id=row.id,
                    artifact_kind=artifact.artifact_kind,
                    absolute_path=str(artifact_path),
                    ready_to_open=artifact.ready_to_open,
                    created_at=_utc_now(),
                )
            )

        return self._ml_tasks.complete(
            session,
            row.id,
            dict(result_payload),
            _utc_now(),
            persisted_artifacts,
        )

    def _task_attributes(self, row: MLTaskRow) -> dict[str, Any]:
        return {
            "ml.task.type": row.task_type.value,
            "ml.task.status": row.status.value,
        }

    def _record_task(self, row: MLTaskRow, *, error_type: str | None = None) -> None:
        attributes = self._task_attributes(row)
        if error_type is not None:
            attributes["error.type"] = error_type
        record_counter("xenix.ml.task.count", attributes=attributes)

    def _record_task_duration(self, row: MLTaskRow, started_at: float) -> None:
        record_histogram(
            "xenix.ml.task.duration",
            (perf_counter() - started_at) * 1000,
            attributes=self._task_attributes(row),
            unit="ms",
        )

    def _copy_canonical_model(
        self,
        row: MLTaskRow,
        artifact_file_name: str,
        source_path: Path,
    ) -> Path:
        if row.dataset_id is not None:
            destination_dir = dataset_model_dir(self._paths, row.dataset_id)
        else:
            destination_dir = task_models_dir(self._paths, row.id)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / artifact_file_name
        shutil.copy2(source_path, destination_path)
        return destination_path

    def _copy_canonical_apply_output(
        self,
        row: MLTaskRow,
        source_path: Path,
    ) -> Path:
        if row.dataset_id is not None:
            destination_dir = dataset_apply_dir(self._paths, row.dataset_id)
        else:
            destination_dir = task_output_dir(self._paths, row.id)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / f"{row.id}-apply-results.csv"
        shutil.copy2(source_path, destination_path)
        return destination_path

    def _resolve_trained_model_context(
        self,
        session: Any,
        row: MLTaskRow,
        request_context: TrainedModelContextPayload | None,
    ) -> TrainedModelContextPayload:
        if request_context is not None:
            return request_context
        dataset = self._datasets.get(session, row.dataset_id) if row.dataset_id is not None else None
        dataset_name = dataset.name if dataset is not None else ""
        dataset_file_name = Path(dataset.source_path).name if dataset is not None else ""
        context_name = dataset_name or row.id
        return TrainedModelContextPayload(
            run_name=context_name,
            dataset_name=dataset_name,
            dataset_file_name=dataset_file_name,
            train_role_bindings=[],
            apply_role_schema={},
            result_contract={},
            dataset_row_count=0,
            dataset_column_count=0,
            preview_columns=[],
            preview_rows=[],
        )

    def _notify_callbacks(self, task: MLTaskRow) -> None:
        for callback in list(self._callbacks):
            try:
                callback(task)
            except Exception:
                continue

    def _require_existing_path(self, path: Path) -> None:
        if not path.exists():
            raise ValidationError(f"ML task artifact '{path}' does not exist.")

    def _require_transition(self, current: MLTaskStatus, target: MLTaskStatus) -> None:
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidStateTransitionError(
                f"ML task transition from '{current.value}' to '{target.value}' is not allowed."
            )

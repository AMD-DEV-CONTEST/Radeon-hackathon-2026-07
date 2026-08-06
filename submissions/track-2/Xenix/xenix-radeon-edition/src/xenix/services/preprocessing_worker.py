from __future__ import annotations

import json
import shutil
import traceback
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from ..config import AppPaths
from ..exceptions import ValidationError


class PreprocessingWorkerRunner(Protocol):
    def run(self, operation: str, payload: dict[str, Any], *, paths: AppPaths) -> dict[str, Any]:
        """Run one preprocessing operation and return a JSON-serializable payload."""


class LocalPreprocessingWorkerRunner:
    def run(self, operation: str, payload: dict[str, Any], *, paths: AppPaths) -> dict[str, Any]:
        task_dir = paths.temp / "preprocessing-worker" / uuid4().hex
        task_dir.mkdir(parents=True, exist_ok=True)
        request_path = task_dir / "request.json"
        result_path = task_dir / "result.json"
        request_path.write_text(
            json.dumps(
                {
                    "operation": operation,
                    "payload": payload,
                    "paths": _app_paths_payload(paths),
                },
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        context = get_context("spawn")
        process = context.Process(target=run_preprocessing_worker_task, args=(str(task_dir),))
        process.start()
        while process.is_alive():
            process.join(timeout=0.1)

        try:
            if not result_path.exists():
                raise RuntimeError(
                    f"Preprocessing worker exited without a result file. Exit code: {process.exitcode}."
                )
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if result.get("ok") is True:
                worker_result = result.get("result")
                return worker_result if isinstance(worker_result, dict) else {}
            raise _worker_exception(result)
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)


class InlinePreprocessingWorkerRunner:
    def run(self, operation: str, payload: dict[str, Any], *, paths: AppPaths) -> dict[str, Any]:
        return execute_preprocessing_worker_operation(operation, payload, paths)


def run_preprocessing_worker_task(task_dir: str) -> None:
    task_path = Path(task_dir)
    result_path = task_path / "result.json"
    try:
        request = json.loads((task_path / "request.json").read_text(encoding="utf-8"))
        paths = _app_paths_from_payload(request["paths"])
        result = execute_preprocessing_worker_operation(
            str(request["operation"]),
            dict(request.get("payload") or {}),
            paths,
        )
        result_path.write_text(
            json.dumps({"ok": True, "result": result}, ensure_ascii=False),
            encoding="utf-8",
        )
    except BaseException as exc:  # pragma: no cover - subprocess safety net
        result_path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "error_code": getattr(exc, "error_code", None),
                    "error_details": getattr(exc, "error_details", {}),
                    "repair_hints": getattr(exc, "repair_hints", []),
                    "retryable": getattr(exc, "retryable", None),
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )


def execute_preprocessing_worker_operation(
    operation: str,
    payload: dict[str, Any],
    paths: AppPaths,
) -> dict[str, Any]:
    if operation == "data.transform":
        from .data_transform import DataQueryTransformService, DataTransformInput

        input_data = DataTransformInput.model_validate(payload.get("input"))
        result = DataQueryTransformService(paths, worker_runner=InlinePreprocessingWorkerRunner())._transform_in_process(
            input_data
        )
        return result.model_dump(mode="json")

    if operation == "data.clean":
        from .data_cleaning import CleanDatasetInput, DataCleaningService

        input_data = CleanDatasetInput.model_validate(payload.get("input"))
        result = DataCleaningService(paths, worker_runner=InlinePreprocessingWorkerRunner())._clean_dataset_in_process(
            input_data
        )
        return result.model_dump(mode="json")

    if operation == "data.register_generated_dataset":
        return _register_generated_dataset(payload, paths)

    raise ValidationError(f"Unsupported preprocessing worker operation: {operation}.")


def _register_generated_dataset(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    from .artifact_service import ArtifactService
    from .dataset_export_service import DatasetExportService
    from .dataset_inspection import InspectDatasetInput
    from .dataset_service import DatasetService, RegisterDatasetInput
    from .storage import StorageBootstrapService

    output_path = Path(str(payload.get("output_path") or "")).expanduser()
    if not output_path.is_absolute():
        raise ValidationError("Generated dataset output path must be absolute.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValidationError("Generated dataset name cannot be empty.")

    context = StorageBootstrapService().initialize(paths)
    dataset_service = DatasetService(context.session_factory, paths)
    artifact_service = ArtifactService(context.session_factory)
    dataset_export_service = DatasetExportService(
        paths=paths,
        dataset_service=dataset_service,
        artifact_service=artifact_service,
    )

    inspection = dataset_service.inspect_source_file(
        InspectDatasetInput(source_path=str(output_path.resolve()))
    )
    inspection_payload = inspection.model_dump(mode="json", exclude={"source_path"})
    dataset = dataset_service.register_dataset(
        RegisterDatasetInput(
            source_path=str(output_path.resolve()),
            name=name,
            derived_from_dataset_id=payload.get("derived_from_dataset_id"),
        )
    )
    try:
        export_artifact = dataset_export_service.materialize_dataset_export_artifact(
            dataset.id,
            metadata_payload=payload.get("metadata_payload") if isinstance(payload.get("metadata_payload"), dict) else None,
        )
    except Exception:
        try:
            dataset_service.discard_unreferenced_dataset(dataset.id)
        except Exception:
            pass
        raise

    return {
        "dataset_id": dataset.id,
        "artifact_id": export_artifact.artifact_id,
        "summary": str(payload.get("summary") or ""),
        "inspection": inspection_payload,
    }


def _app_paths_payload(paths: AppPaths) -> dict[str, str]:
    return {
        "home": str(paths.home),
        "config": str(paths.config),
        "logs": str(paths.logs),
        "cache": str(paths.cache),
        "state": str(paths.state),
        "temp": str(paths.temp),
        "artifacts": str(paths.artifacts),
        "resources": str(paths.resources),
    }


def _app_paths_from_payload(payload: dict[str, str]) -> AppPaths:
    return AppPaths(
        home=Path(payload["home"]),
        config=Path(payload["config"]),
        logs=Path(payload["logs"]),
        cache=Path(payload["cache"]),
        state=Path(payload["state"]),
        temp=Path(payload["temp"]),
        artifacts=Path(payload["artifacts"]),
        resources=Path(payload["resources"]),
    )


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _worker_exception(result: dict[str, Any]) -> Exception:
    message = str(result.get("message") or "Preprocessing worker failed.")
    if result.get("error_type") == "ValidationError":
        return ValidationError(
            message,
            error_code=result.get("error_code") if isinstance(result.get("error_code"), str) else None,
            error_details=result.get("error_details") if isinstance(result.get("error_details"), dict) else None,
            repair_hints=result.get("repair_hints") if isinstance(result.get("repair_hints"), list) else None,
            retryable=result.get("retryable") if isinstance(result.get("retryable"), bool) else None,
        )
    details = result.get("traceback")
    if isinstance(details, str) and details.strip():
        return RuntimeError(f"{message}\n{details}")
    return RuntimeError(message)

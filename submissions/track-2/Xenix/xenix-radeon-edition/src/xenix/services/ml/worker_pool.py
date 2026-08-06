from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from ...observability import record_counter, record_histogram, start_span
from .contracts import TaskLogEntry
from .execution import LocalMLWorkerRunner, SshMLWorkerRunner
from .worker_settings import (
    MLWorkerConfig,
    MLWorkerKind,
    MLWorkerSettings,
    MLWorkerSettingsService,
    MLWorkerSetupState,
    MLWorkerValidationStatus,
)


class MLWorkerPool:
    max_dispatch_threads = 32

    def __init__(
        self,
        settings_service: MLWorkerSettingsService,
        *,
        local_runner: LocalMLWorkerRunner | None = None,
    ) -> None:
        self._settings_service = settings_service
        self._local_runner = local_runner or LocalMLWorkerRunner()
        self._active_counts: dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def max_concurrent_tasks(self) -> int:
        settings = self._settings_service.load()
        enabled_workers = self._enabled_workers(settings)
        if not enabled_workers:
            return 1
        return max(1, min(settings.pool.max_concurrent_tasks, sum(worker.max_concurrent_tasks for worker in enabled_workers)))

    def run(
        self,
        entrypoint: Callable[[str], None],
        task_dir: Path,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> int:
        dispatch_started_at = time.perf_counter()
        worker: MLWorkerConfig | None = None
        try:
            worker = self._acquire_worker()
            self._append_log(task_dir, "INFO", f"ML worker selected: {worker.display_name} ({worker.kind.value}).")
            attributes = {"ml.worker.kind": worker.kind.value}
            with start_span("ml.worker_dispatch", attributes):
                if worker.kind is MLWorkerKind.LOCAL:
                    return_code = self._local_runner.run(entrypoint, task_dir, cancel_requested=cancel_requested)
                elif worker.kind is MLWorkerKind.SSH:
                    return_code = SshMLWorkerRunner(worker).run(entrypoint, task_dir, cancel_requested=cancel_requested)
                else:
                    self._append_log(task_dir, "ERROR", f"Unsupported ML worker kind '{worker.kind.value}'.")
                    return_code = 1
            status = "succeeded" if return_code == 0 else "failed"
            record_counter("xenix.ml.worker_dispatch.count", attributes={**attributes, "status": status})
            record_histogram(
                "xenix.ml.worker_dispatch.duration",
                (time.perf_counter() - dispatch_started_at) * 1000,
                attributes={**attributes, "status": status},
                unit="ms",
            )
            return return_code
        finally:
            if worker is not None:
                self._release_worker(worker.id)

    def _acquire_worker(self) -> MLWorkerConfig:
        while True:
            settings = self._settings_service.load()
            with self._lock:
                if not self._enabled_workers(settings):
                    raise RuntimeError("No ML workers are enabled and ready.")
                worker = self._select_worker_locked(settings)
                if worker is not None:
                    self._active_counts[worker.id] = self._active_counts.get(worker.id, 0) + 1
                    return worker
            time.sleep(0.1)

    def _release_worker(self, worker_id: str) -> None:
        with self._lock:
            count = self._active_counts.get(worker_id, 0)
            if count <= 1:
                self._active_counts.pop(worker_id, None)
            else:
                self._active_counts[worker_id] = count - 1

    def _select_worker_locked(self, settings: MLWorkerSettings) -> MLWorkerConfig | None:
        if sum(self._active_counts.values()) >= settings.pool.max_concurrent_tasks:
            return None
        candidates = [
            worker
            for worker in self._enabled_workers(settings)
            if self._active_counts.get(worker.id, 0) < worker.max_concurrent_tasks
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda worker: (
                self._active_counts.get(worker.id, 0) / worker.max_concurrent_tasks,
                -worker.weight,
                0 if worker.kind is MLWorkerKind.SSH else 1,
                worker.id,
            ),
        )[0]

    def _enabled_workers(self, settings: MLWorkerSettings) -> list[MLWorkerConfig]:
        if not settings.pool.enabled:
            return [worker for worker in settings.workers if worker.kind is MLWorkerKind.LOCAL]
        workers: list[MLWorkerConfig] = []
        for worker in settings.workers:
            if not worker.enabled:
                continue
            if worker.kind is MLWorkerKind.LOCAL and not settings.pool.local_worker_enabled:
                continue
            if worker.kind is MLWorkerKind.SSH and not _ssh_worker_ready(worker):
                continue
            workers.append(worker)
        if workers:
            return workers
        return []

    def _append_log(self, task_dir: Path, level: str, message: str) -> None:
        path = task_dir / "logs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(TaskLogEntry(level=level, message=message).model_dump_json())
            handle.write("\n")


def _ssh_worker_ready(worker: MLWorkerConfig) -> bool:
    return (
        worker.setup_state is MLWorkerSetupState.READY
        and worker.last_validation.status is MLWorkerValidationStatus.SUCCEEDED
    )

"""Lifecycle manager for one isolated process per native model package replica."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from services.database_registry import _get_registry_conn, init_registry
from services.model_packages.registry import get_installation, get_manifest
from services.model_packages.verifier import (
    package_target,
    verification_record_is_current,
)
from services.model_runtime.contracts import (
    AdmissionRequest,
    AdmissionStatus,
    LeaseMode,
    WorkerLoadRequest,
    utc_now,
)
from services.model_runtime.scheduler import ResourceScheduler, get_resource_scheduler
from services.model_runtime.worker_protocol import MAX_MESSAGE_BYTES, PROTOCOL_VERSION


ACTIVE_WORKER_STATES = {"COLD", "STARTING", "READY", "BUSY", "DRAINING"}
ALLOWED_OPERATIONS = {"embedding", "vision", "image", "audio", "test"}
REGISTERED_ADAPTERS = {
    "aetherdb_onnx_embedding",
    "aetherdb_torch_bge_vl",
    "aetherdb_diffusers_kandinsky",
    "aetherdb_torch_kokoro",
    "test_worker",
}

log = logging.getLogger(__name__)


class WorkerManagerError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.details = details or {}


def _safe_worker_environment(project_root: Path) -> dict[str, str]:
    allowed_exact = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "VIRTUAL_ENV",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "HIP_PATH",
        "ROCM_PATH",
        "CUDA_PATH",
        "CUDA_HOME",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed_exact
    }
    environment.update(
        {
            "PYTHONPATH": str(project_root),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "AETHERDB_NATIVE_WORKER": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "DIFFUSERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
    )
    return environment


def _resolve_worker_python(runtime_adapter: str) -> Path:
    token = re.sub(r"[^A-Za-z0-9]+", "_", runtime_adapter).upper()
    configured = os.environ.get(f"AETHERDB_WORKER_PYTHON_{token}", "").strip()
    candidate = Path(configured).expanduser() if configured else Path(sys.executable)
    candidate = Path(os.path.abspath(candidate))
    if not candidate.exists():
        raise WorkerManagerError(
            "WORKER_PYTHON_MISSING",
            "Configured Worker Python runtime does not exist",
        )
    if not candidate.is_file() or not candidate.name.lower().startswith("python"):
        raise WorkerManagerError(
            "WORKER_PYTHON_INVALID",
            "Configured Worker runtime must be a Python executable",
        )
    # Preserve virtual-environment launchers on POSIX. Resolving their symlink
    # would invoke the base interpreter without the environment's site packages.
    return candidate


class WorkerClient:
    def __init__(
        self,
        command: list[str],
        *,
        worker_id: str,
        cwd: Path,
        environment: dict[str, str],
        on_event: Callable[[dict], None],
        on_exit: Callable[[int | None], None],
    ):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.worker_id = worker_id
        self._on_event = on_event
        self._on_exit = on_exit
        self._pending: dict[str, queue.Queue] = {}
        self._pending_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._stderr: list[str] = []
        self.process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            creationflags=creationflags,
        )
        self._reader = threading.Thread(
            target=self._read_stdout,
            daemon=True,
            name=f"model-worker-reader-{worker_id[:8]}",
        )
        self._stderr_reader = threading.Thread(
            target=self._read_stderr,
            daemon=True,
            name=f"model-worker-stderr-{worker_id[:8]}",
        )
        self._reader.start()
        self._stderr_reader.start()

    @property
    def pid(self) -> int:
        return self.process.pid

    def alive(self) -> bool:
        return self.process.poll() is None

    def _read_stderr(self):
        if self.process.stderr is None:
            return
        for line in self.process.stderr:
            cleaned = line.strip()[:500]
            if cleaned:
                self._stderr.append(cleaned)
                self._stderr[:] = self._stderr[-20:]

    def _read_stdout(self):
        if self.process.stdout is None:
            return
        for line in self.process.stdout:
            if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if payload.get("protocol_version") != PROTOCOL_VERSION:
                continue
            request_id = payload.get("request_id")
            if payload.get("event") == "heartbeat":
                self._on_event(payload)
                continue
            with self._pending_lock:
                response_queue = self._pending.get(request_id)
            if response_queue is not None:
                response_queue.put(payload)

        exit_code = self.process.poll()
        failure = {
            "protocol_version": PROTOCOL_VERSION,
            "event": "error",
            "ok": False,
            "error": {
                "code": "WORKER_PROCESS_EXITED",
                "message": "Worker process exited before completing the operation",
            },
        }
        # Persist crash state and release leases before waking request callers;
        # otherwise the caller could transiently restore a dead Worker to READY.
        self._on_exit(exit_code)
        with self._pending_lock:
            for response_queue in self._pending.values():
                try:
                    response_queue.put_nowait(failure)
                except queue.Full:
                    pass

    def request(
        self,
        command: str,
        payload: dict | None = None,
        *,
        timeout: float = 30,
    ) -> dict:
        if not self.alive() or self.process.stdin is None:
            raise WorkerManagerError("WORKER_NOT_RUNNING", "Worker process is not running")
        request_id = uuid.uuid4().hex
        response_queue: queue.Queue = queue.Queue(maxsize=1)
        message = {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "command": command,
            "payload": payload or {},
        }
        encoded = json.dumps(message, ensure_ascii=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise WorkerManagerError("IPC_MESSAGE_TOO_LARGE", "Worker request is too large")
        with self._pending_lock:
            self._pending[request_id] = response_queue
        try:
            with self._write_lock:
                self.process.stdin.write(encoded + "\n")
                self.process.stdin.flush()
            try:
                response = response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise WorkerManagerError(
                    "WORKER_TIMEOUT",
                    "Worker did not complete the operation before the timeout",
                ) from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if not response.get("ok"):
            error = response.get("error") or {}
            raise WorkerManagerError(
                str(error.get("code") or "WORKER_ERROR"),
                str(error.get("message") or "Worker operation failed"),
            )
        return response

    def terminate(self, timeout: float = 5) -> int | None:
        if self.alive():
            try:
                self.request("shutdown", timeout=min(timeout, 3))
            except WorkerManagerError:
                pass
        if self.process.stdin is not None and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            exit_code = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                exit_code = self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                exit_code = self.process.wait(timeout=3)
        if threading.current_thread() is not self._reader:
            self._reader.join(timeout=3)
        if threading.current_thread() is not self._stderr_reader:
            self._stderr_reader.join(timeout=3)
        return exit_code


class WorkerManager:
    def __init__(
        self,
        *,
        scheduler: ResourceScheduler | None = None,
        monitor_interval_seconds: float = 2.0,
    ):
        self.scheduler = scheduler or get_resource_scheduler()
        self._clients: dict[str, WorkerClient] = {}
        self._active_jobs: dict[str, str] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._monitor_interval = max(0.2, monitor_interval_seconds)
        init_registry()
        self._recover_orphans()
        self._monitor = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="model-worker-manager",
        )
        self._monitor.start()

    @staticmethod
    def _row(worker_id: str) -> dict | None:
        conn = _get_registry_conn()
        try:
            row = conn.execute(
                "SELECT * FROM model_worker_instances WHERE id=?", (worker_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def _update_worker(worker_id: str, **updates) -> dict:
        allowed = {
            "state",
            "process_id",
            "requested_backend",
            "effective_backend",
            "device_id",
            "device_fingerprint",
            "lease_id",
            "started_at",
            "loaded_at",
            "last_used_at",
            "last_heartbeat_at",
            "stopped_at",
            "exit_code",
            "restart_count",
            "error_code",
            "error_message",
            "metrics_json",
        }
        clean = {key: value for key, value in updates.items() if key in allowed}
        if not clean:
            row = WorkerManager._row(worker_id)
            if row is None:
                raise KeyError(worker_id)
            return row
        columns = ",".join(f"{key}=?" for key in clean)
        conn = _get_registry_conn()
        try:
            cursor = conn.execute(
                f"UPDATE model_worker_instances SET {columns},"
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (*clean.values(), worker_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise KeyError(worker_id)
        finally:
            conn.close()
        return WorkerManager._row(worker_id) or {}

    def _recover_orphans(self):
        now = utc_now()
        conn = _get_registry_conn()
        try:
            rows = conn.execute(
                "SELECT id FROM model_worker_instances WHERE state IN "
                "('COLD','STARTING','READY','BUSY','DRAINING')"
            ).fetchall()
            worker_ids = [row["id"] for row in rows]
            if worker_ids:
                conn.executemany(
                    "UPDATE model_worker_instances SET state='FAILED',process_id=NULL,"
                    "lease_id=NULL,stopped_at=?,error_code='PROCESS_LOST',"
                    "error_message='Worker process did not survive API restart',"
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    [(now, worker_id) for worker_id in worker_ids],
                )
                conn.executemany(
                    "UPDATE model_resource_leases SET status='released',released_at=?,"
                    "release_reason='PROCESS_LOST' WHERE worker_id=? "
                    "AND status IN ('active','releasing')",
                    [(now, worker_id) for worker_id in worker_ids],
                )
                conn.executemany(
                    "UPDATE model_runtime_jobs SET status='failed',completed_at=?,"
                    "error_code='PROCESS_LOST',"
                    "error_message='Worker process did not survive API restart',"
                    "updated_at=CURRENT_TIMESTAMP WHERE worker_id=? "
                    "AND status IN ('queued','running','cancelling')",
                    [(now, worker_id) for worker_id in worker_ids],
                )
                conn.commit()
        finally:
            conn.close()

    def list_workers(self) -> list[dict]:
        conn = _get_registry_conn()
        try:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM model_worker_instances "
                    "ORDER BY created_at DESC,id DESC"
                )
            ]
        finally:
            conn.close()

    def get_worker(self, worker_id: str) -> dict | None:
        return self._row(worker_id)

    def list_jobs(self, *, worker_id: str | None = None, limit: int = 100) -> list[dict]:
        conn = _get_registry_conn()
        try:
            if worker_id:
                rows = conn.execute(
                    "SELECT * FROM model_runtime_jobs WHERE worker_id=? "
                    "ORDER BY created_at DESC,id DESC LIMIT ?",
                    (worker_id, max(1, min(limit, 500))),
                )
            else:
                rows = conn.execute(
                    "SELECT * FROM model_runtime_jobs "
                    "ORDER BY created_at DESC,id DESC LIMIT ?",
                    (max(1, min(limit, 500)),),
                )
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def get_job(job_id: str) -> dict | None:
        conn = _get_registry_conn()
        try:
            row = conn.execute(
                "SELECT * FROM model_runtime_jobs WHERE id=?", (job_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def _default_residency(manifest) -> str:
        if manifest.runtime_policy is not None:
            return manifest.runtime_policy.residency_mode
        return {
            "always": "PINNED",
            "idle_unload": "PREFERRED",
            "shared": "PREFERRED",
            "exclusive": "ON_DEMAND",
        }[manifest.residency_policy_default]

    def start_worker(
        self,
        package_id: str,
        *,
        replica_id: str = "default",
        residency_mode: str | None = None,
    ) -> dict:
        with self._lock:
            for row in self.list_workers():
                if (
                    row["package_id"] == package_id
                    and row["replica_id"] == replica_id
                    and row["state"] in ACTIVE_WORKER_STATES
                ):
                    client = self._clients.get(row["id"])
                    if client and client.alive():
                        if (
                            residency_mode is not None
                            and row["residency_mode"] != residency_mode
                        ):
                            row = self.set_worker_residency(
                                row["id"],
                                residency_mode,
                            )
                        return row
            installation = get_installation(package_id)
            if installation is None or installation["status"] != "installed":
                raise WorkerManagerError(
                    "PACKAGE_NOT_INSTALLED",
                    "Native model package must be installed and verified",
                )
            manifest = get_manifest(package_id, sync=False)
            if manifest.runtime_adapter not in REGISTERED_ADAPTERS:
                raise WorkerManagerError(
                    "UNSUPPORTED_ADAPTER",
                    "Package runtime adapter is not registered by AetherDB",
                )
            if (
                manifest.runtime_adapter == "test_worker"
                and os.environ.get("AETHERDB_ENV", "").lower() not in {"test", "testing"}
            ):
                raise WorkerManagerError(
                    "TEST_ADAPTER_DISABLED",
                    "Test Worker adapters are disabled outside test environments",
                )
            model_root, _ = package_target(manifest)
            if not verification_record_is_current(manifest, model_root):
                raise WorkerManagerError(
                    "PACKAGE_NOT_VERIFIED",
                    "Native model package integrity record is not current",
                )
            residency = residency_mode or self._default_residency(manifest)
            if residency not in {"PINNED", "PREFERRED", "ON_DEMAND"}:
                raise WorkerManagerError("INVALID_RESIDENCY", "Invalid Worker residency mode")
            python_runtime = _resolve_worker_python(manifest.runtime_adapter)
            worker_id = uuid.uuid4().hex
            conn = _get_registry_conn()
            try:
                conn.execute(
                    "INSERT INTO model_worker_instances "
                    "(id,replica_id,package_id,package_version,manifest_digest,"
                    "runtime_adapter,residency_mode,state,python_runtime,"
                    "idle_unload_seconds,started_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        worker_id,
                        replica_id,
                        package_id,
                        manifest.package_version,
                        manifest.digest(),
                        manifest.runtime_adapter,
                        residency,
                        "STARTING",
                        python_runtime.name,
                        (
                            manifest.runtime_policy.idle_unload_seconds
                            if manifest.runtime_policy is not None
                            else 300
                        ),
                        utc_now(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            project_root = Path(__file__).resolve().parents[2]
            command = [
                str(python_runtime),
                "-m",
                "services.model_runtime.worker_process",
                "--worker-id",
                worker_id,
                "--package-id",
                package_id,
                "--package-version",
                manifest.package_version,
                "--manifest-digest",
                manifest.digest(),
                "--runtime-adapter",
                manifest.runtime_adapter,
                "--model-root",
                str(model_root),
            ]
            try:
                client = WorkerClient(
                    command,
                    worker_id=worker_id,
                    cwd=project_root,
                    environment=_safe_worker_environment(project_root),
                    on_event=lambda event: self._on_worker_event(worker_id, event),
                    on_exit=lambda code: self._on_worker_exit(worker_id, code),
                )
                self._clients[worker_id] = client
                client.request("health", timeout=10)
            except Exception as exc:
                self._update_worker(
                    worker_id,
                    state="FAILED",
                    stopped_at=utc_now(),
                    error_code=getattr(exc, "code", "WORKER_START_FAILED"),
                    error_message=getattr(exc, "safe_message", "Worker failed to start"),
                )
                if isinstance(exc, WorkerManagerError):
                    raise
                raise WorkerManagerError(
                    "WORKER_START_FAILED",
                    "Worker failed to start",
                ) from exc
            return self._update_worker(
                worker_id,
                state="COLD",
                process_id=client.pid,
                last_heartbeat_at=utc_now(),
                error_code=None,
                error_message=None,
            )

    def set_worker_residency(self, worker_id: str, residency_mode: str) -> dict:
        if residency_mode not in {"PINNED", "PREFERRED", "ON_DEMAND"}:
            raise WorkerManagerError("INVALID_RESIDENCY", "Invalid Worker residency mode")
        row = self._row(worker_id)
        if row is None:
            raise KeyError(worker_id)
        if row["state"] in {"FAILED", "STOPPED"}:
            raise WorkerManagerError(
                "WORKER_NOT_RUNNING",
                "Stopped or failed Worker residency cannot be changed",
            )
        return self._update_worker(worker_id, residency_mode=residency_mode)

    def _client(self, worker_id: str) -> WorkerClient:
        client = self._clients.get(worker_id)
        if client is None or not client.alive():
            raise WorkerManagerError("WORKER_NOT_RUNNING", "Worker process is not running")
        return client

    def load_worker(
        self,
        worker_id: str,
        request: WorkerLoadRequest,
        *,
        allow_unverified_probe: bool = False,
        timeout: float = 120,
    ) -> dict:
        row = self._row(worker_id)
        if row is None:
            raise KeyError(worker_id)
        if row["state"] in {"READY", "BUSY"}:
            return {"worker": row, "admission": None}
        client = self._client(worker_id)
        snapshot = self.scheduler.capture_snapshot()
        admission_request = AdmissionRequest(
            package_id=row["package_id"],
            task_id=request.task_id,
            requested_backend=request.requested_backend,
            requested_lease_mode=request.requested_lease_mode,
            priority=request.priority,
            competition_mode=request.competition_mode,
        )
        decision = self.scheduler.evaluate(
            admission_request,
            snapshot=snapshot,
            acquire=True,
            worker_id=worker_id,
            allow_unverified_probe=allow_unverified_probe,
        )
        if decision.status != AdmissionStatus.ADMITTED:
            raise WorkerManagerError(
                decision.reason_code,
                decision.message,
                details={"admission": decision.model_dump(mode="json")},
            )
        device = next(
            (item for item in snapshot.devices if item.device_id == decision.device_id),
            None,
        )
        self._update_worker(
            worker_id,
            state="STARTING",
            requested_backend=request.requested_backend,
            effective_backend=decision.effective_backend,
            device_id=decision.device_id,
            device_fingerprint=device.fingerprint if device else None,
            lease_id=decision.lease_id,
            error_code=None,
            error_message=None,
        )
        try:
            response = client.request(
                "load",
                {
                    "operation_id": f"load:{request.task_id}",
                    "backend": decision.effective_backend,
                    "device_id": decision.device_id,
                    "visible_index": device.visible_index if device else None,
                },
                timeout=timeout,
            )
            data = response["data"]
            if data.get("effective_backend") != decision.effective_backend:
                raise WorkerManagerError(
                    "BACKEND_MISMATCH",
                    "Worker effective backend did not match resource admission",
                )
        except Exception as exc:
            if decision.lease_id:
                self.scheduler.release_lease(
                    decision.lease_id,
                    reason="WORKER_LOAD_FAILED",
                )
            self._update_worker(
                worker_id,
                state="FAILED",
                lease_id=None,
                error_code=getattr(exc, "code", "WORKER_LOAD_FAILED"),
                error_message=getattr(exc, "safe_message", "Worker failed to load model"),
            )
            raise
        worker = self._update_worker(
            worker_id,
            state="READY",
            loaded_at=utc_now(),
            last_used_at=utc_now(),
            last_heartbeat_at=utc_now(),
            effective_backend=data.get("effective_backend"),
            error_code=None,
            error_message=None,
        )
        return {
            "worker": worker,
            "admission": decision.model_dump(mode="json"),
            "runtime": data,
        }

    def unload_worker(self, worker_id: str, *, reason: str = "UNLOADED") -> dict:
        row = self._row(worker_id)
        if row is None:
            raise KeyError(worker_id)
        if row["state"] == "COLD":
            return row
        if row["state"] == "BUSY":
            raise WorkerManagerError("WORKER_BUSY", "Busy Worker must be drained first")
        client = self._client(worker_id)
        client.request("unload", {"operation_id": f"unload:{uuid.uuid4().hex}"}, timeout=60)
        if row.get("lease_id"):
            self.scheduler.release_lease(row["lease_id"], reason=reason)
        return self._update_worker(
            worker_id,
            state="COLD",
            lease_id=None,
            device_id=None,
            device_fingerprint=None,
            effective_backend=None,
            loaded_at=None,
        )

    def stop_worker(self, worker_id: str) -> dict:
        row = self._row(worker_id)
        if row is None:
            raise KeyError(worker_id)
        client = self._clients.get(worker_id)
        self._update_worker(worker_id, state="DRAINING")
        exit_code = client.terminate() if client else row.get("exit_code")
        if row.get("lease_id"):
            try:
                self.scheduler.release_lease(row["lease_id"], reason="WORKER_STOPPED")
            except (KeyError, WorkerManagerError):
                pass
        with self._lock:
            self._clients.pop(worker_id, None)
        return self._update_worker(
            worker_id,
            state="STOPPED",
            process_id=None,
            lease_id=None,
            device_id=None,
            device_fingerprint=None,
            stopped_at=utc_now(),
            exit_code=exit_code,
        )

    def probe_worker(
        self,
        worker_id: str,
        *,
        requested_backend: str,
        priority: int = 100,
        keep_loaded: bool = False,
    ) -> dict:
        load = self.load_worker(
            worker_id,
            WorkerLoadRequest(
                task_id=f"runtime-probe:{uuid.uuid4().hex}",
                requested_backend=requested_backend,
                requested_lease_mode=LeaseMode.EXCLUSIVE,
                priority=priority,
                competition_mode=True,
            ),
            allow_unverified_probe=True,
        )
        row = load["worker"]
        client = self._client(worker_id)
        response = client.request(
            "probe",
            {"operation_id": f"probe:{uuid.uuid4().hex}"},
            timeout=120,
        )
        data = response["data"]
        self._update_worker(
            worker_id,
            state="READY",
            last_used_at=utc_now(),
            error_code=None,
            error_message=None,
        )
        if not data.get("verified") or data.get("effective_backend") != row["effective_backend"]:
            raise WorkerManagerError(
                "RUNTIME_PROBE_FAILED",
                "Worker runtime probe did not verify the admitted backend",
            )
        status = {
            "rocm_migraphx": "VERIFIED_ROCM",
            "rocm_pytorch": "VERIFIED_ROCM",
            "cuda": "VERIFIED_CUDA",
            "cpu": "TESTED",
        }[row["effective_backend"]]
        evidence = self.scheduler.record_runtime_evidence(
            package_id=row["package_id"],
            device_fingerprint=row["device_fingerprint"] or "cpu",
            backend=row["effective_backend"],
            verification_status=status,
            probe_ref=f"worker:{worker_id}",
            evidence={
                key: value
                for key, value in data.items()
                if key
                in {
                    "effective_backend",
                    "execution_provider",
                    "dimensions",
                    "batch_items",
                    "normalized",
                    "elapsed_ms",
                    "output_digest",
                    "output_size_bytes",
                    "width",
                    "height",
                    "seed",
                }
            },
        )
        if not keep_loaded:
            self.unload_worker(worker_id, reason="PROBE_COMPLETED")
        return {"worker": self._row(worker_id), "probe": data, "evidence": evidence}

    def execute(
        self,
        package_id: str,
        *,
        task_id: str,
        operation: str,
        payload: dict,
        requested_backend: str = "auto",
        priority: int = 50,
        timeout: float = 180,
        load_timeout: float = 120,
        replica_id: str = "default",
        job_started: Callable[[str], bool | None] | None = None,
    ) -> dict:
        if operation not in ALLOWED_OPERATIONS:
            raise WorkerManagerError("INVALID_OPERATION", "Unsupported Worker operation")
        worker = self.start_worker(package_id, replica_id=replica_id)
        if worker["state"] not in {"READY", "BUSY"}:
            loaded = self.load_worker(
                worker["id"],
                WorkerLoadRequest(
                    task_id=task_id,
                    requested_backend=requested_backend,
                    priority=priority,
                ),
                timeout=load_timeout,
            )
            worker = loaded["worker"]
        job_id = uuid.uuid4().hex
        request_digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        conn = _get_registry_conn()
        try:
            conn.execute(
                "INSERT INTO model_runtime_jobs "
                "(id,worker_id,package_id,task_id,operation,status,request_digest,"
                "requested_backend,effective_backend,device_id,lease_id,priority,started_at) "
                "VALUES (?,?,?,?,?,'running',?,?,?,?,?,?,?)",
                (
                    job_id,
                    worker["id"],
                    package_id,
                    task_id,
                    operation,
                    request_digest,
                    requested_backend,
                    worker["effective_backend"],
                    worker["device_id"],
                    worker["lease_id"],
                    priority,
                    utc_now(),
                ),
            )
            conn.execute(
                "UPDATE model_worker_instances SET state='BUSY',last_used_at=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (utc_now(), worker["id"]),
            )
            conn.commit()
        finally:
            conn.close()
        with self._lock:
            self._active_jobs[job_id] = worker["id"]
        client = self._client(worker["id"])
        try:
            if job_started is not None and job_started(job_id) is False:
                raise WorkerManagerError(
                    "CANCELLED",
                    "Worker operation was cancelled before inference started",
                )
            response = client.request(
                "infer",
                {**payload, "operation_id": job_id},
                timeout=timeout,
            )
            data = response["data"]
            metadata = {
                "keys": sorted(key for key in data if key != "vectors"),
                "effective_backend": data.get("effective_backend"),
                "elapsed_ms": data.get("elapsed_ms"),
                "dimensions": data.get("dimensions"),
                "vector_count": len(data.get("vectors") or []),
                "output_digest": data.get("output_digest"),
                "output_size_bytes": data.get("output_size_bytes"),
                "width": data.get("width"),
                "height": data.get("height"),
                "seed": data.get("seed"),
            }
            conn = _get_registry_conn()
            try:
                conn.execute(
                    "UPDATE model_runtime_jobs SET status='completed',completed_at=?,"
                    "effective_backend=?,result_metadata_json=?,updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (
                        utc_now(),
                        data.get("effective_backend") or worker["effective_backend"],
                        json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                        job_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            self._update_worker(
                worker["id"],
                state="READY",
                last_used_at=utc_now(),
                error_code=None,
                error_message=None,
            )
            return {"job_id": job_id, "result": data}
        except WorkerManagerError as exc:
            status = "cancelled" if exc.code == "CANCELLED" else "failed"
            conn = _get_registry_conn()
            try:
                conn.execute(
                    "UPDATE model_runtime_jobs SET status=?,completed_at=?,error_code=?,"
                    "error_message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (status, utc_now(), exc.code, exc.safe_message, job_id),
                )
                conn.commit()
            finally:
                conn.close()
            current = self._row(worker["id"])
            if current and current["state"] != "FAILED":
                self._update_worker(
                    worker["id"],
                    state="READY",
                    last_used_at=utc_now(),
                    error_code=exc.code,
                    error_message=exc.safe_message,
                )
            raise
        finally:
            with self._lock:
                self._active_jobs.pop(job_id, None)
            current = self._row(worker["id"])
            if current and current["residency_mode"] == "ON_DEMAND" and current["state"] == "READY":
                try:
                    self.unload_worker(worker["id"], reason="ON_DEMAND_COMPLETED")
                except WorkerManagerError:
                    pass

    def cancel_job(self, job_id: str) -> dict:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] not in {"queued", "running", "cancelling"}:
            return job
        conn = _get_registry_conn()
        try:
            conn.execute(
                "UPDATE model_runtime_jobs SET cancel_requested=1,status='cancelling',"
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
            conn.commit()
        finally:
            conn.close()
        client = self._clients.get(job["worker_id"])
        if client and client.alive():
            client.request("cancel", {"operation_id": job_id}, timeout=5)
        return self.get_job(job_id) or {}

    def _on_worker_event(self, worker_id: str, event: dict):
        row = self._row(worker_id)
        if row is None:
            return
        metrics = (event.get("data") or {}).get("metrics") or {}
        state = event.get("state") if event.get("state") in ACTIVE_WORKER_STATES else row["state"]
        try:
            self._update_worker(
                worker_id,
                state=state,
                last_heartbeat_at=utc_now(),
                metrics_json=json.dumps(metrics, ensure_ascii=True, sort_keys=True),
            )
            if row.get("lease_id"):
                self.scheduler.heartbeat_lease(
                    row["lease_id"],
                    actual_vram_mb=metrics.get("actual_vram_mb"),
                    actual_peak_vram_mb=metrics.get("actual_peak_vram_mb"),
                )
        except (KeyError, WorkerManagerError):
            return

    def _on_worker_exit(self, worker_id: str, exit_code: int | None):
        row = self._row(worker_id)
        if row is None:
            return
        intended = row["state"] in {"DRAINING", "STOPPED"}
        if row.get("lease_id"):
            try:
                self.scheduler.release_lease(
                    row["lease_id"],
                    reason="WORKER_STOPPED" if intended else "WORKER_CRASHED",
                )
            except (KeyError, WorkerManagerError):
                pass
        final_state = "STOPPED" if intended and exit_code in {0, None} else "FAILED"
        self._update_worker(
            worker_id,
            state=final_state,
            process_id=None,
            lease_id=None,
            device_id=None,
            device_fingerprint=None,
            stopped_at=utc_now(),
            exit_code=exit_code,
            error_code=None if final_state == "STOPPED" else "WORKER_CRASHED",
            error_message=None
            if final_state == "STOPPED"
            else "Worker process exited unexpectedly",
        )
        conn = _get_registry_conn()
        try:
            conn.execute(
                "UPDATE model_runtime_jobs SET status='failed',completed_at=?,"
                "error_code='WORKER_CRASHED',"
                "error_message='Worker process exited unexpectedly',"
                "updated_at=CURRENT_TIMESTAMP WHERE worker_id=? "
                "AND status IN ('queued','running','cancelling')",
                (utc_now(), worker_id),
            )
            conn.commit()
        finally:
            conn.close()
        with self._lock:
            self._clients.pop(worker_id, None)

    def _monitor_loop(self):
        while not self._stop.wait(self._monitor_interval):
            now = datetime.now(timezone.utc)
            try:
                workers = self.list_workers()
            except sqlite3.OperationalError as exc:
                log.warning("Model worker monitor skipped registry read: %s", exc)
                try:
                    init_registry()
                except Exception:
                    log.exception("Model worker monitor could not initialize registry")
                continue
            for row in workers:
                client = self._clients.get(row["id"])
                if row["state"] in ACTIVE_WORKER_STATES and client and not client.alive():
                    self._on_worker_exit(row["id"], client.process.poll())
                    continue
                if row["state"] != "READY" or row["residency_mode"] != "PREFERRED":
                    continue
                idle_seconds = max(
                    30,
                    int(
                        os.environ.get(
                            "AETHERDB_WORKER_IDLE_UNLOAD_SECONDS",
                            str(row.get("idle_unload_seconds") or 300),
                        )
                    ),
                )
                last_used = row.get("last_used_at")
                if not last_used:
                    continue
                parsed = datetime.fromisoformat(last_used.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if (now - parsed).total_seconds() >= idle_seconds:
                    try:
                        self.unload_worker(row["id"], reason="IDLE_UNLOAD")
                    except (KeyError, WorkerManagerError):
                        pass

    def shutdown(self):
        self._stop.set()
        for worker_id in list(self._clients):
            try:
                self.stop_worker(worker_id)
            except (KeyError, WorkerManagerError):
                client = self._clients.pop(worker_id, None)
                if client:
                    client.terminate()
        if self._monitor.is_alive() and threading.current_thread() is not self._monitor:
            self._monitor.join(timeout=3)


_manager: WorkerManager | None = None
_manager_lock = threading.Lock()


def get_worker_manager() -> WorkerManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = WorkerManager()
        return _manager


def shutdown_worker_manager() -> None:
    global _manager
    with _manager_lock:
        manager = _manager
        _manager = None
    if manager is not None:
        manager.shutdown()

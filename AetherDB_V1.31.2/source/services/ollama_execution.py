"""Persistent Ollama execution coordinated by AetherDB leases and tool policy."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from services.database_registry import _get_registry_conn
from services.model_data_boundary import content_hash
from services.model_reliability import (
    ModelErrorCode,
    ModelExecutionError,
    normalize_model_error,
)
from services.model_runtime.contracts import (
    AdmissionRequest,
    AdmissionStatus,
    ResourceClass,
)
from services.model_runtime.scheduler import (
    ResourceScheduler,
    get_resource_scheduler,
)
from services.model_tools import (
    ToolExecutionContext,
    enabled_tool_specs,
    execute_registered_tool,
)
from services.ollama_observability import runtime_id_for


ACTIVE_EXECUTION_STATUSES = {
    "queued",
    "admitted",
    "running",
    "cancel_requested",
}
TERMINAL_EXECUTION_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "interrupted",
}
MAX_TOOL_ROUNDS = 4
MAX_TOOL_CALLS = 8
MAX_STREAM_LINE_BYTES = 2 * 1024 * 1024
ABSOLUTE_EXECUTION_LIMIT_SECONDS = 30 * 60
DEFAULT_QUEUE_TIMEOUT_SECONDS = 5 * 60


_ACTIVE_RESPONSES: dict[str, Any] = {}
_ACTIVE_RESPONSES_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _task_dict(row) -> dict:
    result = dict(row)
    result["cancel_requested"] = bool(result["cancel_requested"])
    return result


def get_ollama_execution(execution_id: str, *, owner_id: str | None = None) -> dict:
    conn = _get_registry_conn()
    try:
        if owner_id is None:
            row = conn.execute(
                "SELECT * FROM ollama_execution_tasks WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM ollama_execution_tasks "
                "WHERE execution_id=? AND owner_id=?",
                (execution_id, owner_id),
            ).fetchone()
    finally:
        conn.close()
    if not row:
        raise KeyError(execution_id)
    return _task_dict(row)


def list_ollama_executions(
    *,
    owner_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    clauses = []
    params: list[object] = []
    if owner_id is not None:
        clauses.append("owner_id=?")
        params.append(owner_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            f"SELECT * FROM ollama_execution_tasks {where} "
            "ORDER BY created_at DESC,execution_id DESC LIMIT ?",
            (*params, max(1, min(int(limit), 500))),
        ).fetchall()
    finally:
        conn.close()
    return [_task_dict(row) for row in rows]


def list_task_executions(task_id: str, owner_id: str) -> list[dict]:
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ollama_execution_tasks WHERE task_id=? AND owner_id=? "
            "ORDER BY created_at DESC,execution_id DESC",
            (task_id, owner_id),
        ).fetchall()
    finally:
        conn.close()
    return [_task_dict(row) for row in rows]


def _response_close(execution_id: str) -> None:
    with _ACTIVE_RESPONSES_LOCK:
        response = _ACTIVE_RESPONSES.get(execution_id)
    if response is not None:
        try:
            response.close()
        except Exception:
            pass


def cancel_ollama_execution(
    execution_id: str,
    *,
    owner_id: str | None = None,
) -> dict:
    conn = _get_registry_conn()
    try:
        where_owner = "" if owner_id is None else " AND owner_id=?"
        params = (execution_id,) if owner_id is None else (execution_id, owner_id)
        row = conn.execute(
            "SELECT * FROM ollama_execution_tasks WHERE execution_id=?"
            f"{where_owner}",
            params,
        ).fetchone()
        if not row:
            raise KeyError(execution_id)
        if row["status"] in TERMINAL_EXECUTION_STATUSES:
            return _task_dict(row)
        conn.execute(
            "UPDATE ollama_execution_tasks SET cancel_requested=1,"
            "status='cancel_requested',updated_at=?,heartbeat_at=? "
            "WHERE execution_id=?",
            (_now(), _now(), execution_id),
        )
        conn.commit()
    finally:
        conn.close()
    _response_close(execution_id)
    return get_ollama_execution(execution_id, owner_id=owner_id)


def cancel_task_executions(task_id: str, owner_id: str) -> dict:
    tasks = list_task_executions(task_id, owner_id)
    cancellable = [
        item for item in tasks if item["status"] in ACTIVE_EXECUTION_STATUSES
    ]
    for item in cancellable:
        cancel_ollama_execution(item["execution_id"], owner_id=owner_id)
    return {
        "task_id": task_id,
        "cancel_requested_count": len(cancellable),
        "executions": list_task_executions(task_id, owner_id),
    }


def recover_interrupted_ollama_executions(
    scheduler: ResourceScheduler | None = None,
) -> dict:
    scheduler = scheduler or get_resource_scheduler()
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            "SELECT execution_id,task_id,lease_id FROM ollama_execution_tasks "
            "WHERE status IN ('queued','admitted','running','cancel_requested')"
        ).fetchall()
        if rows:
            conn.executemany(
                "UPDATE ollama_execution_tasks SET status='interrupted',"
                "error_code='PROCESS_RESTARTED',updated_at=?,completed_at=? "
                "WHERE execution_id=?",
                [(_now(), _now(), row["execution_id"]) for row in rows],
            )
            conn.commit()
    finally:
        conn.close()
    known_leases = {
        lease["id"]: lease for lease in scheduler.list_leases(active_only=False)
    }
    released = []
    for row in rows:
        if not row["lease_id"]:
            continue
        lease = known_leases.get(row["lease_id"])
        if (
            not lease
            or lease.get("owner_type") != "aetherdb_task"
            or lease.get("task_id") != row["task_id"]
        ):
            continue
        try:
            lease = scheduler.release_lease(
                row["lease_id"],
                reason="OLLAMA_EXECUTION_INTERRUPTED",
            )
            released.append(lease["id"])
        except KeyError:
            continue
    return {
        "interrupted_count": len(rows),
        "released_lease_ids": released,
    }


class RequestsOllamaTransport:
    def open_stream(self, base_url: str, payload: dict):
        import requests

        response = requests.post(
            f"{base_url.rstrip('/')}/api/chat",
            json=payload,
            stream=True,
            timeout=(10, 120),
        )
        response.raise_for_status()
        return response


class OllamaExecutionCoordinator:
    def __init__(
        self,
        *,
        scheduler: ResourceScheduler | None = None,
        transport=None,
        runtime_probe=None,
        queue_timeout_seconds: float = DEFAULT_QUEUE_TIMEOUT_SECONDS,
        absolute_limit_seconds: float = ABSOLUTE_EXECUTION_LIMIT_SECONDS,
        poll_interval_seconds: float = 0.5,
    ):
        self._scheduler = scheduler or get_resource_scheduler()
        self._transport = transport or RequestsOllamaTransport()
        self._runtime_probe = runtime_probe or self._probe_runtime
        self._queue_timeout_seconds = max(0.1, min(queue_timeout_seconds, 30 * 60))
        self._absolute_limit_seconds = max(
            1.0,
            min(absolute_limit_seconds, ABSOLUTE_EXECUTION_LIMIT_SECONDS),
        )
        self._poll_interval_seconds = max(0.05, min(poll_interval_seconds, 5.0))

    @staticmethod
    def _probe_runtime(provider: dict) -> dict:
        from services.ollama_management import get_runtime_status

        return get_runtime_status(provider["id"])

    @staticmethod
    def _create_task(provider: dict, profile: dict, request) -> str:
        execution_id = uuid.uuid4().hex
        runtime_id = runtime_id_for(provider)
        now = _now()
        conn = _get_registry_conn()
        try:
            conn.execute(
                """INSERT INTO ollama_execution_tasks(
                       execution_id,task_id,owner_id,provider_id,model_profile_id,
                       runtime_id,model_name,request_hash,status,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    execution_id,
                    request.task_id,
                    request.owner_id,
                    provider["id"],
                    profile["id"],
                    runtime_id,
                    profile["provider_model_name"],
                    content_hash(
                        {
                            "task_id": request.task_id,
                            "task_type": request.canonical_task_type,
                            "database_id": request.database_id,
                            "book_id": request.book_id,
                            "chapter_id": request.chapter_id,
                            "messages": list(request.messages),
                            "context_task_id": request.context_task_id,
                            "selected_asset_ids": list(request.selected_asset_ids),
                        }
                    ),
                    "queued",
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return execution_id

    @staticmethod
    def _update(execution_id: str, **fields) -> None:
        allowed = {
            "status",
            "lease_id",
            "queue_reason",
            "response_hash",
            "error_code",
            "prompt_tokens",
            "output_tokens",
            "tool_rounds",
            "tool_calls",
            "started_at",
            "heartbeat_at",
            "completed_at",
        }
        clean = {key: value for key, value in fields.items() if key in allowed}
        clean["updated_at"] = _now()
        columns = ",".join(f"{key}=?" for key in clean)
        conn = _get_registry_conn()
        try:
            conn.execute(
                f"UPDATE ollama_execution_tasks SET {columns} WHERE execution_id=?",
                (*clean.values(), execution_id),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _cancel_requested(execution_id: str) -> bool:
        conn = _get_registry_conn()
        try:
            row = conn.execute(
                "SELECT cancel_requested FROM ollama_execution_tasks "
                "WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
        finally:
            conn.close()
        return bool(row and row["cancel_requested"])

    def _admit(
        self,
        execution_id: str,
        provider: dict,
        profile: dict,
        request,
        absolute_deadline: float,
    ) -> dict:
        status = self._runtime_probe(provider)
        if not status.get("running") or not status.get("api_compatible"):
            raise ModelExecutionError(
                ModelErrorCode.LOCAL_SERVICE_NOT_RUNNING,
                "Ollama runtime is unavailable.",
            )
        runtime_id = status.get("runtime_id") or runtime_id_for(provider)
        queue_deadline = min(
            absolute_deadline,
            time.monotonic() + self._queue_timeout_seconds,
        )
        while True:
            if self._cancel_requested(execution_id):
                raise ModelExecutionError(
                    ModelErrorCode.USER_CANCELLED,
                    "Ollama execution was cancelled.",
                )
            decision = self._scheduler.evaluate(
                AdmissionRequest(
                    task_id=request.task_id,
                    resource_class=ResourceClass.REMOTE_RUNTIME,
                    requested_backend="remote",
                    runtime_id=runtime_id,
                    model_id=profile["provider_model_name"],
                    estimated_ram_mb=0,
                ),
                acquire=True,
            )
            if decision.status is AdmissionStatus.ADMITTED:
                self._update(
                    execution_id,
                    status="admitted",
                    lease_id=decision.lease_id,
                    queue_reason=None,
                    heartbeat_at=_now(),
                )
                return decision.model_dump(mode="json")
            if decision.status is not AdmissionStatus.QUEUED:
                raise ModelExecutionError(
                    ModelErrorCode.LOCAL_RESOURCE_INSUFFICIENT,
                    "Ollama resource admission was denied.",
                )
            self._update(
                execution_id,
                status="queued",
                queue_reason=decision.reason_code,
                heartbeat_at=_now(),
            )
            if time.monotonic() >= queue_deadline:
                raise ModelExecutionError(
                    ModelErrorCode.TIMEOUT,
                    "Ollama resource queue timed out.",
                )
            time.sleep(self._poll_interval_seconds)

    def _heartbeat_loop(
        self,
        execution_id: str,
        lease_id: str,
        stop: threading.Event,
    ) -> None:
        while not stop.wait(5.0):
            try:
                self._scheduler.heartbeat_lease(lease_id)
                self._update(execution_id, heartbeat_at=_now())
            except Exception:
                return

    @staticmethod
    def _tool_context(request, profile: dict) -> ToolExecutionContext:
        return ToolExecutionContext(
            task_id=request.task_id,
            model_profile_id=profile["id"],
            database_id=request.database_id,
            book_id=request.book_id,
            chapter_id=request.chapter_id,
            owner_id=request.owner_id,
            context_task_id=request.context_task_id,
            selected_asset_ids=request.selected_asset_ids,
        )

    @staticmethod
    def _tool_call_parts(tool_call: object) -> tuple[str, dict]:
        if not isinstance(tool_call, dict):
            raise ModelExecutionError(
                ModelErrorCode.INVALID_INPUT_FORMAT,
                "Ollama returned an invalid tool call.",
            )
        function = tool_call.get("function")
        if not isinstance(function, dict):
            raise ModelExecutionError(
                ModelErrorCode.INVALID_INPUT_FORMAT,
                "Ollama returned an invalid tool function.",
            )
        name = function.get("name")
        arguments = function.get("arguments", {})
        if not isinstance(name, str) or not name:
            raise ModelExecutionError(
                ModelErrorCode.INVALID_INPUT_FORMAT,
                "Ollama returned a tool call without a name.",
            )
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ModelExecutionError(
                    ModelErrorCode.INVALID_INPUT_FORMAT,
                    "Ollama returned invalid tool arguments.",
                ) from exc
        if not isinstance(arguments, dict):
            raise ModelExecutionError(
                ModelErrorCode.INVALID_INPUT_FORMAT,
                "Ollama tool arguments must be an object.",
            )
        return name, arguments

    def _stream_round(
        self,
        execution_id: str,
        provider: dict,
        payload: dict,
        absolute_deadline: float,
    ) -> dict:
        response = self._transport.open_stream(provider["base_url"], payload)
        with _ACTIVE_RESPONSES_LOCK:
            _ACTIVE_RESPONSES[execution_id] = response
        thinking = ""
        content = ""
        tool_calls = []
        tool_call_hashes = set()
        usage = {"prompt_eval_count": 0, "eval_count": 0}
        done_reason = None
        done_received = False
        try:
            for raw_line in response.iter_lines():
                if self._cancel_requested(execution_id):
                    raise ModelExecutionError(
                        ModelErrorCode.USER_CANCELLED,
                        "Ollama execution was cancelled.",
                    )
                if time.monotonic() >= absolute_deadline:
                    raise ModelExecutionError(
                        ModelErrorCode.TIMEOUT,
                        "Ollama execution exceeded the absolute safety limit.",
                    )
                if not raw_line:
                    continue
                if len(raw_line) > MAX_STREAM_LINE_BYTES:
                    raise ModelExecutionError(
                        ModelErrorCode.STREAM_INTERRUPTED,
                        "Ollama stream frame exceeds the server limit.",
                    )
                try:
                    chunk = json.loads(raw_line)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ModelExecutionError(
                        ModelErrorCode.STREAM_INTERRUPTED,
                        "Ollama returned an invalid stream frame.",
                    ) from exc
                if not isinstance(chunk, dict):
                    raise ModelExecutionError(
                        ModelErrorCode.STREAM_INTERRUPTED,
                        "Ollama returned an invalid stream object.",
                    )
                if chunk.get("error"):
                    raise ModelExecutionError(
                        ModelErrorCode.LOCAL_SERVICE_NOT_RUNNING,
                        "Ollama reported an execution error.",
                    )
                message = chunk.get("message") or {}
                if not isinstance(message, dict):
                    raise ModelExecutionError(
                        ModelErrorCode.STREAM_INTERRUPTED,
                        "Ollama returned an invalid message.",
                    )
                thinking += str(message.get("thinking") or "")
                content += str(message.get("content") or "")
                for tool_call in message.get("tool_calls") or []:
                    fingerprint = content_hash(tool_call)
                    if fingerprint not in tool_call_hashes:
                        tool_call_hashes.add(fingerprint)
                        tool_calls.append(tool_call)
                if chunk.get("done"):
                    done_received = True
                    usage["prompt_eval_count"] += int(
                        chunk.get("prompt_eval_count") or 0
                    )
                    usage["eval_count"] += int(chunk.get("eval_count") or 0)
                    done_reason = chunk.get("done_reason")
                self._update(execution_id, heartbeat_at=_now())
            if self._cancel_requested(execution_id):
                raise ModelExecutionError(
                    ModelErrorCode.USER_CANCELLED,
                    "Ollama execution was cancelled.",
                )
            if not done_received:
                raise ModelExecutionError(
                    ModelErrorCode.STREAM_INTERRUPTED,
                    "Ollama stream ended before a terminal frame.",
                )
        finally:
            with _ACTIVE_RESPONSES_LOCK:
                _ACTIVE_RESPONSES.pop(execution_id, None)
            try:
                response.close()
            except Exception:
                pass
        return {
            "thinking": thinking,
            "content": content,
            "tool_calls": tool_calls,
            "usage": usage,
            "done_reason": done_reason,
        }

    def _run_chat(
        self,
        execution_id: str,
        provider: dict,
        profile: dict,
        request,
        options: dict,
        absolute_deadline: float,
    ) -> dict:
        messages = [dict(message) for message in request.messages]
        tool_specs = (
            enabled_tool_specs(profile["id"])
            if profile.get("supports_tools")
            else []
        )
        tool_context = self._tool_context(request, profile)
        total_usage = {"prompt_eval_count": 0, "eval_count": 0}
        all_thinking = ""
        tool_rounds = 0
        tool_call_count = 0
        final_reason = None
        for _round_index in range(MAX_TOOL_ROUNDS + 1):
            payload = {
                "model": profile["provider_model_name"],
                "messages": messages,
                "stream": True,
            }
            if request.requires_json:
                payload["format"] = "json"
            if options.get("max_tokens"):
                payload["options"] = {"num_predict": int(options["max_tokens"])}
            if tool_specs:
                payload["tools"] = tool_specs
            response = self._stream_round(
                execution_id,
                provider,
                payload,
                absolute_deadline,
            )
            total_usage["prompt_eval_count"] += response["usage"][
                "prompt_eval_count"
            ]
            total_usage["eval_count"] += response["usage"]["eval_count"]
            all_thinking += response["thinking"]
            final_reason = response["done_reason"]
            if not response["tool_calls"]:
                self._update(
                    execution_id,
                    tool_rounds=tool_rounds,
                    tool_calls=tool_call_count,
                )
                return {
                    "content": response["content"],
                    "thinking_content": all_thinking,
                    "usage": total_usage,
                    "finish_reason": final_reason,
                    "warnings": (),
                }
            if tool_rounds >= MAX_TOOL_ROUNDS:
                raise ModelExecutionError(
                    ModelErrorCode.MODEL_UNSUPPORTED_TASK,
                    "Ollama exceeded the controlled tool round limit.",
                )
            tool_rounds += 1
            assistant_message = {
                "role": "assistant",
                "content": response["content"],
                "thinking": response["thinking"],
                "tool_calls": response["tool_calls"],
            }
            messages.append(assistant_message)
            for tool_call in response["tool_calls"]:
                tool_call_count += 1
                if tool_call_count > MAX_TOOL_CALLS:
                    raise ModelExecutionError(
                        ModelErrorCode.MODEL_UNSUPPORTED_TASK,
                        "Ollama exceeded the controlled tool call limit.",
                    )
                tool_name, arguments = self._tool_call_parts(tool_call)
                tool_result = execute_registered_tool(
                    tool_context,
                    tool_name,
                    arguments,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": tool_name,
                        "content": json.dumps(
                            tool_result["result"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                )
        raise ModelExecutionError(
            ModelErrorCode.MODEL_UNSUPPORTED_TASK,
            "Ollama tool execution did not reach a final response.",
        )

    def _execute_sync(
        self,
        execution_id: str,
        provider: dict,
        profile: dict,
        request,
        options: dict,
    ) -> dict:
        absolute_deadline = time.monotonic() + self._absolute_limit_seconds
        lease_id = None
        heartbeat_stop = threading.Event()
        heartbeat_thread = None
        try:
            admission = self._admit(
                execution_id,
                provider,
                profile,
                request,
                absolute_deadline,
            )
            lease_id = admission["lease_id"]
            self._update(
                execution_id,
                status="running",
                started_at=_now(),
                heartbeat_at=_now(),
            )
            heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                args=(execution_id, lease_id, heartbeat_stop),
                daemon=True,
                name=f"ollama-lease-{execution_id[:8]}",
            )
            heartbeat_thread.start()
            result = self._run_chat(
                execution_id,
                provider,
                profile,
                request,
                options,
                absolute_deadline,
            )
            self._update(
                execution_id,
                status="completed",
                response_hash=content_hash(
                    {
                        "content": result["content"],
                        "thinking_content": result["thinking_content"],
                    }
                ),
                prompt_tokens=result["usage"]["prompt_eval_count"],
                output_tokens=result["usage"]["eval_count"],
                completed_at=_now(),
                heartbeat_at=_now(),
            )
            result["execution_evidence"] = {
                "ollama_execution_id": execution_id,
                "resource_lease_id": lease_id,
                "runtime_id": admission["runtime_id"],
                "admission_reason": admission["reason_code"],
            }
            return result
        except Exception as exc:
            error = normalize_model_error(exc)
            cancelled = (
                error.code is ModelErrorCode.USER_CANCELLED
                or self._cancel_requested(execution_id)
            )
            timed_out = error.code is ModelErrorCode.TIMEOUT
            self._update(
                execution_id,
                status=(
                    "cancelled"
                    if cancelled
                    else "timed_out"
                    if timed_out
                    else "failed"
                ),
                error_code=(
                    ModelErrorCode.USER_CANCELLED.value
                    if cancelled
                    else error.code.value
                ),
                completed_at=_now(),
                heartbeat_at=_now(),
            )
            if cancelled:
                raise ModelExecutionError(
                    ModelErrorCode.USER_CANCELLED,
                    "Ollama execution was cancelled.",
                ) from exc
            raise error from exc
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1)
            _response_close(execution_id)
            if lease_id:
                try:
                    task = get_ollama_execution(execution_id)
                    reason = {
                        "completed": "OLLAMA_EXECUTION_COMPLETED",
                        "cancelled": "OLLAMA_EXECUTION_CANCELLED",
                        "timed_out": "OLLAMA_EXECUTION_TIMEOUT",
                    }.get(task["status"], "OLLAMA_EXECUTION_FAILED")
                    self._scheduler.release_lease(lease_id, reason=reason)
                except KeyError:
                    pass

    async def execute(
        self,
        provider: dict,
        profile: dict,
        request,
        options: dict,
    ) -> dict:
        execution_id = self._create_task(provider, profile, request)
        worker = asyncio.create_task(
            asyncio.to_thread(
                self._execute_sync,
                execution_id,
                provider,
                profile,
                request,
                options,
            )
        )
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancel_ollama_execution(execution_id, owner_id=request.owner_id)
            try:
                await asyncio.wait_for(asyncio.shield(worker), timeout=5)
            except Exception:
                pass
            raise


_coordinator: OllamaExecutionCoordinator | None = None
_coordinator_lock = threading.Lock()


def get_ollama_execution_coordinator() -> OllamaExecutionCoordinator:
    global _coordinator
    with _coordinator_lock:
        if _coordinator is None:
            _coordinator = OllamaExecutionCoordinator()
        return _coordinator


def reset_ollama_execution_coordinator_for_tests() -> None:
    global _coordinator
    with _coordinator_lock:
        _coordinator = None

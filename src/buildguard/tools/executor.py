"""Validated, permissioned, timed, audited tool execution."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from buildguard.logging_system.jsonl_writer import redact
from buildguard.schemas.tools import ToolCallResult
from buildguard.security.advanced.capabilities import CapabilityManager
from buildguard.security.audit import ToolAuditLogger
from buildguard.security.permission_engine import PermissionEngine
from buildguard.tools.registry import ToolRegistry
from buildguard.tools.schemas import ToolAuditEntry, ToolExecutionRequest
from buildguard.utils.time import utc_now

LOGGER = logging.getLogger(__name__)


class ToolExecutor:
    """Contain all expected tool failures and return ToolCallResult."""

    def __init__(
        self,
        registry: ToolRegistry,
        permission_engine: PermissionEngine,
        audit_logger: ToolAuditLogger,
        *,
        retry_attempts: int = 2,
        retry_wait_seconds: float = 0.05,
        capability_manager: CapabilityManager | None = None,
        require_capability: bool | None = None,
    ) -> None:
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be positive")
        self.registry = registry
        self.permission_engine = permission_engine
        self.audit_logger = audit_logger
        self.retry_attempts = retry_attempts
        self.retry_wait_seconds = retry_wait_seconds
        self.capability_manager = capability_manager
        self.require_capability = (
            capability_manager is not None
            if require_capability is None
            else require_capability
        )
        if self.require_capability and self.capability_manager is None:
            raise ValueError(
                "A CapabilityManager is required when capability validation is enabled"
            )

    @staticmethod
    def _capability_paths(arguments: dict[str, Any]) -> list[Path]:
        paths: list[Path] = []
        for key, value in arguments.items():
            normalized = key.casefold()
            is_path = (
                normalized in {
                    "path",
                    "directory",
                    "root",
                    "image_path",
                    "image_paths",
                    "video_path",
                    "output_path",
                    "report_path",
                }
                or normalized.endswith(("_path", "_paths"))
            )
            if not is_path:
                continue
            values = value if isinstance(value, list) else [value]
            paths.extend(
                Path(item)
                for item in values
                if isinstance(item, (str, Path))
            )
        return paths

    def _check_capability(
        self,
        request: ToolExecutionRequest,
        *,
        read_only: bool,
        consume: bool,
        arguments: dict[str, Any] | None = None,
    ) -> str | None:
        if not self.require_capability:
            return None
        if request.capability_id is None:
            return "Capability is required for tool execution"
        assert self.capability_manager is not None
        decision = self.capability_manager.authorize(
            request.capability_id,
            task_id=request.task_id,
            tool_name=request.tool_name,
            operation="read" if read_only else "write",
            paths=self._capability_paths(arguments or request.arguments),
            resource_ids=request.resource_ids,
            consume=consume,
        )
        return None if decision.allowed else decision.reason

    def _audit(
        self,
        request: ToolExecutionRequest,
        started_at: datetime,
        decision: Literal["allow", "confirm", "deny"],
        confirmation: Literal["not_required", "pending", "approved", "denied", "expired"],
        status: Literal["success", "failure", "denied", "pending_confirmation"],
        error: str | None,
    ) -> None:
        try:
            self.audit_logger.record(
                ToolAuditEntry(
                    actor=request.actor,
                    task_id=request.task_id,
                    session_id=request.session_id,
                    tool_name=request.tool_name,
                    parameter_summary=redact(request.arguments),
                    permission_decision=decision,
                    confirmation_result=confirmation,
                    started_at=started_at,
                    ended_at=utc_now(),
                    execution_status=status,
                    error=error,
                )
            )
        except Exception as exc:
            LOGGER.error("Tool audit write failed without interrupting execution: %s", exc)

    def execute(self, request: ToolExecutionRequest) -> ToolCallResult:
        started_at = utc_now()
        started = time.perf_counter()
        try:
            tool = self.registry.get(request.tool_name)
        except (KeyError, PermissionError) as exc:
            self._audit(request, started_at, "deny", "not_required", "denied", str(exc))
            return ToolCallResult(
                call_id=request.id,
                success=False,
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        capability_error = self._check_capability(
            request,
            read_only=tool.definition.read_only,
            consume=False,
        )
        if capability_error is not None:
            self._audit(
                request,
                started_at,
                "deny",
                "not_required",
                "denied",
                capability_error,
            )
            return ToolCallResult(
                call_id=request.id,
                success=False,
                error=capability_error,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        permission = self.permission_engine.check(tool.definition, request)
        confirmation_result: Literal[
            "not_required", "pending", "approved", "denied", "expired"
        ] = "not_required"
        if permission.decision == "confirm":
            confirmation_result = "pending"
            confirmation_id = permission.confirmation.id if permission.confirmation else "unknown"
            pending_error = f"Confirmation required: {confirmation_id}"
            self._audit(
                request,
                started_at,
                "confirm",
                confirmation_result,
                "pending_confirmation",
                pending_error,
            )
            return ToolCallResult(
                call_id=request.id,
                success=False,
                error=pending_error,
                output={"confirmation_id": confirmation_id},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        if request.confirmation_id:
            try:
                confirmation_status = self.permission_engine.confirmations.get(
                    request.confirmation_id
                ).status
                confirmation_result = (
                    confirmation_status
                    if confirmation_status in {"approved", "denied", "expired"}
                    else "pending"
                )
            except KeyError:
                confirmation_result = "denied"
        if permission.decision == "deny":
            self._audit(
                request, started_at, "deny", confirmation_result, "denied", permission.reason
            )
            return ToolCallResult(
                call_id=request.id,
                success=False,
                error=permission.reason,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        try:
            parsed_input = tool.definition.input_schema.model_validate(request.arguments)
        except ValidationError as exc:
            validation_error = f"Tool input validation failed: {exc}"
            self._audit(
                request,
                started_at,
                "allow",
                confirmation_result,
                "failure",
                validation_error,
            )
            return ToolCallResult(
                call_id=request.id,
                success=False,
                error=validation_error,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        capability_error = self._check_capability(
            request,
            read_only=tool.definition.read_only,
            consume=True,
            arguments=parsed_input.model_dump(mode="python"),
        )
        if capability_error is not None:
            self._audit(
                request,
                started_at,
                "deny",
                confirmation_result,
                "denied",
                capability_error,
            )
            return ToolCallResult(
                call_id=request.id,
                success=False,
                error=capability_error,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        execution_error: str | None = None
        attempts = self.retry_attempts if tool.definition.read_only else 1
        for attempt in range(attempts):
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="buildguard-tool")
            future = pool.submit(tool.handler, parsed_input)
            try:
                raw_output = future.result(timeout=tool.definition.timeout_seconds)
                output = tool.definition.output_schema.model_validate(raw_output)
                pool.shutdown(wait=False, cancel_futures=True)
                self._audit(
                    request, started_at, "allow", confirmation_result, "success", None
                )
                return ToolCallResult(
                    call_id=request.id,
                    success=True,
                    output=output.model_dump(mode="json"),
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            except FutureTimeoutError:
                execution_error = (
                    f"Tool timed out after {tool.definition.timeout_seconds} seconds"
                )
                future.cancel()
            except Exception as exc:
                execution_error = f"Tool execution failed: {exc}"
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            if attempt + 1 < attempts:
                time.sleep(self.retry_wait_seconds)
        self._audit(
            request,
            started_at,
            "allow",
            confirmation_result,
            "failure",
            execution_error,
        )
        return ToolCallResult(
            call_id=request.id,
            success=False,
            error=execution_error or "Tool execution failed",
            duration_ms=(time.perf_counter() - started) * 1000,
        )

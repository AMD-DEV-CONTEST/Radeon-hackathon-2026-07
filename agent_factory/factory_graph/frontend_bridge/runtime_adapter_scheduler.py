from __future__ import annotations

from typing import Any

from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer
from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendCommand,
    FactoryFrontendEvent,
    event,
)
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    SYSTEM_CHAT_PACKAGE_ID,
)
from agent_factory.runtime_attachments import (
    AttachmentImportError,
    attachment_import_error_payload,
)
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager, WorkerLifecycleEvent
from agent_factory.scheduler_system import (
    SchedulerExecutor,
    SchedulerWorker,
    default_factory_scheduler_runtime,
    scheduler_run_session_id,
    scheduler_tool_approval_override,
)
from agent_factory.scheduler_system.events import SchedulerEventPayload
from agent_factory.tooling import get_factory_tools


class RuntimeSchedulerCommandMixin:
    def scheduler_manage(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip() or SYSTEM_CHAT_PACKAGE_ID
        try:
            for stream_mode, chunk in self.agent_package_runtime.scheduler_events(
                package_id,
                payload=command.payload,
                request_id=command.request_id,
            ):
                if stream_mode == "frontend_event":
                    item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
                    self.emit(item)
                elif stream_mode == "stderr":
                    self.emit(
                        event(
                            "debug_patch",
                            request_id=command.request_id,
                            session_id=self._session_id(),
                            mode=self.mode,
                            graph_id="scheduler_manage",
                            producer_type="factory_runtime",
                            payload={"scheduler_stderr": chunk, "package_id": package_id},
                        )
                    )
        except Exception as exc:
            self._emit_error(command, f"{type(exc).__name__}: {exc}")

    def _emit_scheduler_job_snapshot(
        self,
        event_type: str,
        job: Any,
        *,
        status: str,
        request_id: str | None = None,
    ) -> None:
        self._emit_scheduler_event(
            SchedulerEventPayload(
                event_type=event_type,  # type: ignore[arg-type]
                job_id=job.job_id,
                owner_type=job.owner_type,
                owner_id=job.owner_id,
                target_type=job.target.target_type,
                status=status,
                payload={"job": job.model_dump(mode="json")},
            ),
            request_id=request_id,
        )

    def _start_factory_scheduler(self) -> None:
        runtime = default_factory_scheduler_runtime(event_sink=self._emit_scheduler_event)
        runtime.executor = SchedulerExecutor(
            graph_runner=self._scheduler_graph_runner,
            tool_runner=self._scheduler_tool_runner,
        )
        worker = SchedulerWorker(runtime)
        if self.background_workers is None:
            self.background_workers = RuntimeBackgroundWorkerManager()
        self.background_workers.add(worker)
        self.scheduler_runtime = runtime
        for lifecycle_event in self.background_workers.start_all():
            if lifecycle_event.status == "failed":
                self._emit_worker_lifecycle_failure(lifecycle_event)

    def _shutdown_background_workers(self) -> None:
        if self.background_workers is None:
            return
        for lifecycle_event in self.background_workers.shutdown_all():
            if lifecycle_event.status == "failed":
                self._emit_worker_lifecycle_failure(lifecycle_event)

    def _emit_worker_lifecycle_failure(self, lifecycle_event: WorkerLifecycleEvent) -> None:
        self._emit_scheduler_event(
            SchedulerEventPayload(
                event_type="scheduler_run_failed",
                owner_type="factory",
                owner_id="default",
                status="failed",
                error_summary=(
                    f"background worker {lifecycle_event.action} failed: "
                    f"{lifecycle_event.worker_id}: {lifecycle_event.message}"
                ),
            )
        )

    def _emit_scheduler_event(self, payload: SchedulerEventPayload, *, request_id: str | None = None) -> None:
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=request_id,
            session_id=self._session_id(),
            mode=self.mode,
            graph_id="factory_scheduler",
            producer_type="factory_runtime",
        )
        normalizer.emit_custom_event({"type": "scheduler_event", "payload": payload.model_dump(mode="json")})

    def _scheduler_tool_runner(self, tool_id: str, arguments: dict[str, Any], job: Any, _run: Any) -> dict[str, Any]:
        tools = {tool.name: tool for tool in self._factory_tools()}
        tool = tools.get(tool_id)
        if tool is None:
            return {"status": "failed", "error": f"unknown factory tool: {tool_id}"}
        with scheduler_tool_approval_override(job=job, tool_id=tool_id):
            result = tool.invoke(arguments)
        if isinstance(result, dict):
            return result
        return {"status": "completed", "value": result}

    def _scheduler_graph_runner(self, job: Any, _run: Any) -> dict[str, Any]:
        payload = dict(job.target.payload)
        message = str(payload.get("message") or "").strip()
        request_id = f"scheduler-{_run.run_id}"
        target_scope = str(payload.get("target_scope") or "").strip() or "agent_package"
        if target_scope != "agent_package":
            return {"status": "failed", "error": f"unsupported scheduler graph target_scope: {target_scope}"}
        package_id = str(payload.get("package_id") or "").strip() or SYSTEM_CHAT_PACKAGE_ID
        return self._run_scheduled_agent_package(
            job=job,
            run=_run,
            message=message,
            request_id=request_id,
            package_id=package_id,
        )

    def _run_scheduled_agent_package(
        self,
        *,
        job: Any,
        run: Any,
        message: str,
        request_id: str,
        package_id: str,
    ) -> dict[str, Any]:
        session_id = scheduler_run_session_id(job, run, namespace=f"agent_package:{package_id}")
        package_name = package_id
        try:
            summary = self.agent_package_runtime.package_summary(package_id)
            package_name = str(summary.get("agent_name") or summary.get("name") or package_id)
        except Exception:
            pass
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=request_id,
            session_id=None,
            mode="agent_package",
            graph_id=f"scheduled_agent_package:{package_id}",
            producer_type="factory_runtime",
        )
        try:
            self.agent_package_runtime.ensure_session(
                package_id,
                session_id=session_id,
                first_user_input=message,
                session_kind="scheduler",
                visible_in_agent_session_list=False,
            )
            package_run = self.agent_package_runtime.stream(
                package_id,
                user_input=message,
                session_id=session_id,
                request_id=request_id,
                user_config=dict(job.runtime_config.user_config),
                runtime_request=dict(job.runtime_config.runtime_request),
                session_kind="scheduler",
                visible_in_agent_session_list=False,
            )
            consume_result = self._consume_agent_package_stream(
                package_id=package_id,
                run=package_run,
                normalizer=normalizer,
                frontend_mode="agent_package",
                frontend_session_id=None,
            )
        except AttachmentImportError as exc:
            payload = attachment_import_error_payload(exc)
            normalizer.runtime_event(
                "run_failed",
                span_id=normalizer.run_span_id,
                severity="error",
                message=payload["message"],
                payload=payload,
            )
            return {
                "status": "failed",
                "request_id": request_id,
                "target_scope": "agent_package",
                "package_id": package_id,
                "package_name": package_name,
                "error": payload["message"],
                "payload": payload,
            }
        except Exception as exc:
            normalizer.emit_run_failed(exc)
            return {
                "status": "failed",
                "request_id": request_id,
                "target_scope": "agent_package",
                "package_id": package_id,
                "package_name": package_name,
                "error": f"{type(exc).__name__}: {exc}",
            }
        if consume_result.status == "failed":
            result = _scheduled_failure_result(consume_result, fallback="scheduled agent package run failed")
            return {
                **result,
                "request_id": request_id,
                "target_scope": "agent_package",
                "package_id": package_id,
                "package_name": package_name,
                "agent_session": package_run.session,
            }
        if consume_result.status == "interrupted":
            return {
                "status": "interrupted",
                "request_id": request_id,
                "target_scope": "agent_package",
                "package_id": package_id,
                "package_name": package_name,
                "agent_session": package_run.session,
                "output_summary": "scheduled agent package run requested user input",
            }
        return {
            "status": "completed",
            "request_id": request_id,
            "target_scope": "agent_package",
            "package_id": package_id,
            "package_name": package_name,
            "agent_session": package_run.session,
            "output_summary": "scheduled agent package run completed",
        }

    def _factory_tools(self, tool_ids: list[str] | set[str] | tuple[str, ...] | None = None) -> list[Any]:
        return get_factory_tools(
            tool_ids=tool_ids,
            tool_runtime_resources=self._factory_tool_runtime_resources(),
        )

    def _factory_tool_runtime_resources(self) -> dict[str, Any]:
        if self.scheduler_runtime is None:
            return {}
        return {
            "scheduler_runtime": self.scheduler_runtime,
            "runtime_execution_config": {
                "user_config": {},
                "runtime_request": {},
            },
        }

def _scheduled_failure_result(result: Any, *, fallback: str) -> dict[str, Any]:
    terminal_event = getattr(result, "terminal_event", None)
    payload = getattr(terminal_event, "payload", None)
    payload = payload if isinstance(payload, dict) else {}
    message = str(
        payload.get("message")
        or getattr(terminal_event, "message", None)
        or getattr(result, "message", None)
        or fallback
    )
    return {"status": "failed", "error": message, "payload": payload}


def _normalized_scheduler_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    target = result.get("target")
    if not isinstance(target, dict):
        raise ValueError("scheduler job requires target")
    normalized_target = dict(target)
    target_payload = normalized_target.get("payload")
    normalized_target["payload"] = dict(target_payload) if isinstance(target_payload, dict) else {}
    result["target"] = normalized_target
    return result

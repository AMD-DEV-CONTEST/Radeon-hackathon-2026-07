from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextvars import ContextVar
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from pydantic import BaseModel, ConfigDict

from agent_factory.create_agent.models import PackageToolProbeRecord
from agent_factory.create_agent.probe_jobs import ProbeJobProgress, probe_job_manager
from agent_factory.create_agent.stage_sync import sync_probe_stage
from agent_factory.environment_system import EnvironmentResolutionError, EnvironmentResolver
from agent_factory.create_agent.validation_state import package_digest, package_fingerprint, package_tool_digest
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.factory_graph.frontend_bridge.agent_package_paths import manufacturing_probe_runtime_workspace
from agent_factory.native_runtime import AgentRuntimeLaunchError, NativeAgentRuntimeLauncher
from agent_factory.observed_process import ObservedProcessCancelled, run_observed_process
from agent_factory.models import get_task_model
from agent_factory.resource_system import ResourceStore, ResourceStoreError
from agent_factory.runtime_contracts import AgentPackageLoader, ResourcesContract
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.providers import PackageToolProvider, ToolProviderContext
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_PROBE_TOOL_ID = "create_agent_probe_tool"
PROBE_MODEL_TIMEOUT_SECONDS_ENV = "AGENTFACTORY_CREATE_AGENT_PROBE_MODEL_TIMEOUT_SECONDS"
DEFAULT_PROBE_MODEL_TIMEOUT_SECONDS = 60.0
PROBE_EVALUATION_TIMEOUT_SECONDS_ENV = "AGENTFACTORY_CREATE_AGENT_PROBE_EVALUATION_TIMEOUT_SECONDS"
DEFAULT_PROBE_EVALUATION_TIMEOUT_SECONDS = 8.0
ProbeProgressSink = Callable[[str, dict[str, Any]], None]
_PROBE_PROGRESS_SINK: ContextVar[ProbeProgressSink | None] = ContextVar(
    "create_agent_probe_progress_sink",
    default=None,
)
_PROBE_RECORD_LOCK = threading.RLock()


class PackageToolProbeEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    probe_kind: str = "unknown"
    goal_satisfied: bool | None = None
    tool_returned_business_output: bool = False
    only_error_handling_verified: bool = False


def build_create_agent_probe_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_PROBE_TOOL_ID,
        description=(
            "Inspect package-owned tools and manage asynchronous probe jobs that execute generated tools in the "
            "local isolated runtime through ToolExecutionGateway. Call starts a durable background job; status, "
            "list, and cancel observe or control it. Calls require explicit arguments; prompt is user-facing "
            "context only. Final validation requires fresh completed probe evidence; "
            "a resource_required observation is recorded as configuration_required and does not classify the "
            "tool implementation as failed."
        ),
        entrypoint="agent_factory.create_agent.probe_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["inspect", "call", "status", "list", "cancel"],
                },
                "job_id": {"type": "string"},
                "wait_seconds": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Optional status wait duration. The job remains asynchronous and queryable.",
                },
                "tool_id": {"type": "string", "default": ""},
                "prompt": {
                    "type": "string",
                    "default": "",
                    "description": "Business user prompt used as user-facing context for the probe.",
                },
                "tool_goal": {
                    "type": "string",
                    "default": "",
                    "description": "Optional target scenario the final probe answer should satisfy.",
                },
                "arguments": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Concrete package tool arguments. Use {} only for tools whose input schema has no required fields.",
                },
                "probe_kind": {
                    "type": "string",
                    "enum": ["auto", "success_path", "error_path"],
                    "default": "auto",
                    "description": "Declare whether this probe is intended to exercise a successful business path or an error path. Use auto if unsure.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Target tool runner deadline in seconds. Dependency preparation is an independently observable job stage.",
                },
            },
            "allOf": [
                {
                    "if": {"properties": {"action": {"const": "call"}}},
                    "then": {"required": ["tool_id", "arguments", "timeout_seconds"]},
                },
                {
                    "if": {"properties": {"action": {"enum": ["status", "cancel"]}}},
                    "then": {"required": ["job_id"]},
                },
            ],
            "required": ["action"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "tools": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "probe": {"type": "object", "additionalProperties": True},
                "diagnostics": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            },
            "required": ["action", "tools", "probe", "diagnostics"],
            "additionalProperties": False,
        },
        resources={
            "workspace": "create_agent_workspace",
        },
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.probe_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    action = str(arguments.get("action") or "").strip()
    if action == "inspect":
        return _inspect(workspace)
    if action == "call":
        return _start_call(
            workspace,
            tool_id=str(arguments.get("tool_id") or "").strip(),
            prompt=str(arguments.get("prompt") or "").strip(),
            tool_goal=str(arguments.get("tool_goal") or "").strip(),
            arguments=arguments.get("arguments") if isinstance(arguments.get("arguments"), dict) else None,
            requested_probe_kind=str(arguments.get("probe_kind") or "auto").strip(),
            timeout_seconds=_required_positive_int(arguments, "timeout_seconds"),
        )
    if action == "status":
        job = probe_job_manager.status(
            workspace=workspace,
            job_id=str(arguments.get("job_id") or "").strip(),
            wait_seconds=_optional_non_negative_number(arguments.get("wait_seconds")),
        )
        return _probe_job_envelope(action="status", job=job)
    if action == "list":
        jobs = probe_job_manager.list(workspace=workspace)
        return tool_envelope(
            {
                "action": "list",
                "tools": [],
                "probe": {"jobs": jobs},
                "diagnostics": [],
            },
            summary=f"Found {len(jobs)} asynchronous probe job(s).",
        )
    if action == "cancel":
        job = probe_job_manager.cancel(
            workspace=workspace,
            job_id=str(arguments.get("job_id") or "").strip(),
        )
        return _probe_job_envelope(action="cancel", job=job)
    raise ValueError(f"unsupported probe action: {action}")


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action in {"inspect", "status", "list", "cancel"}:
        return ToolRiskResult(action="allow", risk_level="low").model_dump(mode="json")
    if action == "call":
        return ToolRiskResult(
            action="allow",
            risk_level="low",
            reasons=["create-agent probe calls generated package tools through ToolExecutionGateway"],
        ).model_dump(mode="json")
    return ToolRiskResult(action="deny", risk_level="low", reasons=["unknown probe action"]).model_dump(mode="json")


def _start_call(
    workspace: CreateAgentWorkspace,
    *,
    tool_id: str,
    prompt: str,
    tool_goal: str,
    arguments: dict[str, Any] | None,
    requested_probe_kind: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not tool_id:
        raise ValueError("tool_id is required for probe call")
    discovery = _discover(workspace)
    spec = next((item for item in discovery.tool_specs if item.id == tool_id), None)
    if spec is None:
        raise ValueError(f"package tool is not available for probe: {tool_id}")
    request = {
        "tool_id": tool_id,
        "prompt": prompt,
        "tool_goal": tool_goal,
        "arguments": arguments,
        "probe_kind": requested_probe_kind,
        "timeout_seconds": timeout_seconds,
        "package_digest": package_digest(workspace.root),
        "concurrent": spec.concurrent,
    }

    def execute(
        snapshot: CreateAgentWorkspace,
        progress: ProbeJobProgress,
        cancel_event: threading.Event,
    ) -> dict[str, Any]:
        token = _PROBE_PROGRESS_SINK.set(progress)
        try:
            return _call(
                snapshot,
                record_workspace=workspace,
                tool_id=tool_id,
                prompt=prompt,
                tool_goal=tool_goal,
                arguments=arguments,
                requested_probe_kind=requested_probe_kind,
                timeout_seconds=timeout_seconds,
                cancel_event=cancel_event,
            )
        finally:
            _PROBE_PROGRESS_SINK.reset(token)

    job = probe_job_manager.submit(
        workspace=workspace,
        request=request,
        execute=execute,
    )
    return _probe_job_envelope(action="call", job=job)


def _probe_job_envelope(*, action: str, job: dict[str, Any]) -> dict[str, Any]:
    return tool_envelope(
        {
            "action": action,
            "tools": [],
            "probe": {
                "job": job,
                "asynchronous": True,
                "next_action": (
                    {
                        "tool": CREATE_AGENT_PROBE_TOOL_ID,
                        "arguments": {
                            "action": "status",
                            "job_id": job.get("job_id"),
                        },
                    }
                    if job.get("status") not in {"completed", "failed", "cancelled", "interrupted"}
                    else None
                ),
            },
            "diagnostics": [],
        },
        summary=(
            f"Probe job {job.get('job_id')} is {job.get('status')} "
            f"at stage {job.get('stage')}."
        ),
    )


def _cancelled_probe_result(
    *,
    spec: ToolSpec,
    changed_files: list[str],
    diagnostics: list[Any] | None = None,
) -> dict[str, Any]:
    return tool_envelope(
        {
            "action": "call",
            "tools": [_tool_summary(spec)],
            "probe": {
                "tool_id": spec.id,
                "status": "cancelled",
                "changed_files": changed_files,
            },
            "diagnostics": [
                _diagnostic_payload(item)
                for item in diagnostics or []
            ],
        },
        summary=f"Package tool probe cancelled: {spec.id}.",
    )


def _inspect(workspace: CreateAgentWorkspace) -> dict[str, Any]:
    discovery = _discover(workspace)
    jobs = probe_job_manager.list(workspace=workspace)
    state = workspace.read_tool_probe_state()
    latest = state.latest_by_tool()
    tools = []
    current_digest = package_digest(workspace.root)
    current_fingerprint = package_fingerprint(workspace.root)
    current_tool_digests: dict[str, str] = {}
    for spec in discovery.tool_specs:
        record = latest.get(spec.id)
        current_tool_digest = package_tool_digest(workspace.root, spec.id, fingerprint=current_fingerprint)
        current_tool_digests[spec.id] = current_tool_digest
        tools.append(
            {
                "tool_id": spec.id,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "risk_level": spec.risk_level,
                "last_probe": _probe_record_summary(record, current_tool_digest=current_tool_digest) if record else None,
            }
        )
    return tool_envelope(
        {
            "action": "inspect",
            "tools": tools,
            "probe": {
                "required": bool(tools),
                "current_package_digest": current_digest,
                "current_tool_digests": current_tool_digests,
                "guidance": "Call each generated package tool once with realistic arguments before final validation. Prompt and tool_goal provide human-readable context.",
                "publish_gate": "A probe that only verifies error handling is not sufficient for publish readiness.",
                "input_mode": "direct_tool_execution_with_optional_prompt_to_arguments",
                "freshness": "tool_scoped_digest",
                "jobs": jobs,
            },
            "diagnostics": [_diagnostic_payload(item) for item in discovery.diagnostics],
        },
        summary=f"Discovered {len(tools)} package tool(s) and {len(jobs)} asynchronous probe job(s).",
    )


def _call(
    workspace: CreateAgentWorkspace,
    *,
    record_workspace: CreateAgentWorkspace | None = None,
    tool_id: str,
    prompt: str,
    tool_goal: str,
    arguments: dict[str, Any] | None,
    requested_probe_kind: str,
    timeout_seconds: int,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    if not tool_id:
        raise ValueError("tool_id is required for probe call")
    discovery = _discover(workspace)
    specs = {spec.id: spec for spec in discovery.tool_specs}
    spec = specs.get(tool_id)
    if spec is None:
        raise ValueError(f"package tool is not available for probe: {tool_id}")
    if cancel_event is not None and cancel_event.is_set():
        return _cancelled_probe_result(spec=spec, changed_files=[])
    _emit_probe_progress(
        f"Starting tool probe for {tool_id}.",
        {"tool_id": tool_id, "prompt": prompt},
    )
    before = package_fingerprint(workspace.root)
    direct_probe = _run_direct_probe(
        workspace=workspace,
        spec=spec,
        prompt=prompt,
        tool_goal=tool_goal,
        arguments=arguments,
        requested_probe_kind=requested_probe_kind,
        timeout_seconds=timeout_seconds,
        cancel_event=cancel_event,
    )
    after = package_fingerprint(workspace.root)
    if cancel_event is not None and cancel_event.is_set():
        return _cancelled_probe_result(
            spec=spec,
            changed_files=_changed_files(before, after),
            diagnostics=discovery.diagnostics,
        )
    record = _record_from_direct_probe(
        workspace=workspace,
        spec=spec,
        tool_id=tool_id,
        prompt=prompt,
        tool_goal=tool_goal,
        direct_probe=direct_probe,
    )
    if cancel_event is not None and cancel_event.is_set():
        return _cancelled_probe_result(
            spec=spec,
            changed_files=_changed_files(before, after),
            diagnostics=discovery.diagnostics,
        )
    if record.status in {"passed", "configuration_required"} and record_workspace is not None:
        _promote_environment_lock(
            snapshot=workspace,
            destination=record_workspace,
            expected_fingerprint=before,
        )
    state_workspace = record_workspace or workspace
    with _PROBE_RECORD_LOCK:
        state = state_workspace.read_tool_probe_state()
        state.records.append(record)
        state = state.model_copy(update={"updated_at": datetime.now(UTC).isoformat()})
        state_workspace.write_tool_probe_state(state)
    sync_probe_stage(
        state_workspace,
        passed=record.status == "passed",
        success_path=record.probe_kind == "success_path" and not record.only_error_handling_verified,
    )
    changed_files = _changed_files(before, after)
    transcript = _probe_transcript(direct_probe=direct_probe, record=record)
    _emit_probe_progress(
        f"Tool probe completed: {tool_id} -> {record.status}.",
        {
            "tool_id": tool_id,
            "status": record.status,
            "evaluation": record.evaluation,
            "transcript": transcript,
        },
    )
    return tool_envelope(
        {
            "action": "call",
            "tools": [_tool_summary(spec)],
            "probe": {
                "tool_id": tool_id,
                "status": record.status,
                "observation_status": record.observation_status,
                "execution_status": record.execution_status,
                "contract_status": record.contract_status,
                "message": record.message,
                "prompt": record.prompt,
                "tool_goal": record.tool_goal,
                "probe_kind": record.probe_kind,
                "goal_satisfied": record.goal_satisfied,
                "tool_returned_business_output": record.tool_returned_business_output,
                "only_error_handling_verified": record.only_error_handling_verified,
                "arguments": record.arguments,
                "tool_calls": record.tool_calls,
                "output_summary": record.output_summary,
                "observation_output": record.observation_output,
                "dependency_report": record.dependency_report,
                "runtime_paths": record.runtime_paths,
                "final_answer": record.final_answer,
                "summary": record.summary,
                "evaluator": record.evaluator,
                "evaluation": record.evaluation,
                "transcript": transcript,
                "errors": record.errors,
                "changed_files": changed_files,
                "package_digest": record.package_digest,
                "tool_digest": record.tool_digest,
                "tool_digest_kind": record.tool_digest_kind,
            },
            "diagnostics": [_diagnostic_payload(item) for item in discovery.diagnostics],
        },
        evidence={
            "package_tool_probe": {
                "tool_id": tool_id,
                "status": record.status,
                "changed_files": changed_files,
            }
        },
        summary=_probe_summary(record),
    )


def _promote_environment_lock(
    *,
    snapshot: CreateAgentWorkspace,
    destination: CreateAgentWorkspace,
    expected_fingerprint: dict[str, str],
) -> None:
    source = snapshot.root / "environment.lock.json"
    if not source.is_file():
        raise RuntimeError("successful probe did not produce environment.lock.json")
    with _PROBE_RECORD_LOCK:
        if package_fingerprint(destination.root) != expected_fingerprint:
            raise RuntimeError(
                "package changed while the asynchronous probe was running; "
                "the verified environment lock was not promoted"
            )
        target = destination.root / "environment.lock.json"
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _discover(workspace: CreateAgentWorkspace):
    return PackageToolProvider().discover(ToolProviderContext(package_root=workspace.root))


def _run_direct_probe(
    *,
    workspace: CreateAgentWorkspace,
    spec: ToolSpec,
    prompt: str,
    tool_goal: str,
    arguments: dict[str, Any] | None,
    requested_probe_kind: str,
    timeout_seconds: int,
    cancel_event: threading.Event | None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    resolved_arguments = dict(arguments or {})
    if arguments is None:
        errors.append("probe call requires explicit arguments; pass {} only for a tool with no required input fields")
    if not resolved_arguments and _schema_required_keys(spec.input_schema):
        errors.append("probe arguments are required by the target tool input_schema")
    _emit_probe_progress(
        f"Tool-probe input: {spec.id} args={_one_line(json.dumps(resolved_arguments, ensure_ascii=False, sort_keys=True), 220)}",
        {"tool_id": spec.id, "arguments": resolved_arguments},
    )
    if errors:
        return {
            "prompt": prompt,
            "tool_goal": tool_goal,
            "requested_probe_kind": requested_probe_kind if requested_probe_kind in {"success_path", "error_path"} else "auto",
            "arguments": resolved_arguments,
            "status": "failed",
            "observation": {},
            "events": [],
            "errors": errors,
        }
    try:
        local_result = _run_local_probe(
            workspace=workspace,
            spec=spec,
            arguments=resolved_arguments,
            timeout_seconds=timeout_seconds,
            cancel_event=cancel_event,
        )
    except Exception as exc:
        return {
            "prompt": prompt,
            "tool_goal": tool_goal,
            "requested_probe_kind": requested_probe_kind if requested_probe_kind in {"success_path", "error_path"} else "auto",
            "arguments": resolved_arguments,
            "status": "failed",
            "observation": {},
            "events": [],
            "errors": [*errors, f"local package tool probe failed before execution: {type(exc).__name__}: {exc}"],
        }
    observation_payload = local_result.get("observation") if isinstance(local_result.get("observation"), dict) else {}
    local_errors = [str(item) for item in local_result.get("errors", []) if item]
    dependency_report = local_result.get("dependency_report") if isinstance(local_result.get("dependency_report"), dict) else {}
    events.append(
        {
            "event_type": "tool_completed" if observation_payload.get("status") == "completed" else "tool_failed",
            "tool_id": spec.id,
            "arguments": resolved_arguments,
            "runtime": "local",
            "runtime_paths": _json_preview(local_result.get("runtime_paths", {}), limit=2000),
            "dependency_report": _json_preview(dependency_report, limit=4000),
            "observation": _json_preview(observation_payload, limit=8000),
            "captured_stdout": _one_line(str(local_result.get("captured_stdout") or ""), 1000),
            "captured_stderr": _one_line(str(local_result.get("captured_stderr") or ""), 1000),
        }
    )
    status = str(observation_payload.get("status") or "").strip()
    message = str(observation_payload.get("message") or "").strip()
    _emit_probe_progress(
        f"Local isolated tool observation: {spec.id} {status or local_result.get('status') or '-'}" + (f" - {_one_line(message, 220)}" if message else ""),
        {
            "tool_id": spec.id,
            "status": status,
            "local_status": local_result.get("status"),
            "dependency_status": dependency_report.get("status"),
        },
    )
    return {
        "prompt": prompt,
        "tool_goal": tool_goal,
        "requested_probe_kind": requested_probe_kind if requested_probe_kind in {"success_path", "error_path"} else "auto",
        "arguments": resolved_arguments,
        "status": "completed" if observation_payload.get("status") == "completed" and not errors and not local_errors else "failed",
        "observation": observation_payload,
        "dependency_report": dependency_report,
        "runtime_paths": local_result.get("runtime_paths") if isinstance(local_result.get("runtime_paths"), dict) else {},
        "infrastructure_error": local_result.get("infrastructure_error") if isinstance(local_result.get("infrastructure_error"), dict) else {},
        "phase": str(local_result.get("phase") or ""),
        "captured_stdout": str(local_result.get("captured_stdout") or ""),
        "captured_stderr": str(local_result.get("captured_stderr") or ""),
        "events": _json_preview(events, limit=10000),
        "errors": [*errors, *local_errors],
    }


def _run_local_probe(
    *,
    workspace: CreateAgentWorkspace,
    spec: ToolSpec,
    arguments: dict[str, Any],
    timeout_seconds: int,
    cancel_event: threading.Event | None,
) -> dict[str, Any]:
    try:
        _emit_probe_stage(
            "preparing_environment",
            "Preparing the tool dependency environment.",
            {"tool_id": spec.id},
        )
        EnvironmentResolver().ensure(
            workspace.root,
            on_progress=lambda stage, detail: _emit_probe_stage(
                stage,
                _environment_progress_message(stage, detail),
                {"tool_id": spec.id, **detail},
            ),
            cancel_event=cancel_event,
        )
        if cancel_event is not None and cancel_event.is_set():
            raise ObservedProcessCancelled("probe cancelled after environment preparation")
        _emit_probe_stage(
            "loading_package",
            "The dependency environment is ready; loading the manufacturing package.",
            {"tool_id": spec.id},
        )
        package = AgentPackageLoader().load_path(workspace.package_manifest_path())
    except EnvironmentResolutionError as exc:
        return {
            "status": "failed",
            "phase": "environment_resolution",
            "observation": {},
            "errors": [str(exc)],
            "infrastructure_error": {"status": exc.status, "message": str(exc)},
            "captured_stdout": "",
            "captured_stderr": "",
            "dependency_report": {"status": exc.status},
        }
    runtime_workspace = manufacturing_probe_runtime_workspace(workspace.root.name).ensure()
    runtime_root = runtime_workspace.root
    artifacts_root = runtime_workspace.artifacts
    workdir_root = runtime_workspace.workdir
    extension_root = runtime_workspace.extensions
    try:
        plan = NativeAgentRuntimeLauncher().prepare(
            package=package,
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            runtime_instance_id=str(runtime_root),
            extension_root=extension_root,
        )
    except AgentRuntimeLaunchError as exc:
        return {
            "status": "failed",
            "phase": "local_preflight",
            "observation": {},
            "errors": [str(exc)],
            "infrastructure_error": exc.payload,
            "captured_stdout": "",
            "captured_stderr": "",
            "dependency_report": {},
        }
    command = plan.command_for_python_module("agent_factory.create_agent.local_probe_runner")
    request = json.dumps(
        {
            "tool_id": spec.id,
            "arguments": arguments,
            "runtime_resources": _configured_probe_resources(workspace, spec),
        },
        ensure_ascii=False,
    )
    _emit_probe_stage(
        "starting_probe_runner",
        f"Local isolated probe started: {spec.id}",
        {"tool_id": spec.id, "runtime": "local"},
    )
    try:
        completed = run_observed_process(
            command,
            input_text=request,
            environment=plan.environment,
            timeout_seconds=timeout_seconds,
            cancel_event=cancel_event,
            on_output=lambda stream, line: _observe_probe_runner_output(
                tool_id=spec.id,
                stream=stream,
                line=line,
            ),
        )
    except ObservedProcessCancelled:
        return {
            "status": "failed",
            "phase": "cancelled",
            "observation": {},
            "errors": ["local probe was cancelled"],
            "captured_stdout": "",
            "captured_stderr": "",
            "dependency_report": {},
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "failed",
            "phase": "local_timeout",
            "observation": {},
            "errors": [f"local probe timed out after {timeout_seconds:g}s"],
            "captured_stdout": exc.stdout or "",
            "captured_stderr": exc.stderr or "",
            "dependency_report": {},
        }
    payload = _parse_local_probe_output(
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )
    payload["runtime_paths"] = {
        "runtime_root": str(runtime_root),
        "artifacts_root": str(artifacts_root),
        "workdir_root": str(workdir_root),
        "extension_root": str(extension_root),
    }
    if completed.returncode != 0 and not payload.get("errors"):
        payload["errors"] = [f"local probe exited with code {completed.returncode}"]
    return payload


def _configured_probe_resources(workspace: CreateAgentWorkspace, spec: ToolSpec) -> dict[str, Any]:
    contract_path = workspace.root / "contracts" / "resources.json"
    if not contract_path.exists() or not spec.resources:
        return {}
    contract = ResourcesContract.model_validate_json(contract_path.read_text(encoding="utf-8"))
    descriptors = {item.resource_id: item for item in contract.config.resource_descriptors}
    store = ResourceStore()
    values: dict[str, Any] = {}
    for selector in spec.resources.values():
        resource_id = selector.split(".", 1)[0]
        descriptor = descriptors.get(resource_id)
        if descriptor is None or resource_id in values:
            continue
        try:
            values[resource_id] = store.resolve(workspace.root.name, descriptor)
        except ResourceStoreError as exc:
            if str(exc).startswith("resource_required:"):
                continue
            raise
    return values


def _parse_local_probe_output(*, stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    lines = [line.strip() for line in str(stdout or "").splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            if stderr:
                payload["captured_stderr"] = str(payload.get("captured_stderr") or "") + stderr
            return payload
    stderr_text = str(stderr or "").strip()
    stdout_text = str(stdout or "").strip()
    detail = stderr_text or stdout_text or f"local probe exited with code {returncode} before emitting JSON"
    return {
        "status": "failed",
        "phase": "local_process",
        "observation": {},
        "errors": [f"local probe process failed before emitting JSON: {detail}"],
        "captured_stdout": stdout,
        "captured_stderr": stderr,
        "dependency_report": {},
    }


def _emit_probe_progress(message: str, payload: dict[str, Any] | None = None) -> None:
    detail = dict(payload or {})
    sink = _PROBE_PROGRESS_SINK.get()
    if sink is not None:
        try:
            sink(
                str(detail.get("stage") or "probe_progress"),
                {"message": message, **detail},
            )
        except Exception:
            pass
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer(
            {
                "type": "node_event",
                "payload": {
                    "event_type": "node_progress",
                    "node_id": "create_agent_probe_tool",
                    "node_label": "Package Tool Probe",
                    "node_kind": "tool_probe",
                    "message": message,
                    "payload": detail,
                },
            }
        )
    except Exception:
        return


def _emit_probe_stage(stage: str, message: str, payload: dict[str, Any] | None = None) -> None:
    _emit_probe_progress(message, {"stage": stage, **dict(payload or {})})


def _environment_progress_message(stage: str, detail: dict[str, Any]) -> str:
    if stage == "dependency_process_output":
        return str(detail.get("message") or "Dependency construction is still in progress.")
    return {
        "checking_contract": "Checking the dependency contract.",
        "checking_runtime": "Checking the local runtime environment.",
        "resolving_dependencies": "Resolving shared dependencies.",
        "waiting_for_dependency_profile": "Waiting for the shared dependency profile.",
        "checking_dependency_profile": "Checking the shared dependency cache.",
        "dependency_profile_cache_hit": "Shared dependency cache hit.",
        "creating_python_build_environment": "Creating the Python dependency build environment.",
        "building_python_wheels": "Building Python wheels.",
        "storing_python_wheels": "Storing Python wheels.",
        "installing_npm_dependencies": "Installing npm dependencies.",
        "dependency_profile_stored": "The shared dependency profile is prepared.",
        "dependency_profile_ready": "The dependency profile is ready.",
        "ready": "The dependency environment is ready.",
    }.get(stage, f"Dependency environment stage: {stage}")


def _observe_probe_runner_output(*, tool_id: str, stream: str, line: str) -> None:
    message = line.strip()
    if not message:
        return
    if stream == "stdout":
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict) or payload.get("type") != "probe_progress":
            return
        stage = str(payload.get("stage") or "running_probe")
        detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
        _emit_probe_stage(
            stage,
            {
                "discovering_tools": "Discovering manufacturing-package tools.",
                "compiling_tool": "Compiling the target tool.",
                "executing_tool": "Executing the target tool.",
                "tool_execution_finished": "Target tool execution finished.",
            }.get(stage, f"Tool-probe stage: {stage}"),
            {"tool_id": tool_id, **detail},
        )
        return
    _emit_probe_stage(
        "probe_runner_output",
        message,
        {"tool_id": tool_id, "stream": stream},
    )


def _probe_transcript(*, direct_probe: dict[str, Any], record: PackageToolProbeRecord) -> list[str]:
    lines = [f"Business test prompt: {direct_probe.get('prompt') or record.prompt}"]
    lines.append(
        "Local isolated runtime tool call: "
        f"{record.tool_id} args={_one_line(json.dumps(record.arguments, ensure_ascii=False, sort_keys=True), 240)}"
    )
    dependency_report = direct_probe.get("dependency_report") if isinstance(direct_probe.get("dependency_report"), dict) else {}
    if dependency_report:
        lines.append(f"Dependency initialization: status={dependency_report.get('status') or '-'} phase={dependency_report.get('phase') or '-'}")
    infrastructure_error = direct_probe.get("infrastructure_error") if isinstance(direct_probe.get("infrastructure_error"), dict) else {}
    if infrastructure_error:
        lines.append(
            "Local isolated environment: "
            f"{infrastructure_error.get('why') or '-'} - {_one_line(str(infrastructure_error.get('message') or ''), 240)}"
        )
    observation = direct_probe.get("observation") if isinstance(direct_probe.get("observation"), dict) else {}
    if observation:
        message = str(observation.get("message") or "").strip()
        output = observation.get("output")
        output_text = _one_line(json.dumps(output, ensure_ascii=False, sort_keys=True), 320) if output else ""
        lines.append(
            "Tool result: "
            f"{record.tool_id} status={observation.get('status') or '-'}"
            + (f" message={_one_line(message, 180)}" if message else "")
            + (f" output={output_text}" if output_text else "")
        )
    evaluation = record.evaluation if isinstance(record.evaluation, dict) else {}
    if evaluation:
        lines.append(
            "Small-model summary: "
            f"{_one_line(str(evaluation.get('summary') or ''), 240)}"
        )
    return lines


def _record_from_direct_probe(
    *,
    workspace: CreateAgentWorkspace,
    spec: ToolSpec,
    tool_id: str,
    prompt: str,
    tool_goal: str,
    direct_probe: dict[str, Any],
) -> PackageToolProbeRecord:
    observation = dict(direct_probe.get("observation") or {}) if isinstance(direct_probe.get("observation"), dict) else {}
    arguments = dict(direct_probe.get("arguments") or {}) if isinstance(direct_probe.get("arguments"), dict) else {}
    observation_status = str(observation.get("status") or "")
    execution_status = str(observation.get("execution_status") or "")
    contract_status = str(observation.get("contract_status") or "")
    errors = observation.get("errors")
    if not isinstance(errors, list):
        errors = []
    probe_errors = direct_probe.get("errors")
    if not isinstance(probe_errors, list):
        probe_errors = []
    output = observation.get("output")
    output_payload = output if isinstance(output, dict) else {}
    evaluation_payload = _probe_system_evaluation(direct_probe)
    if not evaluation_payload:
        evaluation_payload = _evaluate_probe_observation(
            spec=spec,
            prompt=prompt,
            tool_goal=tool_goal,
            direct_probe=direct_probe,
        )
    probe_kind = _normalized_probe_kind(
        requested=direct_probe.get("requested_probe_kind"),
        evaluation=evaluation_payload,
        observation=observation,
        output_payload=output_payload,
    )
    tool_returned_business_output = _tool_returned_business_output(
        evaluation=evaluation_payload,
        output_payload=output_payload,
    )
    only_error_handling_verified = _only_error_handling_verified(
        evaluation=evaluation_payload,
        probe_kind=probe_kind,
        output_payload=output_payload,
        observation=observation,
    )
    evaluator = str(evaluation_payload.get("evaluator") or "")
    summary = str(evaluation_payload.get("summary") or "")
    goal_satisfied = evaluation_payload.get("goal_satisfied")
    goal_satisfied_value = goal_satisfied if isinstance(goal_satisfied, bool) else None
    final_answer = _probe_final_answer(spec=spec, observation=observation, summary=summary)
    tool_was_called = bool(observation)
    contract_passed = (
        tool_was_called
        and observation_status == "completed"
        and (not execution_status or execution_status == "completed")
        and (not contract_status or contract_status == "valid")
        and bool(final_answer)
    )
    probe_status = (
        "configuration_required"
        if observation_status == "resource_required"
        else "passed" if contract_passed else "failed"
    )
    return PackageToolProbeRecord(
        tool_id=tool_id,
        probe_kind=probe_kind,
        prompt=prompt,
        tool_goal=tool_goal,
        arguments=arguments,
        tool_calls=[
            {"tool_id": tool_id, "arguments": arguments}
        ],
        package_digest=package_digest(workspace.root),
        tool_digest=package_tool_digest(workspace.root, tool_id),
        status=probe_status,
        observation_status=observation_status,
        execution_status=execution_status,
        contract_status=contract_status,
        message=str(observation.get("message") or "")[:500],
        output_summary=str(observation.get("output_summary") or "")[:500],
        observation_output=_probe_observation_output(output_payload=output_payload, direct_probe=direct_probe),
        dependency_report=_json_preview(direct_probe.get("dependency_report", {}), limit=4000),
        runtime_paths=_json_preview(direct_probe.get("runtime_paths", {}), limit=2000),
        final_answer=final_answer[:2000],
        summary=summary[:1000],
        goal_satisfied=goal_satisfied_value,
        tool_returned_business_output=tool_returned_business_output,
        only_error_handling_verified=only_error_handling_verified,
        evaluator=evaluator,
        evaluation=evaluation_payload,
        errors=[str(item)[:500] for item in [*probe_errors, *errors][:8]],
        probed_at=datetime.now(UTC).isoformat(),
    )


def _normalized_probe_kind(
    *,
    requested: Any,
    evaluation: dict[str, Any],
    observation: dict[str, Any],
    output_payload: dict[str, Any],
) -> str:
    value = str(evaluation.get("probe_kind") or "").strip()
    if value in {"success_path", "error_path"}:
        return value
    requested_value = str(requested or "").strip()
    if requested_value in {"success_path", "error_path"}:
        return requested_value
    return "error_path" if _output_contains_error(output_payload) or _observation_message_looks_error(observation) else "success_path"


def _probe_system_evaluation(direct_probe: dict[str, Any]) -> dict[str, Any]:
    observation = direct_probe.get("observation") if isinstance(direct_probe.get("observation"), dict) else {}
    if str(observation.get("status") or "") == "resource_required":
        return {
            "evaluator": "system",
            "summary": str(observation.get("message") or "Runtime Resource configuration is required.")[:1000],
            "probe_kind": "unknown",
            "goal_satisfied": None,
            "tool_returned_business_output": False,
            "only_error_handling_verified": False,
            "resource_ids": list((observation.get("evidence") or {}).get("resource_ids") or []),
        }
    if observation:
        return {}
    infrastructure_error = direct_probe.get("infrastructure_error") if isinstance(direct_probe.get("infrastructure_error"), dict) else {}
    errors = direct_probe.get("errors") if isinstance(direct_probe.get("errors"), list) else []
    phase = str(direct_probe.get("phase") or "")
    if not infrastructure_error and not errors and not phase:
        return {}
    message = str(infrastructure_error.get("message") or "; ".join(str(item) for item in errors) or phase)
    suggested_action = str(infrastructure_error.get("suggested_action") or "")
    summary = message + (f" Suggested action: {suggested_action}" if suggested_action else "")
    return {
        "evaluator": "system",
        "summary": summary[:1000],
        "probe_kind": "error_path",
        "goal_satisfied": False,
        "tool_returned_business_output": False,
        "only_error_handling_verified": True,
        "infrastructure_error": infrastructure_error,
    }


def _tool_returned_business_output(*, evaluation: dict[str, Any], output_payload: dict[str, Any]) -> bool:
    value = evaluation.get("tool_returned_business_output")
    if isinstance(value, bool) and value and not _output_contains_error(output_payload):
        return True
    return _has_substantive_non_error_output(output_payload)


def _only_error_handling_verified(
    *,
    evaluation: dict[str, Any],
    probe_kind: str,
    output_payload: dict[str, Any],
    observation: dict[str, Any],
) -> bool:
    if _output_contains_error(output_payload) or _observation_message_looks_error(observation):
        return True
    value = evaluation.get("only_error_handling_verified")
    if isinstance(value, bool):
        return value
    if probe_kind == "error_path":
        return True
    return _output_contains_error(output_payload) or _observation_message_looks_error(observation)


def _output_contains_error(output_payload: dict[str, Any]) -> bool:
    for key, value in output_payload.items():
        key_text = str(key).lower()
        if key_text in {"error", "errors", "exception", "traceback"} and value:
            return True
    return False


def _observation_message_looks_error(observation: dict[str, Any]) -> bool:
    message = str(observation.get("message") or "").strip().lower()
    if not message:
        return False
    markers = ("error", "failed", "failure", "exception", "not found", "missing", "不存在", "失败", "错误")
    return any(marker in message for marker in markers)


def _has_substantive_non_error_output(output_payload: dict[str, Any]) -> bool:
    for key, value in output_payload.items():
        if str(key).lower() in {"error", "errors", "exception", "traceback"}:
            continue
        if value in ("", None, [], {}):
            continue
        return True
    return False


def _probe_observation_output(*, output_payload: dict[str, Any], direct_probe: dict[str, Any]) -> dict[str, Any]:
    if output_payload:
        return _json_preview(output_payload, limit=6000)
    return {
        "observation": _json_preview(direct_probe.get("observation", {}), limit=6000),
        "dependency_report": _json_preview(direct_probe.get("dependency_report", {}), limit=4000),
        "infrastructure_error": _json_preview(direct_probe.get("infrastructure_error", {}), limit=2000),
        "runtime_paths": _json_preview(direct_probe.get("runtime_paths", {}), limit=2000),
    }


def _probe_final_answer(*, spec: ToolSpec, observation: dict[str, Any], summary: str) -> str:
    output_summary = str(observation.get("output_summary") or "").strip()
    if output_summary:
        return output_summary
    output = observation.get("output") if isinstance(observation.get("output"), dict) else {}
    if output:
        return _one_line(json.dumps(output, ensure_ascii=False, sort_keys=True), 1800)
    if summary:
        return summary
    message = str(observation.get("message") or "").strip()
    return message or f"{spec.id} returned no user-facing output."


def _evaluate_probe_observation(
    *,
    spec: ToolSpec,
    prompt: str,
    tool_goal: str,
    direct_probe: dict[str, Any],
) -> dict[str, Any]:
    model = get_task_model()
    if model is None:
        return {
            "evaluator": "task_model",
            "evaluator_status": "not_configured",
            "summary": "Task model is not configured; direct tool observation is available for main-model review.",
        }
    observation = direct_probe.get("observation") if isinstance(direct_probe.get("observation"), dict) else {}
    evaluation_messages = [
        SystemMessage(
            content=(
                "You summarize a generated package tool probe from a direct ToolExecutionGateway observation. "
                "Return concise JSON only. The JSON must contain fields summary, probe_kind, goal_satisfied, "
                "tool_returned_business_output, and only_error_handling_verified. "
                "probe_kind must be success_path when the probe exercised the tool's intended successful business behavior, "
                "error_path when it only verified rejection/error handling, or unknown if unclear. "
                "The summary should say whether the final answer appears to satisfy the tool goal. "
                "If no tool goal is provided, summarize whether the final answer is useful for the business prompt."
            )
        ),
        HumanMessage(
            content=json.dumps(
                {
                    "tool": {
                        "id": spec.id,
                        "description": spec.description,
                        "input_schema": spec.input_schema,
                        "output_schema": spec.output_schema,
                    },
                    "business_prompt": prompt,
                    "tool_goal": tool_goal,
                    "arguments": direct_probe.get("arguments") if isinstance(direct_probe.get("arguments"), dict) else {},
                    "observation": _json_preview(observation, limit=12000),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        ),
    ]
    try:
        structured = model.with_structured_output(PackageToolProbeEvaluation, method="json_mode").with_config(
            tags=["nostream"]
        )
        result = _invoke_with_timeout(
            structured,
            evaluation_messages,
            label="task_model probe evaluation",
            timeout=_probe_evaluation_timeout_seconds(),
        )
        evaluation = result if isinstance(result, PackageToolProbeEvaluation) else PackageToolProbeEvaluation.model_validate(result)
        return {
            "evaluator": "task_model",
            "evaluator_status": "completed",
            **evaluation.model_dump(mode="json"),
        }
    except Exception as exc:
        return {
            "evaluator": "task_model",
            "evaluator_status": "failed",
            "summary": f"Task model probe summary failed and was skipped: {type(exc).__name__}: {exc}",
        }


def _probe_record_summary(record: PackageToolProbeRecord, *, current_tool_digest: str) -> dict[str, Any]:
    return {
        "status": record.status,
        "stale": record.tool_digest != current_tool_digest,
        "tool_digest": record.tool_digest,
        "current_tool_digest": current_tool_digest,
        "tool_digest_kind": record.tool_digest_kind,
        "probe_kind": record.probe_kind,
        "goal_satisfied": record.goal_satisfied,
        "tool_returned_business_output": record.tool_returned_business_output,
        "only_error_handling_verified": record.only_error_handling_verified,
        "observation_status": record.observation_status,
        "contract_status": record.contract_status,
        "message": record.message,
        "output_summary": record.output_summary,
        "arguments": record.arguments,
        "final_answer": record.final_answer,
        "dependency_report": record.dependency_report,
        "summary": record.summary,
        "evaluator": record.evaluator,
        "evaluation": record.evaluation,
        "probed_at": record.probed_at,
    }


def _non_streaming_model(model: Any) -> Any:
    if hasattr(model, "model_copy"):
        try:
            return model.model_copy(update={"streaming": False})
        except Exception:
            pass
    return model


def _invoke_with_timeout(runnable: Any, input_value: Any, *, label: str, timeout: float | None = None) -> Any:
    timeout = timeout or _probe_model_timeout_seconds()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(runnable.invoke, input_value)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(f"{label} timed out after {timeout:g}s") from exc
    finally:
        if future.done():
            executor.shutdown(wait=False, cancel_futures=True)


def _probe_model_timeout_seconds() -> float:
    value = os.getenv(PROBE_MODEL_TIMEOUT_SECONDS_ENV)
    if value:
        try:
            parsed = float(value)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return DEFAULT_PROBE_MODEL_TIMEOUT_SECONDS


def _probe_evaluation_timeout_seconds() -> float:
    return _positive_float_env(PROBE_EVALUATION_TIMEOUT_SECONDS_ENV, DEFAULT_PROBE_EVALUATION_TIMEOUT_SECONDS)


def _positive_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value:
        try:
            parsed = float(value)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return default


def _schema_required_keys(schema: dict[str, Any]) -> set[str]:
    required = schema.get("required") if isinstance(schema, dict) else []
    return {str(item) for item in required or [] if str(item)}


def _required_positive_int(arguments: dict[str, Any], key: str) -> int:
    value = arguments.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a positive integer") from exc
    if parsed < 1:
        raise ValueError(f"{key} must be a positive integer")
    return parsed


def _optional_non_negative_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("wait_seconds must be a non-negative number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("wait_seconds must be a non-negative number") from exc
    if parsed < 0:
        raise ValueError("wait_seconds must be a non-negative number")
    return parsed


def _tool_summary(spec: ToolSpec) -> dict[str, Any]:
    return {
        "tool_id": spec.id,
        "description": spec.description,
        "input_schema": spec.input_schema,
        "risk_level": spec.risk_level,
    }


def _diagnostic_payload(item: Any) -> dict[str, Any]:
    return item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def _probe_summary(record: PackageToolProbeRecord) -> str:
    if record.summary:
        return f"Package tool probe {record.status}: {record.tool_id}. {record.summary}"
    if record.output_summary:
        return f"Package tool probe {record.status}: {record.tool_id}. {record.output_summary}"
    return f"Package tool probe {record.status}: {record.tool_id}. {record.message}"


def _json_preview(value: Any, *, limit: int) -> Any:
    normalized = _json_safe(value)
    text = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return normalized
    return {
        "truncated": True,
        "chars": len(text),
        "preview": text[:limit],
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _one_line(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."

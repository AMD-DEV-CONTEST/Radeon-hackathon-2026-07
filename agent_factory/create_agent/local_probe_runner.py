from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import sys
import time
from typing import Any

from agent_factory.agent_runtime_bridge.paths import runtime_bridge_paths
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.gateway import ToolApprovalDecision
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE, ToolOutputStore
from agent_factory.tooling.providers import PackageToolProvider, ToolProviderContext
from agent_factory.tooling.spec import ToolRiskResult, ToolSpec


_BRIDGE_PATHS = runtime_bridge_paths()
PACKAGE_ROOT = _BRIDGE_PATHS.package_root
ARTIFACTS_ROOT = _BRIDGE_PATHS.artifacts_root
RUNTIME_ROOT = _BRIDGE_PATHS.runtime_root
WORKDIR_ROOT = _BRIDGE_PATHS.workdir_root


def main() -> int:
    try:
        request = _read_request()
        result = _run_probe(request)
    except Exception as exc:
        result = {
            "status": "failed",
            "phase": "probe_runner",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")
    return 0 if result.get("status") == "completed" else 1


def _read_request() -> dict[str, Any]:
    raw = sys.stdin.read()
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("probe request must be a JSON object")
    return payload


def _run_probe(request: dict[str, Any]) -> dict[str, Any]:
    started_at = time.monotonic()
    tool_id = str(request.get("tool_id") or "").strip()
    arguments = request.get("arguments") if isinstance(request.get("arguments"), dict) else {}
    if not tool_id:
        raise ValueError("tool_id is required")
    dependency_report = {"status": "complete", "source": "environment_lock"}
    _emit_progress("discovering_tools", tool_id=tool_id)
    discovery = PackageToolProvider().discover(ToolProviderContext(package_root=PACKAGE_ROOT))
    specs = {spec.id: spec for spec in discovery.tool_specs}
    spec = specs.get(tool_id)
    if spec is None:
        return {
            "status": "failed",
            "phase": "tool_discovery",
            "tool_id": tool_id,
            "arguments": arguments,
            "dependency_report": dependency_report,
            "diagnostics": [_json_safe(item) for item in discovery.diagnostics],
            "observation": {},
            "captured_stdout": "",
            "captured_stderr": "",
            "duration_ms": _duration_ms(started_at),
            "errors": [f"package tool is not available: {tool_id}"],
        }
    _emit_progress("compiling_tool", tool_id=tool_id)
    try:
        compiler = ToolCompiler(
            package_root=PACKAGE_ROOT,
            resources=_probe_resources(request),
            approval_handler=_approval_handler,
        )
        tool = compiler.compile(spec)
    except Exception as exc:
        return {
            "status": "failed",
            "phase": "tool_compile",
            "tool_id": tool_id,
            "arguments": arguments,
            "dependency_report": dependency_report,
            "diagnostics": [_json_safe(item) for item in discovery.diagnostics],
            "observation": {},
            "captured_stdout": "",
            "captured_stderr": "",
            "duration_ms": _duration_ms(started_at),
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    _emit_progress("executing_tool", tool_id=tool_id)
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            observation = tool.invoke(arguments)
    except Exception as exc:
        _emit_progress(
            "tool_execution_finished",
            tool_id=tool_id,
            status="failed",
            error_type=type(exc).__name__,
        )
        return {
            "status": "failed",
            "phase": "tool_execution",
            "tool_id": tool_id,
            "arguments": arguments,
            "dependency_report": dependency_report,
            "diagnostics": [_json_safe(item) for item in discovery.diagnostics],
            "observation": {},
            "captured_stdout": stdout.getvalue(),
            "captured_stderr": stderr.getvalue(),
            "duration_ms": _duration_ms(started_at),
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    observation_payload = observation if isinstance(observation, dict) else {"status": "invalid_output", "message": str(observation)}
    _emit_progress(
        "tool_execution_finished",
        tool_id=tool_id,
        status=str(observation_payload.get("status") or "unknown"),
    )
    return {
        "status": "completed" if observation_payload.get("status") == "completed" else "failed",
        "phase": "tool_execution",
        "tool_id": tool_id,
        "arguments": arguments,
        "dependency_report": dependency_report,
        "diagnostics": [_json_safe(item) for item in discovery.diagnostics],
        "observation": observation_payload,
        "captured_stdout": stdout.getvalue(),
        "captured_stderr": stderr.getvalue(),
        "duration_ms": _duration_ms(started_at),
        "errors": [],
    }


def _probe_resources(request: dict[str, Any]) -> dict[str, Any]:
    runtime_resources = request.get("runtime_resources")
    configured = dict(runtime_resources) if isinstance(runtime_resources, dict) else {}
    return {
        **configured,
        "package_root": str(PACKAGE_ROOT),
        "runtime_root": str(RUNTIME_ROOT),
        "artifacts_root": str(ARTIFACTS_ROOT),
        "workdir_root": str(WORKDIR_ROOT),
        "workspace_root": str(PACKAGE_ROOT),
        TOOL_OUTPUT_STORE_RESOURCE: ToolOutputStore(RUNTIME_ROOT / "tool_outputs"),
    }


def _approval_handler(spec: ToolSpec, arguments: dict[str, Any], risk: ToolRiskResult) -> ToolApprovalDecision:
    del spec, arguments, risk
    return ToolApprovalDecision(action="approve")


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _duration_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def _emit_progress(stage: str, **detail: Any) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "type": "probe_progress",
                "stage": stage,
                "detail": _json_safe(detail),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())

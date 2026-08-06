import json
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from buildguard.exceptions import EndpointSecurityError
from buildguard.logging_system.jsonl_writer import JsonlWriter
from buildguard.security.audit import ToolAuditLogger
from buildguard.security.confirmation import ConfirmationManager
from buildguard.security.network_guard import NetworkGuard
from buildguard.security.path_guard import PathGuard
from buildguard.security.permission_engine import PermissionEngine
from buildguard.tools.base import ToolDefinition
from buildguard.tools.builtin.file_tools import register_file_tools
from buildguard.tools.executor import ToolExecutor
from buildguard.tools.registry import ToolRegistry
from buildguard.tools.schemas import ToolExecutionRequest


class ValueInput(BaseModel):
    value: str


class ValueOutput(BaseModel):
    value: str


def definition(
    *,
    name: str = "test_tool",
    permission: str = "auto",
    timeout: float = 1,
    read_only: bool = True,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="A fixed test tool",
        input_schema=ValueInput,
        output_schema=ValueOutput,
        permission=permission,  # type: ignore[arg-type]
        read_only=read_only,
        timeout_seconds=timeout,
        category="test",
    )


def executor(tmp_path: Path, registry: ToolRegistry) -> tuple[ToolExecutor, ConfirmationManager]:
    confirmations = ConfirmationManager(ttl_seconds=60)
    writer = JsonlWriter(tmp_path / "audit.jsonl")
    runner = ToolExecutor(
        registry,
        PermissionEngine(confirmations),
        ToolAuditLogger(writer),
        retry_attempts=1,
    )
    return runner, confirmations


def request(tool: str = "test_tool", **arguments: Any) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        session_id="session",
        task_id="task",
        actor="tester",
        tool_name=tool,
        arguments=arguments or {"value": "ok"},
    )


def test_normal_directory_lists_relative_valid_images(tmp_path: Path) -> None:
    root = tmp_path / "uploads"
    root.mkdir()
    (root / "one.jpg").write_bytes(b"\xff\xd8image")
    (root / "two.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
    (root / "broken.jpg").write_bytes(b"bad")
    registry = ToolRegistry()
    register_file_tools(registry, PathGuard([root]), root, max_items=2)
    tool = registry.get("list_inspection_images")
    output = tool.handler(tool.definition.input_schema(directory=".", max_items=2))
    assert [str(path) for path in output.images] == ["one.jpg", "two.png"]  # type: ignore[attr-defined]
    assert output.skipped == 1  # type: ignore[attr-defined]


def test_path_traversal_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    guard = PathGuard([root])
    with pytest.raises(PermissionError, match="escapes"):
        guard.resolve_read(Path("../outside.txt"))


def test_symlink_escape_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        escaped_file = link / "secret.txt"
        original_resolve = Path.resolve

        def simulated_resolve(path: Path, strict: bool = False) -> Path:
            if path == escaped_file:
                return (outside / "secret.txt").absolute()
            return original_resolve(path, strict=strict)

        monkeypatch.setattr(Path, "resolve", simulated_resolve)
    with pytest.raises(PermissionError, match="escapes"):
        PathGuard([root]).resolve_read(Path("escape/secret.txt"))


@pytest.mark.parametrize(
    "filename", [".env", "id_rsa", "id_ed25519", "server.pem", "private.key", "credentials.json"]
)
def test_sensitive_files_are_blocked(tmp_path: Path, filename: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PermissionError, match="Sensitive"):
        PathGuard([root]).resolve_read(Path(filename))


def test_unauthorized_write_and_overwrite_confirmation(tmp_path: Path) -> None:
    read_root = tmp_path / "read"
    write_root = tmp_path / "write"
    read_root.mkdir()
    write_root.mkdir()
    with pytest.raises(PermissionError, match="No write roots"):
        PathGuard([read_root]).resolve_write(Path("report.md"))
    report = write_root / "report.md"
    report.write_text("old", encoding="utf-8")
    guard = PathGuard([read_root], [write_root])
    with pytest.raises(PermissionError, match="requires confirmation"):
        guard.resolve_write(Path("report.md"))
    assert guard.resolve_write(Path("report.md"), overwrite_confirmed=True) == report.resolve()


def test_remote_network_address_is_blocked() -> None:
    guard = NetworkGuard(["http://127.0.0.1:8080/v1"])
    guard.validate("http://127.0.0.1:8080/models")
    with pytest.raises(EndpointSecurityError):
        guard.validate("https://api.example.com/v1")
    with pytest.raises(EndpointSecurityError):
        NetworkGuard(["http://8.8.8.8:80"]).validate("http://8.8.8.8:80/data")


def test_tool_timeout_is_contained_and_audited(tmp_path: Path) -> None:
    registry = ToolRegistry()

    def slow(raw: BaseModel) -> ValueOutput:
        time.sleep(0.1)
        return ValueOutput(value=str(raw.value))  # type: ignore[attr-defined]

    registry.register(definition(timeout=0.01), slow)
    runner, _ = executor(tmp_path, registry)
    result = runner.execute(request())
    assert not result.success
    assert "timed out" in (result.error or "")


def test_tool_exception_does_not_escape(tmp_path: Path) -> None:
    registry = ToolRegistry()

    def broken(_: BaseModel) -> ValueOutput:
        raise RuntimeError("boom")

    registry.register(definition(), broken)
    runner, _ = executor(tmp_path, registry)
    result = runner.execute(request())
    assert not result.success
    assert "boom" in (result.error or "")


def test_confirmation_and_complete_audit_record(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        definition(permission="confirm"),
        lambda raw: ValueOutput(value=raw.value),  # type: ignore[attr-defined]
    )
    runner, confirmations = executor(tmp_path, registry)
    pending = runner.execute(request(password="secret", value="approved"))
    assert not pending.success
    confirmation_id = pending.output["confirmation_id"]  # type: ignore[index]
    confirmations.decide(str(confirmation_id), True)
    approved_request = request(password="secret", value="approved")
    approved_request.confirmation_id = str(confirmation_id)
    result = runner.execute(approved_request)
    assert result.success
    records = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 2
    final = records[-1]
    assert final["actor"] == "tester"
    assert final["task_id"] == "task"
    assert final["session_id"] == "session"
    assert final["tool_name"] == "test_tool"
    assert final["parameter_summary"]["password"] == "********"
    assert final["permission_decision"] == "allow"
    assert final["confirmation_result"] == "approved"
    assert final["started_at"].endswith("Z")
    assert final["ended_at"].endswith("Z")
    assert final["execution_status"] == "success"
    assert final["error"] is None


def test_registry_unique_selective_and_disable() -> None:
    registry = ToolRegistry()
    registry.register(definition(), lambda raw: ValueOutput(value="ok"))
    with pytest.raises(ValueError, match="already"):
        registry.register(definition(), lambda raw: ValueOutput(value="duplicate"))
    assert [item.name for item in registry.candidates("test")] == ["test_tool"]
    assert registry.candidates("inspection") == []
    registry.disable("test_tool")
    with pytest.raises(PermissionError, match="disabled"):
        registry.get("test_tool")

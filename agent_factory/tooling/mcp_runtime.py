from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import importlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import threading
from typing import Any, AsyncIterator, Callable

from agent_factory.tooling.execution_context import register_runtime_tool_cancellation
from agent_factory.tooling.providers.mcp import (
    MCPDiscoveredTool,
    MCPServerConfig,
    MCPServersConfig,
)


class MCPRuntimeError(RuntimeError):
    pass


class MCPRuntimeCancelled(MCPRuntimeError):
    pass


MCP_CLEANUP_GRACE_SECONDS = 5.0


@dataclass(slots=True)
class MCPRuntimeOperation:
    wait_without_deadline: bool = False
    stderr_callback: Callable[[MCPServerConfig, str], None] | None = None
    _cancelled: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    _task: asyncio.Task[Any] | None = field(default=None, init=False, repr=False)
    _pending_stderr: list[tuple[MCPServerConfig, str]] = field(default_factory=list, init=False, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> bool:
        if self._cancelled.is_set():
            return False
        self._cancelled.set()
        with self._lock:
            loop = self._loop
            task = self._task
        if loop is not None and task is not None and not loop.is_closed():
            loop.call_soon_threadsafe(task.cancel)
        return True

    def bind(self, task: asyncio.Task[Any]) -> None:
        with self._lock:
            loop = asyncio.get_running_loop()
            self._loop = loop
            self._task = task
            pending = self._pending_stderr
            self._pending_stderr = []
        for server, line in pending:
            loop.call_soon(self._deliver_stderr, server, line)
        if self.cancelled:
            task.cancel()

    def unbind(self, task: asyncio.Task[Any]) -> None:
        with self._lock:
            if self._task is task:
                self._task = None
                self._loop = None

    def emit_stderr(self, server: MCPServerConfig, line: str) -> None:
        if self.stderr_callback is None:
            return
        with self._lock:
            loop = self._loop
            if loop is None or loop.is_closed():
                self._pending_stderr.append((server, line))
                return
        loop.call_soon_threadsafe(self._deliver_stderr, server, line)

    def _deliver_stderr(self, server: MCPServerConfig, line: str) -> None:
        if self.stderr_callback is not None:
            self.stderr_callback(server, line)


class MCPRuntimeClient:
    def __init__(self, server: MCPServerConfig, *, operation: MCPRuntimeOperation | None = None) -> None:
        self.server = server
        self.operation = operation
        self._tool_cache: list[MCPDiscoveredTool] | None = None
        self._stderr_logs: list[str] = []

    def list_tools(self) -> list[MCPDiscoveredTool]:
        if self._tool_cache is None:
            operation = self.operation or MCPRuntimeOperation()
            timeout_seconds = self._operation_timeout_seconds()
            self._tool_cache = _run_async(
                self._list_tools(operation=operation),
                timeout_seconds=timeout_seconds,
                operation=operation,
                description=f"list tools for MCP server {self.server.server_id}",
            )
        return list(self._tool_cache)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        operation = MCPRuntimeOperation()
        unregister = register_runtime_tool_cancellation(operation.cancel)
        try:
            return _run_async(
                self._call_tool(tool_name, arguments, operation=operation),
                timeout_seconds=self.server.timeout_seconds,
                operation=operation,
                description=f"call MCP tool {self.server.server_id}/{tool_name}",
            )
        finally:
            unregister()

    def stderr_logs(self) -> list[str]:
        return list(self._stderr_logs)

    async def _list_tools(
        self,
        *,
        operation: MCPRuntimeOperation | None = None,
    ) -> list[MCPDiscoveredTool]:
        async with self._session(operation=operation) as session:
            response = await _with_timeout(
                session.list_tools(),
                timeout_seconds=self._operation_timeout_seconds(),
                operation=f"list tools for MCP server {self.server.server_id}",
                runtime_operation=operation,
            )
            tools = (
                response.get("tools", response)
                if isinstance(response, dict)
                else getattr(response, "tools", response)
            )
            return [_normalize_tool(tool) for tool in tools]

    async def _call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        operation: MCPRuntimeOperation,
    ) -> dict[str, Any]:
        async with self._session(operation=operation) as session:
            result = await _with_timeout(
                session.call_tool(tool_name, arguments),
                timeout_seconds=self.server.timeout_seconds,
                operation=f"call MCP tool {self.server.server_id}/{tool_name}",
                runtime_operation=operation,
            )
        return _normalize_call_result(result)

    @asynccontextmanager
    async def _session(
        self,
        *,
        operation: MCPRuntimeOperation | None = None,
    ) -> AsyncIterator[Any]:
        sdk = _load_mcp_sdk()
        if self.server.transport == "stdio":
            async with self._stdio_session(sdk, operation=operation) as session:
                yield session
            return
        if self.server.transport in {"streamable_http", "sse"}:
            async with self._remote_session(sdk, operation=operation) as session:
                yield session
            return
        raise MCPRuntimeError(f"unsupported MCP transport: {self.server.transport}")

    @asynccontextmanager
    async def _stdio_session(
        self,
        sdk: dict[str, Any],
        *,
        operation: MCPRuntimeOperation | None = None,
    ) -> AsyncIterator[Any]:
        if not self.server.command:
            raise MCPRuntimeError(f"MCP stdio server requires command: {self.server.server_id}")
        env = {**os.environ, **self.server.env}
        cwd = str(Path(self.server.cwd).expanduser().resolve()) if self.server.cwd else None
        params_kwargs = {
            "command": self.server.command,
            "args": self.server.args,
            "env": env,
        }
        if cwd is not None:
            params_kwargs["cwd"] = cwd
        try:
            server_params = sdk["StdioServerParameters"](**params_kwargs)
        except TypeError:
            params_kwargs.pop("cwd", None)
            server_params = sdk["StdioServerParameters"](**params_kwargs)
        stderr_capture = _MCPStderrCapture(
            on_line=(lambda line: operation.emit_stderr(self.server, line)) if operation else None
        )
        try:
            stdio_context = sdk["stdio_client"](server_params, errlog=stderr_capture)
        except TypeError:
            stdio_context = sdk["stdio_client"](server_params)
        try:
            async with stdio_context as streams:
                read_stream, write_stream = streams
                async with sdk["ClientSession"](read_stream, write_stream) as session:
                    await _with_timeout(
                        session.initialize(),
                        timeout_seconds=self._operation_timeout_seconds(),
                        operation=f"initialize MCP server {self.server.server_id}",
                        runtime_operation=operation,
                    )
                    yield session
        finally:
            stderr_capture.close()
            self._stderr_logs.extend(stderr_capture.lines())

    @asynccontextmanager
    async def _remote_session(
        self,
        sdk: dict[str, Any],
        *,
        operation: MCPRuntimeOperation | None = None,
    ) -> AsyncIterator[Any]:
        if not self.server.url:
            raise MCPRuntimeError(f"MCP {self.server.transport} server requires url: {self.server.server_id}")
        client_factory = sdk.get(self.server.transport)
        if client_factory is None:
            raise MCPRuntimeError(f"Python MCP SDK does not provide {self.server.transport} client support")
        try:
            client_context = client_factory(self.server.url, headers=dict(self.server.headers))
        except TypeError:
            client_context = client_factory(self.server.url)
        async with client_context as streams:
            if not isinstance(streams, tuple) or len(streams) < 2:
                raise MCPRuntimeError(f"invalid {self.server.transport} client streams")
            read_stream, write_stream = streams[0], streams[1]
            async with sdk["ClientSession"](read_stream, write_stream) as session:
                await _with_timeout(
                    session.initialize(),
                    timeout_seconds=self._operation_timeout_seconds(),
                    operation=f"initialize MCP server {self.server.server_id}",
                    runtime_operation=operation,
                )
                yield session

    def _operation_timeout_seconds(self) -> float | None:
        if self.operation is not None and self.operation.wait_without_deadline:
            return None
        return self.server.timeout_seconds


class MCPRuntimeManager:
    def __init__(
        self,
        config: MCPServersConfig | dict[str, Any] | None = None,
        *,
        operation: MCPRuntimeOperation | None = None,
    ) -> None:
        self.config = config if isinstance(config, MCPServersConfig) else MCPServersConfig.model_validate(config or {})
        self._clients: dict[str, MCPRuntimeClient] = {
            server.server_id: MCPRuntimeClient(server, operation=operation) if operation else _cached_client(server)
            for server in self.config.servers
            if server.enabled
        }

    def clients(self) -> dict[str, MCPRuntimeClient]:
        return dict(self._clients)


_MCP_CLIENT_CACHE: dict[str, MCPRuntimeClient] = {}


def _cached_client(server: MCPServerConfig) -> MCPRuntimeClient:
    key = json.dumps(server.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    client = _MCP_CLIENT_CACHE.get(key)
    if client is None:
        client = MCPRuntimeClient(server)
        _MCP_CLIENT_CACHE[key] = client
    return client


class _MCPStderrCapture:
    def __init__(self, on_line: Callable[[str], None] | None = None) -> None:
        self._on_line = on_line
        self._lines: list[str] = []
        self._lock = threading.RLock()
        read_fd, write_fd = os.pipe()
        self._reader = os.fdopen(read_fd, mode="r", encoding="utf-8", errors="replace")
        self._writer = os.fdopen(write_fd, mode="w", encoding="utf-8", errors="replace")
        self._thread = threading.Thread(target=self._consume, name="mcp-stderr", daemon=True)
        self._thread.start()

    def write(self, value: Any) -> int:
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
        return self._writer.write(text)

    def flush(self) -> None:
        self._writer.flush()

    def fileno(self) -> int:
        return self._writer.fileno()

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def close(self) -> None:
        if not self._writer.closed:
            self._writer.close()
        self._thread.join(timeout=MCP_CLEANUP_GRACE_SECONDS)

    def _consume(self) -> None:
        try:
            try:
                for raw_line in self._reader:
                    line = raw_line.strip()
                    if not line:
                        continue
                    with self._lock:
                        self._lines.append(line)
                    if self._on_line is not None:
                        self._on_line(line)
            except (OSError, ValueError):
                pass
        finally:
            if not self._reader.closed:
                self._reader.close()


def _run_async(
    coro: Any,
    *,
    timeout_seconds: float | None,
    operation: MCPRuntimeOperation | None,
    description: str,
) -> Any:
    outcome: Queue[tuple[str, Any]] = Queue(maxsize=1)

    def run() -> None:
        try:
            outcome.put(("result", asyncio.run(coro)))
        except BaseException as exc:
            outcome.put(("error", exc))

    worker = threading.Thread(target=run, name="mcp-runtime-call", daemon=True)
    worker.start()
    hard_deadline = None if timeout_seconds is None else timeout_seconds + MCP_CLEANUP_GRACE_SECONDS
    waited = 0.0
    poll_seconds = 0.05
    while True:
        if operation is not None and operation.cancelled:
            try:
                kind, value = outcome.get(timeout=MCP_CLEANUP_GRACE_SECONDS)
            except Empty as exc:
                raise MCPRuntimeCancelled(f"{description} did not stop within cleanup grace period") from exc
            return _resolve_async_outcome(kind, value)
        remaining = None if hard_deadline is None else hard_deadline - waited
        if remaining is not None and remaining <= 0:
            if operation is not None:
                operation.cancel()
            raise MCPRuntimeError(
                f"{description} exceeded its {timeout_seconds:g}s timeout and cleanup did not finish"
            )
        interval = poll_seconds if remaining is None else min(poll_seconds, remaining)
        try:
            kind, value = outcome.get(timeout=interval)
        except Empty:
            waited += interval
            continue
        return _resolve_async_outcome(kind, value)


def _resolve_async_outcome(kind: str, value: Any) -> Any:
    if kind == "error":
        raise value
    return value


async def _with_timeout(
    coro: Any,
    *,
    timeout_seconds: float | None,
    operation: str,
    runtime_operation: MCPRuntimeOperation | None = None,
) -> Any:
    task = asyncio.ensure_future(coro)
    if runtime_operation is not None:
        runtime_operation.bind(task)
    try:
        if timeout_seconds is None:
            return await task
        return await asyncio.wait_for(task, timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise MCPRuntimeError(f"{operation} timed out after {timeout_seconds:g}s") from exc
    except asyncio.CancelledError as exc:
        if runtime_operation is not None and runtime_operation.cancelled:
            raise MCPRuntimeCancelled(f"{operation} was stopped by the user") from exc
        raise
    finally:
        if runtime_operation is not None:
            runtime_operation.unbind(task)


def _load_mcp_sdk() -> dict[str, Any]:
    try:
        mcp_module = importlib.import_module("mcp")
        stdio_module = importlib.import_module("mcp.client.stdio")
    except ModuleNotFoundError as exc:
        raise MCPRuntimeError("Python package 'mcp' is required to use MCP servers") from exc
    sdk = {
        "ClientSession": mcp_module.ClientSession,
        "StdioServerParameters": mcp_module.StdioServerParameters,
        "stdio_client": stdio_module.stdio_client,
    }
    for transport, module_name, attribute in (
        ("streamable_http", "mcp.client.streamable_http", "streamablehttp_client"),
        ("sse", "mcp.client.sse", "sse_client"),
    ):
        try:
            sdk[transport] = getattr(importlib.import_module(module_name), attribute)
        except (ModuleNotFoundError, AttributeError):
            sdk[transport] = None
    return sdk


def _normalize_tool(tool: Any) -> MCPDiscoveredTool:
    payload = _model_dump(tool)
    name = str(payload.get("name") or "")
    input_schema = payload.get("input_schema") or payload.get("inputSchema") or {}
    output_schema = payload.get("output_schema") or payload.get("outputSchema") or {}
    return MCPDiscoveredTool(
        name=name,
        description=str(payload.get("description") or ""),
        input_schema=input_schema if isinstance(input_schema, dict) else {},
        output_schema=output_schema if isinstance(output_schema, dict) else {},
    )


def _normalize_call_result(result: Any) -> dict[str, Any]:
    payload = _model_dump(result)
    if payload.get("isError") is True or payload.get("is_error") is True:
        raise MCPRuntimeError(_mcp_tool_error_message(payload))
    structured = payload.get("structured_content") or payload.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = payload.get("content")
    if content is not None:
        structured_text = _mcp_json_text_content(content)
        if structured_text is not None:
            return structured_text
        return {"content": content}
    return payload


def _mcp_json_text_content(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        return None
    text = content[0].get("text")
    if not isinstance(text, str):
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _mcp_tool_error_message(payload: dict[str, Any]) -> str:
    structured = payload.get("structured_content") or payload.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("error", "message", "detail"):
            value = structured.get(key)
            if value:
                return _mcp_error_value_text(value)
    content = payload.get("content")
    if isinstance(content, list):
        messages = [
            _mcp_error_text_content(str(item.get("text") or "").strip())
            for item in content
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        if messages:
            return "\n".join(messages)
    if content:
        return _mcp_error_value_text(content)
    return "MCP tool returned isError=true without an error message"


def _mcp_error_text_content(value: str) -> str:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(decoded, dict):
        for key in ("error", "message", "detail"):
            detail = decoded.get(key)
            if detail:
                return _mcp_error_value_text(detail)
    return _mcp_error_value_text(decoded)


def _mcp_error_value_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip() or "MCP tool execution failed"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json", by_alias=True)
        return dumped if isinstance(dumped, dict) else {"result": dumped}
    if hasattr(value, "dict"):
        dumped = value.dict()
        return dumped if isinstance(dumped, dict) else {"result": dumped}
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key))
    }

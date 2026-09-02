"""Module 1 — LSP sidecar.

Runs headless language servers over stdio and collects publishDiagnostics
for candidate files. One warm process per language per session.

Supported:
    rust  → rust-analyzer
    go    → gopls
    c/cpp → clangd
    py    → pyright-langserver --stdio
    ts/js → typescript-language-server --stdio

Usage:
    sidecar = LspSidecar(lang="rust", workspace=Path("/workspace"))
    await sidecar.start()
    diagnostics = await sidecar.get_diagnostics(files)
    await sidecar.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from . import DiagnosticSection

logger = logging.getLogger(__name__)

# Per-language server commands.  Checked via shutil.which at runtime.
_LANG_SERVER: dict[str, list[str]] = {
    "rust": ["rust-analyzer"],
    "go": ["gopls"],
    "c": ["clangd", "--log=error"],
    "cpp": ["clangd", "--log=error"],
    "py": ["pyright-langserver", "--stdio"],
    "python": ["pyright-langserver", "--stdio"],
    "ts": ["typescript-language-server", "--stdio"],
    "js": ["typescript-language-server", "--stdio"],
    "typescript": ["typescript-language-server", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
}

_EXT_TO_LANG: dict[str, str] = {
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
}

_LSP_INIT_TIMEOUT = 15.0
_FILE_DIAG_TIMEOUT = 30.0


def detect_server(lang: str) -> str | None:
    """Return the binary name if a server for lang is available, else None."""
    cmd = _LANG_SERVER.get(lang)
    if not cmd:
        return None
    return shutil.which(cmd[0])


def record_versions(workspace: Path, langs: list[str]) -> dict[str, str]:
    """Record LSP server versions in session WAL-compatible dict."""
    versions: dict[str, str] = {}
    for lang in langs:
        cmd = _LANG_SERVER.get(lang)
        if not cmd:
            continue
        binary = shutil.which(cmd[0])
        if not binary:
            versions[lang] = "not_found"
            continue
        try:
            asyncio.get_event_loop().run_until_complete(
                asyncio.create_subprocess_exec(
                    binary,
                    "--version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            )
        except Exception:
            versions[lang] = "version_error"
            continue
        versions[lang] = binary
    return versions


class _LspMessage:
    """Minimal LSP JSON-RPC message builder/parser."""

    @staticmethod
    def encode(obj: dict[str, Any]) -> bytes:
        body = json.dumps(obj).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        return header + body

    @staticmethod
    async def read(reader: asyncio.StreamReader) -> dict[str, Any] | None:
        try:
            header_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not header_line:
                return None
            length = 0
            while header_line.strip():
                if header_line.lower().startswith(b"content-length"):
                    length = int(header_line.split(b":")[1].strip())
                header_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if length == 0:
                return None
            body = await asyncio.wait_for(reader.readexactly(length), timeout=10.0)
            return json.loads(body.decode("utf-8"))
        except Exception:
            return None


class LspSidecar:
    """Headless LSP client for a single language / workspace."""

    def __init__(self, lang: str, workspace: Path, timeout: float = _FILE_DIAG_TIMEOUT):
        self.lang = lang
        self.workspace = workspace
        self.timeout = timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._msg_id = 0
        self._pending_diags: dict[str, list[dict[str, Any]]] = {}

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def start(self) -> bool:
        """Start the language server.  Returns False if unavailable."""
        cmd = _LANG_SERVER.get(self.lang)
        if not cmd:
            logger.debug("No LSP server configured for lang=%s", self.lang)
            return False
        binary = shutil.which(cmd[0])
        if not binary:
            logger.debug("LSP server not found: %s", cmd[0])
            return False

        full_cmd = [binary] + cmd[1:]
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self.workspace),
            )
        except Exception as exc:
            logger.warning("Failed to start LSP server %s: %s", cmd[0], exc)
            return False

        assert self._proc.stdin and self._proc.stdout
        self._writer = self._proc.stdin  # type: ignore[assignment]
        self._reader = self._proc.stdout

        # Send initialize
        init_msg = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "processId": os.getpid(),
                "rootUri": self.workspace.as_uri(),
                "capabilities": {
                    "textDocument": {"publishDiagnostics": {"relatedInformation": False}}
                },
                "workspaceFolders": [{"uri": self.workspace.as_uri(), "name": self.workspace.name}],
            },
        }
        await self._send(init_msg)
        # Wait for initialize response
        try:
            resp = await asyncio.wait_for(
                self._read_until_response(init_msg["id"]),
                timeout=_LSP_INIT_TIMEOUT,
            )
            if resp is None:
                return False
        except TimeoutError:
            logger.warning("LSP initialize timed out for %s", self.lang)
            return False

        # Send initialized notification
        await self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        return True

    async def _send(self, msg: dict[str, Any]) -> None:
        if self._writer is None:
            return
        data = _LspMessage.encode(msg)
        self._writer.write(data)  # type: ignore[union-attr]
        await self._writer.drain()  # type: ignore[union-attr]

    async def _read_until_response(self, req_id: int) -> dict[str, Any] | None:
        assert self._reader
        while True:
            msg = await _LspMessage.read(self._reader)
            if msg is None:
                return None
            # Capture publishDiagnostics notifications
            if msg.get("method") == "textDocument/publishDiagnostics":
                uri = msg.get("params", {}).get("uri", "")
                diags = msg.get("params", {}).get("diagnostics", [])
                self._pending_diags[uri] = diags
            # Return if this is our response
            if msg.get("id") == req_id:
                return msg

    async def get_diagnostics(self, files: list[Path]) -> list[dict[str, Any]]:
        """Open files and collect diagnostics.  Returns flat list."""
        if self._writer is None or self._reader is None:
            return []

        results: list[dict[str, Any]] = []
        for fpath in files:
            if not fpath.exists():
                continue
            uri = fpath.as_uri()
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            lang_id = _EXT_TO_LANG.get(fpath.suffix, self.lang)
            open_msg = {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": lang_id,
                        "version": 1,
                        "text": content,
                    }
                },
            }
            await self._send(open_msg)

            # Drain notifications for up to timeout seconds
            deadline = time.monotonic() + min(self.timeout, _FILE_DIAG_TIMEOUT)
            try:
                while time.monotonic() < deadline:
                    remaining = max(0.1, deadline - time.monotonic())
                    msg = await asyncio.wait_for(_LspMessage.read(self._reader), timeout=remaining)
                    if msg is None:
                        break
                    if msg.get("method") == "textDocument/publishDiagnostics":
                        p = msg.get("params", {})
                        if p.get("uri") == uri:
                            self._pending_diags[uri] = p.get("diagnostics", [])
                            break
                        self._pending_diags[p.get("uri", "")] = p.get("diagnostics", [])
            except TimeoutError:
                pass

            for diag in self._pending_diags.get(uri, []):
                rng = diag.get("range", {}).get("start", {})
                severity_map = {1: "ERROR", 2: "WARN", 3: "INFO", 4: "HINT"}
                results.append(
                    {
                        "file": str(fpath.relative_to(self.workspace)),
                        "line": rng.get("line", 0) + 1,
                        "severity": severity_map.get(diag.get("severity", 1), "?"),
                        "code": str(diag.get("code", "")),
                        "message": diag.get("message", ""),
                        "related_symbols": [
                            r.get("message", "") for r in diag.get("relatedInformation", [])
                        ],
                    }
                )

        return results

    async def stop(self) -> None:
        if self._writer:
            try:
                await self._send(
                    {"jsonrpc": "2.0", "id": self._next_id(), "method": "shutdown", "params": None}
                )
                await self._send({"jsonrpc": "2.0", "method": "exit", "params": None})
            except Exception:
                pass
            try:
                self._writer.close()  # type: ignore[union-attr]
            except Exception:
                pass
        if self._proc:
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except TimeoutError:
                self._proc.kill()


async def run_lsp_pass(
    workspace: Path,
    lang: str,
    files: list[Path],
    timeout: float = _FILE_DIAG_TIMEOUT,
) -> DiagnosticSection:
    """High-level entry point: start server, collect diagnostics, return section."""
    sidecar = LspSidecar(lang=lang, workspace=workspace, timeout=timeout)
    diags: list[dict[str, Any]] = []
    try:
        started = await sidecar.start()
        if started:
            diags = await sidecar.get_diagnostics(files)
    except Exception as exc:
        logger.warning("LSP pass error for %s: %s", lang, exc)
    finally:
        await sidecar.stop()

    section = DiagnosticSection(
        kind="lsp",
        rank=1,
        content=diags,
        token_estimate=sum(len(str(d)) // 4 for d in diags),
    )
    return section

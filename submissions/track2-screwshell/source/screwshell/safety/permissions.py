"""Safety / Permission layer for ScrewShell.

- workspace sandbox: every file access must resolve inside the workspace root
- tool allowlist: only registered read-only tools may run
- path blocklist: secrets dirs are always denied
- dangerous command rejection for shell_readonly
- human approval hook for anything write-like (none in core demo)
- JSON audit log, no remote telemetry
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

BLOCKED_PATH_PATTERNS = [
    re.compile(p) for p in (
        r"(^|/)\.ssh(/|$)", r"(^|/)\.aws(/|$)", r"(^|/)\.gnupg(/|$)",
        r"(^|/)\.config/gcloud(/|$)", r"(^|/)id_rsa", r"(^|/)id_ed25519",
        r"\.pem$", r"(^|/)\.env$", r"(^|/)credentials",
    )
]

DANGEROUS_CMD = re.compile(
    r"(rm\s+-rf|sudo\b|curl[^|]*\|\s*(ba)?sh|wget[^|]*\|\s*(ba)?sh|mkfs|"
    r"dd\s+if=|>\s*/dev/|shutdown|reboot|chmod\s+777|:\(\)\{|\bssh\b|\bscp\b|"
    r"\bnc\b|\bpip\s+install|\bapt\b|\byum\b)", re.I)


@dataclass
class PermissionDecision:
    allowed: bool
    reason: str


class AuditLog:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def record(self, event: str, **kw):
        entry = {"ts": round(time.time(), 3),
                 "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "event": event, **kw}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return entry

    def tail(self, n: int = 20) -> list[dict]:
        if not os.path.isfile(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        return [json.loads(l) for l in lines if l.strip()]


class PermissionGate:
    def __init__(self, workspace: str, allowed_tools: list[str],
                 audit: AuditLog,
                 approval_cb: Optional[Callable[[str], bool]] = None):
        self.workspace = Path(workspace).resolve()
        self.allowed_tools = set(allowed_tools)
        self.audit = audit
        self.approval_cb = approval_cb  # returns True if human approves

    # ---- checks ----

    def check_tool(self, tool: str) -> PermissionDecision:
        if tool not in self.allowed_tools:
            self.audit.record("tool_denied", tool=tool, reason="not in allowlist")
            return PermissionDecision(False, f"tool '{tool}' not in allowlist")
        return PermissionDecision(True, "tool allowed")

    def check_path(self, path: str) -> PermissionDecision:
        try:
            resolved = Path(path).resolve() if os.path.isabs(path) \
                else (self.workspace / path).resolve()
        except (OSError, ValueError) as e:
            return PermissionDecision(False, f"bad path: {e}")
        posix = resolved.as_posix()
        for pat in BLOCKED_PATH_PATTERNS:
            if pat.search(posix):
                self.audit.record("path_denied", path=posix, reason="secrets pattern")
                return PermissionDecision(False, "path matches blocked secret pattern")
        if self.workspace not in resolved.parents and resolved != self.workspace:
            self.audit.record("path_denied", path=posix, reason="outside sandbox")
            return PermissionDecision(
                False, f"path escapes workspace sandbox ({self.workspace})")
        return PermissionDecision(True, "path inside sandbox")

    def check_command(self, cmd: str) -> PermissionDecision:
        m = DANGEROUS_CMD.search(cmd)
        if m:
            self.audit.record("cmd_denied", cmd=cmd[:200], match=m.group(0))
            return PermissionDecision(False, f"dangerous pattern: {m.group(0)!r}")
        return PermissionDecision(True, "command ok")

    def require_approval(self, action: str) -> PermissionDecision:
        """Write-like actions must be approved by a human (UI callback)."""
        if self.approval_cb is None:
            self.audit.record("approval_denied", action=action, reason="no approver")
            return PermissionDecision(False, "no human approver attached")
        ok = bool(self.approval_cb(action))
        self.audit.record("approval", action=action, approved=ok)
        return PermissionDecision(ok, "approved" if ok else "rejected by human")

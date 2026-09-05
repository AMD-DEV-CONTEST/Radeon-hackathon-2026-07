"""Read-only local tool layer for ScrewShell.

All tools run through the PermissionGate (sandbox + allowlist + audit).
Raw outputs go to the ArtifactStore (off-context); the orchestrator only
receives compact digests, keeping the main context small.

Core tools (local only, zero remote APIs):
  rag_search / read_file / list_dir / grep / shell_readonly / rocm_smi

(No web tools exist in this codebase. Earlier README/SPEC drafts mentioned
"web_search / fetch_url, disabled by default" -- those were never implemented;
the `enable_web` constructor flag is kept for API compatibility only and is
ignored. Docs that still claim web tools ship disabled are stale; code wins.)
"""
from __future__ import annotations

import fnmatch
import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from screwshell.safety.permissions import PermissionGate

log = logging.getLogger("screwshell.tools")

# shell_readonly fail-closed allowlist (2026-08-04, P1 security fix).
# The old design was a *blocklist* regex plus shell=True: `rm -rf`, `sudo`
# etc. were denied, but anything not listed (echo $(cat /etc/passwd),
# `cat /etc/passwd | grep root`, `ls; rm -rf /`, backticks, $IFS tricks)
# sailed straight through -- a prompt-injected model could run arbitrary
# shell. The gate is now three fail-closed layers ON TOP of the legacy
# DANGEROUS_CMD blocklist (kept for its audit trail):
#   1. command argv[0] must be in ALLOWED_SHELL_CMDS;
#   2. the command string must contain no shell metacharacter
#      (; & | < > ` $ ( ) \ newline) -- so a shell=True run can only ever
#      execute the allowlisted command, never chain a second one, expand a
#      variable or read a substitution;
#   3. git subcommands and find actions are further restricted to read-only
#      subsets, and path-looking arguments cannot escape the workspace.
# globbing/quoting stay available (that is why we keep shell=True and ban
# metacharacters instead of switching to shell=False argv).
ALLOWED_SHELL_CMDS = {
    "wc", "du", "ls", "head", "tail", "stat", "df", "date", "sort",
    "uniq", "fold", "cut", "tr", "cat", "echo", "find", "grep", "git",
}
GIT_READONLY_SUBCOMMANDS = {
    "log", "status", "diff", "show", "ls-files", "blame", "rev-parse",
    "shortlog", "describe", "branch", "tag",
}
FIND_BANNED_ACTIONS = ("-exec", "-execdir", "-delete", "-ok")
_SHELL_META = re.compile(r"[;&|<>`$\\\n\r]")

# shell_readonly is a read-only probe tool, but absolute / home paths and
# parent-dir traversal would let it reach outside the workspace (e.g.
# `cat /etc/shadow`). Reject them for file-ish arguments.
_PATH_ESCAPE = re.compile(r"^(/|~|\.\.($|/))|/\.\.($|/)")


def _shell_gate_reason(cmd: str) -> str | None:
    """Return a denial reason, or None when the command may run."""
    if not cmd or not cmd.strip():
        return "empty command"
    if _SHELL_META.search(cmd):
        return "shell metacharacter (e.g. ; & | < > $ ` \\ newline) not allowed"
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        return f"unparseable command: {e}"
    if not argv:
        return "empty command"
    prog = argv[0]
    if prog not in ALLOWED_SHELL_CMDS:
        return f"command {prog!r} not in the read-only allowlist"
    if prog == "git":
        sub = argv[1] if len(argv) > 1 else ""
        if sub not in GIT_READONLY_SUBCOMMANDS:
            return f"git subcommand {sub!r} is not read-only"
    if prog == "find":
        for a in argv[1:]:
            if a in FIND_BANNED_ACTIONS:
                return f"find action {a!r} can mutate files"
    for a in argv[1:]:
        if _PATH_ESCAPE.search(a):
            return f"path escapes the workspace sandbox: {a!r}"
    return None


@dataclass
class ToolResult:
    tool: str
    ok: bool
    digest: str                 # compact text for the LLM context
    raw: Any = None             # full payload -> ArtifactStore
    citations: list[dict] = field(default_factory=list)


class Toolkit:
    CORE_TOOLS = ["rag_search", "read_file", "list_dir", "grep",
                  "shell_readonly", "rocm_smi"]

    def __init__(self, gate: PermissionGate, workspace: str,
                 rag_search_fn: Optional[Callable] = None,
                 enable_web: bool = False):
        self.gate = gate
        self.workspace = Path(workspace).resolve()
        self.rag_search_fn = rag_search_fn
        self.enable_web = enable_web  # off by default: core functionality is local-only

    # ---------- dispatch ----------

    def run(self, tool: str, **kw) -> ToolResult:
        dec = self.gate.check_tool(tool)
        if not dec.allowed:
            return ToolResult(tool, False, f"DENIED: {dec.reason}")
        fn = getattr(self, f"_t_{tool}", None)
        if fn is None:
            return ToolResult(tool, False, f"unknown tool {tool}")
        self.gate.audit.record("tool_call", tool=tool,
                               args={k: str(v)[:120] for k, v in kw.items()})
        try:
            return fn(**kw)
        except Exception as e:  # tool errors are data, not crashes
            return ToolResult(tool, False, f"ERROR {type(e).__name__}: {e}")

    def spec(self) -> list[dict]:
        """Tool schemas for the LLM prompt."""
        return [
            {"name": "rag_search", "desc": "Semantic search over the ingested local knowledge base. Args: query (str), top_k (int, default 5). Returns cited chunks.",},
            {"name": "read_file", "desc": "Read a text file inside the workspace. Args: path (str), start_line (int, optional), end_line (int, optional).",},
            {"name": "list_dir", "desc": "List a directory inside the workspace. Args: path (str, default '.').",},
            {"name": "grep", "desc": "Regex search across workspace files. Args: pattern (str), glob (str, default '*'), max_hits (int, default 40).",},
            {"name": "shell_readonly", "desc": "Run a safe read-only shell command inside the workspace (e.g. wc, du, git log). Dangerous commands rejected. Args: cmd (str).",},
            {"name": "rocm_smi", "desc": "Show current AMD GPU utilization/VRAM via rocm-smi. No args.",},
        ]

    # ---------- tools ----------

    def _resolve(self, path: str) -> Path:
        dec = self.gate.check_path(path)
        if not dec.allowed:
            raise PermissionError(dec.reason)
        p = Path(path)
        return p.resolve() if p.is_absolute() else (self.workspace / p).resolve()

    def _t_rag_search(self, query: str, top_k: int = 5) -> ToolResult:
        if self.rag_search_fn is None:
            return ToolResult("rag_search", False, "RAG index not built for this workspace")
        hits = self.rag_search_fn(query, top_k=top_k)
        digest_lines, cites = [], []
        for h in hits:
            loc = f"{h['source']}#L{h['start_line']}-L{h['end_line']}"
            digest_lines.append(f"[{loc}] (score {h['score']:.2f}) {h['text'][:300]}")
            cites.append({"source": h["source"], "start_line": h["start_line"],
                          "end_line": h["end_line"], "score": round(h["score"], 3),
                          "chunk_id": h.get("chunk_id")})
        return ToolResult("rag_search", True,
                          "\n".join(digest_lines) or "no hits",
                          raw=hits, citations=cites)

    def _t_read_file(self, path: str, start_line: int | None = None,
                     end_line: int | None = None) -> ToolResult:
        p = self._resolve(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        s = max(1, start_line or 1)
        e = min(len(lines), end_line or min(len(lines), s + 199))
        body = "\n".join(f"{i}: {lines[i-1]}" for i in range(s, e + 1))
        rel = os.path.relpath(p, self.workspace)
        return ToolResult("read_file", True,
                          f"--- {rel} lines {s}-{e} of {len(lines)} ---\n{body[:6000]}",
                          raw=text,
                          citations=[{"source": rel, "start_line": s, "end_line": e}])

    def _t_list_dir(self, path: str = ".") -> ToolResult:
        p = self._resolve(path)
        entries = []
        for child in sorted(p.iterdir()):
            mark = "/" if child.is_dir() else ""
            size = "" if child.is_dir() else f" ({child.stat().st_size} B)"
            entries.append(f"{child.name}{mark}{size}")
        return ToolResult("list_dir", True, "\n".join(entries[:200]) or "(empty)")

    def _t_grep(self, pattern: str, glob: str = "*", max_hits: int = 40) -> ToolResult:
        rx = re.compile(pattern)
        hits, cites, denied = [], [], 0
        for root, dirs, files in os.walk(self.workspace):
            dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
            for fname in files:
                if not fnmatch.fnmatch(fname, glob):
                    continue
                fp = Path(root) / fname
                # Every candidate file goes through the SAME permission gate as
                # read_file (2026-08-04 P1 fix). The old code walked the tree
                # directly, so BLOCKED_PATH_PATTERNS (.env / .ssh / id_rsa /
                # credentials) were silently bypassable through grep, and a
                # symlink pointing outside the workspace was followed without
                # a sandbox check. Resolve first so a symlink resolves to its
                # real target before the gate inspects it.
                try:
                    rp = fp.resolve()
                except OSError:
                    continue
                if not self.gate.check_path(str(rp)).allowed:
                    denied += 1
                    continue
                if fp.stat().st_size > 2_000_000:
                    continue
                try:
                    for i, line in enumerate(
                            fp.read_text(encoding="utf-8", errors="replace")
                              .splitlines(), 1):
                        if rx.search(line):
                            rel = os.path.relpath(rp, self.workspace)
                            hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                            cites.append({"source": rel, "start_line": i, "end_line": i})
                            if len(hits) >= max_hits:
                                raise StopIteration
                except StopIteration:
                    break
                except OSError:
                    continue
            if len(hits) >= max_hits:
                break
        if denied:
            log.info("grep skipped %d blocked file(s) (secrets/sandbox gate)",
                     denied)
        return ToolResult("grep", True, "\n".join(hits) or "no matches",
                          citations=cites[:20])

    def _t_shell_readonly(self, cmd: str) -> ToolResult:
        dec = self.gate.check_command(cmd)
        if not dec.allowed:
            return ToolResult("shell_readonly", False, f"DENIED: {dec.reason}")
        reason = _shell_gate_reason(cmd)
        if reason is not None:
            self.gate.audit.record("cmd_denied", cmd=cmd[:200],
                                   reason=f"fail-closed gate: {reason}")
            return ToolResult("shell_readonly", False, f"DENIED: {reason}")
        proc = subprocess.run(cmd, shell=True, cwd=self.workspace,
                              capture_output=True, timeout=30)
        # text=True would crash on non-UTF-8 (e.g. Windows cmd.exe GBK) output
        # and leave proc.stdout=None (TypeError on concat). Read bytes and
        # decode lossy instead so a garbled locale never breaks the tool.
        raw = (proc.stdout or b"") + (proc.stderr or b"")
        out = raw.decode("utf-8", errors="replace")[:4000]
        return ToolResult("shell_readonly", proc.returncode == 0,
                          out or f"(exit {proc.returncode}, no output)", raw=out)

    def _t_rocm_smi(self) -> ToolResult:
        try:
            proc = subprocess.run(
                ["rocm-smi", "--showuse", "--showmeminfo", "vram"],
                capture_output=True, text=True, timeout=15)
            return ToolResult("rocm_smi", True, proc.stdout[:2500], raw=proc.stdout)
        except FileNotFoundError:
            return ToolResult("rocm_smi", False, "rocm-smi not available on this host")

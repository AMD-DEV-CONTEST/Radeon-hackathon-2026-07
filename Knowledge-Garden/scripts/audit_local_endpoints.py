#!/usr/bin/env python3
"""audit_local_endpoints.py — local-only endpoint audit (Todo 11 / F4).

Inspects ONLY named endpoint/config assignments:
  - `BASE_URL`-style constants and model/API URL constants (app/llm.py)
  - Vite proxy `target` in web/vite.config.ts
and rejects any configured value whose host is not localhost / 127.0.0.1.
Comments and docstrings are IGNORED — the identical URL inside a comment passes.

Exit 0 when every configured endpoint is local; 1 otherwise (naming the offender).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# cwd-aware: when run inside a disposable worktree (web/vite.config.ts present in
# cwd), audit the WORKTREE files, not the live tree.
if (Path.cwd() / "web" / "vite.config.ts").exists() and Path.cwd() != ROOT:
    ROOT = Path.cwd()

LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "::1")
URL_RE = re.compile(r"https?://([^/:\s'\"]+)")


def _host_of(url: str) -> str | None:
    m = URL_RE.search(url)
    return m.group(1).lower() if m else None


def _is_local(host: str) -> bool:
    return host in LOCAL_HOSTS


def audit_python(path: Path) -> list[str]:
    """Audit named URL constants / assignments in a Python file via AST."""
    offenders: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return [f"{path}: unparseable"]
    for node in ast.walk(tree):
        # skip docstring-only contexts
        targets: list[str] = []
        value: str | None = None
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value.value
        if not targets or value is None:
            continue
        host = _host_of(value)
        if host is None:
            continue
        is_endpoint_const = any(
            "URL" in t.upper() or "BASE" in t.upper() or "ENDPOINT" in t.upper()
            or t in ("DIALOGUE_URL", "BATCH_URL", "FT_DIALOGUE_URL", "FT_BATCH_URL")
            for t in targets)
        if is_endpoint_const and not _is_local(host):
            offenders.append(f"{path}:{node.lineno}: {targets[0]} = {value!r} (host={host})")
    return offenders


def _strip_line_comment(line: str) -> str:
    """Remove a trailing // comment, but NOT // inside a quoted string (e.g. URLs).

    Scans the line tracking quote state; a `//` outside quotes starts a comment.
    """
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote is not None:
            out.append(ch)
            if ch == quote and (i == 0 or line[i - 1] != "\\"):
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            break  # comment
        out.append(ch)
        i += 1
    return "".join(out)


def audit_vite(path: Path) -> list[str]:
    """Audit web/vite.config.ts proxy targets.

    Matches both `target: 'http://...'` and the shorthand `'<path>': 'http://...'`
    proxy value form used by Vite's proxy object. URLs inside comments are ignored.
    """
    offenders: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    # remove /* */ block comments, then strip // line comments (string-aware)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    for i, line in enumerate(text.splitlines(), 1):
        line = _strip_line_comment(line)
        m = re.search(r"target\s*:\s*['\"]([^'\"]+)['\"]", line)
        if not m:
            m = re.search(r"['\"][^'\"]+['\"]\s*:\s*['\"]([^'\"]+)['\"]", line)
        if not m:
            continue
        url = m.group(1)
        host = _host_of(url)
        if host is not None and not _is_local(host):
            offenders.append(f"{path}:{i}: proxy value = {url!r} (host={host})")
    return offenders


def main() -> int:
    offenders: list[str] = []
    for f in (ROOT / "app" / "llm.py",):
        if f.exists():
            offenders += audit_python(f)
    vite = ROOT / "web" / "vite.config.ts"
    if vite.exists():
        offenders += audit_vite(vite)
    if offenders:
        for o in offenders:
            print(f"LOCAL_ENDPOINT_VIOLATION: {o}", file=sys.stderr)
        print("AUDIT_LOCAL_ENDPOINTS_FAIL", file=sys.stderr)
        return 1
    print("AUDIT_LOCAL_ENDPOINTS_OK: all configured endpoints are local-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())

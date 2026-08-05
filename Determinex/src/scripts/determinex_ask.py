"""
scripts/determinex_ask.py — Sprint 1: Diagnostic-First Entry Point
================================================================
Frontier-model-style freeform queries against the Determinex local stack. NO spec
required. Defaults workspace to cwd. Uses determinex-sentinel-v5-dsl (7B Architect)
as the reasoning model with optional workspace RAG, recent-session WAL context,
and stderr-blob diagnosis.

Subcommands:
    ask        Freeform question. Optional --workspace, --stderr, --image,
               --session, --since. Routes through the Sentinel (7B) with
               assembled context.
    where      "Where are we?" — surveys recent sessions, in-flight steps,
               git status, last N failures. No model call needed for the
               quick view; pass --explain to have Sentinel narrate it.
    why        "Why did this break?" — takes --stderr PATH or stdin; assembles
               structured diagnosis and emits a short root-cause hypothesis
               plus the most likely files to inspect.

Examples:
    python scripts/determinex_ask.py ask "what does executor.py do?"
    python scripts/determinex_ask.py where
    python scripts/determinex_ask.py why --stderr last_run.log
    cat err.txt | python scripts/determinex_ask.py why --stderr -

Exit codes: 0 = answered cleanly, 1 = model unavailable, 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

logging.basicConfig(
    level=os.getenv("DETERMINEX_ASK_LOG", "INFO"),
    format="[ASK] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("determinex.ask")

# ── SSRF guard ────────────────────────────────────────────────────────────────
_OLLAMA_URL = os.getenv("DETERMINEX_OLLAMA_URL", "http://localhost:11434")
_parsed = urllib.parse.urlparse(_OLLAMA_URL)
if (_parsed.hostname or "") not in {"localhost", "127.0.0.1", "::1"}:
    raise ValueError(f"DETERMINEX_OLLAMA_URL host '{_parsed.hostname}' not allowed (SSRF guard)")

ARCHITECT_MODEL = os.getenv("DETERMINEX_ARCHITECT_MODEL", "determinex-sentinel-v5-dsl")
ASK_TIMEOUT_S = int(os.getenv("DETERMINEX_ASK_TIMEOUT", "120"))
ASK_NUM_CTX = int(os.getenv("DETERMINEX_ASK_NUM_CTX", "4096"))
ASK_MAX_TOKENS = int(os.getenv("DETERMINEX_ASK_MAX_TOKENS", "512"))


@dataclass
class AskContext:
    question: str
    workspace: Path
    extra_blobs: dict[str, str] = field(default_factory=dict)  # name → content

    def render_prompt(self, system: str) -> tuple[str, str]:
        """Return (system_prompt, user_prompt) capped at ASK_NUM_CTX-ish tokens."""
        parts: list[str] = []
        for name, blob in self.extra_blobs.items():
            if not blob:
                continue
            # Crude truncation by characters; tokenizer-accurate cap happens server-side
            cap = 6000 // max(1, len(self.extra_blobs))
            if len(blob) > cap:
                blob = blob[:cap] + f"\n... [truncated, {len(blob) - cap} chars]"
            parts.append(f"### {name}\n{blob}")
        context_section = "\n\n".join(parts) if parts else "(no auxiliary context attached)"
        user = (
            f"{context_section}\n\n"
            f"### Question\n{self.question}\n\n"
            f"Answer concisely. If you don't have enough information, say so and "
            f"name the single file or command that would resolve the ambiguity."
        )
        return system, user


def _ollama_chat(model: str, system: str, user: str) -> str:
    """POST to /api/chat. Returns the assistant message content, or "" on failure."""
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "num_ctx": ASK_NUM_CTX,
                "num_predict": ASK_MAX_TOKENS,
                "temperature": 0.2,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{_OLLAMA_URL.rstrip('/')}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=ASK_TIMEOUT_S) as resp:  # noqa: S310 (localhost only)
            payload = json.loads(resp.read().decode("utf-8"))
        msg = payload.get("message", {})
        return (msg.get("content") or "").strip()
    except urllib.error.URLError as e:
        log.error("Ollama unreachable at %s: %s", _OLLAMA_URL, e)
        return ""
    except (json.JSONDecodeError, KeyError) as e:
        log.error("Malformed Ollama response: %s", e)
        return ""


# ── Workspace + state collectors ─────────────────────────────────────────────


def _git_summary(workspace: Path, max_lines: int = 30) -> str:
    if not (workspace / ".git").exists():
        return "(not a git repo)"
    try:
        status = subprocess.run(
            ["git", "-C", str(workspace), "status", "--short", "-uno"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        branch = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        log_lines = subprocess.run(
            ["git", "-C", str(workspace), "log", "--oneline", "-10"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        out = f"branch: {branch}\n\nstatus:\n{status or '(clean)'}\n\nrecent log:\n{log_lines}"
        return "\n".join(out.splitlines()[:max_lines])
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return f"(git unavailable: {e})"


def _recent_sessions(workspace: Path, n: int = 3) -> str:
    sessions_dir = workspace / "sessions"
    if not sessions_dir.is_dir():
        return "(no sessions/ directory)"
    entries = sorted(
        (p for p in sessions_dir.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:n]
    if not entries:
        return "(sessions/ empty)"
    lines = []
    for s in entries:
        manifest = s / "manifest.json"
        steps_dir = s / "steps"
        try:
            m = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
            n_steps = len(list(steps_dir.glob("*.complete"))) if steps_dir.is_dir() else 0
            failed = len(list(steps_dir.glob("*.failed"))) if steps_dir.is_dir() else 0
            lines.append(
                f"{s.name[:8]}  lang={m.get('language', '?'):<8} "
                f"steps_done={n_steps}  failed={failed}  budget=${m.get('budget_usd_used', 0):.3f}"
            )
        except (OSError, json.JSONDecodeError):
            lines.append(f"{s.name[:8]}  (manifest unreadable)")
    return "\n".join(lines)


def _scan_workspace_files(workspace: Path, query: str, max_files: int = 8) -> str:
    """Lightweight grep — find files matching keywords from the query."""
    keywords = {w.lower() for w in re.split(r"\W+", query) if len(w) > 3}
    if not keywords:
        return "(no scannable keywords in question)"
    extensions = {".py", ".rs", ".go", ".ts", ".tsx", ".md", ".yaml", ".yml", ".toml"}
    skip = {
        "__pycache__",
        "node_modules",
        ".git",
        "target",
        "venv",
        ".venv",
        "build",
        "dist",
        "logs",
        "sessions",
        ".determinex",
    }
    scored: list[tuple[int, Path]] = []
    count = 0
    for p in workspace.rglob("*"):
        if count > 5000:
            break
        if not p.is_file() or p.suffix not in extensions:
            continue
        if any(part in skip or part.startswith(".") for part in p.relative_to(workspace).parts):
            continue
        count += 1
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = sum(1 for kw in keywords if kw in content.lower())
        if hits:
            scored.append((hits, p))
    scored.sort(reverse=True, key=lambda t: t[0])
    if not scored:
        return "(no files matched keywords)"
    out = []
    for hits, p in scored[:max_files]:
        out.append(f"  • {p.relative_to(workspace)} ({hits} keyword hits)")
    return "\n".join(out)


def _read_blob(spec: str) -> str:
    """Read content from a file path, '-' (stdin), or treat as literal text."""
    if spec == "-":
        return sys.stdin.read()
    p = Path(spec)
    if p.exists() and p.is_file():
        try:
            return p.read_text(encoding="utf-8", errors="replace")[:60_000]
        except OSError as e:
            return f"(unable to read {p}: {e})"
    return spec  # literal text


# ── Subcommands ──────────────────────────────────────────────────────────────


def cmd_ask(args: argparse.Namespace) -> int:
    ctx = AskContext(question=args.question, workspace=Path(args.workspace).resolve())

    if args.stderr:
        ctx.extra_blobs["recent stderr/log"] = _read_blob(args.stderr)
    if args.session_state:
        ctx.extra_blobs["recent sessions"] = _recent_sessions(ctx.workspace)
        ctx.extra_blobs["git state"] = _git_summary(ctx.workspace)
    if args.scan:
        ctx.extra_blobs["likely relevant files"] = _scan_workspace_files(
            ctx.workspace, args.question
        )
    if args.image:
        # Vision integration is Sprint 2 — call out to determinex_vision if available
        try:
            from determinex_vision import describe_image  # type: ignore

            description = describe_image(Path(args.image))
            ctx.extra_blobs[f"image:{Path(args.image).name}"] = description
        except ImportError:
            ctx.extra_blobs["image_warning"] = (
                f"--image {args.image} ignored: determinex_vision not yet installed "
                "(deliverable of Sprint 2)."
            )
        except Exception as e:  # pylint: disable=broad-except
            ctx.extra_blobs["image_error"] = f"vision adapter failed: {e}"
    if args.extra:
        for spec in args.extra:
            if "=" in spec:
                name, value = spec.split("=", 1)
                ctx.extra_blobs[name] = _read_blob(value)
            else:
                ctx.extra_blobs[Path(spec).name] = _read_blob(spec)

    system = (
        "You are Determinex Sentinel, a 7B local Architect. You answer questions about "
        "the Determinex codebase, recent sessions, and debugging signals. Stay concrete: "
        "name files, name commands, name line numbers when you can. If context is "
        "insufficient, name the single thing that would resolve the ambiguity."
    )
    system_prompt, user_prompt = ctx.render_prompt(system)

    t0 = time.monotonic()
    answer = _ollama_chat(args.model, system_prompt, user_prompt)
    elapsed = time.monotonic() - t0

    if not answer:
        print(
            f"ERROR: {args.model} returned no response (Ollama unreachable or model not registered).",
            file=sys.stderr,
        )
        return 1

    if args.json_out:
        print(
            json.dumps(
                {
                    "model": args.model,
                    "answer": answer,
                    "elapsed_s": round(elapsed, 2),
                    "context_blobs": list(ctx.extra_blobs.keys()),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(answer)
        print(f"\n  [{args.model} · {elapsed:.1f}s]", file=sys.stderr)
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    state = {
        "workspace": str(workspace),
        "git": _git_summary(workspace),
        "recent_sessions": _recent_sessions(workspace),
    }
    if args.json_out:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    print("=== Determinex: where-are-we ===")
    print(f"workspace: {state['workspace']}\n")
    print("=== git ===")
    print(state["git"])
    print("\n=== recent sessions ===")
    print(state["recent_sessions"])
    if args.explain:
        ctx = AskContext(
            question="Summarise the project's current state in 4-6 sentences. "
            "What's in progress, what just changed, what looks stuck?",
            workspace=workspace,
            extra_blobs={"git state": state["git"], "recent sessions": state["recent_sessions"]},
        )
        sys_msg = "You are Determinex Sentinel. Summarise project state concisely."
        sp, up = ctx.render_prompt(sys_msg)
        print("\n=== explanation ===")
        narration = _ollama_chat(args.model, sp, up)
        print(narration or "(model unavailable)")
    return 0


def cmd_why(args: argparse.Namespace) -> int:
    stderr_text = _read_blob(args.stderr) if args.stderr else ""
    if not stderr_text.strip():
        print("ERROR: --stderr PATH or '-' (stdin) required for `why`.", file=sys.stderr)
        return 2
    workspace = Path(args.workspace).resolve()
    ctx = AskContext(
        question=(
            "Diagnose the root cause of the failure shown below in 3 lines max. "
            "Then list the most likely 1-3 files to inspect (paths only, no commentary)."
        ),
        workspace=workspace,
        extra_blobs={
            "stderr/log": stderr_text,
            "git state": _git_summary(workspace),
            "recent sessions": _recent_sessions(workspace),
        },
    )
    system = (
        "You are Determinex Sentinel. Given a stderr/log blob and repo state, identify "
        "the single most likely root cause. Cite specific lines or symbols from the "
        "stderr. Do NOT speculate beyond what the stderr supports."
    )
    sp, up = ctx.render_prompt(system)
    diagnosis = _ollama_chat(args.model, sp, up)
    if not diagnosis:
        print("ERROR: model unavailable.", file=sys.stderr)
        return 1
    if args.json_out:
        print(
            json.dumps(
                {"diagnosis": diagnosis, "stderr_bytes": len(stderr_text)}, ensure_ascii=False
            )
        )
    else:
        print(diagnosis)
    return 0


# ── Public hook: diagnose_before_retry (consumable by SWE-bench agent) ───────


def diagnose_before_retry(
    stderr_text: str, workspace: Path | None = None, model: str = ARCHITECT_MODEL
) -> str:
    """
    Pure function the SWE-bench retry loop can call before its next attempt.
    Returns a short root-cause hypothesis string suitable for injection into
    the next builder prompt. Returns "" on model unreachable.
    """
    if not stderr_text.strip():
        return ""
    workspace = workspace or Path.cwd()
    ctx = AskContext(
        question=(
            "Failure occurred. Give a one-paragraph root-cause hypothesis "
            "constrained to the stderr below. End with: NEXT_TRY: <specific change>."
        ),
        workspace=workspace,
        extra_blobs={"stderr": stderr_text, "git state": _git_summary(workspace)},
    )
    sp, up = ctx.render_prompt(
        "You are Determinex Sentinel diagnosing a build failure. Be specific and brief."
    )
    return _ollama_chat(model, sp, up)


# ── CLI plumbing ─────────────────────────────────────────────────────────────


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace", default=str(Path.cwd()), help="Workspace root (default: cwd)"
    )
    parser.add_argument(
        "--model", default=ARCHITECT_MODEL, help=f"Ollama model tag (default: {ARCHITECT_MODEL})"
    )
    parser.add_argument(
        "--json", dest="json_out", action="store_true", help="Emit JSON instead of text"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="determinex-ask", description="Sprint 1 — diagnostic-first entry to Determinex"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ask = sub.add_parser("ask", help="Freeform question against the workspace")
    p_ask.add_argument("question", help="The question to ask")
    p_ask.add_argument("--stderr", help="Path to a stderr/log file, '-' for stdin, or literal text")
    p_ask.add_argument("--image", help="Path to an image to describe (requires Sprint 2 vision)")
    p_ask.add_argument(
        "--session-state", action="store_true", help="Attach recent session WAL + git status"
    )
    p_ask.add_argument(
        "--scan", action="store_true", help="Grep workspace for keyword-matched files"
    )
    p_ask.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Attach extra blob: NAME=PATH or just PATH. Repeatable.",
    )
    _add_common(p_ask)
    p_ask.set_defaults(func=cmd_ask)

    p_where = sub.add_parser("where", help="Survey project state: git + recent sessions")
    p_where.add_argument(
        "--explain", action="store_true", help="Have Sentinel narrate the state (extra model call)"
    )
    _add_common(p_where)
    p_where.set_defaults(func=cmd_where)

    p_why = sub.add_parser("why", help="Diagnose a stderr/log blob")
    p_why.add_argument("--stderr", required=True, help="Path to stderr/log, or '-' for stdin")
    _add_common(p_why)
    p_why.set_defaults(func=cmd_why)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

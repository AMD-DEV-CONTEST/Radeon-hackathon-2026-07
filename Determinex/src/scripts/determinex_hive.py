"""
scripts/determinex_hive.py — Hive Mind Orchestrator (Phase 2) — CLI shell
=======================================================================
Core orchestrator for the Rosetta Stone + Hive Mind architecture.

This module owns:
  - Hardware profiler → tier assignment
  - Workspace manager: temp directory creation, project scaffolding, write_mode merging
  - Step Manifest manager: DAG read/write, topological sort, cycle detection
  - Write-Ahead Log (WAL): .pending / .complete / .failed atomic rename pattern
  - Session resume protocol: status display, context reconstruction, workspace hash check
  - Scaffolding validation pre-flight (cargo check / go mod tidy / pip --dry-run)
  - API budget pre-flight: estimate full session cost before Step 1 executes
  - Compiler Oracle interface: validate(project_state) — project-level, not file-level
  - Compiler output sanitization: sanitize_compiler_output() before quality gate hashing
  - Public API snapshot extraction per step
  - DAG invalidation on retry: detect API drift, flag stale downstream steps
  - Builder context assembler: target region + function signature index for large files
  - Tree-sitter parse failure fallback: regex chunking + parse_mode:degraded marker
  - Semantic DSL encoder/decoder
  - nomic-embed-text adjudication integration
  - Adjudication engine: challenge protocol, min_challenge_delta, max_challenges
  - Architect escalation: 3 Builder fails → full payload → re-plan
  - API model adapter: Claude/Gemini as role-fillers, two-path composite scoring
  - API cost tracking: running counter, budget cap, budget pre-flight, fallback mode
  - Shadow evaluator integration: first 5 steps per task type, auto-fallback
  - Training quality gate: training_ready vs inconclusive classification
  - Async build loop (wavefront parallel execution via ThreadPoolExecutor, compiler_lock)

Phase 1 scope implemented in this file:
  File I/O, WAL logic, temp workspace generation, manifest structure.
  The orchestration loop stubs are present but not yet wired to live inference.

Usage:
    python scripts/determinex_hive.py new-session --spec spec.md --lang rust
    python scripts/determinex_hive.py generate-dag --session <session_id>
    python scripts/determinex_hive.py run-session --session <session_id>
    python scripts/determinex_hive.py resume --session <session_id>
    python scripts/determinex_hive.py list-sessions
    python scripts/determinex_hive.py status --session <session_id>
    python scripts/determinex_hive.py validate-scaffolding --session <session_id>
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

# ── Bootstrap: ensure scripts/ is on sys.path so `hive` package resolves ─────
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# ── Load .env before any module reads os.environ for API keys ─────────────────
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # python-dotenv not installed — keys must be set in the shell environment

# ── Phase 2 Integration Hooks ────────────────────────────────────────────────
# Suppress pynvml FutureWarning that fires on every CLI invocation when torch
# initialises its CUDA context.  The warning is cosmetic noise on Python 3.12+
# and does not affect functionality.
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, message=".*pynvml.*")
try:
    import determinex_inference
    import determinex_rosetta
    from determinex_inference import DeterminexInference
    from determinex_rosetta import RosettaStone
except Exception as e:  # noqa: BLE001 - see below; this MUST NOT be ImportError only
    # `except ImportError` was not enough, and the gap took down the whole
    # product in its shipped form.
    #
    # determinex_inference imports llama_cpp, which loads a native library at
    # import time. When that library is present but its `lib/` directory is not
    # -- exactly what the PyInstaller sidecar produced -- llama_cpp raises
    # FileNotFoundError (WinError 3) from os.add_dll_directory, NOT ImportError.
    # So this guard, whose entire purpose is "these components are optional",
    # let a native-loader failure escape and crash the process on startup:
    # `determinex-hive.exe --help` died before printing anything.
    #
    # A component declared optional has to survive every way its import can
    # fail, not just the tidy one.
    # Say which layer is affected. "Phase 2 Latent Bridge components
    # unavailable" read like a malfunction, when the accurate picture is:
    #   Layer 1 (semantic DSL, the ACTIVE layer) needs neither torch nor a
    #     trained checkpoint and is unaffected.
    #   Layer 2 (soft-prefix projection) needs torch plus a rosetta_v*.pt, and is
    #     a documented v1.5 milestone -- absent by design, not broken.
    # A scary warning about a feature that was never claimed to be on is its own
    # kind of false signal.
    logging.getLogger("hive").info(
        f"Rosetta Layer 2 (latent projection) not available in this build "
        f"({type(e).__name__}: {e}). Layer 1 semantic DSL is unaffected; the "
        "hive runs normally."
    )
    determinex_rosetta = None
    RosettaStone = None
    determinex_inference = None
    DeterminexInference = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="[HIVE] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("hive")


def _redirect_logging_to_stderr() -> None:
    """For JSON-output subcommands (explore/diagnose/fix): move all log handlers
    to stderr so stdout stays clean for machine-readable JSON consumption."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
            handler.stream = sys.stderr


# ── Import all logic from hive.* modules ──────────────────────────────────────
from hive.api_client import (
    cmd_generate_dag,
    load_role_assignments,
)
from hive.compiler import (
    validate_scaffolding,
)
from hive.executor import (
    run_session,
)
from hive.manifest import (
    DEFAULT_SESSION_BUDGET_USD,
    list_sessions,
    load_manifest,
    save_manifest,
    wal_recover_pending,
)
from hive.session_manager import check_session_resume, new_session
from hive.workspace import (
    cleanup_workspace,
)

# ── Paths (kept for backward compat if anything references them) ─────────────
_ROOT = Path(__file__).resolve().parent.parent
_SESSIONS_DIR = _ROOT / "sessions"

# ── Build loop constants (re-export from sub-modules) ─────────────────────────
SHADOW_STEPS_PER_TYPE = 5
SHADOW_REENABLE_THRESHOLD = 20
DEFAULT_SESSION_BUDGET_USD = DEFAULT_SESSION_BUDGET_USD


# ── CLI ───────────────────────────────────────────────────────────────────────


def cmd_new_session(args) -> None:
    spec = Path(args.spec)
    if not spec.exists():
        log.error("Spec file not found: %s", spec)
        sys.exit(1)

    # ── SAFETY: L0+L1 spec gate — runs before anything else ──────────────────
    # Checks content policy (categorical denials) and intent classifier
    # (semantic reframing detection) on the raw spec text.
    spec_text = spec.read_text(encoding="utf-8", errors="replace")
    try:
        from determinex_safety import SafetyDenied
        from hive.safety_gate import pre_spec_gate

        pre_spec_gate(spec_text, source="cli")
    except ImportError:
        log.warning("[SAFETY] Safety gate unavailable — spec check skipped")
    except Exception as _safety_err:
        log.error("[SAFETY] Spec rejected: %s", _safety_err)
        print(f"\n[DETERMINEX SAFETY] Request denied: {_safety_err}", file=sys.stderr)
        sys.exit(2)

    session = new_session(str(spec), args.lang, args.budget)
    print(f"\nSession created: {session.session_id}")
    print(f"Workspace:       {session.project_root}")
    print(f"Lang:            {args.lang}")
    print(f"Budget:          ${session.session_budget_usd:.2f}")

    # Every project the hive builds should default to a project-instructions file any LLM/agent
    # tool reads (Claude Code's CLAUDE.md, Gemini CLI's GEMINI.md, Codex's AGENTS.md, ...) --
    # Ryan, direct instruction 2026-07-27. Best-effort: a project-md generation failure must
    # never abort a real build session over what is a documentation nicety, not the build itself.
    try:
        from determinex_project_md import (
            generate_agents_md,
            spec_to_understanding,
            write_project_md_files,
        )

        workspace = Path(session.project_root)
        understanding = spec_to_understanding(spec_text, args.lang, root=str(workspace))
        title_m = re.search(r"^#\s+(.+)$", spec_text, re.MULTILINE)
        project_name = title_m.group(1).strip() if title_m else workspace.name
        content = generate_agents_md(understanding, project_name)
        written = write_project_md_files(workspace, content)
        if written:
            print(f"Project instructions: {', '.join(p.name for p in written)}")
    except Exception as _md_err:
        log.debug("project-md generation skipped: %s", _md_err)

    # Echo the path the user actually invoked rather than a bare filename. This printed
    # "python determinex_hive.py generate-dag ...", which fails from the repo root -- the only
    # directory the README ever tells you to run from ("python scripts/determinex_hive.py ...").
    # A copy-pasteable next step that does not run is a dead end at the exact moment the user is
    # following instructions.
    # `as_posix()` on purpose: forward slashes work in cmd, PowerShell AND Git Bash, whereas the
    # native backslash form breaks in bash -- and Git Bash is the documented shell here. The
    # README already writes it this way ("python scripts/determinex_hive.py ...").
    _invoked = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "determinex_hive.py"
    try:
        _invoked = Path(sys.argv[0]).resolve().relative_to(Path.cwd()).as_posix()
    except (ValueError, OSError):
        pass
    print(f"\nNext: python {_invoked} generate-dag --session {session.session_id}")


def cmd_run_session(args) -> None:
    """CLI handler for 'run-session': load manifest and execute the DAG."""
    try:
        session = load_manifest(args.session)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error("Session not found or corrupted: %s", e)
        sys.exit(1)

    log.info("Running session: %s", args.session)
    model_assignments = load_role_assignments()
    result = run_session(args.session, model_assignments)

    completed = sum(1 for s in result.steps if s.status == "complete")
    success = completed == len(result.steps)
    if success and not getattr(args, "keep_workspace", False):
        cleanup_workspace(args.session)
    sys.exit(0 if success else 1)


def cmd_purge_workspaces(args) -> None:
    """Remove all workspace directories older than N days (default 1)."""
    import time

    from hive.workspace import WORKSPACE_BASE

    days = getattr(args, "days", 1)
    cutoff = time.time() - days * 86400
    removed = 0
    skipped = 0
    for d in WORKSPACE_BASE.iterdir() if WORKSPACE_BASE.exists() else []:
        if d.is_dir() and d.stat().st_mtime < cutoff:
            import shutil

            shutil.rmtree(d, ignore_errors=True)
            removed += 1
        else:
            skipped += 1
    print(f"Purged {removed} workspace(s) older than {days}d — {skipped} kept.")


def cmd_status(args) -> None:
    try:
        session = load_manifest(args.session)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error("Session not found or corrupted: %s", e)
        sys.exit(1)

    workspace = Path(session.project_root)
    completed = sum(1 for s in session.steps if s.status == "complete")
    total = len(session.steps)
    pending = wal_recover_pending(args.session)

    # G35: actually reset in-progress/orphaned steps to pending in the manifest
    # so resume picks them up rather than skipping them as "in_progress".
    if pending:
        pending_set = set(pending) if not isinstance(pending, set) else pending
        reset_count = 0
        for s in session.steps:
            if s.id in pending_set and s.status != "complete":
                s.status = "pending"
                reset_count += 1
        if reset_count:
            save_manifest(session)
            log.info("cmd_status: reset %d orphaned step(s) to pending in manifest", reset_count)

    print(f"\nSession:     {session.session_id}")
    print(f"Lang:        {session.lang}")
    print(f"Progress:    {completed}/{total} steps complete")
    print(f"API cost:    ${session.api_cost_usd:.4f} / ${session.session_budget_usd:.2f}")
    print(f"Workspace:   {workspace}")
    print(f"Scaffolded:  {session.scaffolding_validated}")
    if pending:
        print(f"WAL pending: {pending} (reset to pending — will retry on resume)")

    print("\nStep summary:")
    for s in session.steps:
        status_icon = {
            "complete": "✓",
            "failed": "✗",
            "pending": "·",
            "in_progress": "»",
            "stale_instruction": "⚠",
        }.get(s.status, "?")
        print(f"  {status_icon} [{s.id:03d}] {s.status:<18} {s.instruction[:60]}")


def cmd_resume(args) -> None:
    try:
        session = load_manifest(args.session)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error("Session not found: %s", e)
        sys.exit(1)

    workspace = Path(session.project_root)
    resume_info = check_session_resume(session, workspace)

    print(f"\nSession {session.session_id}")
    print(f"Progress: {resume_info['completed']}/{resume_info['total']} steps complete")
    print(f"Budget remaining: ${resume_info['budget_remaining']:.2f}")
    print(f"Next steps: {resume_info['next_step_ids']}")

    if resume_info["modified_files"]:
        print("\nWARNING: These files were modified outside Determinex:")
        for f in resume_info["modified_files"]:
            print(f"  {f}")
        print("  Action required: accept changes or revert before resuming.")

    pending = wal_recover_pending(args.session)
    if pending:
        print(f"\nWAL recovery: steps {pending} are incomplete — will retry from scratch")


def cmd_list_sessions(args) -> None:
    sessions = list_sessions()
    if not sessions:
        print("No sessions found.")
        return
    print(f"\n{'Session ID':<38} {'Lang':<8} {'Steps':>7} {'Cost':>8} {'Updated'}")
    print("-" * 80)
    for s in sessions:
        print(
            f"{s['session_id']:<38} {s['lang']:<8} {s['steps']:>7} "
            f"${s['budget_usd']:>6.3f}  {s['updated_at'][:19]}"
        )


def cmd_diagnose(args) -> None:
    """
    Scan workspace for files relevant to an issue and return a JSON diagnosis.

    Tries hive.explorer (CodebaseExplorer) first; falls back to keyword search.
    Outputs: {"explanation": str, "relevant_files": [str], "traceback": str}
    """
    _redirect_logging_to_stderr()
    import json as _json

    workspace = Path(args.workspace)
    issue = args.issue or ""

    if not workspace.exists():
        print(_json.dumps({"ok": False, "error": f"Workspace not found: {workspace}"}))
        sys.exit(1)

    # Try the full CodebaseExplorer diagnosis first
    try:
        from hive.explorer import diagnose_workspace as _diagnose

        manifest = _diagnose(str(workspace), issue)
        diag = manifest.get("diagnosis", {})
        result = {
            "explanation": diag.get("explanation", issue[:200]),
            "relevant_files": diag.get("targets", []),
            "traceback": diag.get("traceback", ""),
            "raw": diag.get("explanation", ""),
        }
        print(_json.dumps(result))
        return
    except Exception:
        pass  # fall through to keyword-based fallback

    # Keyword-based fallback
    keywords = {w.lower() for w in re.split(r"\W+", issue) if len(w) > 3}
    scored: list[tuple[int, str]] = []
    extensions = {".rs", ".go", ".py", ".toml", ".mod", ".txt"}
    for f in workspace.rglob("*"):
        if not f.is_file() or f.suffix not in extensions:
            continue
        if any(p.startswith(".") or p == "__pycache__" for p in f.parts):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            hits = sum(1 for kw in keywords if kw in content.lower())
            if hits:
                scored.append((hits, str(f.relative_to(workspace))))
        except OSError:
            pass

    scored.sort(reverse=True)
    relevant = [path for _, path in scored[:5]]
    explanation = (
        f"Issue: {issue[:200]}\n\nMost relevant files ({len(relevant)}):\n"
        + "\n".join(f"  • {p}" for p in relevant)
        if relevant
        else f"No source files matched: {issue[:200]}"
    )
    print(_json.dumps({"explanation": explanation, "relevant_files": relevant, "raw": explanation}))


def cmd_fix(args) -> None:
    """
    Generate a compiler-verified patch for an issue in the workspace.

    Tries hive.explorer (CodebaseExplorer) first; falls back to file identification.
    Outputs: {"explanation": str, "relevant_files": [str], "patch_hint": str}
    """
    _redirect_logging_to_stderr()
    import json as _json

    workspace = Path(args.workspace)
    issue = args.issue or ""

    if not workspace.exists():
        print(_json.dumps({"ok": False, "error": f"Workspace not found: {workspace}"}))
        sys.exit(1)

    # Try the full CodebaseExplorer fix first
    try:
        from hive.explorer import fix_workspace as _fix

        manifest = _fix(str(workspace), issue, out_path=args.out)
        fix_result = manifest.get("result", {})
        result = {
            "explanation": f"Issue: {issue[:200]}",
            "relevant_files": fix_result.get("files_modified", []),
            "patch_hint": fix_result.get("patch_summary", ""),
            "success": fix_result.get("success", False),
            "raw": fix_result.get("patch_summary", ""),
        }
        print(_json.dumps(result))
        return
    except Exception:
        pass  # fall through to identification-only fallback

    # Identification-only fallback (no model available)
    keywords = {w.lower() for w in re.split(r"\W+", issue) if len(w) > 3}
    scored: list[tuple[int, str]] = []
    for f in workspace.rglob("*"):
        if not f.is_file() or f.suffix not in {".rs", ".go", ".py"}:
            continue
        if any(p.startswith(".") or p == "__pycache__" for p in f.parts):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            hits = sum(1 for kw in keywords if kw in content.lower())
            if hits:
                scored.append((hits, str(f.relative_to(workspace))))
        except OSError:
            pass

    scored.sort(reverse=True)
    relevant = [path for _, path in scored[:3]]
    patch_hint = (
        f"Fix targets: {', '.join(relevant) if relevant else 'unknown'}. "
        f"Use `run-session` with a revised spec to apply a compiler-verified patch."
    )
    result = {
        "explanation": f"Issue: {issue[:200]}",
        "relevant_files": relevant,
        "patch_hint": patch_hint,
        "raw": patch_hint,
    }
    if args.out:
        try:
            Path(args.out).write_text(_json.dumps(result, indent=2), encoding="utf-8")
        except OSError as e:
            result["write_error"] = str(e)
    print(_json.dumps(result))


# ── Bundled helper dispatch (sidecar coverage) ────────────────────────────────
# WHY THIS EXISTS
# The PyInstaller sidecar bundles THIS file, so historically it exposed only the
# hive subcommands. Everything else the Tauri backend needed -- the agent chat room,
# the agent registry, the usage ledger, the toolchain installer, the model bench --
# was invoked through a SECOND path (ide_repair_bridge/agent_chat's run_script_json)
# that shells out to `scripts/<name>.py` by PATH. That path does not exist in an
# installed copy, so those panels were dev-checkout-only while `ipc_hive` was already
# bundled-first and correct.
#
# Two invocation paths, one of them bundled, and new callers reached for whichever was
# nearest -- the same divergence that produced two argv builders and two audit docs.
# This subcommand gives the sidecar coverage for the rest, so `run_script_json` can
# prefer the bundle and fall back to the repo script only in a dev tree.
#
# Allowlisted on purpose: this is a dispatch into arbitrary module main()s, so the set
# is explicit and argparse `choices` rejects anything else before an import happens.
_HELPER_MODULES: tuple[str, ...] = (
    "determinex_agents",
    "determinex_agent_chat",
    "determinex_local_model_bench",
    "determinex_usage_ledger",
    "determinex_toolchain_installer",
    "determinex_corpus_api",
    # The provider registry, so `list_ai_providers` works in an installed copy and not only in a
    # dev checkout. Read-only: its --json path lists provider names, tiers, default models and
    # WHETHER a key is set -- it never reads or emits a key's value.
    "determinex_providers",
    "ide._tauri_driver",
    # The model installer, so the app can offer a one-click fix for the state a fresh
    # install lands in: builder and monitor default to fine-tuned models that no new user
    # could obtain until 2026-07-29. Safe to expose -- its --check mode is read-only, and the
    # install path only downloads published GGUFs and shells `ollama create`.
    "setup.install_determinex_models",
)


def cmd_helper(args) -> None:
    """Run a bundled helper module's main() with the given argv, in-process."""
    import importlib

    name = args.script
    if name not in _HELPER_MODULES:  # argparse enforces this; belt and braces
        print(f"not an allowed helper: {name}", file=sys.stderr)
        raise SystemExit(2)
    mod = importlib.import_module(name)
    main_fn = getattr(mod, "main", None)
    if not callable(main_fn):
        print(f"helper '{name}' has no main()", file=sys.stderr)
        raise SystemExit(2)
    # Two main() conventions live in this repo and the dispatch must serve both:
    # most helpers take no argument and parse sys.argv themselves, while
    # ide/_tauri_driver.py declares main(argv). Guessing wrong raises TypeError, so the
    # signature is inspected rather than assumed.
    forwarded = list(args.rest or [])
    takes_argv = False
    try:
        import inspect

        takes_argv = len(inspect.signature(main_fn).parameters) >= 1
    except (TypeError, ValueError):
        takes_argv = False

    # sys.argv is set either way: a helper that declares main(argv) may still read
    # sys.argv[0] for messages, and it is restored afterwards so one dispatch cannot
    # leak into another.
    saved = sys.argv
    sys.argv = [f"{name.replace('.', '/')}.py", *forwarded]
    try:
        # sys.argv, not `forwarded`: a main(argv) in this repo follows the sys.argv
        # convention and indexes argv[1]/argv[2], so it needs the program name at [0].
        rc = main_fn(sys.argv) if takes_argv else main_fn()
    finally:
        sys.argv = saved
    raise SystemExit(int(rc or 0))


def cmd_explore(args) -> None:
    """Print a JSON workspace summary: file listing, sizes, and step status."""
    _redirect_logging_to_stderr()
    import json as _json

    workspace = Path(args.workspace)
    if not workspace.exists():
        result = {"ok": False, "error": f"Workspace not found: {workspace}"}
        print(_json.dumps(result))
        sys.exit(1)

    _SKIP_DIRS = {"__pycache__", ".git", "node_modules", "target", ".mypy_cache", ".ruff_cache"}
    files = []
    for f in sorted(workspace.rglob("*")):
        if not f.is_file():
            continue
        rel_parts = f.relative_to(workspace).parts
        if any(p.startswith(".") or p in _SKIP_DIRS for p in rel_parts):
            continue
        try:
            size = f.stat().st_size
            files.append({"path": str(f.relative_to(workspace)), "size_bytes": size})
        except OSError:
            pass

    result = {
        "ok": True,
        "workspace": str(workspace),
        "file_count": len(files),
        "files": files[:200],  # cap at 200 to keep response small
    }
    print(_json.dumps(result, indent=2 if not args.json else None))


def cmd_validate_scaffolding(args) -> None:
    try:
        session = load_manifest(args.session)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error("Session not found: %s", e)
        sys.exit(1)

    workspace = Path(session.project_root)
    passed, error = validate_scaffolding(workspace, session.lang)
    if passed:
        session.scaffolding_validated = True
        save_manifest(session)
        print("Scaffolding validation: PASSED — scaffolding_validated set to true")
    else:
        print(f"Scaffolding validation: FAILED\n{error}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Determinex Hive Mind Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # new-session
    p_new = sub.add_parser("new-session", help="Start a new build session")
    p_new.add_argument("--spec", required=True, help="Path to the MD spec file")
    p_new.add_argument("--lang", required=True, choices=["rust", "go", "python"])
    p_new.add_argument(
        "--budget",
        type=float,
        default=DEFAULT_SESSION_BUDGET_USD,
        help=f"API budget in USD (default ${DEFAULT_SESSION_BUDGET_USD:.2f})",
    )
    p_new.set_defaults(func=cmd_new_session)

    # generate-dag
    p_dag = sub.add_parser("generate-dag", help="Call Oracle+Architect to populate step manifest")
    p_dag.add_argument("--session", required=True)
    p_dag.add_argument(
        "--force", action="store_true", help="Regenerate even if steps already exist"
    )
    p_dag.set_defaults(func=cmd_generate_dag)

    # run-session
    p_run = sub.add_parser("run-session", help="Execute the DAG for an existing session")
    p_run.add_argument("--session", required=True)
    p_run.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Do not delete workspace directory on success (for debugging)",
    )
    p_run.set_defaults(func=cmd_run_session)

    # status
    p_status = sub.add_parser("status", help="Show session status")
    p_status.add_argument("--session", required=True)
    p_status.set_defaults(func=cmd_status)

    # resume
    p_resume = sub.add_parser("resume", help="Resume an existing session")
    p_resume.add_argument("--session", required=True)
    p_resume.set_defaults(func=cmd_resume)

    # list-sessions
    p_list = sub.add_parser("list-sessions", help="List all known sessions")
    p_list.set_defaults(func=cmd_list_sessions)

    # validate-scaffolding
    p_val = sub.add_parser("validate-scaffolding", help="Run scaffolding pre-flight check")
    p_val.add_argument("--session", required=True)
    p_val.set_defaults(func=cmd_validate_scaffolding)

    # explore
    p_exp = sub.add_parser("explore", help="Print JSON workspace file listing")
    p_exp.add_argument("--workspace", required=True, help="Path to workspace directory")
    p_exp.add_argument("--json", action="store_true", help="Compact JSON (no indentation)")
    p_exp.set_defaults(func=cmd_explore)

    # diagnose
    p_diag = sub.add_parser("diagnose", help="Find files relevant to a compiler/runtime issue")
    p_diag.add_argument("--workspace", required=True, help="Path to workspace directory")
    p_diag.add_argument("--issue", required=True, help="Issue text or compiler error to diagnose")
    p_diag.set_defaults(func=cmd_diagnose)

    # purge-workspaces
    p_purge = sub.add_parser(
        "purge-workspaces", help="Delete workspace temp dirs older than N days (default 1)"
    )
    p_purge.add_argument(
        "--days", type=int, default=1, help="Remove workspaces older than this many days"
    )
    p_purge.set_defaults(func=cmd_purge_workspaces)

    # fix
    p_fix = sub.add_parser("fix", help="Identify fix targets for an issue in the workspace")
    p_fix.add_argument("--workspace", required=True, help="Path to workspace directory")
    p_fix.add_argument("--issue", required=True, help="Issue description or compiler error")
    p_fix.add_argument("--out", default=None, help="Optional path to write JSON result")
    p_fix.set_defaults(func=cmd_fix)

    p_helper = sub.add_parser(
        "helper",
        help="Run a bundled helper script (sidecar coverage for the "
        "non-hive scripts the desktop backend needs)",
    )
    p_helper.add_argument("script", choices=sorted(_HELPER_MODULES))
    p_helper.add_argument(
        "rest", nargs=argparse.REMAINDER, help="arguments forwarded verbatim to that script"
    )
    p_helper.set_defaults(func=cmd_helper)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

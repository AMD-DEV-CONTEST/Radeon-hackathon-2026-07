"""Main entry point for the Diagnostics Layer.

enrich(workspace, lang, failure_context) -> DiagnosticBundle

Called by the retry loop AFTER a compile-gate failure.  The bundle is
token-budgeted and injected into the correction prompt AFTER compiler errors.
Everything passes through the existing Cloak re-obfuscation path before any
cloud call — zero leakage of LSP symbol names or trace paths.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from . import DiagnosticBundle
from .divergence import capture_divergence
from .lsp_sidecar import run_lsp_pass
from .syscall_diff import run_syscall_diff

logger = logging.getLogger(__name__)


def _find_candidate_files(workspace: Path, lang: str) -> list[Path]:
    """Find the most-recently-modified source files for the given language."""
    ext_map = {
        "rust": [".rs"],
        "go": [".go"],
        "c": [".c", ".h"],
        "cpp": [".cpp", ".cc", ".cxx", ".h", ".hpp"],
        "python": [".py"],
        "py": [".py"],
        "typescript": [".ts", ".tsx"],
        "javascript": [".js", ".jsx"],
        "ts": [".ts", ".tsx"],
        "js": [".js", ".jsx"],
    }
    exts = ext_map.get(lang, [])
    files: list[Path] = []
    for ext in exts:
        files.extend(workspace.rglob(f"*{ext}"))
    # Sort by mtime descending, cap at 10 files to keep latency bounded
    files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:10]
    return files


async def _enrich_async(
    workspace: Path,
    lang: str,
    failure_context: dict[str, Any],
) -> DiagnosticBundle:
    bundle = DiagnosticBundle(workspace=workspace, lang=lang)

    # --- LSP pass (pre-gate warning or gate-fail enrichment) ---
    files = _find_candidate_files(workspace, lang)
    if files:
        try:
            lsp_section = await run_lsp_pass(workspace=workspace, lang=lang, files=files)
            if lsp_section.content:
                bundle.sections.append(lsp_section)
        except Exception as exc:
            logger.warning("LSP enrichment error: %s", exc)

    # --- Divergence capture (behavioral test failure) ---
    candidate = failure_context.get("candidate_path")
    test_id = failure_context.get("test_id", "")
    test_args = failure_context.get("test_args", [])
    stdin_data = failure_context.get("stdin_data")
    if candidate:
        candidate_path = Path(candidate)
        try:
            div_section = await capture_divergence(
                candidate=candidate_path,
                lang=lang,
                test_id=test_id,
                test_args=test_args,
                stdin_data=stdin_data,
            )
            if div_section.content:
                bundle.sections.append(div_section)
        except Exception as exc:
            logger.warning("Divergence enrichment error: %s", exc)

    # --- Syscall differential (Linux only, when reference provided) ---
    reference = failure_context.get("reference_path")
    if reference and candidate:
        reference_path = Path(reference)
        candidate_path = Path(candidate)
        try:
            sc_section = await run_syscall_diff(
                reference=reference_path,
                candidate=candidate_path,
                test_args=test_args,
                stdin_data=stdin_data,
            )
            if sc_section.content:
                bundle.sections.append(sc_section)
        except Exception as exc:
            logger.warning("Syscall diff enrichment error: %s", exc)

    return bundle


def enrich(
    workspace: Path,
    lang: str,
    failure_context: dict[str, Any] | None = None,
) -> DiagnosticBundle:
    """Synchronous entry point.  Runs async logic in a new event loop if needed."""
    if failure_context is None:
        failure_context = {}
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Called from within an async context — return a future, caller must await
            # In practice the retry loop calls this synchronously; create a new loop.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(
                    lambda: asyncio.run(_enrich_async(workspace, lang, failure_context))
                )
                return future.result(timeout=90)
        else:
            return loop.run_until_complete(_enrich_async(workspace, lang, failure_context))
    except Exception as exc:
        logger.warning("enrich() failed: %s", exc)
        return DiagnosticBundle(workspace=workspace, lang=lang)

"""
hive/explorer.py — Hive Mind Integration for the Enterprise Codebase Explorer
===============================================================================
Wires codebase_explorer.py into the Hive Mind session system so that
"explore" and "diagnose" are first-class session types alongside "build".

Session types:
  - build:    Spec-to-Code (Idea/Concept Lab → DAG → build → verify)
  - explore:  Repo-to-Report (load workspace → scan → shadow compile → report)
  - diagnose: Repo-to-Patch (load workspace → locate issue → plan fix → patch)

The explore/diagnose sessions are stored in the same sessions/ directory
with the same manifest.json format, but with session_type="explore"|"diagnose".
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("hive.explorer")

# Bootstrap: ensure scripts/ is on sys.path
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from codebase_explorer import CodebaseExplorer

_ROOT = Path(__file__).resolve().parent.parent.parent
_SESSIONS_DIR = _ROOT / "sessions"


def _save_explorer_manifest(session_id: str, data: dict) -> Path:
    """Save an explorer session manifest."""
    session_dir = _SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    manifest = session_dir / "manifest.json"
    manifest.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return manifest


def explore_workspace(
    workspace_path: str,
    session_id: str | None = None,
) -> dict:
    """
    Create an 'explore' session: scan the workspace, run shadow compilation,
    and generate a diagnostic report.

    Returns the full report as a dict (also saved to manifest.json).
    """
    session_id = session_id or str(uuid.uuid4())
    workspace = Path(workspace_path).resolve()

    log.info("Creating explore session: %s for %s", session_id, workspace)

    explorer = CodebaseExplorer(workspace)
    report = explorer.explore()

    # Convert to dict for serialization
    from dataclasses import asdict

    report_dict = asdict(report)

    manifest_data = {
        "session_id": session_id,
        "session_type": "explore",
        "workspace_path": str(workspace),
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "report": report_dict,
    }

    _save_explorer_manifest(session_id, manifest_data)
    log.info("Explore session %s complete: health=%.0f%%", session_id, report.health_score * 100)

    return manifest_data


def diagnose_workspace(
    workspace_path: str,
    issue_text: str,
    session_id: str | None = None,
) -> dict:
    """
    Create a 'diagnose' session: locate files relevant to the issue,
    capture shadow traceback, and return target files for fixing.

    Returns the diagnosis as a dict (also saved to manifest.json).
    """
    session_id = session_id or str(uuid.uuid4())
    workspace = Path(workspace_path).resolve()

    log.info("Creating diagnose session: %s for %s", session_id, workspace)

    explorer = CodebaseExplorer(workspace)
    diagnosis = explorer.diagnose(issue_text)

    manifest_data = {
        "session_id": session_id,
        "session_type": "diagnose",
        "workspace_path": str(workspace),
        "issue_text": issue_text,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "diagnosis": diagnosis,
    }

    _save_explorer_manifest(session_id, manifest_data)
    log.info(
        "Diagnose session %s complete: %d targets", session_id, len(diagnosis.get("targets", []))
    )

    return manifest_data


def fix_workspace(
    workspace_path: str,
    issue_text: str,
    session_id: str | None = None,
    out_path: str | None = None,
) -> dict:
    """
    Create a 'fix' session: locate the bug, generate a patch, validate it.

    Returns the fix result as a dict (also saved to manifest.json).
    """
    session_id = session_id or str(uuid.uuid4())
    workspace = Path(workspace_path).resolve()

    log.info("Creating fix session: %s for %s", session_id, workspace)

    explorer = CodebaseExplorer(workspace)
    result = explorer.fix(issue_text, out_path)

    from dataclasses import asdict

    result_dict = asdict(result)

    manifest_data = {
        "session_id": session_id,
        "session_type": "fix",
        "workspace_path": str(workspace),
        "issue_text": issue_text,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "status": "complete" if result.success else "failed",
        "result": result_dict,
    }

    _save_explorer_manifest(session_id, manifest_data)

    if result.success:
        log.info(
            "Fix session %s: PATCHED (%d attempts, %d files)",
            session_id,
            result.attempts,
            len(result.files_modified),
        )
    else:
        log.info(
            "Fix session %s: FAILED after %d attempts — %s",
            session_id,
            result.attempts,
            result.error,
        )

    return manifest_data

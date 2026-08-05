"""
scripts/hive/session_manager.py — New session factory and session resume protocol
==================================================================================
Moved from determinex_hive.py (lines ~1540-1611).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from hive.concurrent_guard import WorkspaceLock
from hive.manifest import (
    DEFAULT_SESSION_BUDGET_USD,
    ManifestSession,
    _session_dir,
    save_manifest,
)
from hive.workspace import create_workspace, hash_workspace_files

log = logging.getLogger("hive")

# ── Workspace lock registry ────────────────────────────────────────────────────
# Holds the WorkspaceLock for each active session so it isn't garbage-collected
# before run_session() completes. Call release_session_lock() on session teardown.
_workspace_locks: dict[str, WorkspaceLock] = {}


def release_session_lock(session_id: str) -> None:
    """Release and remove the workspace lock for a completed session."""
    lock = _workspace_locks.pop(session_id, None)
    if lock is not None:
        lock.release()


def check_session_resume(session: ManifestSession, workspace: Path) -> dict:
    """
    Session resume protocol:
    1. Show status: 'N/M steps complete. Resume?'
    2. Context reconstruction payload for API roles
    3. Workspace integrity check: compare current file hashes against manifest
    Returns a resume_info dict for the caller to present to the user.
    """
    completed = [s for s in session.steps if s.status == "complete"]
    pending = [
        s for s in session.steps if s.status in ("pending", "in_progress", "stale_instruction")
    ]
    total = len(session.steps)

    # Workspace hash check
    current_hashes = hash_workspace_files(workspace, session.lang)
    recorded_hashes = session.workspace_file_hashes
    modified_files = [
        f
        for f in current_hashes
        if recorded_hashes.get(f) and current_hashes[f] != recorded_hashes[f]
    ]
    new_files = [f for f in current_hashes if f not in recorded_hashes]

    # Context reconstruction summary for API roles
    api_context_summary = {
        "md_spec_path": session.md_spec_path,
        "lang": session.lang,
        "completed_steps": [
            {
                "id": s.id,
                "instruction": s.instruction,
                "write_mode": s.write_mode,
                "target_file": s.target_file,
                "public_api": s.public_api_snapshot,
            }
            for s in completed
        ],
        "pending_step_ids": [s.id for s in pending],
        "api_cost_so_far": session.api_cost_usd,
    }

    return {
        "session_id": session.session_id,
        "completed": len(completed),
        "total": total,
        "next_step_ids": [s.id for s in pending],
        "modified_files": modified_files,
        "new_files": new_files,
        "api_context_summary": api_context_summary,
        "budget_remaining": session.session_budget_usd - session.api_cost_usd,
    }


def new_session(
    md_spec_path: str, lang: str, budget_usd: float = DEFAULT_SESSION_BUDGET_USD
) -> ManifestSession:
    """Create a new ManifestSession and its directory structure."""
    session_id = str(uuid.uuid4())
    workspace_path, workspace_lock = create_workspace(session_id, lang)  # #28
    _workspace_locks[session_id] = workspace_lock  # hold lock for session lifetime
    now = datetime.now(UTC).isoformat()
    session = ManifestSession(
        session_id=session_id,
        lang=lang,
        md_spec_path=str(md_spec_path),
        project_root=str(workspace_path),
        session_budget_usd=budget_usd,
        created_at=now,
        updated_at=now,
    )
    _session_dir(session_id).mkdir(parents=True, exist_ok=True)
    save_manifest(session)
    log.info("New session: %s  lang=%s  workspace=%s", session_id, lang, workspace_path)
    return session

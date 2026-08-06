"""Audit log: record key operations for permission review."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AUDIT_LOG_DIR = "./.agently/runs/insurance/audit"


def _ensure_dir() -> Path:
    path = Path(AUDIT_LOG_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_audit_event(
    event_type: str,
    actor: str,
    action: str,
    resource: str,
    details: dict[str, Any] | None = None,
    scope: dict[str, str] | None = None,
) -> None:
    """Record one audit event.
    
    Args:
        event_type: event type (e.g. "file_read", "file_write", "query_execute")
        actor: actor identifier (e.g. session_id or user_id)
        action: the action being performed
        resource: the resource being operated on
        details: additional details
        scope: the scope of the operation
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "actor": actor,
        "action": action,
        "resource": resource,
        "scope": scope or {},
        "details": details or {},
    }
    
    try:
        log_dir = _ensure_dir()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = log_dir / f"audit_{date_str}.jsonl"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error("failed to write audit log: %s", e)

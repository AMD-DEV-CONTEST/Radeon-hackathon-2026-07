"""Append-only audit log (JSON Lines) for PHI access events.

Writes to ``output/audit.log``. Each line: timestamp, event, actor, target,
client IP. Never rewritten in place (append mode only).
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("medglass.audit")

AUDIT_FILE = Path("output") / "audit.log"
_LOCK = threading.Lock()


def log(event: str, actor: str = "", target: str = "", detail: str = "",
        ip: str = "") -> None:
    """Append one audit record. Never raises on storage errors."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        "actor": actor,
        "target": target,
        "detail": detail,
        "ip": ip,
    }
    try:
        with _LOCK:
            AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
    except Exception as exc:
        LOG.warning("audit write failed: %s", exc)

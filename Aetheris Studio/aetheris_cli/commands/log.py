"""
Audit log viewing subcommand implementation (aetheris log).
Fetches and formats audit log entries from the Flight Recorder for a given session.
"""

import json
import sys
from typing import Optional
from aetheris_cli.transport.client import AetherisClient


def log_command(
    session_id: str,
    follow: bool = False,
    tool_filter: Optional[str] = None,
    since: Optional[str] = None,
) -> int:
    client = AetherisClient()
    try:
        audit_data = client.get_audit_trail(session_id)
        entries = audit_data.get("entries", [])
        if not entries:
            sys.stdout.write(f"No audit trail entries found for session '{session_id}'.\n")
            return 0

        sys.stdout.write(f"--- Audit Trail for Session: {session_id} ({len(entries)} entries) ---\n")
        for entry in entries:
            tool = entry.get("data", {}).get("tool", "")
            if tool_filter and tool != tool_filter:
                continue

            seq = entry.get("seq")
            event_type = entry.get("event")
            actor = entry.get("actor", "unknown")
            ts = entry.get("timestamp", "")
            
            sys.stdout.write(f"[{seq}] {ts} | {event_type} | actor={actor} | payload={json.dumps(entry.get('data'))}\n")

        return 0
    except Exception as e:
        sys.stderr.write(f"Failed to fetch audit log for '{session_id}': {e}\n")
        return 1

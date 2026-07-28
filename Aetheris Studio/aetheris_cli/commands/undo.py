"""
Time-Travel undo subcommand implementation (aetheris undo).
Performs state rollback and checkpoint inspection for chat sessions.
"""

import sys
from typing import Optional
from aetheris_cli.transport.backend import check_backend_availability
from aetheris_cli.transport.client import AetherisClient


def undo_command(
    session_id: str = "cli_session",
    last: int = 1,
    dry_run: bool = False,
) -> int:
    client = AetherisClient()
    ok, msg = check_backend_availability(client)
    if not ok:
        sys.stderr.write(f"Error: {msg}\n")
        return 3

    if dry_run:
        sys.stdout.write(f"[Dry Run] Would perform Time-Travel rollback on session '{session_id}' to step -{last}.\n")
        return 0

    try:
        res = client.rollback_timetravel(session_id=session_id, user_message_index=last)
        sys.stdout.write(f"Time-Travel rollback successful for session '{session_id}': {res}\n")
        return 0
    except Exception as e:
        sys.stderr.write(f"Time-Travel rollback failed: {e}\n")
        return 1

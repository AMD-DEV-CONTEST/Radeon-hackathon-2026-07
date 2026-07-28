"""
Time-Travel undo subcommand implementation (aetheris undo).
Lists the session's Time-Travel checkpoints and restores the project to the state it had before a chosen user message, always previewing the exact diff first and gating the write behind an explicit confirmation.

Message-anchored ("restore to before user message N") rather than
snapshot-anchored ("restore this one commit"): a single turn routinely
writes several files across several tool calls, so undoing a turn has to
mean all of them, which is exactly what the backend's
checkpoint/restore endpoint does (core/audit/timetravel.py::
restore_to_turn). The Flutter app's per-message ⟲ button drives the same
endpoint -- this is the same feature, not a parallel implementation.
"""

import os
import sys
from typing import Any, Dict, List, Optional

from aetheris_cli.transport.backend import check_backend_availability
from aetheris_cli.transport.client import AetherisClient


def _restorable_turns(snapshots: List[Dict[str, Any]]) -> List[int]:
    """Distinct user-message turns that can be restored to, newest first.

    Only `pre:` snapshots qualify, matching the backend's own filter in
    _earliest_pre_snapshots_from_turn: a `post:` snapshot is the state
    AFTER an edit, never a "restore to before this" target. Turn ids are
    not necessarily contiguous (a turn that only read files writes no
    snapshot at all), so `--last N` indexes into this list rather than
    doing arithmetic on the turn number itself."""
    turns = {
        snap["turn_id"]
        for snap in snapshots
        if snap.get("turn_id") is not None and str(snap.get("message", "")).startswith("pre:")
    }
    return sorted(turns, reverse=True)


def _print_checkpoints(snapshots: List[Dict[str, Any]], turns: List[int]) -> None:
    sys.stdout.write(f"--- Time-Travel checkpoints ({len(turns)} restorable) ---\n")
    for offset, turn_id in enumerate(turns, start=1):
        touched = sorted({
            path
            for snap in snapshots
            if snap.get("turn_id") == turn_id and str(snap.get("message", "")).startswith("pre:")
            for path in snap.get("paths", [])
        })
        preview = ", ".join(touched[:4]) + (f" (+{len(touched) - 4} more)" if len(touched) > 4 else "")
        sys.stdout.write(f"  --last {offset}  -> restore to before user message {turn_id}: {preview or '(no files)'}\n")


def undo_command(
    session_id: str,
    last: int = 1,
    dry_run: bool = False,
    list_only: bool = False,
    assume_yes: bool = False,
    project_dir: Optional[str] = None,
) -> int:
    if last < 1:
        sys.stderr.write("Error: --last must be 1 or greater.\n")
        return 2

    client = AetherisClient()
    ok, msg = check_backend_availability(client)
    if not ok:
        sys.stderr.write(f"Error: {msg}\n")
        return 3

    # The backend resolves Time-Travel snapshots against ITS OWN active
    # project (an env var in the backend process, see
    # core/utils/project_path.py), not against this CLI's cwd. Without
    # this the snapshot list comes back empty for the very project the
    # user is standing in, which reads as "nothing to undo" rather than as
    # the misconfiguration it actually is.
    target_dir = project_dir or os.getcwd()
    try:
        client.set_project_path(target_dir, chat_id=session_id)
    except Exception as e:
        sys.stderr.write(f"Error: could not point the backend at '{target_dir}': {e}\n")
        return 3

    try:
        snapshots = client.list_snapshots(session_id).get("snapshots", [])
    except Exception as e:
        sys.stderr.write(f"Error: could not read the Time-Travel timeline: {e}\n")
        return 1

    turns = _restorable_turns(snapshots)
    if not turns:
        sys.stdout.write(
            f"No Time-Travel checkpoints for session '{session_id}' in {target_dir}.\n"
            "Either the agent hasn't edited anything here yet, or this project isn't a git\n"
            "repository (Time-Travel records snapshots on a git shadow ref, so it stays a\n"
            "no-op outside one -- writes still work, they're just not undoable).\n"
        )
        return 0

    if list_only:
        _print_checkpoints(snapshots, turns)
        return 0

    if last > len(turns):
        sys.stderr.write(
            f"Error: --last {last} requested, but this session only has {len(turns)} "
            f"restorable checkpoint(s). Run `aetheris undo --list` to see them.\n"
        )
        return 2

    target_turn = turns[last - 1]

    try:
        preview = client.preview_checkpoint(session_id, target_turn)
    except Exception as e:
        sys.stderr.write(f"Error: could not build the restore preview: {e}\n")
        return 1

    # preview_rollback returns one entry per touched path even when that
    # path is already identical to the snapshot, with an EMPTY diff string
    # (difflib yields nothing for identical input). Checking the list's
    # length alone therefore reports "1 file would change" for a pure
    # no-op -- and, worse, goes on to "restore" it and print a confident
    # "Restored 1 file(s)". Reproduced directly by running `undo --last 1`
    # twice in a row. Filter on real diff content, not entry count.
    diffs = [d for d in preview.get("diffs", []) if (d.get("diff") or "").strip()]
    if not diffs:
        sys.stdout.write(
            f"Already there: nothing differs from the state before user message {target_turn}. "
            "Nothing was changed.\n"
        )
        return 0

    sys.stdout.write(
        f"Restoring to before user message {target_turn} would change {len(diffs)} file(s):\n\n"
    )
    for entry in diffs:
        sys.stdout.write(f"--- {entry.get('path')} ---\n")
        diff_text = entry.get("diff") or "(no textual diff -- binary or unchanged)\n"
        sys.stdout.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")
        sys.stdout.write("\n")

    if dry_run:
        sys.stdout.write("[--dry-run] Nothing was changed.\n")
        return 0

    if not assume_yes:
        sys.stdout.write(f"Apply this restore to {target_dir}? [y/N]: ")
        sys.stdout.flush()
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("y", "yes"):
            sys.stdout.write("Restore cancelled. Nothing was changed.\n")
            return 4

    try:
        result = client.restore_checkpoint(session_id, target_turn).get("result", {})
    except Exception as e:
        sys.stderr.write(f"Time-Travel restore failed: {e}\n")
        return 1

    if result.get("error"):
        sys.stderr.write(f"Time-Travel restore failed: {result['error']}\n")
        return 1

    sys.stdout.write(result.get("output", "Restore completed.") + "\n")
    return int(result.get("exit_code", 0) or 0)

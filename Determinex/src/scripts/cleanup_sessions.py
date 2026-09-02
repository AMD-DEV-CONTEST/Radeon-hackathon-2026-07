#!/usr/bin/env python3
"""
cleanup_sessions.py — Determinex session directory maintenance utility.

The Determinex orchestrator writes each pipeline run to a UUID-named subdirectory
under sessions/. These accumulate without bound. This script prunes old sessions
by age, with a --dry-run mode for safe inspection first.

Usage:
    python scripts/cleanup_sessions.py --dry-run             # show what would be deleted
    python scripts/cleanup_sessions.py --older-than 30       # delete sessions older than 30 days
    python scripts/cleanup_sessions.py --older-than 7 --keep 10   # keep at least 10 most-recent
    python scripts/cleanup_sessions.py --list                # list all sessions with ages

Options:
    --older-than N    Delete sessions older than N days (default: 30)
    --keep N          Always keep at least N most-recent sessions (default: 5)
    --dry-run         Print what would be deleted without deleting anything
    --list            List all sessions with their ages and sizes
    --sessions-dir P  Path to sessions directory (default: auto-detected)
"""

import argparse
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path


def find_sessions_dir() -> Path:
    """Locate the sessions directory relative to this script."""
    # Try: script is in scripts/, sessions/ is sibling of scripts/
    script_dir = Path(__file__).resolve().parent
    candidate = script_dir.parent / "sessions"
    if candidate.is_dir():
        return candidate
    # Fallback: current working directory
    cwd_candidate = Path.cwd() / "sessions"
    if cwd_candidate.is_dir():
        return cwd_candidate
    raise FileNotFoundError(
        "Could not locate sessions/ directory. "
        "Run from the Determinex repo root or pass --sessions-dir."
    )


def is_uuid_dir(name: str) -> bool:
    """Return True if the directory name is a valid UUID."""
    try:
        uuid.UUID(name)
        return True
    except ValueError:
        return False


def get_session_info(path: Path) -> dict:
    """Return metadata about a session directory."""
    stat = path.stat()
    mtime = stat.st_mtime
    age_days = (time.time() - mtime) / 86400

    # Compute total size
    total_bytes = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    return {
        "path": path,
        "name": path.name,
        "mtime": mtime,
        "age_days": age_days,
        "size_bytes": total_bytes,
        "modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
    }


def format_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def run(args: argparse.Namespace) -> int:
    try:
        sessions_dir = Path(args.sessions_dir) if args.sessions_dir else find_sessions_dir()
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not sessions_dir.is_dir():
        print(f"ERROR: sessions directory not found: {sessions_dir}", file=sys.stderr)
        return 1

    # Collect UUID session dirs only (skip latent_rag.db, specs/, etc.)
    sessions = [
        get_session_info(p) for p in sessions_dir.iterdir() if p.is_dir() and is_uuid_dir(p.name)
    ]

    if not sessions:
        print("No session directories found.")
        return 0

    # Sort newest → oldest
    sessions.sort(key=lambda s: s["mtime"], reverse=True)

    if args.list:
        total_bytes = sum(s["size_bytes"] for s in sessions)
        print(f"\nSessions directory: {sessions_dir}")
        print(f"Total: {len(sessions)} sessions, {format_size(total_bytes)}\n")
        print(f"{'#':<4} {'Modified':<18} {'Age':>8} {'Size':>10}  {'UUID'}")
        print("-" * 70)
        for i, s in enumerate(sessions, 1):
            age = f"{s['age_days']:.0f}d"
            print(
                f"{i:<4} {s['modified']:<18} {age:>8} {format_size(s['size_bytes']):>10}  {s['name']}"
            )
        print()
        return 0

    older_than = args.older_than
    keep = args.keep
    dry_run = args.dry_run
    cutoff_time = time.time() - (older_than * 86400)

    # Sessions to consider for deletion: older than cutoff AND not in the keep-N set
    protected = {s["name"] for s in sessions[:keep]}  # newest N are always safe
    candidates = [s for s in sessions if s["mtime"] < cutoff_time and s["name"] not in protected]

    if not candidates:
        print(
            f"Nothing to clean up (0 sessions older than {older_than} days outside the {keep}-session grace window)."
        )
        return 0

    total_freeable = sum(s["size_bytes"] for s in candidates)
    print(
        f"\n{'DRY RUN — ' if dry_run else ''}Found {len(candidates)} session(s) to delete "
        f"(>{older_than}d old, {format_size(total_freeable)} freeable):\n"
    )

    for s in candidates:
        age = f"{s['age_days']:.0f}d"
        print(
            f"  {'[SKIP] ' if dry_run else '[DELETE] '}{s['name']}  ({age} old, {format_size(s['size_bytes'])})"
        )

    if dry_run:
        print(f"\nDry run complete. Run without --dry-run to delete {len(candidates)} session(s).")
        return 0

    print()
    deleted = 0
    freed = 0
    for s in candidates:
        try:
            shutil.rmtree(s["path"])
            freed += s["size_bytes"]
            deleted += 1
            print(f"  Deleted: {s['name']}")
        except Exception as e:
            print(f"  WARN: Could not delete {s['name']}: {e}", file=sys.stderr)

    print(f"\nDone. Deleted {deleted} session(s), freed {format_size(freed)}.\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Determinex session directory cleanup utility.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--older-than",
        type=int,
        default=30,
        metavar="DAYS",
        help="Delete sessions older than N days (default: 30)",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=5,
        metavar="N",
        help="Always keep at least N most-recent sessions (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted without deleting anything",
    )
    parser.add_argument("--list", action="store_true", help="List all sessions with ages and sizes")
    parser.add_argument(
        "--sessions-dir",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to sessions directory (default: auto-detected)",
    )
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()

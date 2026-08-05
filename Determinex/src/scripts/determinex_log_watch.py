#!/usr/bin/env python3
"""
determinex_log_watch.py — Live colour-coded log tail for active Hive Mind build sessions.

Tails sessions/<id>/session.log, colours output by content, shows step progress,
and exits cleanly when the session completes (status: complete or failed).

Usage:
    python scripts/determinex_log_watch.py                    # auto-detect newest session
    python scripts/determinex_log_watch.py <session_id>       # specific session
    python scripts/determinex_log_watch.py --list             # list all sessions
    python scripts/determinex_log_watch.py --follow           # keep tailing after completion
    python scripts/determinex_log_watch.py --no-colour        # plain output (for piping)
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# ── ANSI colours ──────────────────────────────────────────────────────────────
_COLOUR = True  # toggled off by --no-colour


def _c(code: str, text: str) -> str:
    if not _COLOUR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t):
    return _c("92", t)


def red(t):
    return _c("91", t)


def yellow(t):
    return _c("93", t)


def cyan(t):
    return _c("96", t)


def blue(t):
    return _c("94", t)


def dim(t):
    return _c("2", t)


def bold(t):
    return _c("1", t)


def magenta(t):
    return _c("95", t)


# ── Line classifier ───────────────────────────────────────────────────────────

# Ordered by priority — first match wins
PATTERNS = [
    # Compiler Oracle verdicts
    (
        re.compile(r"\b(COMPILER[:\s]+PASS|compiler.*pass|cargo build.*ok)\b", re.I),
        lambda m, line: green(f"  ✓ {line.strip()}"),
    ),
    (
        re.compile(
            r"\b(COMPILER[:\s]+FAIL|compiler.*error|cargo build.*fail|error\[E\d+\])\b", re.I
        ),
        lambda m, line: red(f"  ✗ {line.strip()}"),
    ),
    # Monitor verdicts
    (
        re.compile(r"\b(MONITOR[:\s]+PASS|verdict.*PASS|VERDICT:.*PASS)\b", re.I),
        lambda m, line: green(f"  ✓ {line.strip()}"),
    ),
    (
        re.compile(r"\b(MONITOR[:\s]+FAIL|verdict.*FAIL|VERDICT:.*FAIL)\b", re.I),
        lambda m, line: yellow(f"  ⚠ {line.strip()}"),
    ),
    # Step transitions
    (
        re.compile(r"\[step[_ ]?(\d+)\].*start|starting step (\d+)|step (\d+).*begin", re.I),
        lambda m, line: cyan(f"\n  ▶ {line.strip()}"),
    ),
    (
        re.compile(r"\[step[_ ]?(\d+)\].*complete|step (\d+).*done|step (\d+).*pass", re.I),
        lambda m, line: green(f"  ✓ {line.strip()}"),
    ),
    (
        re.compile(r"\[step[_ ]?(\d+)\].*fail|step (\d+).*failed|step (\d+).*retry", re.I),
        lambda m, line: red(f"  ✗ {line.strip()}"),
    ),
    # Session lifecycle
    (
        re.compile(r"session\s+(complete|finished|done|succeeded)", re.I),
        lambda m, line: bold(green(f"\n  ★ {line.strip()}")),
    ),
    (
        re.compile(r"session\s+(failed|aborted|error)", re.I),
        lambda m, line: bold(red(f"\n  ✗ {line.strip()}")),
    ),
    (
        re.compile(r"(oracle|architect|builder|monitor)\s*(role|step|starting|running)", re.I),
        lambda m, line: magenta(f"  ◆ {line.strip()}"),
    ),
    # Retries and escalations
    (
        re.compile(r"(retry|retrying|attempt\s+\d+)", re.I),
        lambda m, line: yellow(f"  ↺ {line.strip()}"),
    ),
    (
        re.compile(r"(escalat|architect.*replan|re[-_]?plan)", re.I),
        lambda m, line: yellow(f"  ⬆ {line.strip()}"),
    ),
    # Cost tracking
    (
        re.compile(r"(cost|tokens?|budget)[\s:]+[\$\d]", re.I),
        lambda m, line: dim(f"  💰 {line.strip()}"),
    ),
    # DSL messages
    (re.compile(r"^INTENT:", re.M), lambda m, line: dim(f"  ≋ {line.strip()}")),
    # Generic errors/warnings
    (
        re.compile(r"\b(error|exception|traceback|critical)\b", re.I),
        lambda m, line: red(f"  ! {line.strip()}"),
    ),
    (re.compile(r"\b(warning|warn)\b", re.I), lambda m, line: yellow(f"  ~ {line.strip()}")),
    # Info / progress
    (re.compile(r"\b(info|debug)\b", re.I), lambda m, line: dim(f"    {line.strip()}")),
]


def colour_line(raw: str) -> str:
    line = raw.rstrip()
    if not line:
        return ""
    for pattern, formatter in PATTERNS:
        m = pattern.search(line)
        if m:
            return formatter(m, line)
    # Default: dim pass-through
    return dim(f"    {line}")


# ── Session discovery ─────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = REPO_ROOT / "sessions"


def find_sessions() -> list[Path]:
    if not SESSIONS_DIR.exists():
        return []
    return sorted(
        [d for d in SESSIONS_DIR.iterdir() if d.is_dir() and (d / "session.log").exists()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )


def newest_session() -> Path | None:
    sessions = find_sessions()
    return sessions[0] if sessions else None


def find_session_by_id(session_id: str) -> Path | None:
    # Exact match first
    exact = SESSIONS_DIR / session_id
    if exact.exists() and (exact / "session.log").exists():
        return exact
    # Prefix match
    for d in find_sessions():
        if d.name.startswith(session_id):
            return d
    return None


def read_manifest(session_dir: Path) -> dict | None:
    manifest = session_dir / "manifest.json"
    if manifest.exists():
        try:
            return json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


# ── Progress bar ──────────────────────────────────────────────────────────────


def render_progress(manifest: dict | None) -> str:
    if not manifest:
        return ""
    steps = manifest.get("steps", [])
    if not steps:
        return ""
    total = len(steps)
    done = sum(1 for s in steps if s.get("status") == "complete")
    failed = sum(1 for s in steps if s.get("status") == "failed")
    in_prog = sum(1 for s in steps if s.get("status") == "in_progress")

    bar_width = 30
    filled = int(bar_width * done / total) if total > 0 else 0
    bar = green("█" * filled) + dim("░" * (bar_width - filled))
    pct = int(100 * done / total) if total > 0 else 0

    status_bits = [f"{green(str(done))} done"]
    if in_prog:
        status_bits.append(f"{cyan(str(in_prog))} running")
    if failed:
        status_bits.append(f"{red(str(failed))} failed")
    status_bits.append(f"{dim(str(total - done - failed - in_prog))} pending")

    return f"  [{bar}] {pct}%  {' · '.join(status_bits)}"


def render_session_header(session_dir: Path, manifest: dict | None):
    sid = session_dir.name
    print(f"\n{bold(cyan('─' * 60))}")
    print(f"  {bold('Session:')} {cyan(sid)}")
    if manifest:
        lang = manifest.get("lang", "?")
        status = manifest.get("status", "?")
        proj = manifest.get("project_name", "")
        status_col = (
            green(status)
            if status == "complete"
            else red(status)
            if status == "failed"
            else yellow(status)
        )
        print(
            f"  {bold('Project:')} {proj or dim('(unnamed)')}  "
            f"{bold('Lang:')} {lang}  "
            f"{bold('Status:')} {status_col}"
        )
    print(render_progress(manifest))
    print(f"{bold(cyan('─' * 60))}\n")


# ── Session listing ───────────────────────────────────────────────────────────


def list_sessions():
    sessions = find_sessions()
    if not sessions:
        print(f"  {red('No sessions found.')} Run a build to create one.")
        return

    print(f"\n  {bold('Sessions')} (newest first):\n")
    for sd in sessions[:20]:
        manifest = read_manifest(sd)
        status = "?"
        lang = "?"
        proj = ""
        if manifest:
            status = manifest.get("status", "?")
            lang = manifest.get("lang", "?")
            proj = manifest.get("project_name", "")

        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(sd.stat().st_mtime))
        status_col = (
            green(status)
            if status == "complete"
            else red(status)
            if status == "failed"
            else yellow(status)
        )
        log_size = (sd / "session.log").stat().st_size if (sd / "session.log").exists() else 0
        log_kb = f"{log_size // 1024}KB" if log_size >= 1024 else f"{log_size}B"

        print(
            f"  {dim(sd.name[:36])}  {status_col:<20}  {cyan(lang):<8}  {mtime}  {dim(log_kb)}"
            + (f"  {dim(proj)}" if proj else "")
        )

    print()


# ── Tail loop ─────────────────────────────────────────────────────────────────


def is_session_finished(manifest: dict | None) -> bool:
    if not manifest:
        return False
    return manifest.get("status") in ("complete", "failed")


def tail_session(session_dir: Path, follow: bool = False):
    log_path = session_dir / "session.log"
    if not log_path.exists():
        print(f"  {red('Log file not found:')} {log_path}")
        return

    manifest = read_manifest(session_dir)
    render_session_header(session_dir, manifest)

    # Print existing content first
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            rendered = colour_line(line)
            if rendered:
                print(rendered)

    # Check if already finished
    if is_session_finished(manifest) and not follow:
        print(f"\n  {bold(dim('Session already complete.'))} Use --follow to keep watching.")
        return

    # Tail new lines
    print(f"\n  {dim('Watching for new output…  (Ctrl-C to stop)')}\n")
    last_progress_time = time.time()

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)  # seek to end
            while True:
                line = f.readline()
                if line:
                    rendered = colour_line(line)
                    if rendered:
                        print(rendered, flush=True)
                else:
                    time.sleep(0.25)

                    # Refresh manifest every 3s for progress + completion detection
                    if time.time() - last_progress_time > 3:
                        manifest = read_manifest(session_dir)
                        last_progress_time = time.time()

                        # Print progress bar update
                        prog = render_progress(manifest)
                        if prog:
                            print(f"\r{prog}", end="", flush=True)

                        if is_session_finished(manifest) and not follow:
                            print()  # newline after progress
                            final_status = manifest.get("status", "?")
                            if final_status == "complete":
                                print(f"\n  {bold(green('★ Build complete!'))}")
                            else:
                                print(f"\n  {bold(red('✗ Build failed.'))} Check logs above.")
                            return

    except KeyboardInterrupt:
        print(f"\n  {dim('Stopped.')}")


# ── Optional: detect from Tauri app data dir ─────────────────────────────────


def find_sessions_in_appdata() -> list[Path]:
    """Also check the Tauri app data directory for sessions."""
    candidates = []

    # Windows: %APPDATA%\Determinex\sessions or similar
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        for subdir in ["Determinex", "com.determinex.hive", "determinex-hive"]:
            p = Path(appdata) / subdir / "sessions"
            if p.exists():
                candidates.extend(
                    d for d in p.iterdir() if d.is_dir() and (d / "session.log").exists()
                )

    return sorted(candidates, key=lambda d: d.stat().st_mtime, reverse=True)


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    global _COLOUR

    parser = argparse.ArgumentParser(description="Determinex Hive Mind live log watcher")
    parser.add_argument("session_id", nargs="?", help="Session ID or prefix (default: newest)")
    parser.add_argument("--list", action="store_true", help="List all sessions and exit")
    parser.add_argument(
        "--follow", action="store_true", help="Keep tailing after session completes"
    )
    parser.add_argument("--no-colour", "--no-color", action="store_true", help="Plain text output")
    args = parser.parse_args()

    if args.no_colour:
        _COLOUR = False

    if args.list:
        list_sessions()
        # Also check appdata
        extra = find_sessions_in_appdata()
        if extra:
            print(f"  {dim('Also found in AppData:')}")
            for d in extra[:5]:
                print(f"  {dim(str(d))}")
        return

    session_dir: Path | None = None

    if args.session_id:
        session_dir = find_session_by_id(args.session_id)
        if not session_dir:
            # Try appdata
            for d in find_sessions_in_appdata():
                if d.name.startswith(args.session_id):
                    session_dir = d
                    break
        if not session_dir:
            print(f"  {red('Session not found:')} {args.session_id}")
            print(f"  {dim('Use --list to see available sessions.')}")
            sys.exit(1)
    else:
        session_dir = newest_session()
        if not session_dir:
            # Try appdata
            extra = find_sessions_in_appdata()
            session_dir = extra[0] if extra else None
        if not session_dir:
            print(f"  {red('No sessions found.')}")
            print(f"  {dim('Start a build first, then run this watcher.')}")
            sys.exit(1)
        print(f"  {dim('Auto-selected newest session:')} {cyan(session_dir.name)}")

    tail_session(session_dir, follow=args.follow)


if __name__ == "__main__":
    main()

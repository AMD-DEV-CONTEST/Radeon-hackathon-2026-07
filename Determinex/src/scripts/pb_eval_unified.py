"""
pb_eval_unified.py — Run ProgramBench evals locally or on Hetzner.

Routing:
  total tests < 500  → local
  total tests 500-2000 → Hetzner preferred, local fallback
  total tests > 2000  → always Hetzner

Usage:
  python scripts/pb_eval_unified.py --tool entr
  python scripts/pb_eval_unified.py --batch pending_unlock/priority_1_under100
  python scripts/pb_eval_unified.py --tool entr --force-local
  python scripts/pb_eval_unified.py --tool entr --force-hetzner
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
PB_DIR = ROOT / "corpus" / "programbench"
PENDING_BASE = PB_DIR / "pending_unlock"
LOCKED_BASE = PB_DIR / "locked"
INDEX_FILE = PB_DIR / "eval_index.json"
LOG_DIR = ROOT / "logs"
REGRESSIONS_LOG = LOG_DIR / "regressions.jsonl"


def _is_dir(p: str | Path | None) -> bool:
    """`Path.is_dir()` that treats "I am not allowed to look" as "not this one".

    pathlib swallows ENOENT/ENOTDIR/EBADF/ELOOP and re-raises everything else, so EACCES
    propagates. Probing "/root/ProgramBench" as a non-root user therefore raises
    PermissionError at IMPORT time -- this module could not be imported at all on any Linux
    box where /root is the usual 0700, which is every one of them except the eval box.
    Found by CI: `ERROR tests/scripts/test_pb_eval_unified_disk_guard.py - PermissionError:
    [Errno 13] Permission denied: '/root/ProgramBench'`, at collection, before a single
    assertion ran. A candidate path we cannot stat is simply not our install.
    """
    try:
        return bool(p) and Path(p).is_dir()
    except OSError:
        return False


# Local ProgramBench install (box-portable: env override -> Linux box -> Windows dev)
def _detect_pb_local() -> Path:
    for c in (os.environ.get("PROGRAMBENCH_HOME"), "/root/ProgramBench", "T:/Dev/ProgramBench"):
        if _is_dir(c):
            return Path(c)
    return Path("T:/Dev/ProgramBench")


def _detect_pb_staging() -> Path:
    e = os.environ.get("PB_STAGING_DIR")
    if e:
        return Path(e)
    # on the Linux eval box, stage under /root/determinex-staging (same place official_eval uses)
    return (
        Path("/root/determinex-staging")
        if _is_dir("/root/ProgramBench")
        else Path("T:/determinex-programbench")
    )


PB_LOCAL = _detect_pb_local()
PB_LOCAL_VENV_UV = PB_LOCAL / ".venv" / "Scripts" / "uv.exe"  # Windows path (unused on Linux)
PB_STAGING = _detect_pb_staging()

# Hetzner config
HETZNER_CONFIG = ROOT / "config" / "hetzner.json"
HETZNER_IP = "5.78.192.163"
HETZNER_SSH_KEY = Path.home() / ".ssh" / "id_citadel"
HETZNER_REMOTE_DIR = "/root/determinex-pb-uncap"

# Cap detection pattern
CAP_PATTERN = re.compile(r"^\s*del\s+items\s*\[\s*\d+\s*:\s*\]\s*$", re.MULTILINE)
KEYWORD_FILTER = re.compile(
    r"if any\(s in nodeid for s in \([^)]*(?:tmux|interactive|libtmux|pexpect|test_pty)[^)]*\)\)",
    re.IGNORECASE,
)


def load_index() -> list[dict]:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return []


def save_index(index: list[dict]) -> None:
    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def update_index_entry(slug: str, updates: dict) -> None:
    index = load_index()
    for e in index:
        if e["slug"] == slug:
            e.update(updates)
            break
    else:
        index.append({"slug": slug, **updates})
    save_index(index)


def find_uncapped_tarball(slug: str) -> Path | None:
    """Find submission_uncapped.tar.gz or fall back to submission.tar.gz."""
    for pri in ("priority_1_under100", "priority_2_under300", "priority_3_over300", ""):
        base = PENDING_BASE / pri / slug if pri else PENDING_BASE / slug
        uncapped = base / "submission_uncapped.tar.gz"
        if uncapped.exists():
            return uncapped
        fallback = base / "submission.tar.gz"
        if fallback.exists():
            return fallback
    # Also check locked dirs
    for d in LOCKED_BASE.iterdir():
        if d.is_dir() and slug in d.name:
            t = d / "submission.tar.gz"
            if t.exists():
                return t
    return None


def find_tool_dir(slug: str) -> Path | None:
    for pri in ("priority_1_under100", "priority_2_under300", "priority_3_over300", ""):
        base = PENDING_BASE / pri / slug if pri else PENDING_BASE / slug
        if base.exists():
            return base
    return None


def verify_submission(tarball: Path) -> tuple[bool, list[str]]:
    """Verify the submission is safe to eval. Returns (ok, warnings)."""
    warnings = []
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            for m in tf.getmembers():
                if m.name.endswith("compile.sh") or "conftest.py" in m.name:
                    f = tf.extractfile(m)
                    if f is None:
                        continue
                    content = f.read().decode("utf-8", errors="replace")

                    if m.name.endswith("compile.sh"):
                        if CAP_PATTERN.search(content):
                            return False, [f"ABORT: del items[N:] cap still present in {m.name}"]

                    if "conftest.py" in m.name:
                        if KEYWORD_FILTER.search(content):
                            warnings.append(f"WARN: Old keyword TUI filter in {m.name}")
                        if "timeout" not in content:
                            warnings.append(f"WARN: No timeout configured in {m.name}")

    except Exception as ex:
        return False, [f"ABORT: Cannot read tarball: {ex}"]

    return True, warnings


def count_tests_in_tarball(tarball: Path) -> int:
    """Estimate test count from locked eval or unlock_ticket."""
    # Try to read from the tool's unlock_ticket
    for _pri in ("priority_1_under100", "priority_2_under300", "priority_3_over300", ""):
        # Find the slug from tarball parent
        slug_dir = tarball.parent
        ticket = slug_dir / "unlock_ticket.json"
        if ticket.exists():
            try:
                t = json.loads(ticket.read_text())
                est = t.get("estimated_uncapped_total") or t.get("current_total", 0)
                if est:
                    return est
            except Exception:
                pass
    return 0


def route_eval(total_tests: int, force_local: bool, force_hetzner: bool) -> str:
    if force_local:
        return "local"
    if force_hetzner:
        return "hetzner"
    if total_tests < 500:
        return "local"
    if total_tests <= 2000:
        # Prefer Hetzner if configured
        return "hetzner" if HETZNER_CONFIG.exists() else "local"
    return "hetzner"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_eval_disk_headroom(
    path: str | Path | None = None, min_free_gb: float | None = None
) -> dict:
    """Fail fast before ProgramBench eval if the Docker host is low on disk.

    PB evals build multi-GB Docker images and write result artifacts from inside
    containers. When the host root filesystem is nearly full, the failure mode is
    often a hung/no-report eval instead of a clean "disk full" exception.
    """
    if path is None:
        path = os.environ.get("DETERMINEX_PB_DISK_GUARD_PATH")
    if path is None:
        path = "/" if _is_dir("/root/ProgramBench") else PB_STAGING.anchor or "."
    if min_free_gb is None:
        min_free_gb = float(os.environ.get("DETERMINEX_PB_MIN_FREE_GB", "20"))
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024**3)
    total_gb = usage.total / (1024**3)
    if free_gb < min_free_gb:
        raise RuntimeError(
            "PB eval disk guard: "
            f"{Path(path)} has {free_gb:.1f}GB free, below required "
            f"{min_free_gb:.1f}GB. Prune inactive programbench-compiled "
            "Docker caches before launching eval."
        )
    return {"path": str(path), "free_gb": free_gb, "total_gb": total_gb, "min_free_gb": min_free_gb}


def _get_canonical_slug(slug: str) -> tuple[str, str]:
    """Return (canonical_slug, author) for a tool slug.

    Reads from unlock_ticket.json if available, otherwise uses slug directly.
    canonical_slug format: 'author__tool.hash'
    """
    # Try ticket first
    for pri in ("priority_1_under100", "priority_2_under300", "priority_3_over300", ""):
        base = PENDING_BASE / pri / slug if pri else PENDING_BASE / slug
        ticket_path = base / "unlock_ticket.json"
        if ticket_path.exists():
            try:
                ticket = json.loads(ticket_path.read_text())
                canonical = ticket.get("canonical_slug", "")
                author = ticket.get("author", "")
                if canonical and author:
                    return canonical, author
            except Exception:
                pass

    # Fall back: slug may already be canonical (author__tool.hash)
    if "__" in slug:
        return slug, slug.split("__")[0]
    return slug, slug.split(".")[0]


def run_local_eval(slug: str, tarball: Path) -> dict | None:
    """Run eval locally using T:/Dev/ProgramBench.

    Creates the ProgramBench expected structure:
      staging_dir/canonical_slug/submission.tar.gz
    where canonical_slug is 'author__tool.hash' (e.g. 'eradman__entr.8e2e8b4').
    """
    disk = ensure_eval_disk_headroom()
    print(
        f"  Disk preflight: {disk['free_gb']:.1f}GB free at {disk['path']} "
        f"(min {disk['min_free_gb']:.1f}GB)"
    )
    canonical, author = _get_canonical_slug(slug)
    staging_dir = PB_STAGING / f"uncap_{slug}_{int(time.time())}"
    task_dir = staging_dir / canonical
    task_dir.mkdir(parents=True, exist_ok=True)

    # Place the tarball as submission.tar.gz inside the task dir
    dest_tarball = task_dir / "submission.tar.gz"
    shutil.copy2(tarball, dest_tarball)

    preflight_submission(canonical, dest_tarball)  # oracle: catch compile.sh mangling + stale cache

    try:
        cmd = ["uv", "run", "programbench", "eval", str(staging_dir), "--filter", author, "--force"]

        print(f"  Staging: {staging_dir}/{canonical}/")
        print(f"  Running local eval: {' '.join(cmd)}")
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PROGRAMBENCH_DOCKER_CPUS"] = "4"

        # Popen + current-test stall poll. run_hetzner_eval has this; run_local_eval lacked it, so a
        # stuck local eval blocked the box drive for the full 2h timeout. Kill if the eval's
        # compiled containers stop changing tests for STALL_SECS, or it exceeds HARD_CAP.
        # A momentary no-container gap is treated as PROGRESSING (never false-kill on a transient).
        STALL_SECS = int(os.environ.get("DETERMINEX_PB_STALL_SECS", "240"))
        HARD_CAP = int(os.environ.get("DETERMINEX_PB_EVAL_HARD_CAP_SECS", "1800"))
        POLL = int(os.environ.get("DETERMINEX_PB_POLL_SECS", "45"))
        logf = staging_dir / "eval.out"
        with open(logf, "w", encoding="utf-8") as _lf:
            proc = subprocess.Popen(
                cmd, cwd=str(PB_LOCAL), env=env, stdout=_lf, stderr=subprocess.STDOUT, text=True
            )
            t0 = time.time()
            stalled = 0
            reason = None
            last_sig = None
            while True:
                try:
                    proc.wait(timeout=POLL)
                    break
                except subprocess.TimeoutExpired:
                    pass
                # PROGRESS = is the eval advancing THROUGH TESTS? Container CPU is the WRONG signal:
                # a STUCK eval whose tmux/tool/xdist threads keep spinning reads >5% and looks "busy"
                # forever (ov ran 15min+ at ~3%, never progressing, and the old <5% gate never fired).
                # The reliable signal is the set of PYTEST_CURRENT_TEST inside the compiled eval
                # container + the log size: a working eval changes the current test every few seconds
                # (PB caps each test at <=30s), a stuck one shows the SAME (or empty) current test and
                # a frozen log. So we trip a stall in 4min instead of riding the 30min cap.
                # find ALL of THIS tool's eval containers (PB runs branches in PARALLEL, each its own
                # container from the same compiled image) and EXCLUDE other tools -- box7 --all runs
                # several evals at once, and sampling another tool's (progressing) container would
                # read ITS progress and never flag THIS one as stuck (the concurrency trap).
                try:
                    cids = subprocess.run(
                        f"docker ps --format '{{{{.ID}}}} {{{{.Image}}}}' | grep -F 'compiled/{slug}' "
                        f"| awk '{{print $1}}'",
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=20,
                    ).stdout.split()
                except Exception:
                    cids = []
                ctests = (
                    "" if cids else "?"
                )  # no container yet (building/between) -> treat as progress
                for cid in cids:
                    try:
                        ctests += subprocess.run(
                            [
                                "docker",
                                "exec",
                                cid,
                                "sh",
                                "-c",
                                "cat /proc/[0-9]*/environ 2>/dev/null | tr '\\000' '\\n' | "
                                "grep -h PYTEST_CURRENT_TEST=",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=15,
                        ).stdout
                    except Exception:
                        ctests = (
                            "?"  # unmeasurable -> progress (never false-kill on a docker hiccup)
                        )
                        break
                if ctests != "?":
                    ctests = "\n".join(
                        sorted(ctests.splitlines())
                    )  # order-independent across polls
                try:
                    logsz = logf.stat().st_size
                except Exception:
                    logsz = 0
                sig = (ctests, logsz)
                # progressed if: unmeasurable/no-container-yet, OR the UNION of current tests across
                # the tool's branch containers changed, OR the log grew, since the last poll.
                progressed = ctests == "?" or last_sig is None or sig != last_sig
                last_sig = sig
                stalled = 0 if progressed else stalled + POLL
                if ctests == "?":
                    current = "building/no-container"
                else:
                    tests = []
                    for line in ctests.splitlines():
                        if line.startswith("PYTEST_CURRENT_TEST="):
                            tests.append(line.split("=", 1)[1])
                    current = "; ".join(tests[:3]) if tests else "no current pytest"
                    if len(tests) > 3:
                        current += f"; +{len(tests) - 3} more"
                if len(current) > 220:
                    current = current[:217] + "..."
                print(
                    f"  [eval heartbeat] {slug}: elapsed={int(time.time() - t0)}s "
                    f"stalled={stalled}s log={logsz}B current={current}",
                    flush=True,
                )
                if stalled >= STALL_SECS:
                    reason = (
                        f"no test progress for {stalled}s (current-test set + log frozen = stuck)"
                    )
                elif time.time() - t0 >= HARD_CAP:
                    reason = f"exceeded {HARD_CAP}s hard cap"
                if reason:
                    print(
                        f"  HANG: {slug} {reason} -> killing eval + compiled containers",
                        file=sys.stderr,
                    )
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        if not cids:
                            cids = subprocess.run(
                                f"docker ps --format '{{{{.ID}}}} {{{{.Image}}}}' | "
                                f"grep -F 'compiled/{slug}' | awk '{{print $1}}'",
                                shell=True,
                                capture_output=True,
                                text=True,
                                timeout=20,
                            ).stdout.split()
                        for cid in cids:
                            subprocess.run(
                                ["docker", "rm", "-f", cid], capture_output=True, timeout=30
                            )
                    except Exception:
                        pass
                    _alert_hang(slug, int(time.time() - t0))
                    return None
        rc = proc.returncode
        if rc != 0:
            try:
                tail = logf.read_text(encoding="utf-8", errors="replace")[-500:]
            except Exception:
                tail = ""
            print(f"  Eval rc={rc}: {tail}", file=sys.stderr)

        # Find the eval output json (named canonical.eval.json)
        eval_jsons = list(staging_dir.rglob("*.eval.json"))
        if not eval_jsons:
            print("  ERROR: No eval.json produced", file=sys.stderr)
            return {"passed": 0, "total": 0, "outcome": "NO_EVAL_JSON", "pct": 0.0}

        data = json.loads(eval_jsons[0].read_text(encoding="utf-8", errors="replace"))
        diagnose_not_run(data, canonical)  # oracle auto-surfaces not_run causes
        return data
    except Exception as ex:
        print(f"  ERROR: {ex}", file=sys.stderr)
        return None
    finally:
        try:
            shutil.rmtree(staging_dir, ignore_errors=True)
        except Exception:
            pass


def preflight_submission(slug: str, tarball: Path) -> list:
    """Oracle preflight before every eval (operator ask 2026-06-26): catch the build-breaking
    gotchas automatically instead of after a wasted eval.
      (1) compile.sh MANGLING -- a heredoc that expanded host shell vars bakes in an absolute
          host PATH / `(x86)` parens / `cd "/usr/bin"` -> dash `Syntax error "(" unexpected`.
      (2) STALE :determinex-cached image -> executable_hash_mismatch -> all not_run. Auto-purge it.
      (3) PROHIBITED upstream source shipped (provenance) -- many real-repo source files + an ELF.
    Returns a list of warnings (also printed loudly)."""
    import tarfile as _tf

    warns = []
    hard_rejects = []
    # (2) purge stale compiled-cache so a changed submission never reuses an old binary
    try:
        subprocess.run(
            ["docker", "rmi", "-f", f"programbench-compiled/{slug}:determinex-cached"],
            capture_output=True,
            timeout=60,
        )
    except Exception:
        pass
    try:
        with _tf.open(tarball) as t:
            members = t.getmembers()
            comp = next((m for m in members if m.name.strip("./") == "compile.sh"), None)
            if comp:
                txt = t.extractfile(comp).read().decode("utf-8", "replace")
                bad = [
                    m
                    for m in (
                        "/c/Users",
                        "/c/Program Files",
                        "(x86)",
                        'cd "/usr/bin"',
                        "\\Users\\",
                        "Microsoft VS Code",
                    )
                    if m in txt
                ]
                # a baked host PATH is a long line with many colon-separated absolute
                # dirs (:/usr/...); a base64 printf blob is long but has NO colons -> skip it.
                longpath = any(len(ln) > 400 and ln.count(":/") >= 3 for ln in txt.splitlines())
                if bad or longpath:
                    warns.append(
                        "compile.sh MANGLED (heredoc expanded host vars: %s%s). Rebuild it "
                        "LITERAL (quoted <<'EOF' or a .py file). It will fail with a dash "
                        "syntax error." % (bad, " +400-char PATH line" if longpath else "")
                    )
            # (3) prohibited-upstream heuristic: many source files + an ELF named like the tool
            srcs = [
                m for m in members if m.isfile() and m.name.endswith((".go", ".rs", ".c", ".cpp"))
            ]
            short = slug.split("__")[-1].split(".")[0]
            elf = False
            for m in members:
                if m.isfile() and m.name.strip("./") in (short, short + ".exe") and m.size > 200000:
                    f = t.extractfile(m)
                    if f and f.read(4) == b"\x7fELF":
                        elf = True
                        break
            if elf:
                hard_rejects.append(
                    f"submission ships a prebuilt {short} ELF -> PROHIBITED. "
                    "Remove it; build from source."
                )
            if len(srcs) > 8:
                hard_rejects.append(
                    f"submission has {len(srcs)} source files -> likely UPSTREAM tree "
                    "(prohibited). A legit reimpl is 1-few authored files."
                )
    except Exception as e:
        warns.append(f"preflight scan error: {e}")
    warns.extend(hard_rejects)
    for w in warns:
        print(f"  ⚠️  [preflight oracle] {slug}: {w}", file=sys.stderr)
    if hard_rejects:
        raise RuntimeError("PROVENANCE_REJECT: " + " | ".join(hard_rejects))
    return warns


def diagnose_not_run(data: dict, slug: str = "") -> dict:
    """Oracle auto-surfaces not_run causes after every eval (operator ask 2026-06-26).
    not_run = a test in tests.json that produced NO result -> the binary/collection broke, NOT a
    behavioral miss. This prints a loud, actionable verdict so a broken build never looks like a
    low score. Composes the known not_run taxonomy (build-fail / hash-mismatch / cap / bidir / TUI)."""

    def _w(o):
        if isinstance(o, dict):
            if "test_results" in o and isinstance(o["test_results"], list):
                return o["test_results"]
            for v in o.values():
                r = _w(v)
                if r is not None:
                    return r
        return None

    tr = _w(data) or []
    from collections import Counter

    c = Counter(t.get("status") for t in tr)
    nr = c.get("not_run", 0)
    total = len(tr)
    out = {
        "total": total,
        "passed": c.get("passed", 0),
        "not_run": nr,
        "failed": c.get("failure", 0) + c.get("failed", 0),
        "skipped": c.get("skipped", 0),
    }
    if nr == 0:
        return out
    # classify the not_run cause from the result rows
    ecs = Counter(
        (t.get("extra", {}) or {}).get("error_code") for t in tr if t.get("status") == "not_run"
    )
    msg = []
    if nr == total:  # EVERYTHING not_run -> build/collection broke
        if "executable_hash_mismatch" in ecs:
            msg.append(
                "ALL not_run + executable_hash_mismatch -> STALE :determinex-cached image. "
                "FIX: docker rmi -f programbench-compiled/%s:determinex-cached, re-eval." % slug
            )
        else:
            msg.append(
                "ALL not_run -> BUILD or COLLECTION BROKE (no executable / 0 tests collected). "
                "FIX: run compile.sh in the :task image, check build.err (syntax/rc127), purge "
                ":determinex-cached, verify executable is produced."
            )
    else:
        # partial: prefix-dupe (bidir) vs cap vs genuine TUI
        names = [t.get("name", "") for t in tr if t.get("status") == "not_run"]
        tui = sum(1 for n in names if re.search(r"tmux|_tui_|pty|curses|pexpect", n, re.I))
        if tui:
            msg.append(
                f"{tui}/{nr} not_run look TUI (tmux/pty/curses) -> provision tmux + PTY or confirm genuine."
            )
        msg.append(
            f"{nr}/{total} not_run -> check bidir-prefix dupes (determinex_pb_bidir_restore) / "
            "collection cap (del items / collect_ignore_glob) before trusting the score."
        )
    print(
        f"\n  ⚠️  [not_run oracle] {slug}: {nr}/{total} not_run. " + " ".join(msg) + "\n",
        file=sys.stderr,
    )
    return out


def _alert_hang(slug: str, stalled_secs: int) -> None:
    """Ping on a stuck/hung eval: loud line + append to a hang-alert ledger (+ optional
    determinex_notify if present). Lets a batch flag hangs instead of silently burning time."""
    msg = f"HANG: {slug} stalled {stalled_secs}s (eval auto-escaped)"
    print(f"\n{'!' * 60}\n  ⚠️  {msg}\n{'!' * 60}", file=sys.stderr)
    try:
        led = ROOT / "logs" / "pb_hang_alerts.jsonl"
        led.parent.mkdir(parents=True, exist_ok=True)
        with open(led, "a", encoding="utf-8") as f:
            f.write(
                json.dumps({"ts": int(time.time()), "slug": slug, "stalled_secs": stalled_secs})
                + "\n"
            )
    except Exception:
        pass
    try:
        import determinex_notify  # type: ignore

        fn = next(
            (
                getattr(determinex_notify, n)
                for n in ("notify", "send", "push", "alert")
                if callable(getattr(determinex_notify, n, None))
            ),
            None,
        )
        if fn:
            fn(msg)  # best-effort ping
    except Exception:
        pass


def run_hetzner_eval(slug: str, tarball: Path) -> dict | None:
    """Run eval on Hetzner via SSH."""
    ssh_host = HETZNER_IP
    ssh_key = str(HETZNER_SSH_KEY)
    remote_dir = f"{HETZNER_REMOTE_DIR}/{slug}_{int(time.time())}"
    remote_eval_dir = f"{remote_dir}/eval_run"
    # PB `programbench eval <dir>` expects <dir>/<slug>/submission.tar.gz and extracts it
    # itself. The prior code extracted the tarball CONTENTS into remote_eval_dir, so eval
    # found no submission and exited ~0s with no eval.json. Keep the tarball in a slug
    # subdir; do NOT pre-extract.
    remote_slug_dir = f"{remote_eval_dir}/{slug}"
    remote_tarball = f"{remote_slug_dir}/submission.tar.gz"
    log_file = f"/root/{slug}_uncap_eval.log"

    def ssh(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        for attempt in range(3):
            try:
                return subprocess.run(
                    [
                        "ssh",
                        "-i",
                        ssh_key,
                        "-o",
                        "StrictHostKeyChecking=no",
                        f"root@{ssh_host}",
                        cmd,
                    ],
                    capture_output=True,
                    text=True,
                    check=check,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                if attempt == 2:
                    raise
                time.sleep(2)

    def scp_to(local: Path, remote: str) -> None:
        for attempt in range(3):
            try:
                subprocess.run(
                    [
                        "scp",
                        "-i",
                        ssh_key,
                        "-o",
                        "StrictHostKeyChecking=no",
                        str(local),
                        f"root@{ssh_host}:{remote}",
                    ],
                    check=True,
                    timeout=300,
                )
                return
            except subprocess.TimeoutExpired:
                if attempt == 2:
                    raise
                time.sleep(2)

    def scp_from(remote: str, local: Path) -> None:
        for attempt in range(3):
            try:
                subprocess.run(
                    [
                        "scp",
                        "-i",
                        ssh_key,
                        "-o",
                        "StrictHostKeyChecking=no",
                        f"root@{ssh_host}:{remote}",
                        str(local),
                    ],
                    check=True,
                    timeout=300,
                )
                return
            except subprocess.TimeoutExpired:
                if attempt == 2:
                    raise
                time.sleep(2)

    try:
        print(f"  Preparing Hetzner eval for {slug}...")
        # Create remote staging dir (slug subdir holds the tarball; PB eval extracts it)
        ssh(f"mkdir -p {remote_slug_dir}")

        # Upload tarball into <eval_dir>/<slug>/submission.tar.gz (no pre-extract)
        print(f"  Uploading tarball ({tarball.stat().st_size:,} bytes)...")
        scp_to(tarball, remote_tarball)

        # Purge the stale cached compiled image on Hetzner so the CHANGED submission rebuilds
        # from the uploaded tarball. Without this the harness reuses programbench-compiled/
        # <slug>:determinex-cached (the OLD, often no-binary build) -> the autodrive re-evals a
        # stale binary, sees "no progress", and gives up (needs-manual-build). THE gap that
        # blocked auto-recovery (entr/datasurgeon/blake3 each recovered the instant the cache was
        # purged + rebuilt). run_local_eval's preflight purges locally; this is the remote-side
        # equivalent so the closed loop works off-box, where the autodrive actually runs.
        print(f"  Purging stale Hetzner cache for {slug} (rebuild from fresh submission)...")
        ssh(
            f"docker rmi -f programbench-compiled/{slug}:determinex-cached 2>/dev/null || true",
            check=False,
        )

        # Determine author filter
        if "__" in slug:
            author = slug.split("__")[0]
        else:
            author = slug.split(".")[0]

        # Run eval on Hetzner
        eval_cmd = (
            f"PYTHONUTF8=1 PROGRAMBENCH_DOCKER_CPUS=4 "
            f"nohup /root/ProgramBench/.venv/bin/programbench eval "
            f"{remote_eval_dir} --filter {author} --force "
            f"> {log_file} 2>&1 & echo $!"
        )
        result = ssh(eval_cmd)
        pid = result.stdout.strip()
        print(f"  Hetzner eval PID: {pid}")

        # Poll for completion, WITH stall-detection + auto-escape.
        # LIVENESS IS CPU-BASED, not log-size-based (the gdu/pipr lesson): a big suite runs
        # 600+ tests per branch SILENTLY for >8 min -- the stdout log doesn't grow, but the
        # eval is PROGRESSING (pytest is burning CPU). The old size-only check killed those
        # slow-but-working branches as false "hangs". A TRUE hang = pytest blocked on a
        # C-level read => its CPU time stops advancing. So we stall only when BOTH the log is
        # frozen AND the eval container's pytest CPU has not advanced.
        print("  Waiting for eval to complete...")
        STALL_SECS = 300  # 5 min of no log growth AND no MEANINGFUL CPU advance = hung
        _base = slug.split("__")[-1].split(".")[0]

        def _pytest_cpu_secs() -> int:
            # cumulative CPU seconds of pytest in the live eval container (0 if none found)
            cid = ssh(
                f"docker ps --format '{{{{.ID}}}} {{{{.Image}}}}' | grep -i '{_base}' "
                f"| head -1 | cut -d' ' -f1",
                check=False,
            ).stdout.strip()
            if not cid:
                return -1
            # sum CPU TIME of ALL processes in the eval container, not just pytest: during a
            # test the CPU is burned by the TOOL subprocess (pipr/gdu/...), so pytest's own
            # CPU reads ~flat and a pytest-only measure false-stalls a working eval. All-proc
            # CPU advances whenever any test is actually running.
            r = ssh(
                f'docker exec {cid} sh -c "ps -eo time= 2>/dev/null"', check=False
            ).stdout.strip()
            tot = 0
            for tok in r.split():
                parts = tok.replace("-", ":").split(":")
                try:
                    secs = 0
                    for x in parts:
                        secs = secs * 60 + int(x)
                    tot += secs
                except ValueError:
                    pass
            return tot

        last_size, stalled_for, last_cpu = -1, 0, -1
        for attempt in range(120):  # hard cap 60 min (30s poll)
            time.sleep(30)
            check = ssh(f"ps -p {pid} > /dev/null 2>&1; echo $?", check=False)
            if check.stdout.strip() != "0":
                print(f"  Process {pid} completed after ~{attempt * 30}s")
                break
            sz = ssh(f"wc -c < {log_file} 2>/dev/null || echo 0", check=False)
            try:
                cur = int((sz.stdout or "0").strip() or 0)
            except ValueError:
                cur = 0
            cpu = _pytest_cpu_secs()
            # progressed if: log grew, OR pytest CPU advanced, OR CPU was UNMEASURABLE this poll
            # (cpu<0: container between branches / transient SSH or docker-exec hiccup). Treating
            # an unmeasurable query as "progressing" prevents FALSE kills of a working eval (the
            # pipr 2040s false-kill) -- we only count a stall when we POSITIVELY see CPU flat.
            # require a MEANINGFUL cpu advance (>5 CPU-secs/poll = a test actually ran); idle
            # background/tmux/xdist threads creep cumulative CPU ~1 sec/poll and must NOT count as
            # progress (that idle-creep is exactly why a stuck eval rode the cap "progressing").
            progressed = (cur != last_size) or (cpu < 0) or (last_cpu < 0) or (cpu > last_cpu + 5)
            stalled_for = 0 if progressed else stalled_for + 30
            last_size, last_cpu = cur, cpu
            if stalled_for >= STALL_SECS:
                print(
                    f"  ⚠️  HANG ALERT: {slug} stalled {stalled_for}s (log frozen AND "
                    f"pytest CPU not advancing = genuinely hung) -- killing + skipping",
                    file=sys.stderr,
                )
                _alert_hang(slug, stalled_for)
                ssh(
                    f"kill -9 {pid} 2>/dev/null; pkill -9 -f '{remote_eval_dir}' 2>/dev/null; "
                    f"docker ps --format '{{{{.ID}}}} {{{{.Image}}}}' | grep -i '{slug.split('__')[-1].split('.')[0]}' "
                    f"| awk '{{print $1}}' | xargs -r docker kill 2>/dev/null",
                    check=False,
                )
                ssh(f"rm -rf {remote_dir}", check=False)
                return {"passed": 0, "total": 0, "outcome": "HANG", "pct": 0.0}
            if attempt % 4 == 0:
                log_check = ssh(f"tail -3 {log_file} 2>/dev/null || echo 'no log'", check=False)
                print(f"  [{attempt * 30}s] {log_check.stdout.strip()}")
        else:
            print(f"  ⚠️  HANG ALERT: {slug} hit 60-min cap -- killing", file=sys.stderr)
            _alert_hang(slug, 3600)
            ssh(f"kill -9 {pid} 2>/dev/null", check=False)
            return {"passed": 0, "total": 0, "outcome": "HANG", "pct": 0.0}

        # Find and download eval json
        find_result = ssh(
            f"find {remote_eval_dir} -name '*.eval.json' 2>/dev/null | head -1", check=False
        )
        remote_json = find_result.stdout.strip()

        if not remote_json:
            print("  ERROR: No eval.json found on Hetzner", file=sys.stderr)
            return {"passed": 0, "total": 0, "outcome": "NO_EVAL_JSON", "pct": 0.0}

        with tempfile.NamedTemporaryFile(suffix=".eval.json", delete=False) as _f:
            local_json = Path(_f.name)
        scp_from(remote_json, local_json)

        data = json.loads(local_json.read_text(encoding="utf-8", errors="replace"))
        local_json.unlink(missing_ok=True)

        # Cleanup remote
        ssh(f"rm -rf {remote_dir}", check=False)

        return data

    except subprocess.TimeoutExpired:
        print("  ERROR: SSH/SCP timed out", file=sys.stderr)
        return None
    except Exception as ex:
        print(f"  ERROR: Hetzner eval failed: {ex}", file=sys.stderr)
        return None


def classify_result(data: dict, slug: str = "") -> dict:  # noqa: ARG001
    tr = data.get("test_results", [])
    ctr = collections.Counter(r.get("status") for r in tr)
    total = len(tr)
    passed = ctr.get("passed", 0)
    not_run = ctr.get("not_run", 0)
    skipped = ctr.get("skipped", 0)
    failed = ctr.get("failure", 0) + ctr.get("failed", 0)
    pct = (passed / total * 100) if total else 0.0

    if passed == total and not_run == 0 and failed == 0 and skipped == 0:
        outcome = "STRICT_LOCK"
        tier = "tier_1_perfect"
    elif passed + skipped == total and not_run == 0 and failed == 0:
        outcome = "UPSTREAM_SKIPS"
        tier = "tier_2_upstream_skips"
    elif passed > 0:
        outcome = "PARTIAL"
        tier = ""
    else:
        outcome = "PARTIAL"
        tier = ""

    failed_tests = [
        r.get("test_id", "")
        for r in tr
        if r.get("status") not in ("passed", "not_run", "skipped") and r.get("status") is not None
    ]

    return dict(
        outcome=outcome,
        tier=tier,
        passed=passed,
        total=total,
        not_run=not_run,
        skipped=skipped,
        failed=failed,
        pct=pct,
        failed_tests=failed_tests[:10],
    )


def print_result_banner(slug: str, res: dict, source: str) -> None:
    icon = {"STRICT_LOCK": "🔒", "UPSTREAM_SKIPS": "⚡", "PARTIAL": "🔸", "REGRESSION": "⚠️"}.get(
        res["outcome"], "?"
    )
    print()
    print(f"  {icon} {res['outcome']}: {slug}")
    print(
        f"     passed={res['passed']} total={res['total']} "
        f"not_run={res['not_run']} skipped={res['skipped']} failed={res['failed']}"
    )
    print(f"     score={res['pct']:.2f}%  source={source}")
    if res.get("failed_tests"):
        print("     First failures:")
        for t in res["failed_tests"][:5]:
            print(f"       {t}")


def print_leaderboard_summary(index: list[dict]) -> None:
    strict = [e for e in index if e.get("status") == "strict_lock"]
    upstream = [e for e in index if e.get("status") == "upstream_skips"]
    pending = [e for e in index if e.get("status") == "pending_unlock"]
    total = len(index)

    print()
    print("┌─" + "─" * 65 + "─┐")
    print(f"│ {'DETERMINEX PROGRAMBENCH — CURRENT STANDINGS':<65} │")
    print("├─" + "─" * 65 + "─┤")
    print(f"│ {'Rank':<5} {'Tool':<35} {'Score':>7} {'Tier':<6} {'Status':<12} │")
    print("├─" + "─" * 65 + "─┤")

    combined = [(e, 0) for e in strict] + [(e, 1) for e in upstream]
    for i, (e, _) in enumerate(combined[:20], 1):
        slug = e["slug"][:35]
        pct = e["official_score_pct"]
        tier = e.get("tier", "")[:6]
        status = "🔒 LOCK" if e["status"] == "strict_lock" else "⚡ NEAR"
        print(f"│ {i:<5} {slug:<35} {pct:>6.1f}% {tier:<6} {status:<12} │")

    if len(combined) < 20:
        # Fill with top pending
        for e in pending[: 20 - len(combined)]:
            i = len(combined) + pending.index(e) + 1
            slug = e["slug"][:35]
            pct = e["official_score_pct"]
            print(f"│ {i:<5} {slug:<35} {pct:>6.1f}% {'':6} {'⏳ PEND':<12} │")

    print("├─" + "─" * 65 + "─┤")
    print(
        f"│ Strict locks: {len(strict)}/{total} ({len(strict) / total * 100:.1f}%) "
        f"| Pending: {len(pending)} tools{'':<15} │"
    )
    print("└─" + "─" * 65 + "─┘")


def run_eval(
    slug: str, force_local: bool = False, force_hetzner: bool = False, dry_run: bool = False
) -> dict | None:
    print(f"\n{'=' * 65}")
    print(f"EVAL: {slug}")
    print(f"{'=' * 65}")

    tarball = find_uncapped_tarball(slug)
    if tarball is None:
        print(f"  ERROR: No tarball found for '{slug}'", file=sys.stderr)
        return None

    print(f"  Tarball: {tarball}")

    # Pre-eval verification
    ok, warnings = verify_submission(tarball)
    if not ok:
        for w in warnings:
            print(f"  {w}", file=sys.stderr)
        return None
    for w in warnings:
        print(f"  {w}")

    # Estimate test count for routing
    total_estimate = count_tests_in_tarball(tarball)
    print(f"  Estimated tests: {total_estimate if total_estimate else 'unknown'}")

    # Route
    source = route_eval(total_estimate, force_local, force_hetzner)
    print(f"  Routing to: {source.upper()}")

    if dry_run:
        print(f"  [DRY RUN] Would run on {source}")
        return None

    # Execute eval
    t_start = time.time()
    if source == "hetzner":
        data = run_hetzner_eval(slug, tarball)
    else:
        data = run_local_eval(slug, tarball)

    elapsed = time.time() - t_start
    print(f"  Eval time: {elapsed:.0f}s")

    if data is None:
        return None

    # Classify result
    res = classify_result(data, slug)
    print_result_banner(slug, res, source)

    # Save eval result to tool dir
    tool_dir = find_tool_dir(slug)
    if tool_dir:
        result_path = tool_dir / "latest_eval_result.json"
        result_path.write_text(
            json.dumps(
                {
                    "slug": slug,
                    "eval_source": source,
                    "eval_timestamp": datetime.now(UTC).isoformat(),
                    **res,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # Update unlock_ticket
        ticket_path = tool_dir / "unlock_ticket.json"
        if ticket_path.exists():
            try:
                ticket = json.loads(ticket_path.read_text())
                ticket["last_attempt"] = datetime.now(UTC).isoformat()
                ticket["attempts"] = ticket.get("attempts", 0) + 1
                if res["outcome"] in ("STRICT_LOCK", "UPSTREAM_SKIPS"):
                    ticket["status"] = "passed"
                else:
                    ticket["status"] = "failed"
                ticket_path.write_text(json.dumps(ticket, indent=2), encoding="utf-8")
            except Exception:
                pass

    # Log regression
    index = load_index()
    for e in index:
        if e["slug"] == slug:
            prev_best = e.get("official_passed", 0)
            if res["passed"] < prev_best:
                res["outcome"] = "REGRESSION"
                reg = {
                    "slug": slug,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "prev_passed": prev_best,
                    "new_passed": res["passed"],
                    "total": res["total"],
                }
                LOG_DIR.mkdir(exist_ok=True)
                with open(REGRESSIONS_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps(reg) + "\n")
                print(f"\n  ⚠️  REGRESSION: {slug} dropped {prev_best}→{res['passed']}")
                print("     Previous best preserved. Check logs/regressions.jsonl")
            break

    # Update index entry
    update_index_entry(
        slug,
        {
            "official_score_pct": round(res["pct"], 4),
            "official_passed": res["passed"],
            "official_total": res["total"],
            "official_not_run": res["not_run"],
            "official_skipped": res["skipped"],
            "official_failed": res["failed"],
            "last_eval_source": source,
            "last_eval_time": datetime.now(UTC).isoformat(),
        },
    )

    # Promote if lock
    if res["outcome"] in ("STRICT_LOCK", "UPSTREAM_SKIPS") and res["outcome"] != "REGRESSION":
        from pb_promote import promote_tool

        promote_tool(slug, data, source=source, tarball=tarball)

    return res


def get_batch_tools(batch_path_str: str) -> list[str]:
    """Get tools from a batch directory, sorted by not_run ASC, score DESC."""
    batch_path = (
        PB_DIR / batch_path_str if not Path(batch_path_str).is_absolute() else Path(batch_path_str)
    )
    if not batch_path.exists():
        # Try as relative to pending
        batch_path = PENDING_BASE / batch_path_str.replace("pending_unlock/", "")

    tools_with_info = []
    for d in batch_path.iterdir():
        if not d.is_dir():
            continue
        slug = d.name
        ticket_path = d / "unlock_ticket.json"
        nr = 9999
        pct = 0.0
        if ticket_path.exists():
            try:
                t = json.loads(ticket_path.read_text())
                nr = t.get("current_not_run", 9999)
                total = t.get("current_total", 1)
                passed = t.get("current_passed", 0)
                pct = passed / total * 100 if total else 0
            except Exception:
                pass
        tools_with_info.append((nr, -pct, slug))

    tools_with_info.sort()
    return [slug for _, _, slug in tools_with_info]


def main():
    parser = argparse.ArgumentParser(description="Run PB evals locally or on Hetzner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tool", help="Eval a single tool")
    group.add_argument("--batch", help="Eval all tools in a pending_unlock subdirectory")

    parser.add_argument("--force-local", action="store_true")
    parser.add_argument("--force-hetzner", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true", help="Route and verify but don't actually run eval"
    )
    args = parser.parse_args()

    if args.tool:
        result = run_eval(
            args.tool,
            force_local=args.force_local,
            force_hetzner=args.force_hetzner,
            dry_run=args.dry_run,
        )
        if result is None:
            return 1
    else:
        tools = get_batch_tools(args.batch)
        if not tools:
            print(f"No tools found in batch: {args.batch}")
            return 1

        print(f"Batch: {len(tools)} tools in {args.batch}")
        print(f"Order: {', '.join(tools[:5])}{'...' if len(tools) > 5 else ''}")

        results = {"locks": [], "failed": [], "partial": [], "errors": []}
        for slug in tools:
            result = run_eval(
                slug,
                force_local=args.force_local,
                force_hetzner=args.force_hetzner,
                dry_run=args.dry_run,
            )
            if result is None:
                results["errors"].append(slug)
            elif result["outcome"] in ("STRICT_LOCK", "UPSTREAM_SKIPS"):
                results["locks"].append(slug)
            elif result["outcome"] == "PARTIAL":
                results["partial"].append(slug)
            else:
                results["failed"].append(slug)

        print(f"\n{'=' * 65}")
        print(f"BATCH COMPLETE: {args.batch}")
        print(f"  New locks:   {len(results['locks'])}: {', '.join(results['locks'])}")
        print(f"  Partial:     {len(results['partial'])}: {', '.join(results['partial'])}")
        print(f"  Errors:      {len(results['errors'])}: {', '.join(results['errors'])}")

    index = load_index()
    print_leaderboard_summary(index)
    return 0


if __name__ == "__main__":
    sys.exit(main())

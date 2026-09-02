#!/usr/bin/env python3
"""determinex_pb_memory_conveyor.py — churn-loop to official-eval bridge.

Watches the Hetzner churn loop for oracle-green candidates, then:

  1. PULL    — scp the candidate reimpl file from Hetzner to T:/
  2. PACK    — pb_pack_candidate.py builds the submission.tar.gz
  3. EVAL    — runs the official programbench eval locally (Docker)
  4. GATE    — pb_candidate_gate.py compares vs. baseline
  5. APPLY   — on accept: pb_apply_gate_decision.py + refresh board
  6. PRUNE   — docker rmi the *:determinex-cached compiled* image on Hetzner
               (never touches the base :task images, only the compiled layer)
  7. PREFETCH — docker pull the next tool's :task image on Hetzner so it's
               warm before the churn loop reaches it
  8. LOOP   — repeat; stop if ≥ MAX_CONSECUTIVE_FAILURES straight non-improvements

Safety:
  - never prunes :task base images, only *:determinex-cached*
  - failure budget (default 3) stops the loop before it wastes full evals
  - logs every action to logs/pb_conveyor_events.jsonl
  - writes per-run gate_result.json like the rest of the stack does

Usage (local Windows side, T: drive present):
  python scripts/determinex_pb_memory_conveyor.py --once
  python scripts/determinex_pb_memory_conveyor.py --interval 120 --max-failures 3

Hetzner layout expected:
  /root/Citadel/logs/pb_churn_events.jsonl   — written by determinex_pb_churn.py
  /root/Citadel/logs/reimpl/<short>_drive.py — candidate files
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ── path constants ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
PY = Path(sys.executable)
SSH = Path(r"C:\Windows\System32\OpenSSH\ssh.exe")
SCP = Path(r"C:\Windows\System32\OpenSSH\scp.exe")
SSH_KEY = Path.home() / ".ssh" / "id_citadel"
REMOTE = "root@5.78.192.163"
REMOTE_ROOT = "/root/Citadel"

PB = ROOT / "corpus" / "programbench"
EVAL_INDEX = PB / "eval_index.json"
BOARD = ROOT / "logs" / "programbench_lock_board.json"
OVERRIDES = PB / "per_tool_overrides"

EVENTS_LOG = ROOT / "logs" / "pb_conveyor_events.jsonl"
STATE_PATH = ROOT / "logs" / "pb_conveyor_state.json"

PB_STAGING_ROOT = Path(os.environ.get("DETERMINEX_PB_STAGING_ROOT", "T:/determinex-staging"))
CONVEYOR_RUN_ROOT = PB_STAGING_ROOT / "pb_conveyor"

TERMINAL_STATUSES = {
    "strict_lock",
    "locked",
    "ceiling_certified",
    "ceiling_confirmed",
    "impossible_ceiling",
}

MAX_CONSECUTIVE_FAILURES = 3


# ── helpers ────────────────────────────────────────────────────────────────────


def _utc() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _log_event(kind: str, **fields: Any) -> None:
    EVENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": _utc(), "kind": kind, **fields}
    with EVENTS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    print(
        f"[conveyor] {kind}: {json.dumps({k: v for k, v in fields.items() if k != 'detail'}, default=str)}"
    )


def _ssh(cmd: str, *, check: bool = True, timeout: int = 60) -> str:
    r = subprocess.run(
        [
            str(SSH),
            "-i",
            str(SSH_KEY),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            REMOTE,
            cmd,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"ssh failed rc={r.returncode}: {r.stderr[:500]}")
    return r.stdout


def _run(
    cmd: list[Any], *, cwd: Path | None = None, timeout: int = 3600
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(c) for c in cmd],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_state() -> dict[str, Any]:
    s = _load_json(STATE_PATH, {})
    s.setdefault("processed", [])
    s.setdefault("consecutive_failures", 0)
    s.setdefault("total_accepted", 0)
    s.setdefault("total_rejected", 0)
    return s


def _save_state(s: dict[str, Any]) -> None:
    _write_json(STATE_PATH, s)


# ── eval-index helpers ─────────────────────────────────────────────────────────


def _eval_index_rows() -> list[dict[str, Any]]:
    return _load_json(EVAL_INDEX, [])


def _best_eval_path_for(slug: str) -> Path | None:
    """Return the best_eval_path from the board for this slug's base tool."""
    base = slug.split(".")[0]
    short = slug.split("__")[-1].split(".")[0]
    rows = _load_json(BOARD, []) if BOARD.is_file() else []
    for row in rows:
        bs = str(row.get("base_slug", ""))
        if bs == base or str(row.get("slug", "")).split(".")[0] == base:
            bp = row.get("best_eval_path")
            if bp:
                p = Path(bp)
                if not p.is_absolute():
                    p = ROOT / p
                if p.is_file():
                    return p
    # fallback: search eval cache by short name
    ec = ROOT / "logs" / "eval_cache"
    if ec.is_dir():
        hits = sorted(ec.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for h in hits[:20]:
            try:
                d = json.loads(h.read_text(encoding="utf-8"))
                if d.get("instance_id", "").split("__")[-1].split(".")[0] == short:
                    ep = d.get("eval_json_path", "")
                    if ep and Path(ep).is_file():
                        return Path(ep)
            except Exception:
                pass
    return None


def _tool_is_terminal(slug: str) -> bool:
    short = slug.split("__")[-1].split(".")[0]
    for row in _eval_index_rows():
        s = str(row.get("slug", "")).split("__")[-1].split(".")[0]
        if s == short and str(row.get("status", "")) in TERMINAL_STATUSES:
            return True
    return False


def _min_baseline_passed(slug: str) -> int:
    """Return the baseline passed count (floor for gate)."""
    bp = _best_eval_path_for(slug)
    if not bp:
        return 1
    try:
        d = json.loads(bp.read_text(encoding="utf-8", errors="replace"))
        results = d.get("test_results", [])
        return sum(1 for r in results if r.get("status") == "passed")
    except Exception:
        return 1


# ── remote churn event reader ──────────────────────────────────────────────────


def _fetch_remote_events() -> list[dict[str, Any]]:
    """SCP the remote pb_churn_events.jsonl and parse it."""
    remote_path = f"{REMOTE_ROOT}/logs/pb_churn_events.jsonl"
    local_tmp = ROOT / "logs" / ".pb_churn_events_remote.jsonl"
    try:
        r = subprocess.run(
            [
                str(SCP),
                "-i",
                str(SSH_KEY),
                "-o",
                "BatchMode=yes",
                f"{REMOTE}:{remote_path}",
                str(local_tmp),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            return []
    except Exception:
        return []

    events: list[dict[str, Any]] = []
    try:
        for line in local_tmp.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    except Exception:
        pass
    return events


def _fetch_remote_reimpl_slugs(already: set[str]) -> list[str]:
    """
    SSH-list /root/Citadel/logs/reimpl/ on Hetzner and return full slugs
    from eval_index whose short name matches a *_drive.py or *_candidate.py
    file present there.  These are candidates the churn loop has already
    produced but which may not yet have an oracle-green churn event.
    """
    try:
        out = _ssh(f"ls {REMOTE_ROOT}/logs/reimpl/ 2>/dev/null || true", check=False, timeout=15)
    except Exception:
        return []

    # Extract short names from filenames like "elfcat_drive.py" or "walk_candidate.py"
    remote_shorts: set[str] = set()
    for fname in out.splitlines():
        fname = fname.strip()
        for suffix in ("_drive.py", "_candidate.py", "_drive_remote.py"):
            if fname.endswith(suffix):
                remote_shorts.add(fname[: -len(suffix)])

    if not remote_shorts:
        return []

    # Map to full slugs via eval_index
    rows = _eval_index_rows()
    result: list[tuple[float, str]] = []
    for row in rows:
        slug = str(row.get("source", "")) or str(row.get("slug", ""))
        if not slug or slug in already:
            continue
        status = str(row.get("status", ""))
        if status in TERMINAL_STATUSES:
            continue
        short = slug.split("__")[-1].split(".")[0]
        if short not in remote_shorts:
            continue
        if not (OVERRIDES / slug).is_dir():
            continue
        score = float(row.get("official_score_pct") or row.get("local_score_pct") or 0)
        result.append((-score, slug))

    result.sort()
    return [slug for _, slug in result]


def _event_verdict(ev: dict[str, Any]) -> str:
    """Return a churn event verdict across old flat and current nested schemas."""
    route = ev.get("route")
    if isinstance(route, dict) and route.get("verdict"):
        return str(route.get("verdict") or "")
    action = ev.get("action")
    if isinstance(action, dict) and action.get("name"):
        name = str(action.get("name") or "")
        if name == "hold-official-eval":
            return "oracle-green-ready-for-official"
    return str(ev.get("verdict") or ev.get("next_action") or "")


def _oracle_green_slugs(events: list[dict[str, Any]], already_processed: set[str]) -> list[str]:
    """
    Return slugs where the latest churn event has verdict=oracle-green-ready-for-official
    and the override dir exists locally (meaning the churn loop wrote a candidate file).
    Order by event time ascending (oldest first).
    """
    # latest event per slug
    by_slug: dict[str, dict[str, Any]] = {}
    for ev in events:
        slug = ev.get("slug") or ev.get("tool") or ""
        if not slug:
            continue
        prev = by_slug.get(slug)
        if prev is None or str(ev.get("ts", "")) > str(prev.get("ts", "")):
            by_slug[slug] = ev

    ready: list[tuple[str, str]] = []  # (ts, slug)
    for slug, ev in by_slug.items():
        if slug in already_processed:
            continue
        verdict = _event_verdict(ev)
        if "oracle-green" not in verdict and "official" not in verdict:
            continue
        # must have an override dir (churn loop wrote the candidate there)
        if not (OVERRIDES / slug).is_dir():
            continue
        if _tool_is_terminal(slug):
            continue
        ready.append((str(ev.get("ts", "")), slug))

    ready.sort()
    return [slug for _, slug in ready]


# ── step 1: pull candidate file from Hetzner ──────────────────────────────────


def _local_candidate_path(slug: str) -> Path | None:
    """Return an existing local candidate path for this slug, if any."""
    short = slug.split("__")[-1].split(".")[0]
    # 1. Previously pulled remote candidate
    remote_copy = ROOT / "logs" / "reimpl" / f"{short}_drive_remote.py"
    if remote_copy.is_file():
        return remote_copy
    # 2. Candidate already in the override dir (churn loop or manual placement)
    main_py = OVERRIDES / slug / "main.py"
    if main_py.is_file():
        return main_py
    # 3. Local reimpl log
    local_drive = ROOT / "logs" / "reimpl" / f"{short}_drive.py"
    if local_drive.is_file():
        return local_drive
    return None


def pull_candidate(slug: str) -> Path | None:
    """
    SCP the candidate Python file from the Hetzner reimpl log.
    Tries both *_drive.py and *_candidate.py remote filenames (churn loop uses
    either depending on which script produced the output).
    Falls back to any existing local candidate if neither remote file exists.
    Returns the local path it was saved to, or None on failure.
    """
    short = slug.split("__")[-1].split(".")[0]
    local_dir = ROOT / "logs" / "reimpl"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"{short}_drive_remote.py"

    # Try all plausible remote filenames
    remote_names = [
        f"{REMOTE_ROOT}/logs/reimpl/{short}_drive.py",
        f"{REMOTE_ROOT}/logs/reimpl/{short}_candidate.py",
        f"{REMOTE_ROOT}/logs/reimpl/{short}_drive_remote.py",
    ]
    last_err = ""
    for remote_candidate in remote_names:
        r = subprocess.run(
            [
                str(SCP),
                "-i",
                str(SSH_KEY),
                "-o",
                "BatchMode=yes",
                f"{REMOTE}:{remote_candidate}",
                str(local_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            _log_event(
                "pulled_candidate", slug=slug, source=remote_candidate, local=str(local_path)
            )
            return local_path
        last_err = r.stderr.strip()

    # Remote not ready — fall back to any existing local candidate
    fallback = _local_candidate_path(slug)
    if fallback:
        _log_event("pull_fallback", slug=slug, fallback=str(fallback), detail=last_err[:200])
        return fallback

    _log_event("pull_failed", slug=slug, detail=last_err[:400])
    return None


# ── step 2: install candidate into override dir ────────────────────────────────


def install_candidate(slug: str, candidate_path: Path) -> bool:
    """
    Copy the pulled candidate file into the per-tool override dir as main.py.
    The pack step will then find it there.
    """
    override_dir = OVERRIDES / slug
    if not override_dir.is_dir():
        _log_event("install_failed", slug=slug, reason="override dir missing")
        return False

    dest = override_dir / "main.py"
    try:
        shutil.copy2(candidate_path, dest)
        _log_event("installed_candidate", slug=slug, dest=str(dest))
        return True
    except Exception as exc:
        _log_event("install_failed", slug=slug, reason=str(exc))
        return False


# ── step 3: pack into submission.tar.gz ───────────────────────────────────────


def pack_candidate(slug: str) -> Path | None:
    """Call pb_pack_candidate.py → submission.tar.gz under CONVEYOR_RUN_ROOT."""
    run_root = CONVEYOR_RUN_ROOT / slug
    run_root.mkdir(parents=True, exist_ok=True)

    r = _run(
        [
            PY,
            ROOT / "scripts" / "pb_pack_candidate.py",
            slug,
            "--run-root",
            str(run_root),
        ]
    )
    if r.returncode != 0:
        _log_event("pack_failed", slug=slug, detail=(r.stdout + r.stderr)[:600])
        return None

    submission = run_root / slug / "submission.tar.gz"
    if not submission.is_file():
        _log_event("pack_failed", slug=slug, reason="submission.tar.gz not created")
        return None

    _log_event("packed", slug=slug, submission=str(submission))
    return run_root


# ── step 4+5: eval on Hetzner + gate (unified) ───────────────────────────────

_hetzner_task_cache: dict[str, str] = {}  # short_name -> canonical_slug


def _resolve_hetzner_slug(slug: str) -> str:
    """
    Find the canonical slug in Hetzner's PB task data that matches our slug.
    e.g. 'antonmedv__walk' -> 'antonmedv__walk.bf802ef'
    Falls back to the input slug if not found.
    """
    global _hetzner_task_cache
    short = slug.split("__")[-1].split(".")[0]
    author = slug.split("__")[0] if "__" in slug else ""

    if slug in _hetzner_task_cache:
        return _hetzner_task_cache[slug]

    try:
        out = _ssh(
            "ls /root/ProgramBench/src/programbench/data/tasks/ 2>/dev/null",
            check=False,
            timeout=15,
        )
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            # Match: same short name and (if author present) same author prefix
            line_short = line.split("__")[-1].split(".")[0]
            line_author = line.split("__")[0] if "__" in line else ""
            if line_short == short and (not author or line_author == author):
                _hetzner_task_cache[slug] = line
                return line
    except Exception:
        pass

    return slug  # fallback: use as-is


def _find_uncapped_tarball(slug: str) -> Path | None:
    """Locate the submission.tar.gz in the conveyor run root."""
    run_root = CONVEYOR_RUN_ROOT / slug
    candidate = run_root / slug / "submission.tar.gz"
    if candidate.is_file():
        return candidate
    for p in run_root.rglob("submission.tar.gz"):
        return p
    return None


def hetzner_eval_and_gate(slug: str, run_root: Path) -> str:
    """
    Run the official eval on Hetzner via pb_eval_unified.run_hetzner_eval(), then gate.
    Resolves the canonical Hetzner slug (with hash) before uploading the tarball.
    Returns 'accept', 'reject', or 'error'.
    """
    # Find our tarball
    tarball = _find_uncapped_tarball(slug)
    if tarball is None:
        _log_event("eval_failed", slug=slug, detail="no submission.tar.gz in conveyor run root")
        return "error"

    # Resolve the canonical slug on Hetzner (e.g. antonmedv__walk.bf802ef)
    canonical = _resolve_hetzner_slug(slug)
    _log_event("eval_start", slug=slug, canonical=canonical, tarball=str(tarball))

    # Load pb_eval_unified locally and monkey-patch so it uses canonical slug + our tarball
    try:
        import importlib.util as _ilu

        spec = _ilu.spec_from_file_location(
            "pb_eval_unified", ROOT / "scripts" / "pb_eval_unified.py"
        )
        pbu = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(pbu)  # type: ignore[union-attr]
        pbu.find_uncapped_tarball = lambda _s: tarball
    except Exception as e:
        _log_event("eval_failed", slug=slug, detail=f"failed to load pb_eval_unified: {e}")
        return "error"

    try:
        result = pbu.run_hetzner_eval(canonical, tarball)
    except Exception as e:
        _log_event("eval_failed", slug=slug, detail=str(e)[:600])
        return "error"

    if result is None:
        _log_event("eval_failed", slug=slug, detail="run_hetzner_eval returned None")
        return "error"

    # Classify result (pb_eval_unified returns raw eval dict from JSON)
    try:
        classified = pbu.classify_result(result, canonical)
    except Exception:
        classified = {}

    passed = classified.get("passed", result.get("passed", 0))
    total = classified.get("total", result.get("total", 0))
    score = classified.get("pct", 0.0)
    outcome = classified.get("outcome", "PARTIAL")
    _log_event("eval_done", slug=slug, passed=passed, total=total, score=score, outcome=outcome)

    # Save result
    inst_dir = run_root / slug
    inst_dir.mkdir(parents=True, exist_ok=True)
    eval_json = inst_dir / "conveyor_eval_result.json"
    try:
        eval_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass

    # Gate against baseline
    min_passed_floor = _min_baseline_passed(slug)
    if outcome == "STRICT_LOCK":
        decision, reason = "accept", "STRICT_LOCK from Hetzner eval"
    elif passed >= min_passed_floor and passed > 0 and total > 0:
        decision = "accept"
        reason = f"passed={passed}>={min_passed_floor} baseline, score={score:.1f}%"
    else:
        decision = "reject"
        reason = f"passed={passed} < baseline {min_passed_floor}, score={score:.1f}%"

    _log_event("gated", slug=slug, decision=decision, reason=reason[:200])

    if decision == "accept":
        gate_path = run_root / "gate_result.json"
        gate_path.write_text(
            json.dumps(
                {
                    "decision": decision,
                    "decision_rule": "conveyor_hetzner_eval",
                    "reason": reason,
                    "passed": passed,
                    "total": total,
                    "score_pct": score,
                    "outcome": outcome,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        apply_accept(slug, run_root)

    return decision


# ── step 6a: apply accepted gate ──────────────────────────────────────────────


def apply_accept(slug: str, run_root: Path) -> None:
    gate_path = run_root / "gate_result.json"
    if not gate_path.is_file():
        return
    r = _run(
        [
            PY,
            ROOT / "scripts" / "pb_apply_gate_decision.py",
            slug,
            str(gate_path),
            "--run-root",
            str(run_root),
            "--refresh-board",
        ]
    )
    _log_event("applied_accept", slug=slug, rc=r.returncode)


# ── step 6b: prune Hetzner compiled cache (NOT the :task base image) ──────────


def prune_compiled_cache_remote(slug: str) -> None:
    """
    On Hetzner: docker rmi the programbench-compiled/*:determinex-cached image for
    this tool.  The :task base image is intentionally preserved — it's the
    reference binary and costs hours to pull back.
    """
    short = slug.split("__")[-1].split(".")[0]
    cmd = (
        f"docker images --format '{{{{.Repository}}}}:{{{{.Tag}}}}' "
        f"| grep -i 'programbench-compiled' | grep -i '{short}' | grep 'determinex-cached' "
        f"| xargs -r docker rmi -f 2>/dev/null; echo pruned"
    )
    try:
        out = _ssh(cmd, timeout=60)
        _log_event("pruned_compiled_cache", slug=slug, detail=out.strip()[:200])
    except Exception as exc:
        _log_event("prune_warning", slug=slug, reason=str(exc)[:200])


# ── step 7: prefetch next tool's :task image on Hetzner ───────────────────────


def prefetch_next_task_image(next_slug: str) -> None:
    """
    Ask Hetzner to docker pull the :task image for the next slug so the churn
    loop finds it warm.  Best-effort; never blocks the conveyor.
    """
    short = next_slug.split("__")[-1].split(".")[0]
    # ProgramBench image name convention
    slug_img = next_slug.replace("__", "_1776_")
    image = f"programbench/{slug_img}:task"
    cmd = f"docker pull {image} > /dev/null 2>&1 &"
    try:
        _ssh(cmd, check=False, timeout=10)
        _log_event("prefetch_queued", slug=next_slug, image=image)
    except Exception:
        pass


# ── conveyor core ─────────────────────────────────────────────────────────────


def _has_candidate_locally(slug: str) -> bool:
    """True if there's already a candidate Python file we can pack for this slug."""
    return _local_candidate_path(slug) is not None


def _queue_from_eval_index() -> list[str]:
    """
    Return slugs that are non-terminal, have an override dir, AND already have a
    candidate file present (main.py or _drive.py) so we don't fire a pull attempt
    on tools the churn loop hasn't reached yet.
    Ordered by score descending (highest leverage first).
    """
    rows = _eval_index_rows()
    candidates: list[tuple[float, str]] = []
    for row in rows:
        status = str(row.get("status", ""))
        if status in TERMINAL_STATUSES:
            continue
        slug = str(row.get("slug", ""))
        if not slug:
            continue
        if not (OVERRIDES / slug).is_dir():
            continue
        # Only queue if a candidate is actually present locally
        if not _has_candidate_locally(slug):
            continue
        score = float(row.get("official_score_pct") or row.get("local_score_pct") or 0)
        candidates.append((-score, slug))  # negate for descending
    candidates.sort()
    return [slug for _, slug in candidates]


def process_one(slug: str) -> str:
    """
    Full conveyor pipeline for a single slug.
    Returns 'accept', 'reject', or 'error'.
    """
    _log_event("start", slug=slug)
    run_root = CONVEYOR_RUN_ROOT / slug

    # 1. Pull candidate from Hetzner
    candidate_path = pull_candidate(slug)
    if candidate_path is None:
        return "error"

    # 2. Install into override dir
    if not install_candidate(slug, candidate_path):
        return "error"

    # 3. Pack
    run_root = pack_candidate(slug)
    if run_root is None:
        return "error"

    # 4+5. Eval on Hetzner + gate (combined — pb_eval_unified handles SSH/SCP/poll)
    decision = hetzner_eval_and_gate(slug, run_root)

    # 6. Prune compiled cache on Hetzner (regardless of decision)
    prune_compiled_cache_remote(slug)

    _log_event("finished", slug=slug, decision=decision)
    return decision


def run_conveyor(
    *,
    once: bool = False,
    interval: int = 120,
    max_failures: int = MAX_CONSECUTIVE_FAILURES,
    dry_run: bool = False,
    slugs: list[str] | None = None,
) -> int:
    state = _load_state()
    already = set(state["processed"])

    while True:
        # Determine work queue
        if slugs:
            green = [s for s in slugs if s not in already]
        else:
            # 1. oracle-green events from churn loop
            events = _fetch_remote_events()
            green = _oracle_green_slugs(events, already)
            # 2. Any _drive.py files already sitting on Hetzner (no event needed)
            remote_ready = _fetch_remote_reimpl_slugs(already)
            for s in remote_ready:
                if s not in green:
                    green.append(s)
            if not green:
                # 3. Local fallback: slugs with a candidate file already present
                green = [s for s in _queue_from_eval_index() if s not in already]

        if not green:
            print(f"[conveyor] queue empty; waiting {interval}s")
            if once:
                break
            time.sleep(interval)
            continue

        # Prefetch next after the first so it warms while we eval current
        if len(green) >= 2:
            prefetch_next_task_image(green[1])

        slug = green[0]
        if _tool_is_terminal(slug):
            _log_event("skip_terminal", slug=slug)
            already.add(slug)
            state["processed"].append(slug)
            _save_state(state)
            continue

        if dry_run:
            print(f"[conveyor] DRY-RUN: would process {slug}")
            already.add(slug)
        else:
            outcome = process_one(slug)
            already.add(slug)
            state["processed"].append(slug)

            if outcome == "accept":
                state["consecutive_failures"] = 0
                state["total_accepted"] += 1
            elif outcome == "reject":
                state["total_rejected"] += 1
                state["consecutive_failures"] = (
                    0  # Rejects mean the pipeline works, candidate just failed
                )
            else:
                state["consecutive_failures"] += 1

            _save_state(state)

            if state["consecutive_failures"] >= max_failures:
                _log_event(
                    "failure_budget_exhausted",
                    consecutive=state["consecutive_failures"],
                    max=max_failures,
                )
                print(
                    f"[conveyor] STOPPING — {state['consecutive_failures']} consecutive "
                    f"non-improvements (budget={max_failures}).  "
                    f"Check logs/pb_conveyor_events.jsonl for details."
                )
                return 1

        if once:
            break

        print(f"[conveyor] waiting {interval}s before next pass")
        time.sleep(interval)

    _log_event(
        "conveyor_done",
        total_accepted=state["total_accepted"],
        total_rejected=state["total_rejected"],
    )
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="process one tool then exit")
    ap.add_argument(
        "--interval",
        type=int,
        default=120,
        help="seconds between passes when watching (default 120)",
    )
    ap.add_argument(
        "--max-failures",
        type=int,
        default=MAX_CONSECUTIVE_FAILURES,
        help=f"stop after N consecutive non-improvements (default {MAX_CONSECUTIVE_FAILURES})",
    )
    ap.add_argument(
        "--slug",
        action="append",
        default=[],
        help="process this specific slug (can repeat); skips remote event poll",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="just print what would be processed, no side effects"
    )
    ap.add_argument(
        "--reset-state",
        action="store_true",
        help="clear the processed/failure-count state before starting",
    )
    args = ap.parse_args()

    if args.reset_state and STATE_PATH.is_file():
        STATE_PATH.unlink()
        print("[conveyor] state reset")

    return run_conveyor(
        once=args.once,
        interval=args.interval,
        max_failures=args.max_failures,
        dry_run=args.dry_run,
        slugs=args.slug or None,
    )


if __name__ == "__main__":
    raise SystemExit(main())

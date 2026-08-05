#!/usr/bin/env python3
"""ProgramBench packet preflight — REQUIRED before any per-tool override edit.

The preflight is mechanical. It captures git/board/source/eval state and
classifies the task into one of:

    RECOVERY  active override hash != best-run source hash
              (recover source first, reproduce best score, THEN patch)
    PATCH     override == best source AND tool is < 100% on official eval
              (apply one micro-primitive, gate against best eval JSON)
    ARCHIVE   official best is 100/100 but `corpus/programbench/locked/<tool>` is missing
              (run `pb_lock_archiver.py`)
    BLOCKED   missing artifact: best-run source, best eval JSON, or docker image
              (do not edit; report missing artifact path)

Outputs a single JSON blob to stdout. Exit code:
    0  classification was emitted (any of RECOVERY/PATCH/ARCHIVE/BLOCKED — the
       classification itself is in the JSON; exit 0 doesn't mean "safe to edit")
    1  malformed input or unrecoverable error (e.g. board JSON corrupt)

Usage:
    python scripts/pb_packet_preflight.py <slug>
    python scripts/pb_packet_preflight.py <slug> --json-only
    python scripts/pb_packet_preflight.py <slug> --strict   # exit 1 if RECOVERY/BLOCKED

The strict mode is meant for `pb_make_packet.py` / `pb_factory_worker_loop.py`
to refuse to emit a PATCH packet when the preflight says RECOVERY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_ROOT = ROOT / "corpus" / "programbench" / "per_tool_overrides"
LOCKED_ROOT = ROOT / "corpus" / "programbench" / "locked"
BOARD_JSON = ROOT / "logs" / "programbench_lock_board.json"
ACCEPTED_RUNS = ROOT / "logs" / "programbench_factory" / "accepted_runs.jsonl"


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _run(*cmd: str, cwd: Path | None = None) -> str:
    try:
        out = subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return out.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _git_state() -> dict:
    head = _run("git", "rev-parse", "HEAD", cwd=ROOT)
    branch = _run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=ROOT)
    # Best-effort remote head (no fetch — preflight is read-only by design).
    remote_head = _run("git", "rev-parse", f"origin/{branch}", cwd=ROOT)
    behind = ""
    ahead = ""
    if head and remote_head:
        cnt = _run(
            "git",
            "rev-list",
            "--left-right",
            "--count",
            f"{remote_head}...{head}",
            cwd=ROOT,
        )
        parts = cnt.split()
        if len(parts) == 2:
            behind, ahead = parts[0], parts[1]
    dirty_raw = _run("git", "status", "--porcelain", cwd=ROOT)
    dirty = [ln.strip() for ln in dirty_raw.splitlines() if ln.strip()]
    return {
        "branch": branch,
        "head": head,
        "remote_head": remote_head,
        "commits_behind_remote": int(behind) if behind.isdigit() else None,
        "commits_ahead_remote": int(ahead) if ahead.isdigit() else None,
        "dirty_files": dirty,
    }


def _board_row(slug: str) -> dict | None:
    if not BOARD_JSON.is_file():
        return None
    try:
        data = json.loads(BOARD_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, list):
        return None
    base = slug.rsplit(".", 1)[0] if "." in slug else slug
    base_slug = base if "__" in base else slug.split(".")[0]
    for row in data:
        bs = row.get("base_slug", "")
        if bs == base_slug or bs.endswith(f"__{slug.split('__', 1)[-1].split('.')[0]}"):
            return row
    # Fallback: prefix match on slug.
    short = slug.split(".")[0]
    for row in data:
        if row.get("base_slug", "") == short:
            return row
    return None


def _board_freshness(row: dict, accepted_runs: Path) -> dict:
    """Compare board mtime vs accepted_runs.jsonl last line — if accepted_runs
    has a row newer than the board's `eval_mtime`, the board is stale."""
    info = {"accepted_runs_exists": accepted_runs.is_file(), "stale": None}
    if not accepted_runs.is_file():
        return info
    last_line = ""
    try:
        with accepted_runs.open("r", encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    last_line = ln.strip()
    except OSError:
        return info
    if not last_line:
        return info
    try:
        last = json.loads(last_line)
    except json.JSONDecodeError:
        return info
    info["last_accepted_slug"] = last.get("slug")
    info["last_accepted_passed"] = last.get("passed")
    return info


def _git_head_file_hash(rel_path: str) -> str | None:
    """SHA-256[:16] of the file content as committed at HEAD."""
    out = subprocess.run(
        ["git", "show", f"HEAD:{rel_path.replace(chr(92), '/')}"],
        cwd=str(ROOT),
        capture_output=True,
        check=False,
        timeout=30,
    )
    if out.returncode != 0:
        return None
    h = hashlib.sha256()
    h.update(out.stdout)
    return h.hexdigest()[:16]


def _classify(
    override_main: Path,
    override_compile: Path,
    best_main: Path | None,
    best_compile: Path | None,
    best_eval_json: Path | None,
    locked_dir: Path,
    board_row: dict | None,
    override_main_head_hash: str | None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    # Block cases first.
    if board_row is None:
        return "BLOCKED", ["no row in logs/programbench_lock_board.json"]

    # LOCKED short-circuit: official best is 100/100 AND a locked archive exists.
    # The tool is finished; no edit needed.
    best_passed = board_row.get("best_passed")
    best_runnable = board_row.get("best_runnable_total")
    locked_present = (
        bool(board_row.get("locked_dir") or board_row.get("locked_archive")) or locked_dir.is_dir()
    )
    is_perfect = (
        isinstance(best_passed, int)
        and isinstance(best_runnable, int)
        and best_runnable > 0
        and best_passed == best_runnable
    )
    if is_perfect and locked_present:
        return "LOCKED", [
            f"best_passed=best_runnable={best_passed}/{best_runnable}; locked archive present — no edit needed"
        ]

    if best_eval_json is None or not best_eval_json.is_file():
        reasons.append(f"missing best_eval_path: {best_eval_json}")
        # Still try to classify recovery/archive on source presence.
    if best_main is None or not best_main.is_file():
        reasons.append("no best-run source available")

    # Override-present check.
    override_main_present = override_main.is_file()
    override_compile_present = override_compile.is_file()
    if not override_main_present:
        return "BLOCKED", reasons + [f"override main.py missing: {override_main}"]

    # If override compile.sh is missing but best source has one, that's RECOVERY.
    if not override_compile_present and best_compile and best_compile.is_file():
        return "RECOVERY", reasons + ["override compile.sh missing — recover from best source"]

    # Hash parity.
    ovr_hash = _sha256_file(override_main)
    best_hash = _sha256_file(best_main) if best_main else None
    if best_hash is None:
        # Source we can't compare against — treat as PATCH but flag in reasons.
        reasons.append("no best-source hash to compare; assuming PATCH if score < 100")
    elif ovr_hash != best_hash:
        # Distinguish pre-session drift (committed override differs from best
        # source) from in-flight edits (HEAD matches best, but working tree
        # has uncommitted changes — that is the expected PATCH state).
        head_hash = override_main_head_hash
        if head_hash and head_hash == best_hash:
            reasons.append(
                f"working-tree override {ovr_hash} differs from HEAD {head_hash} "
                f"(in-flight edit); HEAD matches best source — treating as PATCH"
            )
        else:
            return "RECOVERY", reasons + [
                f"override main.py hash {ovr_hash} != best source hash {best_hash}",
            ]

    # Archive case: 100% already, but locked/ is missing.
    if is_perfect and not locked_present:
        return "ARCHIVE", reasons + [
            f"best_passed=best_runnable={best_passed}/{best_runnable}; locked dir missing",
        ]

    if reasons:
        # Soft warning, still PATCH.
        return "PATCH", reasons
    return "PATCH", []


def _resolve_override_paths(slug: str) -> tuple[Path, Path]:
    """Find the override's main source file and compile.sh.

    Native tools have main.rs (Rust), main.go (Go), main.c/main.cpp (C/C++).
    Python upstreams have main.py. Probe each in order and return the first
    match so the preflight classifier works for both wrapper-debt and native
    overrides.
    """
    d = OVERRIDES_ROOT / slug
    compile_sh = d / "compile.sh"
    candidates = [
        d / "main.py",  # python upstream
        d / "src" / "main.rs",  # rust (Cargo layout)
        d / "main.rs",
        d / "main.go",
        d / "main.c",
        d / "main.cpp",
        d / "main.cc",
    ]
    for c in candidates:
        if c.is_file():
            return c, compile_sh
    # Glob fallback for typical native layouts (cmd/<tool>/main.go etc.)
    for pat in (
        "cmd/**/main.go",
        "src/**/main.rs",
        "src/**/*.cpp",
        "src/**/*.c",
        "**/main.go",
        "**/main.rs",
    ):
        try:
            matches = sorted(d.glob(pat), key=lambda p: len(p.parts))
        except OSError:
            matches = []
        if matches:
            return matches[0], compile_sh
    # Nothing found — fall back to main.py path so classifier can BLOCK with
    # the historical "main.py missing" message.
    return d / "main.py", compile_sh


def _resolve_best_source(board_row: dict | None) -> tuple[Path | None, Path | None]:
    """Find the best-run source directory by inspecting `best_eval_path`'s
    parent (`<run_root>/<slug>/`). Look for `source/main.py` and
    `source/compile.sh` siblings. If not present, return (None, None)."""
    if not board_row:
        return None, None
    best_eval = board_row.get("best_eval_path")
    if not best_eval:
        return None, None
    best_eval_path = Path(best_eval)
    candidate_root = best_eval_path.parent / "source"
    if not candidate_root.is_dir():
        return None, None
    # Probe in priority order: native first, then python
    for name in ("main.py", "main.rs", "src/main.rs", "main.go", "main.c", "main.cpp", "main.cc"):
        p = candidate_root / name
        if p.is_file():
            return p, candidate_root / "compile.sh"
    # Glob fallback for typical native subdir layouts
    for pat in ("cmd/**/main.go", "src/**/main.rs", "src/**/*.cpp", "**/main.go", "**/main.rs"):
        try:
            matches = sorted(candidate_root.glob(pat), key=lambda p: len(p.parts))
        except OSError:
            matches = []
        if matches:
            return matches[0], candidate_root / "compile.sh"
    return None, candidate_root / "compile.sh"


def preflight(slug: str) -> dict:
    git = _git_state()
    override_main, override_compile = _resolve_override_paths(slug)
    board_row = _board_row(slug)
    best_main, best_compile = _resolve_best_source(board_row)
    best_eval = (
        Path(board_row["best_eval_path"]) if board_row and board_row.get("best_eval_path") else None
    )
    base_slug = board_row.get("base_slug") if board_row else slug.split(".")[0]
    locked_dir = LOCKED_ROOT / (
        base_slug.split("__")[-1] if base_slug and "__" in base_slug else (base_slug or slug)
    )
    freshness = _board_freshness(board_row or {}, ACCEPTED_RUNS)

    override_main_rel = override_main.relative_to(ROOT).as_posix()
    override_main_head_hash = _git_head_file_hash(override_main_rel)

    classification, reasons = _classify(
        override_main=override_main,
        override_compile=override_compile,
        best_main=best_main,
        best_compile=best_compile,
        best_eval_json=best_eval,
        locked_dir=locked_dir,
        board_row=board_row,
        override_main_head_hash=override_main_head_hash,
    )

    return {
        "slug": slug,
        "classification": classification,
        "reasons": reasons,
        "git": git,
        "board_row": {
            "base_slug": (board_row or {}).get("base_slug"),
            "best_passed": (board_row or {}).get("best_passed"),
            "best_runnable_total": (board_row or {}).get("best_runnable_total"),
            "best_score": (board_row or {}).get("best_score"),
            "best_eval_path": (board_row or {}).get("best_eval_path"),
            "latest_passed": (board_row or {}).get("latest_passed"),
            "latest_runnable_total": (board_row or {}).get("latest_runnable_total"),
            "latest_eval_path": (board_row or {}).get("latest_eval_path"),
            "factory_accepted": (board_row or {}).get("factory_accepted"),
            "factory_registry_line": (board_row or {}).get("factory_registry_line"),
            "eval_mtime": (board_row or {}).get("eval_mtime"),
        }
        if board_row
        else None,
        "paths": {
            "active_override_main": str(override_main),
            "active_override_compile": str(override_compile),
            "best_source_main": str(best_main) if best_main else None,
            "best_source_compile": str(best_compile) if best_compile else None,
            "best_eval_json": str(best_eval) if best_eval else None,
            "locked_dir": str(locked_dir),
        },
        "hashes": {
            "active_override_main_sha256_16": _sha256_file(override_main),
            "active_override_main_head_sha256_16": override_main_head_hash,
            "active_override_compile_sha256_16": _sha256_file(override_compile),
            "best_source_main_sha256_16": _sha256_file(best_main) if best_main else None,
            "best_source_compile_sha256_16": _sha256_file(best_compile) if best_compile else None,
        },
        "exists": {
            "override_main": override_main.is_file(),
            "override_compile": override_compile.is_file(),
            "best_source_main": bool(best_main and best_main.is_file()),
            "best_source_compile": bool(best_compile and best_compile.is_file()),
            "best_eval_json": bool(best_eval and best_eval.is_file()),
            "locked_dir": locked_dir.is_dir(),
        },
        "accepted_runs": freshness,
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="ProgramBench packet preflight — classify task before editing."
    )
    p.add_argument("slug", help="ProgramBench instance id, e.g. owner__repo.hash")
    p.add_argument("--json-only", action="store_true", help="Suppress the human header.")
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if classification is RECOVERY or BLOCKED.",
    )
    args = p.parse_args(argv)

    try:
        result = preflight(args.slug)
    except Exception as ex:  # noqa: BLE001 — surface anything to the caller
        json.dump(
            {"slug": args.slug, "classification": "BLOCKED", "error": str(ex)},
            sys.stdout,
            indent=2,
        )
        print()
        return 1

    if not args.json_only:
        cls = result["classification"]
        print(f"# pb_packet_preflight  slug={args.slug}  classification={cls}")
        if result.get("reasons"):
            for r in result["reasons"]:
                print(f"#   reason: {r}")
        print()
    json.dump(result, sys.stdout, indent=2)
    print()

    if args.strict and result["classification"] in {"RECOVERY", "BLOCKED", "LOCKED"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

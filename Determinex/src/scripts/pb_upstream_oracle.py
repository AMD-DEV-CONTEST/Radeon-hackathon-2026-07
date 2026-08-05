#!/usr/bin/env python3
"""ProgramBench upstream-binary oracle (skeleton).

When two tests in different branches assert contradictory expected outputs
for the same code path, the factory's rule is: build the upstream binary
from source and let its actual output adjudicate. This script LOCATES that
source, detects its language, and emits a build plan to disk. It does NOT
build unless `--execute` is passed.

Search locations (in order):
  1. <branch-dir>/ (if `--branch-dir` is given by the caller)
  2. T:/determinex-programbench/_extracted_tests/<slug>/<branch>/
  3. T:/determinex-programbench/*/<slug>/source/   (any run dir's source/)

Language detection:
  - Rust:   Cargo.toml present
  - Go:     go.mod present
  - Python: pyproject.toml or setup.py present
  - Other:  reports detected files but no build command

Output:
  logs/programbench_factory/<slug>/upstream_oracle_plan.json
  (written even in dry-run mode)

Usage:
  python scripts/pb_upstream_oracle.py anordal__shellharden.6a6ffd4
  python scripts/pb_upstream_oracle.py anordal__shellharden.6a6ffd4 \\
      --branch-dir T:/determinex-programbench/_extracted_tests/anordal__shellharden.6a6ffd4/<branch>
  python scripts/pb_upstream_oracle.py anordal__shellharden.6a6ffd4 --execute  # ACTUALLY build
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTORY_DIR = ROOT / "logs" / "programbench_factory"
EXTRACTED_TESTS = Path(
    os.environ.get(
        "DETERMINEX_PB_EXTRACTED",
        "T:/determinex-programbench/_extracted_tests",
    )
)
DEFAULT_PB_ROOT = Path(
    os.environ.get(
        "DETERMINEX_PB_ROOT",
        "T:/determinex-programbench",
    )
)


def _detect_language(dir_path: Path) -> tuple[str, list[Path]]:
    """Inspect a directory for build markers. Returns (lang, marker_files)."""
    markers: dict[str, list[Path]] = {"rust": [], "go": [], "python": [], "other": []}
    if not dir_path.is_dir():
        return "missing", []
    for child in dir_path.iterdir():
        n = child.name.lower()
        if n == "cargo.toml":
            markers["rust"].append(child)
        elif n == "go.mod":
            markers["go"].append(child)
        elif n in ("pyproject.toml", "setup.py", "setup.cfg"):
            markers["python"].append(child)
    if markers["rust"]:
        return "rust", markers["rust"]
    if markers["go"]:
        return "go", markers["go"]
    if markers["python"]:
        return "python", markers["python"]
    return "other", []


def _build_command(lang: str, dir_path: Path) -> list[str]:
    if lang == "rust":
        return ["cargo", "build", "--release"]
    if lang == "go":
        return ["go", "build", "-o", "executable", "."]
    if lang == "python":
        # No "build" - Python tools run directly. We surface install instead.
        return ["pip", "install", "-e", "."]
    return []  # unknown


def _candidate_dirs(slug: str, branch_dir: Path | None) -> list[Path]:
    """Order: explicit branch_dir -> extracted tests (any branch) -> any run dir's source/."""
    out: list[Path] = []
    if branch_dir:
        out.append(branch_dir)

    extracted_root = EXTRACTED_TESTS / slug
    if extracted_root.is_dir():
        # Try the first immediate subdir (each branch is a hash-named dir)
        for sub in sorted(extracted_root.iterdir()):
            if sub.is_dir():
                out.append(sub)
                break

    # Any T:/determinex-programbench/<run>/<slug>/source/
    if DEFAULT_PB_ROOT.is_dir():
        for run in sorted(DEFAULT_PB_ROOT.iterdir()):
            src = run / slug / "source"
            if src.is_dir():
                out.append(src)
                break

    # De-dup preserving order
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        rp = str(p.resolve()) if p.exists() else str(p)
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def make_plan(slug: str, branch_dir: Path | None) -> dict[str, Any]:
    candidates = _candidate_dirs(slug, branch_dir)
    chosen: dict[str, Any] | None = None
    for d in candidates:
        lang, markers = _detect_language(d)
        if lang != "missing" and lang != "other":
            chosen = {
                "dir": str(d),
                "language": lang,
                "markers": [str(m) for m in markers],
                "build_command": _build_command(lang, d),
            }
            break

    plan = {
        "slug": slug,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "candidate_dirs": [str(p) for p in candidates],
        "chosen": chosen,
        "note": (
            "No buildable source found. Inspect the candidate dirs above; "
            "you may need to pass --branch-dir explicitly."
            if chosen is None
            else "Pass --execute to invoke the build_command in the chosen dir. "
            "Use the resulting binary to adjudicate disputed fixtures."
        ),
    }
    return plan


def write_plan(slug: str, plan: dict[str, Any]) -> Path:
    out_dir = FACTORY_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "upstream_oracle_plan.json"
    out_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def execute_build(plan: dict[str, Any]) -> dict[str, Any]:
    """Run the build_command in the chosen dir. Returns a result summary."""
    chosen = plan.get("chosen")
    if not chosen:
        return {"executed": False, "reason": "no chosen build dir"}
    cmd = chosen.get("build_command") or []
    if not cmd:
        return {
            "executed": False,
            "reason": f"no build_command for language {chosen.get('language')}",
        }
    cwd = chosen["dir"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        return {
            "executed": True,
            "cwd": cwd,
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-1200:],
            "stderr_tail": (proc.stderr or "")[-1200:],
        }
    except subprocess.TimeoutExpired:
        return {
            "executed": True,
            "cwd": cwd,
            "cmd": cmd,
            "returncode": -1,
            "error": "timeout after 900s",
        }
    except Exception as e:
        return {
            "executed": True,
            "cwd": cwd,
            "cmd": cmd,
            "returncode": -1,
            "error": f"{type(e).__name__}: {e}",
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="ProgramBench instance id, e.g. owner__repo.hash")
    ap.add_argument(
        "--branch-dir",
        type=Path,
        default=None,
        help="optional explicit path to upstream source for a specific branch",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="actually invoke the build_command (default: dry-run)",
    )
    args = ap.parse_args()

    plan = make_plan(args.slug, args.branch_dir)

    if args.execute:
        plan["build_result"] = execute_build(plan)

    out_path = write_plan(args.slug, plan)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    print()
    print(f"wrote {out_path}")
    if not args.execute:
        print("(dry-run: did not invoke build_command)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

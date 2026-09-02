#!/usr/bin/env python3
"""Conservative ProgramBench lock archiver.

When a tool reaches official display 100 (passed == runnable, runnable > 0),
this script can mechanically lay down the standard locked-archive layout
under `corpus/programbench/locked/<short>/`. It does the bare structural work;
it does NOT author rich `lessons.md`, edit READMEs creatively, or touch any
other locked tool.

Safety:
  - Refuses to run without `--confirm-100`.
  - Verifies eval JSON has `passed == runnable` and `runnable > 0`.
  - Refuses to overwrite an existing `eval_report.json` unless `--force`.
  - Refuses to write under any other path than `corpus/programbench/locked/<short>/`.
  - Default is `--dry-run` (no file writes; just prints the plan).

Locked-archive layout (matches gping/ripsecrets/htmlq/ripgrep/zoxide):
  corpus/programbench/locked/<short>/
    README.md                    # rendered from template + eval counts
    eval_report.json             # verbatim copy of the source eval JSON
    source/                      # mirror of <run_root>/<slug>/source/
    submission.tar.gz            # copy of <run_root>/<slug>/submission.tar.gz
    lessons.md.stub              # placeholder if no lessons.md present yet

Usage:
  python scripts/pb_lock_archiver.py orf__gping.26eb5b9 \\
      T:/determinex-programbench/<run>/orf__gping.26eb5b9/orf__gping.26eb5b9.eval.json \\
      T:/determinex-programbench/<run> \\
      --confirm-100
  # Default is dry-run unless --execute is also passed.

  python scripts/pb_lock_archiver.py orf__gping.26eb5b9 \\
      T:/determinex-programbench/<run>/orf__gping.26eb5b9/orf__gping.26eb5b9.eval.json \\
      T:/determinex-programbench/<run> \\
      --confirm-100 --execute
  # Performs the actual file writes.
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCKED_ROOT = ROOT / "corpus" / "programbench" / "locked"
REPORT_ROOT = ROOT / "logs" / "programbench_factory" / "lock_reports"
REPORT_INDEX = REPORT_ROOT / "LOCK_REPORTS.jsonl"

README_TEMPLATE = """\
# {short} lock

Tool: `{slug}`

Locked on: {date}

Official ProgramBench eval:

- Score: `100/100`
- Runnable denominator: `{passed}/{runnable} passed`
- Extra manifest entries: `{not_run} not_run`, `{skipped} skipped`
- Eval artifact: `eval_report.json`
- Submission artifact: `submission.tar.gz`
- Source: `source/main.py` (or main.<ext>)

Notes:

- Mechanical archive produced by `scripts/pb_lock_archiver.py`.
  The structural skeleton is in place. Author `lessons.md` from the
  closing sequence and replace `lessons.md.stub` when ready.
- Executable hash: `{exe16}`
"""

LESSONS_STUB = """\
# {slug} - lessons (stub)

This file was placed by `scripts/pb_lock_archiver.py` to mark that the
archive structure is complete but the post-mortem has not been authored.

Authoring guide (compare with `corpus/programbench/locked/htmlq/lessons.md`
or `corpus/programbench/locked/ripsecrets/lessons.md`):

1. TL;DR - one paragraph on what single decision closed the lock.
2. Hard discoveries - numbered list of mistakes you would not repeat.
3. Cluster transfer notes - patterns that other tools in the same cluster
   (e.g. fd, ripgrep family; jq cluster; ANSI-color text-tools) can lift.
4. Architecture summary - ASCII layout of `main.py` plus the load-bearing
   semantics (parsers, state machines, encoders).
5. Verifying against upstream - exact `cargo build --release` (or `go build`)
   command for the upstream binary used to adjudicate disputed tests.

Replace this file (filename `lessons.md`, not `lessons.md.stub`) before
publishing the lock or committing the archive to git.
"""


def _parse_eval(eval_path: Path) -> dict[str, Any]:
    if not eval_path.is_file():
        raise SystemExit(f"eval JSON not found: {eval_path}")
    try:
        data = json.loads(eval_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        raise SystemExit(f"failed to parse eval JSON: {e}")
    if data.get("error_code"):
        raise SystemExit(f"eval reports error_code={data['error_code']}; refusing to archive")
    tr = data.get("test_results") or []
    statuses: dict[str, int] = {}
    for t in tr:
        s = str(t.get("status", "?"))
        statuses[s] = statuses.get(s, 0) + 1
    passed = statuses.get("passed", 0)
    failed = statuses.get("failure", 0) + statuses.get("failed", 0)
    skipped = statuses.get("skipped", 0)
    not_run = statuses.get("not_run", 0)
    errored = statuses.get("error", 0)
    runnable = passed + failed + errored
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "not_run": not_run,
        "errored": errored,
        "runnable": runnable,
        "total": len(tr),
        "executable_hash": (data.get("executable_hash") or "")[:64],
        "eval_path": str(eval_path),
    }


def _short_name(slug: str) -> str:
    if "__" in slug:
        right = slug.split("__", 1)[1]
        if "." in right:
            return right.split(".", 1)[0]
        return right
    return slug


def _plan(
    slug: str,
    eval_path: Path,
    run_root: Path,
    force: bool,
) -> dict[str, Any]:
    summary = _parse_eval(eval_path)
    short = _short_name(slug)
    locked_dir = LOCKED_ROOT / short

    inst_dir = run_root / slug
    submission_src = inst_dir / "submission.tar.gz"
    source_src = inst_dir / "source"

    # Refuse to write outside locked_dir
    if not str(locked_dir.resolve()).startswith(str(LOCKED_ROOT.resolve())):
        raise SystemExit(f"locked dir escape: {locked_dir}")

    target_eval = locked_dir / "eval_report.json"
    target_submission = locked_dir / "submission.tar.gz"
    target_source = locked_dir / "source"
    target_readme = locked_dir / "README.md"
    target_lessons_stub = locked_dir / "lessons.md.stub"
    target_lessons = locked_dir / "lessons.md"

    will_overwrite_eval = target_eval.is_file()
    if will_overwrite_eval and not force:
        raise SystemExit(
            f"refusing to overwrite existing eval_report.json: {target_eval}. "
            "Use --force to override (audit Codex commit-history first)."
        )

    return {
        "slug": slug,
        "short": short,
        "summary": summary,
        "locked_dir": str(locked_dir),
        "will_overwrite_eval": will_overwrite_eval,
        "source_paths": {
            "eval_path": str(eval_path),
            "submission_src": str(submission_src),
            "source_src": str(source_src),
            "submission_exists": submission_src.is_file(),
            "source_exists": source_src.is_dir(),
        },
        "target_paths": {
            "eval_report": str(target_eval),
            "submission": str(target_submission),
            "source": str(target_source),
            "readme": str(target_readme),
            "lessons_stub": str(target_lessons_stub),
            "lessons_existing": str(target_lessons) if target_lessons.is_file() else None,
        },
    }


def _check_lock_safety(plan: dict[str, Any]) -> None:
    s = plan["summary"]
    if s["runnable"] <= 0:
        raise SystemExit("eval has runnable == 0; cannot be a 100/100 lock")
    if s["passed"] != s["runnable"]:
        raise SystemExit(
            f"eval is not display 100: passed={s['passed']} runnable={s['runnable']}. "
            "Refusing to archive; use a 100/100 eval JSON."
        )
    paths = plan["source_paths"]
    if not paths["submission_exists"]:
        raise SystemExit(f"submission.tar.gz missing at {paths['submission_src']}")
    if not paths["source_exists"]:
        raise SystemExit(f"source/ missing at {paths['source_src']}")


def execute(plan: dict[str, Any]) -> list[str]:
    s = plan["summary"]
    paths = plan["source_paths"]
    targets = plan["target_paths"]
    locked_dir = Path(plan["locked_dir"])
    locked_dir.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []

    # Copy eval JSON
    shutil.copy2(paths["eval_path"], targets["eval_report"])
    actions.append(f"copy eval_report.json: {paths['eval_path']} -> {targets['eval_report']}")

    # Copy submission
    shutil.copy2(paths["submission_src"], targets["submission"])
    actions.append(f"copy submission.tar.gz: {paths['submission_src']} -> {targets['submission']}")

    # Mirror source/ (no overwrite of __pycache__ or build outputs)
    src_dir = Path(paths["source_src"])
    dst_dir = Path(targets["source"])
    dst_dir.mkdir(parents=True, exist_ok=True)
    exclude_dirs = {"__pycache__", "target"}
    exclude_files = {"executable"}
    for src_file in src_dir.rglob("*"):
        rel = src_file.relative_to(src_dir)
        if any(part in exclude_dirs for part in rel.parts):
            continue
        if src_file.name in exclude_files:
            continue
        dst_file = dst_dir / rel
        if src_file.is_dir():
            dst_file.mkdir(parents=True, exist_ok=True)
        else:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
    actions.append(f"mirror source/: {paths['source_src']} -> {targets['source']}")

    # Render README
    readme_body = README_TEMPLATE.format(
        short=plan["short"],
        slug=plan["slug"],
        date=datetime.date.today().isoformat(),
        passed=s["passed"],
        runnable=s["runnable"],
        not_run=s["not_run"],
        skipped=s["skipped"],
        exe16=s["executable_hash"][:16],
    )
    Path(targets["readme"]).write_text(readme_body, encoding="utf-8")
    actions.append(f"render README.md: {targets['readme']}")

    # Lessons stub (only if no existing lessons.md present)
    if not targets["lessons_existing"]:
        Path(targets["lessons_stub"]).write_text(
            LESSONS_STUB.format(slug=plan["slug"]), encoding="utf-8"
        )
        actions.append(f"write lessons.md.stub: {targets['lessons_stub']}")

    return actions


def _counts_from_board() -> dict[str, Any]:
    board_path = ROOT / "logs" / "programbench_lock_board.json"
    if not board_path.is_file():
        return {}
    rows = json.loads(board_path.read_text(encoding="utf-8", errors="replace"))
    locked = 0
    for row in rows:
        passed = row.get("best_passed") or 0
        runnable = row.get("best_runnable_total") or 0
        if row.get("locked_dir") or (runnable > 0 and passed == runnable):
            locked += 1
    return {
        "locked_100": locked,
        "remaining_to_200": max(0, 200 - locked),
    }


def _run_refresh() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for script in ("pb_score_audit.py", "pb_pool_status.py"):
        cmd = [sys.executable, str(ROOT / "scripts" / script)]
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        steps.append(
            {
                "script": script,
                "returncode": proc.returncode,
                "stdout_tail": "\n".join(proc.stdout.splitlines()[-8:]),
                "stderr_tail": "\n".join(proc.stderr.splitlines()[-8:]),
            }
        )
    return steps


def _write_lock_report(
    plan: dict[str, Any], actions: list[str], refresh: list[dict[str, Any]]
) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    safe_short = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in plan["short"])
    report_path = REPORT_ROOT / f"{now.strftime('%Y%m%dT%H%M%SZ')}_{safe_short}.md"
    counts = _counts_from_board()
    s = plan["summary"]
    body = [
        f"# LOCK REPORT - {plan['short']}",
        "",
        "TRUMPET: TA-DA. PROGRAMBENCH LOCK ARCHIVED.",
        "",
        f"- Slug: `{plan['slug']}`",
        f"- Score: `{s['passed']}/{s['runnable']}`",
        f"- Total entries: `{s['total']}`",
        f"- Not run: `{s['not_run']}`",
        f"- Skipped: `{s['skipped']}`",
        f"- Executable hash: `{s['executable_hash']}`",
        f"- Locked dir: `{plan['locked_dir']}`",
        f"- Eval JSON: `{s['eval_path']}`",
        "",
        "## Board",
        "",
        f"- Locked 100: `{counts.get('locked_100', 'unknown')}`",
        f"- Remaining to 200: `{counts.get('remaining_to_200', 'unknown')}`",
        "",
        "## Archive Actions",
        "",
    ]
    body.extend(f"- {action}" for action in actions)
    body.extend(["", "## Refresh"])
    for step in refresh:
        body.append("")
        body.append(f"- `{step['script']}` rc=`{step['returncode']}`")
        if step["stderr_tail"]:
            body.append(f"  stderr tail: `{step['stderr_tail']}`")
    body.append("")
    report_path.write_text("\n".join(body), encoding="utf-8")

    index_row = {
        "created_at": now.isoformat(),
        "slug": plan["slug"],
        "short": plan["short"],
        "passed": s["passed"],
        "runnable": s["runnable"],
        "locked_dir": plan["locked_dir"],
        "report_path": str(report_path),
        **counts,
    }
    with REPORT_INDEX.open("a", encoding="utf-8") as f:
        f.write(json.dumps(index_row, sort_keys=True) + "\n")
    return report_path


def _print_trumpet(plan: dict[str, Any], report_path: Path | None, counts: dict[str, Any]) -> None:
    s = plan["summary"]
    print()
    print("============================================================")
    print("TRUMPET: TA-DA. PROGRAMBENCH LOCK ARCHIVED.")
    print(f"LOCK: {plan['short']}  {s['passed']}/{s['runnable']}  slug={plan['slug']}")
    if counts:
        print(
            f"BOARD: {counts.get('locked_100')} locked, {counts.get('remaining_to_200')} remaining to 200"
        )
    if report_path:
        print(f"REPORT: {report_path}")
    print("============================================================")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="ProgramBench instance id, e.g. owner__repo.hash")
    ap.add_argument("eval_json", type=Path, help="path to the 100/100 eval JSON to archive")
    ap.add_argument(
        "run_root", type=Path, help="parent dir holding <slug>/{source,submission.tar.gz}"
    )
    ap.add_argument(
        "--confirm-100",
        action="store_true",
        required=False,
        help="REQUIRED: explicit acknowledgement that this eval JSON is a 100/100 lock",
    )
    ap.add_argument(
        "--execute", action="store_true", help="actually perform the writes (default is dry-run)"
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing eval_report.json (audit history first!)",
    )
    args = ap.parse_args()

    if not args.confirm_100:
        sys.stderr.write(
            "ERROR: --confirm-100 is required. The archiver refuses to act on an "
            "unverified 100/100 claim.\n"
        )
        return 2

    plan = _plan(args.slug, args.eval_json, args.run_root, force=args.force)
    print(
        json.dumps(
            {
                "slug": plan["slug"],
                "short": plan["short"],
                "summary": plan["summary"],
                "locked_dir": plan["locked_dir"],
                "will_overwrite_eval": plan["will_overwrite_eval"],
                "target_paths": plan["target_paths"],
                "source_paths": plan["source_paths"],
            },
            indent=2,
        )
    )

    _check_lock_safety(plan)
    print()

    if not args.execute:
        print("(dry-run; pass --execute to perform the file writes)")
        return 0

    actions = execute(plan)
    print("Actions performed:")
    for a in actions:
        print(f"  {a}")
    refresh = _run_refresh()
    report_path = _write_lock_report(plan, actions, refresh)
    _print_trumpet(plan, report_path, _counts_from_board())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""ProgramBench score/coverage audit from eval JSON artifacts.

This intentionally does not trust the Markdown work matrix as machine truth.
It scans eval JSON files, override dirs, extracted local tests, and lock dirs,
then writes a normalized lock board.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_ROOT = Path("T:/determinex-programbench")
OVERRIDES_DIR = ROOT / "corpus/programbench/per_tool_overrides"
EXTRACTED_DIR = DEFAULT_EVAL_ROOT / "_extracted_tests"
LOCKED_DIR = ROOT / "corpus/programbench/locked"
REPRODUCIBLE_OVERRIDES_JSON = ROOT / "corpus/programbench/reproducible_eval_overrides.json"
OUT_JSON = ROOT / "logs/programbench_lock_board.json"
OUT_CSV = ROOT / "logs/programbench_lock_board.csv"
ACCEPTED_RUNS_JSONL = ROOT / "logs/programbench_factory/accepted_runs.jsonl"


def base_slug(name: str) -> str:
    parts = name.split(".")
    if len(parts) >= 2 and len(parts[-1]) in (7, 8, 12):
        return ".".join(parts[:-1]).lower()
    return name.lower()


def iter_eval_jsons(eval_root: Path) -> list[Path]:
    if not eval_root.is_dir():
        return []
    paths: list[Path] = []
    for pattern in ("determinex_pb*/*/*.eval.json", "v*/*/*.eval.json", "pb_*/*/*.eval.json"):
        paths.extend(eval_root.glob(pattern))
    seen = {p.resolve(): p for p in paths}
    return sorted(seen.values(), key=lambda p: p.stat().st_mtime)


def summarize_eval(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        return {"eval_path": str(path), "eval_error": f"{type(e).__name__}: {e}"}

    results = data.get("test_results") or []
    counts: dict[str, int] = {}
    for item in results:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1

    passed = counts.get("passed", 0)
    failed = counts.get("failure", 0) + counts.get("failed", 0)
    skipped = counts.get("skipped", 0)
    not_run = counts.get("not_run", 0)
    errored = counts.get("error", 0)
    total = len(results)
    runnable_total = passed + failed + errored
    score = 100.0 * passed / runnable_total if runnable_total else 0.0
    raw_score = 100.0 * passed / total if total else 0.0
    return {
        "eval_path": str(path),
        "eval_mtime": path.stat().st_mtime,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "not_run": not_run,
        "errored": errored,
        "total": total,
        "runnable_total": runnable_total,
        "score": score,
        "raw_score": raw_score,
        "error_code": data.get("error_code"),
    }


def iter_accepted_run_evals(path: Path = ACCEPTED_RUNS_JSONL) -> list[dict[str, Any]]:
    """Return accepted factory gate eval summaries from the append-only registry.

    The registry is local operator state, not a lock archive. Accepted rows are
    allowed to update the working board so dispatch and packet generation use
    the highest verified official eval, including fresh gated improvements that
    have not yet been archived as locks.
    """
    if not path.is_file():
        return []
    summaries: list[dict[str, Any]] = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        slug = str(row.get("slug") or "").strip()
        eval_raw = row.get("candidate_eval")
        if not slug or not eval_raw:
            continue
        eval_path = Path(str(eval_raw))
        if not eval_path.is_absolute():
            eval_path = ROOT / eval_path
        if not eval_path.is_file():
            continue
        summary = summarize_eval(eval_path)
        summary.update(
            {
                "slug": slug,
                "base_slug": base_slug(slug),
                "factory_accepted": True,
                "factory_registry_path": str(path),
                "factory_registry_line": line_no,
                "gate_result_path": row.get("gate_result_path"),
                "run_root": row.get("run_root"),
            }
        )
        summaries.append(summary)
    return summaries


def load_reproducible_overrides(
    path: Path = REPRODUCIBLE_OVERRIDES_JSON,
) -> dict[str, dict[str, Any]]:
    """Load audited reproducible-best overrides for stale historical peaks."""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for slug, payload in raw.items():
        if isinstance(payload, dict):
            out[base_slug(str(slug))] = payload
    return out


def apply_reproducible_overrides(grouped: dict[str, dict[str, Any]]) -> None:
    """Force audited reproducible evals to be the board's working best."""
    overrides = load_reproducible_overrides()
    for key, payload in overrides.items():
        eval_raw = payload.get("eval_path")
        if not eval_raw:
            continue
        eval_path = Path(str(eval_raw))
        if not eval_path.is_absolute():
            eval_path = ROOT / eval_path
        if not eval_path.is_file():
            continue
        slug = str(payload.get("slug") or key)
        summary = summarize_eval(eval_path)
        summary.update(
            {
                "slug": slug,
                "base_slug": key,
                "reproducible_override": True,
                "reproducible_override_reason": payload.get("reason"),
                "reproducible_override_source": str(REPRODUCIBLE_OVERRIDES_JSON),
            }
        )
        if key not in grouped:
            grouped[key] = {"latest": summary, "best": summary, "eval_count": 1}
        else:
            grouped[key]["best"] = summary


def summarize_locked_archives() -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    if not LOCKED_DIR.is_dir():
        return summaries
    for tool_dir in LOCKED_DIR.iterdir():
        if not tool_dir.is_dir():
            continue
        report = tool_dir / "eval_report.json"
        if not report.is_file():
            continue
        summary = summarize_eval(report)
        summary["eval_path"] = str(report)
        summary["eval_mtime"] = report.stat().st_mtime
        summary["slug"] = tool_dir.name
        summary["base_slug"] = base_slug(tool_dir.name)
        summary["locked_archive"] = True
        summaries[base_slug(tool_dir.name)] = summary
    return summaries


def grouped_evals(eval_root: Path) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    def add_summary(summary: dict[str, Any]) -> None:
        key = str(summary.get("base_slug") or base_slug(str(summary.get("slug") or "")))
        if not key:
            return
        if key not in grouped:
            grouped[key] = {"latest": summary, "best": summary, "eval_count": 1}
            return
        grouped[key]["eval_count"] += 1
        if summary.get("eval_mtime", 0) > grouped[key]["latest"].get("eval_mtime", 0):
            grouped[key]["latest"] = summary
        best = grouped[key]["best"]
        if summary.get("score", 0) > best.get("score", 0) or (
            summary.get("score", 0) == best.get("score", 0)
            and summary.get("eval_mtime", 0) > best.get("eval_mtime", 0)
        ):
            grouped[key]["best"] = summary

    for path in iter_eval_jsons(eval_root):
        slug = path.stem.removesuffix(".eval")
        summary = summarize_eval(path)
        summary["slug"] = slug
        summary["base_slug"] = base_slug(slug)
        add_summary(summary)
    for summary in iter_accepted_run_evals():
        add_summary(summary)
    apply_reproducible_overrides(grouped)
    return grouped


def dir_keys(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    return {base_slug(p.name) for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")}


def locked_tool_dir_keys(path: Path) -> set[str]:
    """Like dir_keys(), but for LOCKED_DIR specifically: excludes dotfile/organizational
    folders (.vscode, tier_1_perfect, tier_2_upstream_skips, ...) that are not real PB
    tool submissions. A real locked-tool dir carries either eval_report.json or
    submission.tar.gz (same marker summarize_locked_archives() already requires)."""
    if not path.is_dir():
        return set()
    keys: set[str] = set()
    for p in path.iterdir():
        if not p.is_dir() or p.name.startswith("."):
            continue
        if (p / "eval_report.json").is_file() or (p / "submission.tar.gz").is_file():
            keys.add(base_slug(p.name))
    return keys


def tool_short_name(key: str) -> str:
    """Return the human/tool directory name for a canonical ProgramBench key."""
    return key.split("__", 1)[1] if "__" in key else key


def build_board(eval_root: Path) -> list[dict[str, Any]]:
    evals = grouped_evals(eval_root)
    locked_archives = summarize_locked_archives()
    overrides = dir_keys(OVERRIDES_DIR)
    extracted = dir_keys(eval_root / "_extracted_tests")
    locked = locked_tool_dir_keys(LOCKED_DIR)

    canonical_short_names = {tool_short_name(key) for key in set(evals) | overrides | extracted}
    locked_only = locked - canonical_short_names
    keys = sorted(set(evals) | overrides | extracted | locked_only)
    board: list[dict[str, Any]] = []
    for key in keys:
        short_name = tool_short_name(key)
        locked_dir_name = key if key in locked else short_name if short_name in locked else None
        row = {
            "base_slug": key,
            "has_eval": key in evals,
            "has_override": key in overrides,
            "has_extracted_tests": key in extracted,
            "locked_dir": locked_dir_name is not None,
            "locked_dir_name": locked_dir_name,
        }
        if key in evals:
            best = evals[key]["best"]
            latest = evals[key]["latest"]
            row.update(best)
            row.update(
                {
                    "best_score": best.get("score"),
                    "best_passed": best.get("passed"),
                    "best_total": best.get("total"),
                    "best_runnable_total": best.get("runnable_total"),
                    "best_raw_score": best.get("raw_score"),
                    "best_eval_path": best.get("eval_path"),
                    "latest_score": latest.get("score"),
                    "latest_passed": latest.get("passed"),
                    "latest_total": latest.get("total"),
                    "latest_runnable_total": latest.get("runnable_total"),
                    "latest_raw_score": latest.get("raw_score"),
                    "latest_eval_path": latest.get("eval_path"),
                    "eval_count": evals[key]["eval_count"],
                    "latest_regressed_from_best": (
                        latest.get("score", 0) + 1e-9 < best.get("score", 0)
                    ),
                }
            )
        else:
            row.update(
                {
                    "slug": key,
                    "score": None,
                    "best_score": None,
                    "latest_score": None,
                    "passed": None,
                    "failed": None,
                    "skipped": None,
                    "errored": None,
                    "total": None,
                    "runnable_total": None,
                    "not_run": None,
                    "raw_score": None,
                    "eval_path": None,
                }
            )
        if locked_dir_name and locked_dir_name in locked_archives:
            locked_summary = locked_archives[locked_dir_name]
            row.update(
                {
                    "locked_score": locked_summary.get("score"),
                    "locked_passed": locked_summary.get("passed"),
                    "locked_total": locked_summary.get("total"),
                    "locked_runnable_total": locked_summary.get("runnable_total"),
                    "locked_raw_score": locked_summary.get("raw_score"),
                    "locked_eval_path": locked_summary.get("eval_path"),
                }
            )
            if (locked_summary.get("score") or 0) >= (row.get("best_score") or 0):
                row.update(locked_summary)
                row["base_slug"] = key
                row["slug"] = row.get("slug") or key
                row["locked_archive_slug"] = locked_summary.get("slug")
                row.update(
                    {
                        "best_score": locked_summary.get("score"),
                        "best_passed": locked_summary.get("passed"),
                        "best_total": locked_summary.get("total"),
                        "best_runnable_total": locked_summary.get("runnable_total"),
                        "best_raw_score": locked_summary.get("raw_score"),
                        "best_eval_path": locked_summary.get("eval_path"),
                    }
                )
        if row["locked_dir"]:
            action = "verify/archive-lock"
        elif row["has_eval"] and row.get("best_score", 0) >= 99.5:
            action = "lock-now"
        elif row["has_eval"] and row.get("best_score", 0) >= 70:
            action = "push-to-lock"
        elif row["has_eval"] and row["has_override"]:
            action = "hand-test-iterate"
        elif row["has_extracted_tests"]:
            action = "create-override"
        else:
            action = "recover-tests-or-task"
        row["next_action"] = action
        board.append(row)
    return board


def write_outputs(board: list[dict[str, Any]], json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(board, indent=2, sort_keys=True), encoding="utf-8")

    fields = [
        "base_slug",
        "slug",
        "best_score",
        "latest_score",
        "passed",
        "failed",
        "skipped",
        "errored",
        "total",
        "runnable_total",
        "not_run",
        "raw_score",
        "has_eval",
        "has_override",
        "has_extracted_tests",
        "locked_dir",
        "latest_regressed_from_best",
        "next_action",
        "factory_accepted",
        "reproducible_override",
        "best_eval_path",
        "latest_eval_path",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in board:
            writer.writerow(row)


def print_summary(board: list[dict[str, Any]]) -> None:
    def count(pred) -> int:
        return sum(1 for row in board if pred(row))

    print(f"tools: {len(board)}")
    print(f"with eval: {count(lambda r: r['has_eval'])}")
    print(f"with extracted tests: {count(lambda r: r['has_extracted_tests'])}")
    print(f"with override: {count(lambda r: r['has_override'])}")
    print(f"locked dirs: {count(lambda r: r['locked_dir'])}")
    print(f"lock-now >=99.5: {count(lambda r: r['next_action'] == 'lock-now')}")
    print(f"push-to-lock >=70: {count(lambda r: r['next_action'] == 'push-to-lock')}")
    print(f"hand-test-iterate: {count(lambda r: r['next_action'] == 'hand-test-iterate')}")
    print(f"create-override: {count(lambda r: r['next_action'] == 'create-override')}")
    print(f"latest regressions from best: {count(lambda r: r.get('latest_regressed_from_best'))}")
    print()
    top = sorted(
        [r for r in board if isinstance(r.get("best_score"), float)],
        key=lambda r: r["best_score"],
        reverse=True,
    )[:20]
    for row in top:
        latest = row.get("latest_score")
        latest_text = f"{latest:.2f}" if isinstance(latest, (int, float)) else "n/a"
        print(
            f"{row['best_score']:6.2f}  {row['base_slug']:<45} "
            f"best={row['best_passed']}/{row.get('best_runnable_total') or row['best_total']} "
            f"latest={latest_text}  {row['next_action']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    parser.add_argument("--json", type=Path, default=OUT_JSON)
    parser.add_argument("--csv", type=Path, default=OUT_CSV)
    parser.add_argument(
        "--skip-language-classify",
        action="store_true",
        help="skip the post-audit language-classification step",
    )
    args = parser.parse_args()

    board = build_board(args.eval_root)
    write_outputs(board, args.json, args.csv)
    print_summary(board)
    print(f"\njson: {args.json}")
    print(f"csv:  {args.csv}")

    # Refresh the language classification side-car. The classifier reads the
    # board JSON we just wrote and produces LANGUAGE_CLASSIFICATION.{json,md}.
    # Native-required vs python-sufficient is a load-bearing factor in
    # candidate routing - keep it in lockstep with the board.
    if not args.skip_language_classify:
        try:
            import subprocess as _sp

            classifier = Path(__file__).resolve().parent / "pb_language_classifier.py"
            if classifier.is_file():
                _sp.run([sys.executable, str(classifier)], check=False)
        except Exception as err:  # nosec - best-effort refresh
            sys.stderr.write(f"[score-audit] language-classify refresh failed: {err}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

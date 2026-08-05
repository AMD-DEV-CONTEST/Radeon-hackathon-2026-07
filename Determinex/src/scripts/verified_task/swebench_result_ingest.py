"""Ingest SWE-bench harness outcomes into the signed verdict corpus.

This is an adapter around the existing CorpusManager and benchmark payload
completion gate. It records model attempts and official harness outcomes as
verdict data; it does not import gold patches or mutate benchmark fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agents.base_agent import CorpusType  # noqa: E402
from corpus.corpus_manager import CorpusManager  # noqa: E402
from swe_run.dataset import load_dataset_split  # noqa: E402

from verified_task.bench_to_corpus_eligibility import complete_benchmark_payload  # noqa: E402
from verified_task.verdict_recorder import atomic_write_json  # noqa: E402


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            instance_id = row.get("instance_id")
            if not isinstance(instance_id, str) or not instance_id:
                raise ValueError(f"{path}:{line_no}: missing instance_id")
            rows[instance_id] = row
    return rows


def _repo_bucket(instance_id: str, instance: dict[str, Any] | None) -> str:
    repo = (instance or {}).get("repo") or instance_id.split("__", 1)[0]
    return str(repo).split("/")[-1].lower()


def _language_for(split: str, instance: dict[str, Any] | None) -> str:
    language = (instance or {}).get("language")
    if isinstance(language, str) and language.strip():
        return language.strip().lower()
    if split in {"lite", "verified", "full"}:
        return "python"
    return "unknown"


def _classify_failure(
    *,
    status: str,
    repo_bucket: str,
    patch: str,
    instance: dict[str, Any] | None,
) -> str:
    if status == "empty":
        return "empty_patch"
    if status == "error":
        return "harness_error"
    if not patch.strip():
        return "empty_patch"
    if not patch.lstrip().startswith("diff --git"):
        return "patch_format_malformed"
    tests = str((instance or {}).get("FAIL_TO_PASS") or "").lower()
    problem = str((instance or {}).get("problem_statement") or "").lower()
    combined = f"{tests}\n{problem}"
    if repo_bucket == "sympy":
        return "semantic_wrong_logic_sympy_symbolic_math"
    if repo_bucket == "django":
        return "semantic_wrong_logic_django_api_contract"
    if repo_bucket == "matplotlib":
        return "semantic_wrong_logic_visualization_api"
    if repo_bucket == "astropy":
        return "semantic_wrong_logic_scientific_python"
    if "test" in combined:
        return "semantic_test_failure"
    return "semantic_wrong_logic"


def _repair_prompt(status: str, failure_class: str, instance: dict[str, Any] | None) -> str:
    fail_to_pass = (instance or {}).get("FAIL_TO_PASS") or ""
    if status == "empty":
        return (
            "Previous attempt produced no patch. Localize the failing behavior from "
            "the issue and FAIL_TO_PASS tests, then produce a minimal unified diff."
        )
    if status == "error":
        return (
            "Official harness errored for this attempt. Re-run only after separating "
            "environment/image failure from patch behavior."
        )
    return (
        "Official SWE-bench harness rejected the attempted patch. Treat this as "
        f"{failure_class}; reason through the issue and tests before proposing a "
        f"new patch. FAIL_TO_PASS={fail_to_pass}"
    )


def _status_sets(report: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "resolved": set(report.get("resolved_ids", [])),
        "unresolved": set(report.get("unresolved_ids", [])),
        "empty": set(report.get("empty_patch_ids", [])),
        "error": set(report.get("error_ids", [])),
    }


def _iter_selected_ids(
    status_sets: dict[str, set[str]],
    include_status: set[str],
) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for status in ("unresolved", "empty", "error", "resolved"):
        if status not in include_status:
            continue
        for instance_id in sorted(status_sets[status]):
            items.append((status, instance_id))
    return items


def _make_record(
    *,
    status: str,
    instance_id: str,
    prediction: dict[str, Any] | None,
    instance: dict[str, Any] | None,
    manifest: dict[str, Any],
    report_path: Path,
    predictions_path: Path,
    split: str,
    source_run_label: str,
) -> dict[str, Any]:
    patch = str((prediction or {}).get("model_patch") or "")
    repo = str((instance or {}).get("repo") or instance_id.split("__", 1)[0])
    repo_bucket = _repo_bucket(instance_id, instance)
    language = _language_for(split, instance)
    failure_class = (
        "none"
        if status == "resolved"
        else _classify_failure(
            status=status,
            repo_bucket=repo_bucket,
            patch=patch,
            instance=instance,
        )
    )
    verdict = "pass" if status == "resolved" else ("error" if status == "error" else "fail")
    problem = str((instance or {}).get("problem_statement") or "")
    fail_to_pass = (instance or {}).get("FAIL_TO_PASS")
    pass_to_pass = (instance or {}).get("PASS_TO_PASS")
    model_name = str((prediction or {}).get("model_name_or_path") or source_run_label)
    validator_command = (
        "python -m swebench.harness.run_evaluation "
        f"--predictions_path {predictions_path} "
        "--dataset_name princeton-nlp/SWE-bench_Lite --split test "
        f"--run_id {source_run_label}"
    )
    payload = complete_benchmark_payload(
        {
            "benchmark": "SWE-bench_Lite",
            "task_id": instance_id,
            "language": language,
            "source_kind": "benchmark_verdict",
            "initial_prompt": problem,
            "workspace": repo,
            "attempt_index": 1,
            "attempt_code_or_patch": patch,
            "validator_results": [
                {
                    "validator": "swebench.harness.run_evaluation",
                    "status": status,
                    "resolved": status == "resolved",
                    "report_path": str(report_path),
                    "prediction_path": str(predictions_path),
                    "source_run": source_run_label,
                }
            ],
            "verdict": verdict,
            "repair_outcome": verdict,
            "failure_class": failure_class,
            "failure_type": failure_class,
            "repair_prompt": _repair_prompt(status, failure_class, instance),
            "final_patch": patch if status == "resolved" else "",
            "privacy_policy": "public_benchmark_uncloaked",
            "cloak_mode": "off",
            "license_gate": "benchmark_dataset",
            "safety_gate": "passed",
            "supply_chain_gate": "swebench_dataset",
            "model_router": (manifest.get("models") or {}).get("backend", "unknown"),
            "router_used": model_name,
            "validator": [validator_command],
            "source_benchmark": "SWE-bench_Lite",
            "license_provenance": "SWE-bench benchmark dataset",
            "verifier_command": [validator_command],
            "verifier_result": verdict,
            "corpus_type": CorpusType.CODE_VERDICT.value,
            "trace_kind": "swebench_official_harness_verdict",
            "repo": repo,
            "repo_bucket": repo_bucket,
            "base_commit": (instance or {}).get("base_commit"),
            "fail_to_pass": fail_to_pass,
            "pass_to_pass": pass_to_pass,
            "source_prediction_run": source_run_label,
            "source_manifest": manifest,
            "source_report_schema_version": report_path.name,
            "gold_patch_imported": False,
            "benchmark_contamination_note": (
                "This row stores the model attempt and official verdict only. "
                "Gold benchmark patches are not imported."
            ),
        }
    )
    input_hash_src = json.dumps(
        {
            "instance_id": instance_id,
            "repo": repo,
            "base_commit": (instance or {}).get("base_commit"),
            "problem": problem,
            "fail_to_pass": fail_to_pass,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    output_hash_src = json.dumps(
        {
            "instance_id": instance_id,
            "status": status,
            "patch_sha256": hashlib.sha256(patch.encode("utf-8", "replace")).hexdigest(),
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    manager = CorpusManager()
    return manager._normalize_record(
        corpus_type=CorpusType.CODE_VERDICT,
        task_id=instance_id,
        input_hash=hashlib.sha256(input_hash_src.encode("utf-8")).hexdigest(),
        output_hash=hashlib.sha256(output_hash_src.encode("utf-8")).hexdigest(),
        source_benchmark="SWE-bench_Lite",
        payload=payload,
    )


def build_records(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = _read_json(args.report)
    manifest = _read_json(args.manifest) if args.manifest else {}
    predictions = _read_jsonl(args.predictions)
    status_sets = _status_sets(report)
    include_status = set(args.include_status.split(","))
    selected = _iter_selected_ids(status_sets, include_status)
    if args.max_records:
        selected = selected[: args.max_records]
    instance_ids = [instance_id for _, instance_id in selected]
    dataset_rows = load_dataset_split(args.split, instance_ids=instance_ids)
    dataset_by_id = {row["instance_id"]: row for row in dataset_rows}
    source_run_label = (
        args.source_run
        or manifest.get("run_id")
        or (next(iter(predictions.values())).get("model_name_or_path") if predictions else "")
        or args.report.stem
    )

    records: list[dict[str, Any]] = []
    missing_predictions = 0
    missing_dataset = 0
    for status, instance_id in selected:
        prediction = predictions.get(instance_id)
        instance = dataset_by_id.get(instance_id)
        if prediction is None:
            missing_predictions += 1
        if instance is None:
            missing_dataset += 1
        records.append(
            _make_record(
                status=status,
                instance_id=instance_id,
                prediction=prediction,
                instance=instance,
                manifest=manifest,
                report_path=args.report,
                predictions_path=args.predictions,
                split=args.split,
                source_run_label=source_run_label,
            )
        )

    status_counts = Counter(record.get("verdict", "unknown") for record in records)
    failure_counts = Counter(record.get("failure_class", "unknown") for record in records)
    summary = {
        "created_utc": datetime.now(UTC).isoformat(),
        "report": str(args.report),
        "predictions": str(args.predictions),
        "manifest": str(args.manifest) if args.manifest else "",
        "split": args.split,
        "source_run": source_run_label,
        "include_status": sorted(include_status),
        "selected_records": len(records),
        "status_counts": dict(status_counts),
        "failure_class_counts": dict(failure_counts),
        "missing_predictions": missing_predictions,
        "missing_dataset": missing_dataset,
        "execute": args.execute,
        "corpus_root": str(args.corpus_root),
    }
    return records, summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest SWE-bench report outcomes into signed corpus."
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--split", default="lite")
    parser.add_argument(
        "--include-status",
        default="unresolved,empty,error",
        help="Comma-separated statuses to ingest: unresolved,empty,error,resolved",
    )
    parser.add_argument("--source-run", default="")
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--corpus-root", type=Path, default=Path("T:/determinex_corpus"))
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=Path("logs/swebench/corpus_ingest/swebench_ingest_summary.json"),
    )
    parser.add_argument(
        "--execute", action="store_true", help="Write records to the signed corpus."
    )
    args = parser.parse_args()

    for path in [args.report, args.predictions]:
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.manifest and not args.manifest.is_file():
        raise FileNotFoundError(args.manifest)

    records, summary = build_records(args)
    if args.execute and records:
        manager = CorpusManager(root=args.corpus_root)
        manager._write_records(CorpusType.CODE_VERDICT, records)
    atomic_write_json(args.summary_out, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

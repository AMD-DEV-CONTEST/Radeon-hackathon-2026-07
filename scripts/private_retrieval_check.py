"""Evaluate a private workspace without copying its documents into the repo.

The query manifest is JSONL and may live outside the repository. Results contain
paths and scores only; document text is never written to the output report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import LocalRetriever, assess_file_matches, compile_intent, route_workspace_request, scan_workspace


def _relative(path: str, root: Path) -> str:
    return Path(path).resolve().relative_to(root.resolve()).as_posix()


def _load_queries(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not isinstance(value.get("query"), str):
            raise ValueError(f"Invalid query row at line {line_number}")
        rows.append(value)
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ratio(numerator: float, denominator: int) -> float:
    return round(numerator / max(denominator, 1), 3)


def _expected_aliases(retriever: LocalRetriever, root: Path, expected: list[str]) -> set[str]:
    """Accept exact paths plus alternate formats with the same normalized stem."""

    expected_paths = {(root / item).resolve() for item in expected}
    expected_families = {retriever._file_family(path.name) for path in expected_paths}
    aliases = {path.relative_to(root).as_posix() for path in expected_paths if path.exists()}
    for path in retriever.paths:
        if retriever._file_family(path.name) in expected_families:
            aliases.add(path.resolve().relative_to(root).as_posix())
    return aliases


def run(corpus: Path, queries: Path, index_file: Path, rebuild: bool = False, limit: int = 8) -> dict[str, Any]:
    started = time.perf_counter()
    root = corpus.resolve()
    rows = _load_queries(queries)
    retriever = LocalRetriever(index_file=index_file)
    scan_details: dict[str, Any] = {"reused": bool(retriever.evidence)}
    if rebuild or not retriever.evidence:
        scan = scan_workspace(root)
        retriever.index_paths(scan.files, accumulate=False)
        scan_details = {
            "reused": False,
            "scanned_entries": scan.scanned_entries,
            "supported_files": len(scan.files),
            "skipped": sum(scan.skip_counts.values()),
            "skip_counts": scan.skip_counts,
        }

    retrieval_rows: list[dict[str, Any]] = []
    no_answer_rows: list[dict[str, Any]] = []
    clarification_rows: list[dict[str, Any]] = []
    routing_rows: list[dict[str, Any]] = []
    for row in rows:
        plan, telemetry, compiler = compile_intent(row["query"], None)
        route = route_workspace_request(row["query"], plan)
        routing_rows.append({
            "id": row["id"],
            "expected": row["intent"],
            "actual": route,
            "passed": (
                route == "sensitive_record_scan"
                if row["intent"] == "sensitive_record_scan"
                else route == "file_locator"
                if row["intent"] in {"file_locator", "artifact_summary"}
                else True
            ),
        })
        category = str(row.get("category", "uncategorized"))
        if row.get("should_clarify"):
            clarification_rows.append({
                "id": row["id"],
                "expected": True,
                "actual": plan.clarification_needed,
                "passed": plan.clarification_needed,
                "category": category,
            })
            continue
        expected = [str(item) for item in row.get("expected_files", [])]
        if row["intent"] not in {"file_locator", "artifact_summary"}:
            continue
        matches = retriever.locate_files(row["query"], limit=limit, intent_plan=plan)
        decision = assess_file_matches(row["query"], plan, matches)
        ranked = [
            {
                "path": _relative(match.source_path, root),
                "score": match.score,
                "confidence": match.confidence,
                "family": match.file_family,
                "reasons": list(match.reasons),
            }
            for match in matches
        ]
        if row.get("expect_no_match"):
            no_answer_rows.append({
                "id": row["id"],
                "category": category,
                "actual": decision.status,
                "passed": decision.status == "no_match",
                "top_score": decision.top_score,
                "score_margin": decision.score_margin,
                "compiler": compiler,
            })
            continue
        if not expected:
            continue
        aliases = _expected_aliases(retriever, root, expected)
        expected_alias_groups = [
            _expected_aliases(retriever, root, [item])
            for item in expected
        ]
        ranked_paths = [item["path"] for item in ranked]
        hit_positions = [index + 1 for index, path in enumerate(ranked_paths) if path in aliases]
        expected_coverage = sum(
            1
            for accepted in expected_alias_groups
            if any(path in accepted for path in ranked_paths[:limit])
        ) / max(len(expected_alias_groups), 1)
        retrieval_rows.append({
            "id": row["id"],
            "query": row["query"],
            "expected": expected,
            "accepted_aliases": sorted(aliases),
            "top_results": ranked,
            "top1": bool(hit_positions and hit_positions[0] == 1),
            "recall_at_5": bool(hit_positions and hit_positions[0] <= 5),
            "reciprocal_rank": 1.0 / hit_positions[0] if hit_positions else 0.0,
            "expected_coverage_at_limit": round(expected_coverage, 3),
            "compiler": compiler,
            "compiler_error": telemetry.get("error"),
            "category": category,
            "decision": {
                "status": decision.status,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "top_score": decision.top_score,
                "score_margin": decision.score_margin,
            },
            "auto_selected": decision.status == "confident",
            "safe_decision": bool(hit_positions and hit_positions[0] == 1) or decision.status != "confident",
            "expect_multiple": bool(row.get("expect_multiple") or len(expected) > 1),
        })

    case_count = len(retrieval_rows)
    auto_selected = [item for item in retrieval_rows if item["auto_selected"]]
    single_target_rows = [item for item in retrieval_rows if not item["expect_multiple"]]
    multi_target_rows = [item for item in retrieval_rows if item["expect_multiple"]]
    category_metrics: dict[str, dict[str, Any]] = {}
    for category in sorted({item["category"] for item in retrieval_rows}):
        category_rows = [item for item in retrieval_rows if item["category"] == category]
        category_metrics[category] = {
            "cases": len(category_rows),
            "top1_accuracy": _ratio(sum(item["top1"] for item in category_rows), len(category_rows)),
            "recall_at_5": _ratio(sum(item["recall_at_5"] for item in category_rows), len(category_rows)),
            "mean_reciprocal_rank": _ratio(sum(item["reciprocal_rank"] for item in category_rows), len(category_rows)),
        }
    corpus_hashes = sorted({item.source_sha256 for item in retriever.evidence if item.source_sha256})
    corpus_fingerprint = hashlib.sha256("|".join(corpus_hashes).encode("ascii")).hexdigest()
    result = {
        "corpus": str(root),
        "queries": str(queries.resolve()),
        "index_file": str(index_file.resolve()),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "query_manifest_sha256": _sha256_file(queries),
        "corpus_fingerprint": corpus_fingerprint,
        "index": {
            **scan_details,
            "indexed_sources": len({item.source_path for item in retriever.evidence}),
            "indexed_chunks": len(retriever.evidence),
            "ingestion_errors": len(retriever.ingestion_errors),
        },
        "metrics": {
            "retrieval_cases": case_count,
            "top1_accuracy": round(sum(item["top1"] for item in retrieval_rows) / max(case_count, 1), 3),
            "recall_at_5": round(sum(item["recall_at_5"] for item in retrieval_rows) / max(case_count, 1), 3),
            "mean_reciprocal_rank": round(sum(item["reciprocal_rank"] for item in retrieval_rows) / max(case_count, 1), 3),
            "mean_expected_coverage": round(sum(item["expected_coverage_at_limit"] for item in retrieval_rows) / max(case_count, 1), 3),
            "clarification_accuracy": round(sum(item["passed"] for item in clarification_rows) / max(len(clarification_rows), 1), 3),
            "routing_accuracy": round(sum(item["passed"] for item in routing_rows) / max(len(routing_rows), 1), 3),
            "no_answer_cases": len(no_answer_rows),
            "no_answer_accuracy": _ratio(sum(item["passed"] for item in no_answer_rows), len(no_answer_rows)),
            "auto_selection_coverage": _ratio(len(auto_selected), case_count),
            "auto_selection_precision": _ratio(sum(item["top1"] for item in auto_selected), len(auto_selected)),
            "safe_decision_rate": _ratio(sum(item["safe_decision"] for item in retrieval_rows), case_count),
            "unsafe_wrong_auto_selections": sum(not item["safe_decision"] for item in retrieval_rows),
            "single_target_cases": len(single_target_rows),
            "single_target_top1_accuracy": _ratio(sum(item["top1"] for item in single_target_rows), len(single_target_rows)),
            "multi_target_cases": len(multi_target_rows),
            "multi_target_full_coverage_accuracy": _ratio(
                sum(item["expected_coverage_at_limit"] >= 1.0 for item in multi_target_rows),
                len(multi_target_rows),
            ),
        },
        "category_metrics": category_metrics,
        "retrieval_failures": [item for item in retrieval_rows if not item["top1"]],
        "no_answer_failures": [item for item in no_answer_rows if not item["passed"]],
        "no_answer_rows": no_answer_rows,
        "clarification_rows": clarification_rows,
        "routing_failures": [item for item in routing_rows if not item["passed"]],
        "rows": retrieval_rows,
    }
    return result


def sanitized_report(result: dict[str, Any]) -> dict[str, Any]:
    """Remove queries, paths, filenames, excerpts, and expected labels."""

    return {
        "schema": 1,
        "query_manifest_sha256": result["query_manifest_sha256"],
        "corpus_fingerprint": result["corpus_fingerprint"],
        "elapsed_seconds": result["elapsed_seconds"],
        "index": result["index"],
        "metrics": result["metrics"],
        "category_metrics": result["category_metrics"],
        "failure_ids": [item["id"] for item in result["retrieval_failures"]],
        "no_answer_failure_ids": [item["id"] for item in result["no_answer_failures"]],
        "routing_failure_ids": [item["id"] for item in result["routing_failures"]],
        "clarification_failure_ids": [item["id"] for item in result["clarification_rows"] if not item["passed"]],
        "compiler_modes": sorted({item["compiler"] for item in result["rows"]}),
        "privacy": {
            "contains_query_text": False,
            "contains_source_paths": False,
            "contains_expected_filenames": False,
            "contains_document_text": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--index-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--public-output", type=Path, default=None)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    result = run(args.corpus, args.queries, args.index_file, rebuild=args.rebuild, limit=args.limit)
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    if args.public_output:
        args.public_output.parent.mkdir(parents=True, exist_ok=True)
        args.public_output.write_text(
            json.dumps(sanitized_report(result), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

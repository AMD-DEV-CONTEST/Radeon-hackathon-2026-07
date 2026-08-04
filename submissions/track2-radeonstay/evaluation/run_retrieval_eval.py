#!/usr/bin/env python3
"""Evaluate local policy retrieval against fixed knowledge-QA fixtures.

This evaluator uses only the Python standard library plus RadeonStay's local
``PolicyRetriever``.  It performs no network access and does not invoke a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from radeonstay.retrieval import (  # noqa: E402
    PolicyRetriever,
    SearchResult,
    policy_corpus_sha256,
    validate_policy_directory,
)


DEFAULT_CASES = PROJECT_ROOT / "evaluation" / "fixtures" / "cases.jsonl"
DEFAULT_POLICIES = PROJECT_ROOT / "data" / "policies"
OFFICIAL_SUITE_VERSION = "30-case-p0-v3"
OFFICIAL_SUITE_SHA256 = "60fae4be0bd7a16ee9b2e7963bb3afccbf319c2ed64cd3ba43acfc912bfd3d1b"
OFFICIAL_KNOWLEDGE_IDS = tuple(f"KQ-{index:03d}" for index in range(1, 9))


def source_tree_sha256(project_root: Path) -> str:
    digest = hashlib.sha256()
    excluded_names = {
        ".coverage",
        ".env",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "runtime",
    }
    excluded_suffixes = (".egg-info", ".pyc", ".pyo", ".pyd")
    for path in sorted(project_root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(project_root)
        if any(
            part in excluded_names or part.endswith(excluded_suffixes)
            for part in relative.parts
        ):
            continue
        if relative.parts[:2] == ("evaluation", "results"):
            continue
        label = relative.as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(label).to_bytes(4, "big"))
        digest.update(label)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def git_provenance(project_root: Path) -> dict[str, str]:
    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(project_root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    repository_root = git("rev-parse", "--show-toplevel")
    project_prefix = git("rev-parse", "--show-prefix").rstrip("/")
    if not project_prefix:
        raise RuntimeError("Retrieval evidence must come from a repository subdirectory")
    status = git("status", "--porcelain=v1", "--untracked-files=all", "--", ".")
    if status:
        raise RuntimeError(
            "Official retrieval evidence requires all RadeonStay source files to be "
            "tracked and clean"
        )
    return {
        "repository_root": repository_root,
        "project_prefix": project_prefix,
        "commit": git("rev-parse", "--verify", "HEAD"),
        "project_tree": git("rev-parse", f"HEAD:{project_prefix}"),
        "source_tree_sha256": source_tree_sha256(project_root),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute Recall@1 and Recall@3 for local policy retrieval."
    )
    parser.add_argument("--run-id", required=True, help="Shared evidence run identifier")
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES,
        help=f"JSONL fixture path (default: {DEFAULT_CASES})",
    )
    parser.add_argument(
        "--policies",
        type=Path,
        default=DEFAULT_POLICIES,
        help=f"Local policy directory (default: {DEFAULT_POLICIES})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for the same JSON report printed to stdout.",
    )
    return parser.parse_args(argv)


def validate_run_id(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
    first_allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    if not 1 <= len(value) <= 48 or value[0] not in first_allowed or any(
        character not in allowed for character in value
    ):
        raise ValueError("run-id has an invalid format")
    return value


def load_knowledge_cases(path: Path) -> list[dict[str, Any]]:
    suite_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if suite_sha256 != OFFICIAL_SUITE_SHA256:
        raise ValueError(
            "Official retrieval evaluation requires the immutable suite; "
            f"received SHA256 {suite_sha256}"
        )
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            if item.get("category") != "knowledge_qa":
                continue
            case_id = item.get("id")
            prompt = item.get("prompt")
            citations = item.get("expected", {}).get("citations", [])
            if not isinstance(case_id, str) or not case_id:
                raise ValueError(f"Missing knowledge case id at {path}:{line_number}")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f"Missing prompt for {case_id} at {path}:{line_number}")
            if not isinstance(citations, list) or not citations:
                raise ValueError(f"Missing expected citations for {case_id}")
            if not all(isinstance(citation, dict) for citation in citations):
                raise ValueError(f"Expected citation objects for {case_id}")
            cases.append(item)
    if tuple(case["id"] for case in cases) != OFFICIAL_KNOWLEDGE_IDS:
        raise ValueError("Knowledge case IDs do not match the release manifest")
    return cases


def result_is_traceable(result: SearchResult, policy_dir: Path) -> bool:
    try:
        source = (policy_dir / result.source_path).resolve()
        source.relative_to(policy_dir)
    except (OSError, ValueError):
        return False
    return source.is_file() and bool(result.matched_text.strip())


def citation_matches(result: SearchResult, expected: Mapping[str, Any]) -> bool:
    """Match every document/section field provided by a fixture citation."""

    document = expected.get("document")
    section = expected.get("section")
    if document is not None and result.document != document:
        return False
    if section is not None and result.section != section:
        return False
    return document is not None or section is not None


def has_expected_result(
    results: Iterable[SearchResult], expected_citations: list[dict[str, Any]]
) -> bool:
    return any(
        citation_matches(result, citation)
        for result in results
        for citation in expected_citations
    )


def evaluate(
    retriever: PolicyRetriever,
    cases: list[dict[str, Any]],
    *,
    policy_dir: Path,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    hits_at_1 = 0
    hits_at_3 = 0
    traceability_failures: list[dict[str, Any]] = []

    for case in cases:
        expected_citations = case["expected"]["citations"]
        results = retriever.search(case["prompt"], top_k=3)
        recall_at_1 = has_expected_result(results[:1], expected_citations)
        recall_at_3 = has_expected_result(results[:3], expected_citations)
        hits_at_1 += int(recall_at_1)
        hits_at_3 += int(recall_at_3)
        for rank, result in enumerate(results[:3], 1):
            if not result_is_traceable(result, policy_dir):
                traceability_failures.append(
                    {
                        "case_id": case["id"],
                        "rank": rank,
                        "source_path": result.source_path,
                    }
                )
        rows.append(
            {
                "id": case["id"],
                "prompt": case["prompt"],
                "expected_citations": expected_citations,
                "retrieved": [
                    {"rank": rank, **result.as_dict()}
                    for rank, result in enumerate(results[:3], 1)
                ],
                "recall_at_1": recall_at_1,
                "recall_at_3": recall_at_3,
            }
        )

    total = len(rows)
    recall_at_3 = round(hits_at_3 / total, 6)
    quality_gate = {
        "recall_at_3_at_least_095": recall_at_3 >= 0.95,
        "all_results_traceable": not traceability_failures,
    }
    return {
        "evaluation": "radeonstay-local-policy-retrieval",
        "suite_version": OFFICIAL_SUITE_VERSION,
        "suite_sha256": OFFICIAL_SUITE_SHA256,
        "knowledge_case_ids": list(OFFICIAL_KNOWLEDGE_IDS),
        "policy_corpus_sha256": policy_corpus_sha256(policy_dir),
        "cases_path": str(DEFAULT_CASES),
        "policies_path": str(DEFAULT_POLICIES),
        "summary": {
            "knowledge_qa_cases": total,
            "hits_at_1": hits_at_1,
            "hits_at_3": hits_at_3,
            "recall_at_1": round(hits_at_1 / total, 6),
            "recall_at_3": recall_at_3,
        },
        "traceability_failures": traceability_failures,
        "quality_gate": {**quality_gate, "passed": all(quality_gate.values())},
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started_at = datetime.now(UTC)
    run_id = validate_run_id(args.run_id)
    cases_path = args.cases.expanduser().resolve()
    official_policies = validate_policy_directory(
        DEFAULT_POLICIES,
        project_root=PROJECT_ROOT,
    )
    policies_path = validate_policy_directory(
        args.policies,
        project_root=PROJECT_ROOT,
    )
    if policies_path != official_policies:
        raise ValueError("Official retrieval evaluation requires data/policies")
    provenance = git_provenance(PROJECT_ROOT)
    policy_hash = policy_corpus_sha256(policies_path, project_root=PROJECT_ROOT)
    cases = load_knowledge_cases(cases_path)
    retriever = PolicyRetriever.from_directory(policies_path)
    report = evaluate(retriever, cases, policy_dir=policies_path)
    report["run_id"] = run_id
    report["started_at_utc"] = started_at.isoformat(timespec="seconds")
    report["completed_at_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    report["provenance"] = provenance
    report["cases_path"] = str(cases_path)
    report["policies_path"] = str(policies_path)
    if report.get("policy_corpus_sha256") != policy_hash:
        raise RuntimeError("Policy corpus changed during retrieval evaluation")
    if policy_corpus_sha256(policies_path, project_root=PROJECT_ROOT) != policy_hash:
        raise RuntimeError("Policy corpus changed during retrieval evaluation")
    if git_provenance(PROJECT_ROOT) != provenance:
        raise RuntimeError("RadeonStay source changed during retrieval evaluation")
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if args.output is not None:
        output_path = args.output.expanduser().resolve()
        if output_path.exists():
            raise FileExistsError(f"Refusing to overwrite evidence: {output_path}")
        if not output_path.parent.is_dir():
            raise FileNotFoundError(
                f"Output parent does not exist: {output_path.parent}"
            )
        with output_path.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    sys.stdout.write(rendered)
    return 0 if report["quality_gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Insurance RAG Agent batch evaluation runner.

Runs InsuranceAgent.query() round by round and case by case, collects trace facts,
executes host deterministic checks + model semantic judge, and generates a summary report
and release gate verdict.

Usage:
    python scripts/run_eval.py --cases docs/eval/insurance_qa_50.json --rounds 1 --trial-id trial-001
    python scripts/run_eval.py --cases docs/eval/insurance_qa_50.json --rounds 3 --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# Ensure the project root is on the Python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.eval.cases import load_cases, load_rules, validate_case_rules
from src.eval.checks import deterministic_verdicts
from src.eval.judge import flatten_rules, judge_run
from src.eval.report import (
    DEFAULT_GATE_CRITERIA,
    generate_release_gate_report,
    summarize_levels,
    write_results_json,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("insurance.eval")

# -- Default paths
DEFAULT_CASES_FILE = PROJECT_ROOT / "docs" / "eval" / "insurance_qa_50.json"
DEFAULT_RULES_FILE = PROJECT_ROOT / "src" / "eval" / "rules.yaml"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "eval_results"
DEFAULT_ROUNDS = 1

AppRunner = Callable[..., Awaitable[dict[str, Any]]]
JudgeRunner = Callable[..., Awaitable[list[dict[str, object]]]]


def _file_fingerprint(path: Path) -> str:
    """Compute the SHA256 fingerprint of a file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _model_name(settings_path: Path) -> str:
    """Extract the model name from SETTINGS.yaml."""

    if not settings_path.exists():
        return "unknown"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    provider = next(iter(settings))
    return str(settings[provider].get("model", "unknown"))


def _aggregate_level(levels: list[str]) -> str:
    """Aggregate multiple levels into a single level: any fail -> fail, all pass -> pass, otherwise -> unknown."""

    values = set(levels)
    if "fail" in values:
        return "fail"
    if values == {"pass"}:
        return "pass"
    return "unknown"


def _all_rules(
    stage_rules: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    """Flatten all rules into a flat list."""

    return [
        {
            "stage": stage,
            "rule_id": str(rule["rule_id"]),
            "description": str(rule["description"]),
        }
        for stage, rules in stage_rules.items()
        for rule in rules
    ]


async def _run_agent(
    agent: Any,
    question: str,
    session_id: str,
) -> dict[str, Any]:
    """Run InsuranceAgent.query() and return the result dictionary."""

    return await agent.query(question, session_id=session_id)


async def run_eval(
    *,
    cases_file: Path = DEFAULT_CASES_FILE,
    rules_file: Path = DEFAULT_RULES_FILE,
    trial_id: str,
    rounds: int = DEFAULT_ROUNDS,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    limit: int | None = None,
    gate_criteria: dict[str, Any] | None = None,
    app_runner: AppRunner | None = None,
    judge_runner: JudgeRunner | None = None,
) -> Path:
    """Run the insurance RAG Agent case by case and round by round, and write the evaluation results.

    Args:
        cases_file: path to the evaluation cases JSON file.
        rules_file: path to the evaluation rules YAML file.
        trial_id: unique identifier for this evaluation run.
        rounds: number of repeated rounds (each round re-runs all cases).
        output_root: output root directory.
        limit: only evaluate the first N cases (None means all).
        gate_criteria: release gate criteria (None uses the defaults).
        app_runner: custom application runner (None uses InsuranceAgent).
        judge_runner: custom judge runner (None uses judge_run).

    Returns:
        Path to the results file.
    """

    if rounds < 1:
        raise ValueError("rounds must be positive")

    # Load cases and rules
    cases = load_cases(cases_file)
    rules = load_rules(rules_file)
    validate_case_rules(cases, rules)
    stage_rules = rules["stage_rules"]
    all_rules = _all_rules(stage_rules)

    if limit is not None and limit > 0:
        cases = cases[:limit]

    # Initialize the Agent (if not using a custom runner)
    agent: Any = None
    if app_runner is None:
        from src.agent.main import InsuranceAgent

        agent = InsuranceAgent()
        try:
            agent.init_rag()
            logger.info("RAG retriever initialization complete")
        except FileNotFoundError as e:
            logger.warning("RAG not initialized: %s - will run in pure LLM mode", e)

    judge_runner = judge_runner or judge_run

    # Create the output directory
    batch_directory = output_root / trial_id
    batch_directory.mkdir(parents=True, exist_ok=True)

    case_rows: list[dict[str, Any]] = []
    rule_rows: list[dict[str, Any]] = []

    for round_number in range(1, rounds + 1):
        round_id = f"round-{round_number:02d}"
        logger.info("=== %s started (round %d/%d, %d cases) ===", trial_id, round_number, rounds, len(cases))

        for case_index, case in enumerate(cases):
            case_id = f"case-{case_index + 1:03d}"
            question = str(case.get("question", ""))
            session_id = f"{trial_id}-{round_id}-{case_id}"

            logger.info("[%s] %s: %s", round_id, case_id, question[:50])

            try:
                # Run the Agent
                if app_runner is not None:
                    run = await app_runner(question, session_id=session_id)
                else:
                    run = await _run_agent(agent, question, session_id)

                # Build case_rules
                case_rules = {
                    "expected_refs": case.get("expected_refs", []),
                    "expected_answer": case.get("expected_answer", ""),
                    "category": case.get("category", ""),
                    "difficulty": case.get("difficulty", ""),
                    "context_dependency": case.get("context_dependency", ""),
                }

                # Host deterministic checks
                host_rows = deterministic_verdicts(
                    run=run,
                    case_rules=case_rules,
                    stage_rules=stage_rules,
                )

                # Model semantic judge
                model_rows = await judge_runner(
                    case=case,
                    case_rules=case_rules,
                    stage_rules=stage_rules,
                    candidate_run=run,
                )

                verdicts = list(host_rows) + list(model_rows)

                # Aggregate the end_to_end level
                e2e_verdicts = [
                    v for v in verdicts if str(v.get("stage")) == "end_to_end"
                ]
                e2e_levels = [str(v.get("level", "unknown")) for v in e2e_verdicts]
                level = _aggregate_level(e2e_levels) if e2e_levels else "unknown"

                final_answer = str(run.get("answer", ""))
                run_status = str(run.get("status", "completed"))
                reason = ";".join(str(v.get("reason", "")) for v in e2e_verdicts)
                query_type = str(run.get("query_type", "unknown"))

            except BaseException as exc:
                logger.error("[%s] %s run failed: %s: %s", round_id, case_id, type(exc).__name__, exc)
                verdicts = [
                    {
                        **rule,
                        "level": "unknown",
                        "evidence": [],
                        "reason": f"application or evaluation run failed: {type(exc).__name__}: {exc}",
                    }
                    for rule in all_rules
                ]
                level = "unknown"
                final_answer = ""
                run_status = "error"
                reason = f"{type(exc).__name__}: {exc}"
                query_type = "unknown"

            # Record the case result
            case_rows.append({
                "trial_id": trial_id,
                "round_id": round_id,
                "case_id": case_id,
                "category": str(case.get("category", "")),
                "difficulty": str(case.get("difficulty", "")),
                "question": question,
                "expected_answer": str(case.get("expected_answer", "")),
                "expected_refs": case.get("expected_refs", []),
                "actual_answer": final_answer,
                "run_status": run_status,
                "level": level,
                "reason": reason,
                "query_type": query_type,
            })

            # Record the rule result
            for verdict in verdicts:
                evidence_values = verdict.get("evidence", [])
                if not isinstance(evidence_values, list):
                    evidence_values = []
                rule_rows.append({
                    "trial_id": trial_id,
                    "round_id": round_id,
                    "case_id": case_id,
                    "category": str(case.get("category", "")),
                    "stage": str(verdict.get("stage", "")),
                    "rule_id": str(verdict.get("rule_id", "")),
                    "description": str(verdict.get("description", "")),
                    "level": str(verdict.get("level", "unknown")),
                    "evidence": ";".join(str(v) for v in evidence_values),
                    "reason": str(verdict.get("reason", "")),
                })

            logger.info("[%s] %s -> level=%s, status=%s", round_id, case_id, level, run_status)

    # Generate the summary
    case_summary = summarize_levels(case_rows)
    rule_summary = summarize_levels(rule_rows)

    # Stage summaries
    stage_summaries: dict[str, dict[str, int | float]] = {}
    stages_seen = sorted({str(r.get("stage", "")) for r in rule_rows})
    for stage in stages_seen:
        stage_verdicts = [r for r in rule_rows if str(r.get("stage", "")) == stage]
        stage_summaries[stage] = summarize_levels(stage_verdicts)

    # Release gate report
    eval_results = {
        "case_results": case_rows,
        "rule_results": rule_rows,
    }
    gate_report = generate_release_gate_report(eval_results, gate_criteria)

    # Assemble the complete results
    results = {
        "run_info": {
            "trial_id": trial_id,
            "rounds": rounds,
            "case_count": len(cases),
            "cases_file": str(cases_file),
            "rules_file": str(rules_file),
            "cases_sha256": _file_fingerprint(cases_file),
            "rules_sha256": _file_fingerprint(rules_file),
            "judge_model": _model_name(PROJECT_ROOT / "src" / "eval" / "SETTINGS.yaml"),
            "judge_prompt_sha256": _file_fingerprint(
                PROJECT_ROOT / "src" / "eval" / "prompts" / "semantic_judge.yaml"
            ),
            "created_at": datetime.now().astimezone().isoformat(),
        },
        "case_summary": case_summary,
        "rule_summary": rule_summary,
        "stage_summaries": stage_summaries,
        "case_results": case_rows,
        "rule_results": rule_rows,
        "release_gate": gate_report,
    }

    output_path = write_results_json(results, batch_directory / "eval_results.json")
    logger.info("=== Evaluation complete: %s ===", output_path)
    logger.info(
        "Summary: cases=%d, pass=%d, fail=%d, unknown=%d, pass_rate=%.1f%%",
        case_summary["total"],
        case_summary["passed"],
        case_summary["failed"],
        case_summary["unknown"],
        case_summary["pass_rate"] * 100,
    )
    logger.info("Release gate: %s", "PASS" if gate_report["passed"] else "FAIL")
    return output_path


async def main() -> None:
    parser = argparse.ArgumentParser(description="Insurance RAG Agent batch evaluation")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_FILE, help="evaluation cases JSON file path")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_FILE, help="evaluation rules YAML file path")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="number of repeated rounds")
    parser.add_argument(
        "--trial-id",
        default=datetime.now().strftime("trial-%Y%m%d-%H%M%S"),
        help="unique identifier for this evaluation run",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="output root directory")
    parser.add_argument("--limit", type=int, default=None, help="only evaluate the first N cases")
    args = parser.parse_args()

    output = await run_eval(
        cases_file=args.cases,
        rules_file=args.rules,
        trial_id=args.trial_id,
        rounds=args.rounds,
        output_root=args.output_root,
        limit=args.limit,
    )
    print(f"\nEvaluation results saved: {output}")


if __name__ == "__main__":
    asyncio.run(main())

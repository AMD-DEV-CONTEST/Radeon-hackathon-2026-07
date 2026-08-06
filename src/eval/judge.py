"""Use Eval's own model configuration to complete Insurance RAG Agent semantic evaluation.

The judge uses an isolated Agently Agent and SETTINGS.yaml, decoupled from the agent under test.
Model-owned semantic rules (owner=model):
- understand.relevant  — the system correctly understood the insurance question intent
- plan.appropriate     — query routing (rag_query vs data_query) is appropriate
- fetch.relevant       — retrieved documents are relevant to the question
- retrieval.relevant   — retrieved documents are relevant to the question
- answer.accurate      — answer is based on retrieved documents and factually accurate
- answer.complete      — answer fully covers all parts of the question
- citation.cited       — key facts all have [[ref:xxx]] citation markers
- e2e.user_satisfied   — end-to-end answer satisfies user needs
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agently import Agently
from dotenv import find_dotenv, load_dotenv


EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS_PATH = EVAL_DIR / "SETTINGS.yaml"
PROMPT_PATH = EVAL_DIR / "prompts" / "semantic_judge.yaml"
LEVELS = {"pass", "fail", "unknown"}


def flatten_rules(
    stage_rules: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    """Flatten the stage-grouped YAML rules into judge input.

    Only owner=model rules are kept, for the judge agent to evaluate.
    """

    return [
        {
            "stage": stage,
            "rule_id": str(rule["rule_id"]),
            "description": str(rule["description"]),
        }
        for stage, rules in stage_rules.items()
        for rule in rules
        if rule.get("owner", "model") == "model"
    ]


def _unknown(rule: dict[str, str], reason: str) -> dict[str, object]:
    """Build one unknown verdict row."""

    return {
        **rule,
        "level": "unknown",
        "evidence": [],
        "reason": reason,
    }


def normalize_verdicts(
    payload: dict[str, Any],
    rules: list[dict[str, str]],
) -> list[dict[str, object]]:
    """Validate judge return in rule order; missing or invalid items are recorded as unknown.

    Args:
        payload: The raw dict returned by the judge agent.
        rules: The model rules expanded by flatten_rules().

    Returns:
        A verdict row list of the same length as rules, each row containing
        stage, rule_id, description, level, evidence, reason.
    """

    returned = payload.get("verdicts", [])
    if not isinstance(returned, list):
        return [_unknown(rule, "judge returned verdicts is not a list") for rule in rules]

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in returned:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("stage", "")), str(item.get("rule_id", "")))
        grouped.setdefault(key, []).append(item)

    normalized: list[dict[str, object]] = []
    for rule in rules:
        key = (rule["stage"], rule["rule_id"])
        matches = grouped.get(key, [])
        if not matches:
            normalized.append(_unknown(rule, "judge did not return this rule"))
            continue
        if len(matches) > 1:
            normalized.append(_unknown(rule, "judge returned this rule multiple times"))
            continue

        item = matches[0]
        level = str(item.get("level", ""))
        if level not in LEVELS:
            normalized.append(_unknown(rule, "level must be pass, fail, or unknown"))
            continue
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            evidence = []
        normalized.append(
            {
                **rule,
                "level": level,
                "evidence": [str(value) for value in evidence],
                "reason": str(item.get("reason", "")).strip() or "judge gave no reason",
            }
        )
    return normalized


async def judge_run(
    *,
    case: dict[str, Any],
    case_rules: dict[str, Any],
    stage_rules: dict[str, list[dict[str, str]]],
    candidate_run: dict[str, Any],
    settings_path: Path = DEFAULT_SETTINGS_PATH,
) -> list[dict[str, object]]:
    """Complete model-level semantic evaluation for one Insurance RAG Agent run.

    Use an isolated Agently Agent + SETTINGS.yaml to load the judge prompt
    and perform semantic quality assessment of the answer, citations, and
    retrieval results in candidate_run.

    Args:
        case: Evaluation case dict (question, expected_answer, expected_refs, ...).
        case_rules: The case-specific rules.
        stage_rules: All rules grouped by stage from rules.yaml.
        candidate_run: The run-result dict of InsuranceAgent.query().
        settings_path: Path to the judge model's SETTINGS.yaml.

    Returns:
        A verdict row list of the same length as flatten_rules().
    """

    rules = flatten_rules(stage_rules)
    try:
        load_dotenv(find_dotenv(usecwd=True))
        Agently.load_settings(
            "yaml_file",
            str(settings_path),
            auto_load_env=True,
            raise_empty=True,
        )
        result = await (
            Agently.create_agent(name="insurance-eval-judge")
            .load_yaml_prompt(
                PROMPT_PATH,
                mappings={
                    "question": case.get("question", ""),
                    "expected_answer": case.get("expected_answer", ""),
                    "expected_refs": case.get("expected_refs", []),
                    "business_boundary": case.get("context_dependency", ""),
                    "case_rules": case_rules,
                    "evaluation_rules": rules,
                    "candidate_run": candidate_run,
                },
            )
            .create_execution()
            .async_start()
        )
    except Exception as exc:
        reason = f"judge request failed: {type(exc).__name__}: {exc}"
        return [_unknown(rule, reason) for rule in rules]
    return normalize_verdicts(dict(result), rules)


__all__ = [
    "DEFAULT_SETTINGS_PATH",
    "PROMPT_PATH",
    "flatten_rules",
    "judge_run",
    "normalize_verdicts",
]

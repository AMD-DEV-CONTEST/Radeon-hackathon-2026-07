from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator


def load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_three_cases_and_twelve_balanced_questions_are_frozen():
    cases = load("experiments/fixtures/cases.json")["cases"]
    questions = load("experiments/configs/evaluation_questions.json")["questions"]
    assert [case["scenario_id"] for case in cases] == ["demo_a", "demo_b", "demo_c"]
    assert len(questions) == 12
    assert Counter(item["category"] for item in questions) == {
        "vehicle": 3,
        "liability": 3,
        "rights": 3,
        "evidence": 3,
    }
    assert all(item["expected_document_ids"] for item in questions)
    assert all(item["retrieval_query"] for item in questions)
    assert all(
        item["retrieval_query"] != item["question"] for item in questions
    )


def test_grid_and_prompt_variants_match_experiment_contract():
    grid = load("experiments/configs/rag_grid.json")
    prompts = load("experiments/configs/liability_prompts.json")["prompts"]
    assert grid["retrieval_top_k"] == [4, 8, 12]
    assert grid["rerank_keep"] == [3, 5]
    assert set(prompts) == {"A", "B"}
    assert "证据" in prompts["B"]["system"]
    assert "不确定" in prompts["B"]["system"]


def test_sparse_feedback_sample_contract():
    schema = load("experiments/configs/sparse_feedback.schema.json")
    Draft202012Validator.check_schema(schema)
    example = {
        "case_id": "CASE-X",
        "question_id": "LIA-01",
        "answer_A": "A",
        "answer_B": "B",
        "preferred": "B",
        "reason": "证据引用更完整",
        "missing_evidence": ["路口监控"],
        "unsupported_claim": [],
        "risk_level": "low",
    }
    Draft202012Validator(schema).validate(example)

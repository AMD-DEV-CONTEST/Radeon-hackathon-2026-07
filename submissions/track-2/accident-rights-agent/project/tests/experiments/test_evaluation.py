from __future__ import annotations

import json

from experiments.memory.evaluation import evaluate_answer
from experiments.sparse_feedback.models import SparseFeedbackRecord
from experiments.sparse_feedback.prompt_ab import _feedback_record


def test_answer_evaluator_fails_closed_on_unsupported_id_and_risk_language():
    content = json.dumps(
        {
            "answer": "一定主责",
            "fact_ids": ["FACT-UNKNOWN"],
            "evidence_ids": ["NODE-OK"],
            "law_ids": ["LAW-OK"],
            "liability_hypotheses": ["H1", "H2"],
            "missing_evidence": [],
            "uncertainty": "仍需复核",
            "approval_status": "pending",
        },
        ensure_ascii=False,
    )
    result = evaluate_answer(
        content,
        allowed_fact_ids={"FACT-OK"},
        allowed_evidence_ids={"NODE-OK"},
        allowed_law_ids={"LAW-OK"},
        uncertainty_required=True,
    )
    assert result["verifier_pass"] is False
    assert result["unsupported_ids"]["fact_ids"] == ["FACT-UNKNOWN"]
    assert result["risk_markers"] == ["一定主责"]


def test_sparse_feedback_model_has_no_training_payload():
    record = SparseFeedbackRecord.model_validate(
        {
            "case_id": "CASE-X",
            "question_id": "LIA-03",
            "answer_A": "A",
            "answer_B": "B",
            "preferred": "B",
            "reason": "B 保留不确定性",
            "missing_evidence": [],
            "unsupported_claim": [],
            "risk_level": "low",
        }
    )
    assert "training" not in record.model_dump()
    assert "lora" not in record.model_dump()


def test_simulated_review_flags_case_specific_unsupported_claims():
    def result(content: str):
        return {
            "content": content,
            "quality": {
                "quality_score": 100.0,
                "unsupported_ids": {
                    "fact_ids": [],
                    "evidence_ids": [],
                    "law_ids": [],
                },
                "risk_markers": [],
                "verifier_pass": True,
                "payload": {"missing_evidence": []},
            },
        }

    record = _feedback_record(
        {"case_id": "CASE-B", "scenario_id": "demo_b"},
        {"A": result("非机动车逆行为主因"), "B": result("现有证据不足")},
    )
    assert record.preferred.value == "B"
    assert record.risk_level.value == "high"
    assert "逆行" in record.unsupported_claim[0]

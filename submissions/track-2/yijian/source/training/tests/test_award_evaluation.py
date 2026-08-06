# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


TRAINING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING_ROOT))

import award_evaluation as evaluation  # noqa: E402


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_formal_case_minimums_are_materialized(tmp_path: Path) -> None:
    manifest = evaluation.build_cases(tmp_path, [])
    assert manifest["counts"] == {"structureSafety": 220, "failurePrivacy": 24, "unseen": 0}
    assert manifest["gates"]["structureSafetyAtLeast200"] is True
    assert manifest["gates"]["failurePrivacyAtLeast20"] is True
    assert manifest["passed"] is False
    rows = evaluation.read_jsonl(tmp_path / "structure_safety.jsonl")
    categories = {}
    for row in rows:
        categories[row["category"]] = categories.get(row["category"], 0) + 1
    assert categories == {
        "task_decomposition": 60,
        "rag_source_chain": 40,
        "memory_consent": 40,
        "multi_turn": 40,
        "evidence_safety": 40,
    }


def test_blind_pack_and_scoring_gate(tmp_path: Path) -> None:
    questions = tmp_path / "questions.jsonl"
    baseline = tmp_path / "baseline.jsonl"
    lora = tmp_path / "lora.jsonl"
    current = tmp_path / "current.jsonl"
    rows = [{"id": f"case-{i:02d}", "question": f"问题{i}"} for i in range(30)]
    write_jsonl(questions, rows)
    for path, prefix in ((baseline, "基线"), (lora, "LoRA"), (current, "27B")):
        write_jsonl(path, [{"caseId": row["id"], "answer": f"{prefix}回答{index}"} for index, row in enumerate(rows)])
    html_path = tmp_path / "blind.html"
    key_path = tmp_path / "key.json"
    pack = evaluation.build_blind_pack(
        baseline=baseline, lora=lora, current=current, questions=questions,
        output_html=html_path, output_key=key_path,
    )
    html = html_path.read_text(encoding="utf-8")
    assert 'id="progress"' in html
    assert "completed()!==expected" in html
    assert "全部完成后导出评分" in html
    key = json.loads(key_path.read_text(encoding="utf-8"))
    score_for = {"baseline14": 3, "lora14": 5, "current27": 4}
    draft = {
        "schemaVersion": evaluation.BLIND_DRAFT_SCHEMA,
        "status": "human_scored",
        "packSha256": pack["packSha256"],
        "records": [
            {
                "caseId": row["caseId"],
                "alias": row["alias"],
                "evidence": score_for[row["model"]],
                "depth": score_for[row["model"]],
                "actionability": score_for[row["model"]],
                "severe": row["model"] == "baseline14",
            }
            for row in key["mappings"]
        ],
    }
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    result = evaluation.score_blind(draft_path, key_path, tmp_path / "result.json")
    assert result["passed"] is True
    assert result["loraUplift"] >= .20
    assert result["severeContradictions"]["baseline14"] == 30


def test_blind_pack_accepts_vllm_report_outputs(tmp_path: Path) -> None:
    questions = tmp_path / "questions.jsonl"
    rows = [{"id": f"case-{i:02d}", "question": f"问题{i}"} for i in range(30)]
    write_jsonl(questions, rows)
    paths = []
    for name in ("baseline", "lora", "current"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({
            "schemaVersion": "yijian-vllm-evaluation-output-v1",
            "results": [
                {"caseId": row["id"], "answer": f"{name}-{index}", "succeeded": True}
                for index, row in enumerate(rows)
            ],
        }, ensure_ascii=False), encoding="utf-8")
        paths.append(path)
    pack = evaluation.build_blind_pack(
        baseline=paths[0], lora=paths[1], current=paths[2], questions=questions,
        output_html=tmp_path / "blind.html", output_key=tmp_path / "key.json",
    )
    assert pack["cases"] == 30


def test_ai_assisted_blind_scoring_requires_all_human_confirmations(tmp_path: Path) -> None:
    mappings = [
        {"caseId": f"case-{index:02d}", "alias": alias, "model": model}
        for index in range(30)
        for alias, model in zip(("A", "B", "C"), ("baseline14", "lora14", "current27"))
    ]
    key = {"schemaVersion": evaluation.BLIND_KEY_SCHEMA, "packSha256": "a" * 64, "mappings": mappings}
    key_path = tmp_path / "key.json"
    key_path.write_text(json.dumps(key), encoding="utf-8")
    draft = {
        "schemaVersion": evaluation.BLIND_DRAFT_SCHEMA,
        "status": "human_scored",
        "packSha256": "a" * 64,
        "assistance": {
            "type": "ai_prescore",
            "schemaVersion": "yijian-ai-blind-prescore-v1",
            "humanFinalDecision": True,
        },
        "humanConfirmedCases": [f"case-{index:02d}" for index in range(29)],
        "records": [
            {
                "caseId": row["caseId"],
                "alias": row["alias"],
                "evidence": 4,
                "depth": 4,
                "actionability": 4,
                "severe": False,
            }
            for row in mappings
        ],
    }
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    with pytest.raises(ValueError, match="必须人工确认全部30题"):
        evaluation.score_blind(draft_path, key_path, tmp_path / "result.json")
    draft["humanConfirmedCases"].append("case-29")
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    result = evaluation.score_blind(draft_path, key_path, tmp_path / "result.json")
    assert result["means"] == {"baseline14": 4.0, "lora14": 4.0, "current27": 4.0}

# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))

import agent_multitask_corpus as corpus


def creator_row(
    case_id: str,
    video_id: str,
    position_hash: str,
    board_fingerprint: str = "",
) -> dict:
    evidence = {
        "positionHash": position_hash,
        "boardFingerprint": board_fingerprint,
        "questionTarget": "actual",
        "pedagogy": {"mechanism": ["先核对强制应手"], "boundary": "不外推整盘。"},
        "katagoFacts": {
            "trustedArtifactRef": {"artifactSha256": "c" * 64},
        },
    }
    return {
        "messages": [
            {"role": "system", "content": "只依据证据回答。"},
            {
                "role": "user",
                "content": "证据：" + json.dumps(evidence, ensure_ascii=False)
                + f"\n问题：为什么实战手不好？案例 {case_id}",
            },
            {"role": "assistant", "content": '{"answer":"错过共同急点。","followUps":["继续看具体次序吗？"]}'},
        ],
        "metadata": {
            "id": case_id,
            "target": "actual",
            "license": "creator-authorized",
            "commercialDeployment": False,
            "splitGroup": f"video:{video_id}",
            "videoId": video_id,
            "authorizationId": "auth-1",
            "reviewApprovalId": f"approval-{case_id}",
            "reviewerId": "reviewer-1",
            "sourceChainBindingSha256": "a" * 64,
            "reviewInputHashes": {"unitContentSha256": "b" * 64},
        },
    }


def task_row(
    source_type: str,
    task_type: str,
    index: int,
    *,
    split: str = "train",
    source_case_id: str | None = None,
) -> dict:
    source_case_id = source_case_id or f"{source_type}-{index}"
    assistant = "回答"
    if task_type == "planner":
        assistant = json.dumps({
            "schemaVersion": "agent-plan-v1",
            "questionTarget": "position",
            "steps": [{"tool": "inspect_position", "target": "position"}],
            "focus": ["evidence_boundary"],
            "confidence": "high",
        }, ensure_ascii=False)
    return {
        "messages": [
            {"role": "system", "content": "系统"},
            {"role": "user", "content": f"问题 {source_case_id}"},
            {"role": "assistant", "content": assistant},
        ],
        "metadata": {
            "sourceCaseId": source_case_id,
            "sourceType": source_type,
            "taskType": task_type,
            "split": split,
            "splitGroup": f"{source_type}:{split}:{index}",
            "sourceIds": (
                ["yijian-original-pedagogy-v2"]
                if source_type == "project_original"
                else ["qijing-compare-strength"]
            ),
            "license": (
                "project-original"
                if source_type == "project_original" else "public-domain"
            ),
        },
    }


def balanced_rows() -> tuple[list[dict], list[dict]]:
    project = []
    for index in range(5):
        project.append(task_row("project_original", "planner", index))
    for index in range(3):
        project.append(task_row("project_original", "answer", 10 + index))
    for index in range(4):
        project.append(task_row("project_original", "followup", 20 + index))
    for index in range(2):
        project.append(task_row("project_original", "memory_privacy", 30 + index))
    public = [
        task_row("public_domain", "answer", 40 + index)
        for index in range(4)
    ]
    return project, public


def test_compile_corpus_builds_three_way_isolated_multitask_rows():
    project, public = balanced_rows()
    by_split, manifest = corpus.compile_corpus(
        creator_train=[creator_row("creator-train", "BV-train", "1" * 64)],
        creator_dev=[creator_row("creator-dev", "BV-dev", "2" * 64)],
        creator_test=[creator_row("creator-test", "BV-test", "3" * 64)],
        project_rows=project,
        public_rows=public,
        minimum_train_rows=20,
        minimum_creator_train_cases=1,
        minimum_creator_holdout_cases=2,
        minimum_project_cases=1,
        minimum_public_cases=1,
    )
    assert manifest["passed"] is True
    assert manifest["counts"] == {"dev": 3, "test": 3, "train": 21}
    creator_tasks = [
        row["metadata"]["taskType"] for row in by_split["train"]
        if row["metadata"]["sourceType"] == "creator_authorized"
    ]
    assert creator_tasks == ["answer", "planner", "followup"]


def test_compile_corpus_rejects_position_leakage():
    project, public = balanced_rows()
    with pytest.raises(corpus.CorpusError, match="泄漏"):
        corpus.compile_corpus(
            creator_train=[creator_row("creator-train", "BV-train", "1" * 64)],
            creator_dev=[creator_row("creator-dev", "BV-dev", "1" * 64)],
            creator_test=[creator_row("creator-test", "BV-test", "3" * 64)],
            project_rows=project,
            public_rows=public,
            minimum_train_rows=1,
            minimum_creator_train_cases=1,
            minimum_creator_holdout_cases=1,
            minimum_project_cases=1,
            minimum_public_cases=1,
        )


def test_compile_corpus_rejects_symmetric_board_fingerprint_leakage():
    project, public = balanced_rows()
    with pytest.raises(corpus.CorpusError, match="boardFingerprint"):
        corpus.compile_corpus(
            creator_train=[creator_row(
                "creator-train", "BV-train", "1" * 64, "f" * 64
            )],
            creator_dev=[creator_row(
                "creator-dev", "BV-dev", "2" * 64, "f" * 64
            )],
            creator_test=[creator_row(
                "creator-test", "BV-test", "3" * 64, "e" * 64
            )],
            project_rows=project,
            public_rows=public,
            minimum_train_rows=1,
            minimum_creator_train_cases=1,
            minimum_creator_holdout_cases=1,
            minimum_project_cases=1,
            minimum_public_cases=1,
        )


def test_project_planner_must_pass_agent_protocol():
    row = task_row("project_original", "planner", 1)
    row["messages"][-1]["content"] = '{"tool":"shell"}'
    with pytest.raises(corpus.CorpusError, match="Planner金标不合法"):
        corpus._project_rows([row], "project_original")


def test_creator_projection_removes_bulk_artifacts_but_preserves_signed_answer():
    row = creator_row("creator-compact", "BV-compact", "1" * 64)
    evidence = corpus._evidence_from_creator(row)
    evidence["katagoFacts"]["analysisArtifact"] = {
        "engine": {"binarySha256": "e" * 64},
        "candidates": [{"move": "Q16", "pv": ["Q16", "D4"]}],
    }
    row["messages"][1]["content"] = (
        "证据：" + json.dumps(evidence, ensure_ascii=False)
        + "\n问题：为什么实战手不好？案例creator-compact"
    )
    projected = corpus._creator_rows([row], "train")[0]
    assert projected["messages"][-1] == row["messages"][-1]
    assert "binarySha256" not in projected["messages"][1]["content"]
    assert "Q16" in projected["messages"][1]["content"]
    assert projected["metadata"]["promptProjection"] == "creator-evidence-compact-v1"

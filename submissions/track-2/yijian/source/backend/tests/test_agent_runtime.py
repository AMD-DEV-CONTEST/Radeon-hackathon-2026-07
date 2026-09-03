# -*- coding: utf-8 -*-
"""Agent 规划、检索、显式记忆与安全轨迹契约测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import agent_runtime


POSITION = {
    "turn": 5,
    "phase": "布局",
    "toPlay": "白",
    "moveCandidates": {
        "sameMove": False,
        "actual": {
            "move": "K4",
            "region": {"label": "中央下方"},
            "rules": {"legal": True},
            "heuristics": {
                "role": "串联下边框架",
                "openingStrategy": {"strategicType": "side_framework_bridge"},
            },
        },
        "best": {
            "move": "C17",
            "region": {"label": "左边上方"},
            "rules": {"legal": True},
            "heuristics": {
                "role": "争夺角部行棋次序",
                "openingStrategy": {"strategicType": "corner_approach"},
            },
        },
    },
}
EVIDENCE = {
    "source": "katago",
    "demo": False,
    "bestMove": "C17",
    "playerWinrateDelta": -0.049,
    "variationEvidence": {
        "status": "ready",
        "schemaVersion": "variation-evidence-v3-group-role-semantics",
        "branches": {"best": {"move": "C17"}},
        "claimBoundary": {"notDirectlyProven": ["thickness"]},
    },
}


def test_validate_plan_rejects_coordinates_numbers_and_unknown_fields():
    valid = {
        "schemaVersion": "agent-plan-v1",
        "questionTarget": "best",
        "steps": [{"tool": "compare_moves", "target": "best"}],
        "focus": ["opening_priority", "evidence_boundary"],
        "confidence": "high",
    }
    assert agent_runtime.validate_plan(valid) == valid
    with pytest.raises(agent_runtime.AgentProtocolError, match="字段"):
        agent_runtime.validate_plan({**valid, "reasoning": "hidden"})
    with pytest.raises(agent_runtime.AgentProtocolError, match="坐标或数字"):
        agent_runtime.validate_plan({
            **valid,
            "steps": [{"tool": "compare_moves", "target": "C17"}],
        })


def test_deterministic_plan_routes_comparison_variation_and_principles():
    plan = agent_runtime.deterministic_plan(
        "为什么实战手不好？结合后续变化说明厚薄和先手次序。",
        "actual",
    )
    assert plan["schemaVersion"] == "agent-plan-v1"
    assert len(plan["steps"]) <= 3
    assert plan["steps"][0]["tool"] == "compare_moves"
    assert agent_runtime.needs_variation_evidence(plan) is True
    assert "move_order" in plan["focus"]


def test_execute_plan_separates_evidence_and_returns_safe_trace():
    plan = {
        "schemaVersion": "agent-plan-v1",
        "questionTarget": "comparison",
        "steps": [
            {"tool": "compare_moves", "target": "comparison"},
            {"tool": "analyze_variations", "target": "comparison"},
            {"tool": "retrieve_principles", "target": "comparison"},
        ],
        "focus": ["opening_priority", "evidence_boundary"],
        "confidence": "high",
    }
    output = agent_runtime.execute_plan(
        plan,
        question="为什么角部争夺优先于下边框架？",
        position=POSITION,
        evidence=EVIDENCE,
    )
    assert output["schemaVersion"] == "agent-tool-results-v1"
    assert [item["tool"] for item in output["items"]] == [
        "compare_moves", "analyze_variations", "retrieve_principles",
    ]
    assert output["items"][0]["result"]["analysis"]["source"] == "katago"
    assert output["items"][2]["result"]["sourceLayer"] == "retrieved_heuristics"
    trace = output["agentTrace"]
    assert trace["schemaVersion"] == "agent-trace-v1"
    assert all("result" not in item for item in trace["items"])
    assert all(len(item["evidenceHash"]) == 64 for item in trace["items"])


def test_retrieval_uses_local_fts5_bm25_and_keeps_source_metadata(tmp_path):
    database = tmp_path / "mentor.db"
    result = agent_runtime.retrieve_principles(
        "布局时为什么要先比较双方弱棋和角部方向？",
        "comparison",
        POSITION,
        database=database,
    )
    assert result["backend"] == "sqlite_fts5_bm25"
    assert result["items"]
    first = result["items"][0]
    assert first["sourceId"]
    assert first["title"]
    assert first["tags"]
    assert len(first["textHash"]) == 64
    assert first["confidence"] == "heuristic"


def test_memory_requires_explicit_enable_and_clear(tmp_path):
    database = tmp_path / "mentor.db"
    session = agent_runtime.create_session(database)
    value = {
        "sessionId": session["sessionId"],
        "gameId": "game-1",
        "turn": 5,
        "contextId": "a" * 64,
        "positionHash": "b" * 64,
        "evidenceHash": "c" * 64,
        "title": "布局先看角部急场",
        "summary": "比较边上扩张前，先检查未完成的角部争夺。",
        "tags": ["布局", "角部", "次序"],
    }
    with pytest.raises(agent_runtime.AgentProtocolError, match="尚未开启"):
        agent_runtime.save_lesson(database, value)
    agent_runtime.set_memory_enabled(database, session["sessionId"], True)
    saved = agent_runtime.save_lesson(database, value)
    assert saved["saved"] is True
    recalled = agent_runtime.recall_lessons(
        database, session["sessionId"], "上次布局角部次序的问题"
    )
    assert recalled and recalled[0]["title"] == value["title"]
    deleted = agent_runtime.delete_lesson(
        database, session["sessionId"], saved["id"]
    )
    assert deleted["deleted"] is True
    assert agent_runtime.list_lessons(database, session["sessionId"])["items"] == []
    agent_runtime.save_lesson(database, value)
    cleared = agent_runtime.clear_session(database, session["sessionId"])
    assert cleared["deleted"] == 1
    assert agent_runtime.list_lessons(database, session["sessionId"])["items"] == []


def test_remember_tool_never_writes_automatically(tmp_path):
    database = tmp_path / "mentor.db"
    session = agent_runtime.create_session(database, memory_enabled=True)
    plan = {
        "schemaVersion": "agent-plan-v1",
        "questionTarget": "position",
        "steps": [{"tool": "remember_lesson", "target": "position"}],
        "focus": ["evidence_boundary"],
        "confidence": "medium",
    }
    output = agent_runtime.execute_plan(
        plan,
        question="记住这条",
        position=POSITION,
        evidence=EVIDENCE,
        memory_db=database,
        session_id=session["sessionId"],
        memory_enabled=True,
    )
    assert output["items"][0]["status"] == "approval_required"
    assert agent_runtime.list_lessons(database, session["sessionId"])["items"] == []

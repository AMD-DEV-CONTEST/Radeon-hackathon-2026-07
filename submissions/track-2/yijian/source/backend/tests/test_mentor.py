# -*- coding: utf-8 -*-
"""双模型导师协议、失败降级与反馈闭环回归测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import coach
import classical_go
import mentor


EVIDENCE = {
    "source": "katago",
    "demo": False,
    "winrate": 52.9,
    "scoreLead": .6,
    "bestMove": "D10",
    "recommendations": [{"move": "D10", "visits": 64}],
}
PURPOSE = {
    "title": "第 28 手 白 D10 的作用",
    "region": "左边中腹",
    "role": "制造接触和压力",
    "ownNearby": 2,
    "enemyNearby": 2,
    "captured": 0,
    "confidence": "heuristic",
    "evidenceSummary": "从 KataGo 证据看，本手后黑胜率下降 0.6 个百分点。",
    "nextFocus": "比较后续先手和地盘转换。",
}
DUAL_POSITION = {
    "turn": 5,
    "toPlay": "白",
    "phase": "布局",
    "move": "K4",
    "moveCandidates": {
        "sameMove": False,
        "actual": {
            "move": "K4",
            "player": "B",
            "region": {"label": "中央下方"},
            "geometry": {
                "zone": "side", "zoneLabel": "边上", "sectorLabel": "下边",
                "confidence": "deterministic",
            },
            "heuristics": {
                "role": "靠近己方棋块补强",
                "confidence": "heuristic",
                "openingStrategy": {
                    "strategicType": "side_framework_bridge",
                    "development": "位于同侧两翼己子之间，扩张并串联宽阔的边上框架",
                    "priorityPrinciple": "布局通常先看角部争夺，再看边上扩张",
                    "framework": {
                        "sameSideFriendlyStones": 2,
                        "spansBothFlanks": True,
                        "formation": "three_star_style",
                        "description": "落点与同侧两翼己子构成三连星式宽框架",
                    },
                },
            },
        },
        "best": {
            "move": "C17",
            "player": "B",
            "region": {"label": "左边上方"},
            "geometry": {
                "zone": "corner", "zoneLabel": "角部", "sectorLabel": "左上角",
                "confidence": "deterministic",
            },
            "heuristics": {
                "role": "进入角部要点，具体效果需要变化验证",
                "confidence": "heuristic",
                "openingStrategy": {
                    "strategicType": "corner_approach",
                    "development": "接近对方已有角部棋子，主动争夺角上的行棋次序",
                    "priorityPrinciple": "布局通常先看角部争夺，再看边上扩张",
                    "cornerContext": {
                        "ownStones": 1,
                        "opponentStones": 1,
                        "description": "对方已在该角落子，当前着法属于角部争夺而非抢占空角",
                    },
                },
            },
        },
    },
}


def test_baseline_mentor_keeps_engine_evidence():
    result = mentor.explain(
        "baseline", coach.DEFAULT_SETTINGS,
        {"turn": 28, "toPlay": "黑"}, EVIDENCE, PURPOSE,
    )
    assert result["primary"]["source"] == "baseline"
    assert result["evidence"] == EVIDENCE
    assert "52.9%" in result["evidenceLine"]
    assert result["primary"]["title"] == PURPOSE["title"]
    assert any("启发式判断" in text for text in result["primary"]["paragraphs"])


def test_agent_planner_defaults_to_safe_server_plan(monkeypatch):
    monkeypatch.delenv("YIJIAN_AGENT_PLANNER_ENABLED", raising=False)
    prepared = mentor.plan_chat(
        "cloud", "为什么实战手不好？", [], DUAL_POSITION, {
            **EVIDENCE, "bestMove": "C17",
        }, "actual",
    )
    assert prepared["planSource"] == "server_deterministic"
    assert prepared["questionTarget"]["kind"] == "actual"
    assert any(
        step["tool"] == "analyze_variations"
        for step in prepared["plan"]["steps"]
    )


def test_agent_planner_invalid_model_output_falls_back(monkeypatch):
    monkeypatch.setenv("YIJIAN_AGENT_PLANNER_ENABLED", "1")

    def fail(*_args, **_kwargs):
        raise mentor.MentorProviderError("非法规划")

    monkeypatch.setattr(mentor, "_call_plan_provider", fail)
    prepared = mentor.plan_chat(
        "cloud", "比较实战和首选。", [], DUAL_POSITION, EVIDENCE,
        "comparison",
    )
    assert prepared["planSource"] == "server_deterministic"
    assert "非法规划" in prepared["planError"]
    assert prepared["plan"]["questionTarget"] == "comparison"


def test_conceptual_questions_override_stale_move_button_intent():
    evidence = {**EVIDENCE, "bestMove": "C17"}
    term_target = mentor._question_target(
        "什么是缓气劫？和普通劫有什么区别？",
        DUAL_POSITION,
        evidence,
        "best",
    )
    opening_target = mentor._question_target(
        "为什么三连星没有点三三好？",
        DUAL_POSITION,
        evidence,
        "actual",
    )

    assert term_target["kind"] == "position"
    assert term_target["source"] == "conceptual_question_router"
    assert term_target["conceptualKind"] == "ko_definition"
    assert opening_target["kind"] == "position"
    assert opening_target["conceptualKind"] == "opening_tradeoff"


def test_conceptual_questions_answer_from_terminology_not_current_move_template():
    result = mentor.chat(
        "cloud",
        "什么是缓气劫？和普通劫有什么区别？",
        [],
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        {**EVIDENCE, "bestMove": "C17"},
        PURPOSE,
        "best",
    )

    assert result["degraded"] is False
    assert result["source"] == "terminology"
    assert result["answerMode"] == "terminology_reference"
    assert "缓气劫｜" in result["answer"]
    assert "普通劫的区别" in result["answer"]
    assert "AI 首选" not in result["answer"]
    assert "C17" not in result["answer"]


def test_opening_concept_answer_does_not_claim_a_current_best_move():
    result = mentor.chat(
        "cloud",
        "为什么三连星没有点三三好？",
        [],
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        {**EVIDENCE, "bestMove": "C17"},
        PURPOSE,
        "best",
    )

    assert result["source"] == "terminology"
    assert "三连星并不天然不如点三三" in result["answer"]
    assert "谁绝对更好" in result["answer"]
    assert "AI 首选" not in result["answer"]


def test_local_model_failure_degrades_without_blocking(monkeypatch):
    def fail(*_args, **_kwargs):
        raise mentor.MentorProviderError("本地模型尚未启动")

    monkeypatch.setattr(mentor, "_call_provider", fail)
    result = mentor.explain(
        "local", coach.DEFAULT_SETTINGS,
        {"turn": 28, "toPlay": "黑"}, EVIDENCE, PURPOSE,
    )
    assert result["degraded"] is True
    assert result["primary"]["source"] == "baseline"
    assert "本地模型尚未启动" in result["errors"]["local"]


def test_compare_mode_returns_both_outputs(monkeypatch):
    def fake(provider, *_args, **_kwargs):
        return {
            "source": provider,
            "sourceLabel": provider,
            "model": f"fake-{provider}",
            "latencyMs": 12,
            "title": PURPOSE["title"],
            "paragraphs": [f"{provider}-目的", f"{provider}-得失", f"{provider}-关注"],
        }

    monkeypatch.setattr(mentor, "_call_provider", fake)
    result = mentor.explain(
        "compare", coach.DEFAULT_SETTINGS,
        {"turn": 28, "toPlay": "黑"}, EVIDENCE, PURPOSE,
    )
    assert result["degraded"] is False
    assert set(result["results"]) == {"baseline", "local", "cloud"}
    assert result["primary"]["source"] == "local"


def test_single_provider_uses_matching_cached_narrative(monkeypatch):
    def must_not_call(*_args, **_kwargs):
        raise AssertionError("cache hit must not call the model")

    cached = {
        "source": "cloud",
        "sourceLabel": "云端增强老师",
        "model": "Yijian-Classical-Go",
        "latencyMs": 731,
        "title": PURPOSE["title"],
        "paragraphs": ["目的", "取舍", "下一步"],
        "schemaVersion": "report-narrative-v1",
    }
    monkeypatch.setattr(mentor, "_call_provider", must_not_call)
    result = mentor.explain(
        "cloud",
        coach.DEFAULT_SETTINGS,
        {"turn": 28, "toPlay": "黑"},
        EVIDENCE,
        PURPOSE,
        cached,
    )
    assert result["cached"] is True
    assert result["primary"]["cached"] is True
    assert result["primary"]["paragraphs"] == ["目的", "取舍", "下一步"]


def test_cached_narrative_never_crosses_provider(monkeypatch):
    def fake(provider, *_args, **_kwargs):
        return {
            "source": provider,
            "sourceLabel": provider,
            "model": "fresh",
            "latencyMs": 12,
            "title": PURPOSE["title"],
            "paragraphs": ["fresh-purpose", "fresh-tradeoff", "fresh-next"],
        }

    monkeypatch.setattr(mentor, "_call_provider", fake)
    result = mentor.explain(
        "local",
        coach.DEFAULT_SETTINGS,
        {"turn": 28, "toPlay": "黑"},
        EVIDENCE,
        PURPOSE,
        {
            "source": "cloud",
            "paragraphs": ["stale"],
            "schemaVersion": "report-narrative-v1",
        },
    )
    assert result.get("cached") is not True
    assert result["primary"]["model"] == "fresh"


def test_model_numeric_claims_are_replaced_by_deterministic_copy():
    sanitized = mentor._remove_numeric_claims({
        "purpose": "这手关联2个棋群",
        "tradeoff": "胜率下降99个百分点",
        "nextFocus": "继续看第3手",
    }, PURPOSE, EVIDENCE)
    assert sanitized["purpose"] == PURPOSE["role"]
    assert "KataGo 证据" in sanitized["tradeoff"]
    assert sanitized["nextFocus"] == PURPOSE["nextFocus"]
    assert not any(char.isdigit() for text in sanitized.values() for char in text)
    mock_evidence = {**EVIDENCE, "source": "mock", "demo": True}
    mock_copy = mentor._remove_numeric_claims({
        "purpose": "关联2个棋群",
        "tradeoff": "下降99个百分点",
        "nextFocus": "继续看第3手",
    }, PURPOSE, mock_evidence)
    assert "演示分析证据" in mock_copy["tradeoff"]
    assert "KataGo" not in mock_copy["tradeoff"]
    mock_answer = mentor._chat_fallback(
        "推荐变化是什么？", mock_evidence, PURPOSE
    )
    assert "演示分析首选" in mock_answer
    assert "KataGo" not in mock_answer


def test_unsupported_ko_or_joseki_language_is_replaced():
    sanitized = mentor._remove_unsupported_domain_claims(
        {
            "purpose": "这手先计算劫材够不够。",
            "tradeoff": "把伪威胁计入总账。",
            "nextFocus": "背熟这个定式分支。",
        },
        {"turn": 28, "phase": "中盘"},
        EVIDENCE,
        PURPOSE,
    )
    assert sanitized["purpose"] == PURPOSE["role"]
    assert "权威证据" in sanitized["tradeoff"]
    assert sanitized["nextFocus"] == PURPOSE["nextFocus"]


def test_model_placeholder_copy_is_rejected():
    copied = """{"purpose":"这一手的目的与关联棋群", "tradeoff":"所得、代价或不确定性", "nextFocus":"下一步具体观察动作"}"""
    try:
        mentor._extract_json(copied)
    except mentor.MentorProviderError as error:
        assert "字段说明" in str(error)
    else:
        raise AssertionError("模板复述不应作为有效讲解")


def test_chat_accepts_plain_text_before_running_evidence_validators():
    parsed = mentor._chat_json(
        "结论｜这里先处理双方弱棋。\n解释｜再比较连接、切断和先手。"
    )
    assert parsed["answer"].startswith("结论｜")
    assert parsed["followUps"] == []


def test_chat_uses_model_and_returns_board_action(monkeypatch):
    def fake_chat(*_args, **_kwargs):
        return {
            "answer": "这手主要是在中央制造接触，同时限制对方外势。",
            "followUps": ["对方最强应对是什么？"],
            "source": "local",
            "sourceLabel": "本地离线老师",
            "model": "fake-local",
            "latencyMs": 23,
        }

    monkeypatch.setattr(mentor, "_call_chat_provider", fake_chat)
    result = mentor.chat(
        "local", "演示一下 AI 推荐变化", [], coach.DEFAULT_SETTINGS,
        {"turn": 28, "toPlay": "黑", "move": "D10"}, EVIDENCE, PURPOSE,
    )
    assert result["source"] == "local"
    assert result["degraded"] is False
    assert result["context"]["turn"] == 28
    assert result["actions"] == [
        {"id": "show_variation", "label": "在棋盘演示推荐变化"}
    ]


def test_chat_failure_returns_useful_deterministic_answer(monkeypatch):
    def fail(*_args, **_kwargs):
        raise mentor.MentorProviderError("本地老师未启动")

    monkeypatch.setattr(mentor, "_call_chat_provider", fail)
    result = mentor.chat(
        "local", "为什么这手不好？", [], coach.DEFAULT_SETTINGS,
        {"turn": 28, "toPlay": "黑", "move": "D10"}, EVIDENCE, PURPOSE,
    )
    assert result["source"] == "baseline"
    assert result["degraded"] is True
    assert PURPOSE["role"] in result["answer"]
    assert "本地老师未启动" in result["error"]


def test_chat_rejects_model_generated_numbers():
    copied_number = """{"answer":"胜率下降99个百分点", "followUps":[]}"""
    try:
        mentor._chat_json(copied_number)
    except mentor.MentorProviderError as error:
        assert "数值证据" in str(error)
    else:
        raise AssertionError("模型不能成为第二套数值来源")


def test_chat_allows_only_server_rule_counts_and_known_coordinates():
    position = {
        "moveCandidates": {
            "actual": {
                "move": "K6",
                "rules": {
                    "libertiesBeforeAfter": {
                        "own": [2, 3],
                        "opponent": [2, 1],
                    },
                },
            },
            "best": {"move": "L2", "rules": {"captures": 0}},
        },
    }
    passed = mentor._validate_supported_numbers(
        "K6 让己方棋块从 2→3 气，但 L2 仍是共同急点。",
        position,
    )
    assert passed["mentionedMoves"] == ["K6", "L2"]
    assert passed["mentionedRuleNumbers"] == [2.0, 3.0]
    with pytest.raises(mentor.MentorProviderError, match="未提供的规则计数"):
        mentor._validate_supported_numbers("这手让棋块增加到 9 气。", position)
    with pytest.raises(mentor.MentorProviderError, match="未提供的坐标"):
        mentor._validate_supported_numbers("下一手去 Q16。", position)


def test_chat_routes_best_move_question_and_rejects_wrong_region(monkeypatch):
    evidence = {**EVIDENCE, "bestMove": "C17"}

    def wrong_region(*_args, **_kwargs):
        return {
            "answer": "可以理解为首选在中央下方靠近己方棋块补强。",
            "followUps": [],
            "source": "local",
            "sourceLabel": "本地离线老师",
            "model": "fake-local",
            "latencyMs": 9,
        }

    monkeypatch.setattr(mentor, "_call_chat_provider", wrong_region)
    result = mentor.chat(
        "local",
        "AI 首选在哪里？",
        [],
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        evidence,
        PURPOSE,
    )

    assert result["degraded"] is True
    assert result["source"] == "baseline"
    assert "J" in result["answer"]
    assert "左上角" in result["answer"]
    assert "中央下方" not in result["answer"]
    assert "回答区域" in result["error"]
    assert result["context"]["questionTarget"]["kind"] == "best"
    assert result["context"]["questionTarget"]["move"] == "C17"
    assert result["context"]["answerValidation"]["status"] == "fallback"


def test_chat_accepts_best_move_answer_bound_to_authoritative_region(monkeypatch):
    evidence = {**EVIDENCE, "bestMove": "C17"}

    def correct_region(*_args, **_kwargs):
        return {
            "answer": (
                "结论｜AI 首选位于左边上方，先进入角部要点。\n"
                "布局价值｜角部争夺通常比单纯边上扩张优先，但这是布局启发式。\n"
                "全局对抗｜先碰触对方角部，可以争取行棋主动；实战则先发展下边框架。\n"
                "子力发展｜首选保留向两边发展的余地，实战让边上子力更连贯。\n"
                "时机判断｜实战并非坏棋，只是当前角部方向更急，仍需用变化核对。"
            ),
            "followUps": [],
            "source": "local",
            "sourceLabel": "本地离线老师",
            "model": "fake-local",
            "latencyMs": 8,
        }

    monkeypatch.setattr(mentor, "_call_chat_provider", correct_region)
    result = mentor.chat(
        "local",
        "从古典棋理看，AI 首选好在哪里？",
        [],
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        evidence,
        PURPOSE,
    )

    assert result["degraded"] is False
    assert result["answer"].startswith("结论｜AI 首选位于左边上方")
    assert "入境侵疆，常存先手" in result["answer"]
    assert result["context"]["questionTarget"]["kind"] == "best"
    validation = result["context"]["answerValidation"]
    assert validation["status"] == "passed"
    assert validation["expectedRegion"] == "左边上方"
    assert validation["mentionedRegions"] == ["中央下方", "左边上方"]
    assert validation["classicalGuidance"]["status"] == "server_appended"


def test_midgame_local_fight_rejects_opening_template_and_falls_back(monkeypatch):
    position = {
        "turn": 77,
        "phase": "中盘",
        "move": "K6",
        "moveCandidates": {
            "actual": {
                "move": "K6",
                "player": "B",
                "region": {"label": "中央下方"},
                "geometry": {"zoneLabel": "中腹", "sectorLabel": "中央"},
                "rules": {
                    "libertiesBeforeAfter": {
                        "own": [2, 3],
                        "opponent": [2, 1],
                    },
                },
                "heuristics": {
                    "role": "在局部同时承担补强与施压作用",
                    "localSituation": {
                        "scope": "local_fight",
                        "label": "局部对杀",
                        "ownNearby": 9,
                        "enemyNearby": 8,
                    },
                },
            },
            "best": {
                "move": "L2",
                "player": "B",
                "region": {"label": "中央下方"},
                "geometry": {"zoneLabel": "边上", "sectorLabel": "下边"},
                "rules": {
                    "libertiesBeforeAfter": {
                        "own": [0, 3],
                        "opponent": [2, 1],
                    },
                },
                "heuristics": {
                    "role": "靠近对方棋块施加压力",
                    "localSituation": {
                        "scope": "local_fight",
                        "label": "局部对杀",
                        "ownNearby": 5,
                        "enemyNearby": 6,
                    },
                },
                "analysis": {"pv": ["L2", "P17", "L7", "F17"]},
            },
        },
    }
    evidence = {
        **EVIDENCE,
        "bestMove": "L2",
        "source": "katago",
        "demo": False,
        "decisionRelation": {
            "actualMove": "K6",
            "bestMoveBeforeActual": "L2",
            "bestMoveAfterActual": "L2",
            "missedBestBecameOpponentBestReply": True,
            "description": "实战没有占据原首选点；落子后轮到对手时，同一坐标仍是引擎首选",
            "interpretationBoundary": "具体战术效果仍须沿推荐变化核对",
            "source": "katago_pre_post_sequence",
            "confidence": "high",
        },
    }
    position["decisionRelation"] = evidence["decisionRelation"]
    purpose = {
        **PURPOSE,
        "evidenceSummary": "KataGo 证据显示，本手造成显著损失。",
    }

    def off_scope(*_args, **_kwargs):
        return {
            "answer": "这手应该比较中腹取势和下边的发展潜力。",
            "followUps": [],
            "source": "local",
            "sourceLabel": "本地离线老师",
            "model": "fake-local",
            "latencyMs": 8,
        }

    monkeypatch.setattr(mentor, "_call_chat_provider", off_scope)
    result = mentor.chat(
        "local",
        "为什么这手不好？",
        [],
        coach.DEFAULT_SETTINGS,
        position,
        evidence,
        purpose,
        "actual",
    )

    assert result["degraded"] is True
    assert "双方共同急点" in result["answer"]
    assert "让给了对手" in result["answer"]
    assert "发展潜力" not in result["answer"]
    assert "S" in result["answer"]
    assert "J" in result["answer"]
    assert "己方相邻棋块由 2 气增至 3 气" in result["answer"]
    assert "由 2 气减至 1 气" in result["answer"]
    assert "回答偏离局部对杀证据" in result["error"]

    prompt = mentor._chat_prompt(
        "为什么这手不好？",
        coach.DEFAULT_SETTINGS,
        position,
        evidence,
        purpose,
        {"kind": "actual", "label": "实战手"},
    )
    assert '"同一急点被让给对手":true' in prompt
    assert '"显示名":"S"' in prompt
    assert '"显示名":"J"' in prompt
    assert '"坐标":"K6"' not in prompt
    assert '"坐标":"L2"' not in prompt
    assert '"己方相邻棋块气数变化":"由 2 变为 3 气"' in prompt
    assert '"对方相邻棋块气数变化":"由 2 变为 1 气"' in prompt


def test_local_fight_rejects_reversed_counts_and_vague_diagnosis():
    position = {
        "turn": 77,
        "phase": "中盘",
        "moveCandidates": {
            "actual": {
                "move": "K6",
                "heuristics": {
                    "localSituation": {
                        "scope": "local_fight",
                        "ownNearby": 9,
                        "enemyNearby": 8,
                    },
                },
            },
        },
    }
    with pytest.raises(mentor.MentorProviderError) as caught:
        mentor._validate_answer_scope(
            (
                "当前是局部对杀，应检查气、连接、切断和先手。"
                "附近己方较少、对方较近，可以参考 AI 首选。"
            ),
            "为什么这一手问题严重",
            {"kind": "actual"},
            position,
        )
    assert "附近棋子数量关系说反" in str(caught.value)


def test_ambiguous_question_uses_server_resolved_best_move_intent(monkeypatch):
    evidence = {**EVIDENCE, "bestMove": "C17"}

    def fail(*_args, **_kwargs):
        raise mentor.MentorProviderError("使用确定性回答验证目标")

    monkeypatch.setattr(mentor, "_call_chat_provider", fail)
    result = mentor.chat(
        "local",
        "为什么要外搬？",
        [],
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        evidence,
        PURPOSE,
        "best",
    )

    target = result["context"]["questionTarget"]
    assert target == {
        "kind": "best",
        "label": "AI 首选",
        "move": "C17",
        "source": "client_intent_server_resolved",
        "confidence": "high",
        "evidencePath": "facts.moveCandidates.best",
    }
    assert "J" in result["answer"]
    assert "左上角" in result["answer"]
    assert "S" in result["answer"]
    assert "中央下方" not in result["answer"]
    assert "金角银边草肚皮" in result["answer"]


def test_opening_fallback_gives_conclusion_global_tradeoff_and_timing(monkeypatch):
    evidence = {**EVIDENCE, "bestMove": "C17"}

    def fail(*_args, **_kwargs):
        raise mentor.MentorProviderError("验证服务端专业降级")

    monkeypatch.setattr(mentor, "_call_chat_provider", fail)
    result = mentor.chat(
        "cloud",
        "为什么 AI 首选更好？",
        [],
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        evidence,
        PURPOSE,
        "best",
    )

    assert result["degraded"] is True
    assert result["context"]["questionTarget"]["kind"] == "best"
    assert all(
        marker in result["answer"]
        for marker in ("先说结论｜", "为什么先碰角｜", "全局会怎样｜", "两手的潜力｜", "什么时候再走边｜")
    )
    assert "J" in result["answer"] and "S" in result["answer"]
    assert "角部争夺而非抢占空角" in result["answer"]
    assert "宽框架" in result["answer"]
    assert "不是说 S 是坏棋" in result["answer"]


def test_opening_followup_answers_three_three_vs_three_star_instead_of_repeating(monkeypatch):
    evidence = {**EVIDENCE, "bestMove": "C17"}
    previous = mentor._opening_comparison_fallback(
        DUAL_POSITION, evidence, DUAL_POSITION["moveCandidates"]
    )
    first_focused_answer = mentor._opening_territory_influence_fallback(
        "为什么要先点三三不是拆边", DUAL_POSITION, DUAL_POSITION["moveCandidates"]
    )

    def fail(*_args, **_kwargs):
        raise mentor.MentorProviderError("验证专项追问降级")

    monkeypatch.setattr(mentor, "_call_chat_provider", fail)
    result = mentor.chat(
        "cloud",
        "为什么角的优先级更高",
        [
            {"role": "user", "content": "为什么要先点三三不是拆边"},
            {"role": "assistant", "content": previous},
        ],
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        evidence,
        PURPOSE,
        "best",
    )

    assert result["degraded"] is True
    assert result["answerMode"] == "deterministic_fallback"
    assert result["answer"] != previous
    assert result["answer"] != first_focused_answer
    assert all(
        marker in result["answer"]
        for marker in ("J 是点三三", "S", "三连星", "实空", "模样", "外势", "更快、更确定")
    )
    assert any(marker in result["answer"] for marker in ("侵消", "落空", "偏缓"))
    assert "金角银边草肚皮" not in result["answer"]


def test_opening_focus_prompt_includes_both_moves_and_deterministic_point_type():
    evidence = {**EVIDENCE, "bestMove": "C17"}
    target = mentor._question_target(
        "为什么角的优先级更高", DUAL_POSITION, evidence, "best"
    )
    prompt = mentor._chat_prompt(
        "为什么角的优先级更高",
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        evidence,
        PURPOSE,
        target,
        [{"role": "assistant", "content": "上一轮完整回答"}],
    )

    assert '"实战手"' in prompt and '"AI首选"' in prompt
    assert '"棋盘点型":"三三"' in prompt
    assert '"边上框架":"落点与同侧两翼己子构成三连星式宽框架"' in prompt
    assert "只补充回答用户本轮新问" in prompt
    assert "实空与三连星取模样、外势" in prompt


def test_prompt_deduplicates_agent_tool_evidence_and_omits_false_zero_liberties():
    position = {
        **DUAL_POSITION,
        "moveCandidates": {
            **DUAL_POSITION["moveCandidates"],
            "actual": {
                **DUAL_POSITION["moveCandidates"]["actual"],
                "rules": {
                    "legal": True,
                    "libertiesBeforeAfter": {
                        "own": [0, 4],
                        "opponent": [0, 0],
                    },
                },
            },
        },
    }
    agent_context = {
        "toolResults": {
            "schemaVersion": "agent-tool-results-v1",
            "planHash": "a" * 64,
            "items": [{
                "tool": "analyze_variations",
                "target": "comparison",
                "status": "ready",
                "evidenceHash": "b" * 64,
                "result": {
                    "status": "ready",
                    "rawDuplicateMarker": "MUST_NOT_REACH_MODEL",
                    "branches": {"actual": {"privateCoordinate": "Q16"}},
                },
            }],
        },
    }
    prompt = mentor._chat_prompt(
        "为什么这手不好？",
        coach.DEFAULT_SETTINGS,
        position,
        EVIDENCE,
        PURPOSE,
        {"kind": "comparison", "label": "两手比较"},
        agent_context=agent_context,
    )

    assert "MUST_NOT_REACH_MODEL" not in prompt
    assert '"privateCoordinate":"Q16"' not in prompt
    assert '"事实位置":"上方多分支变化裁决"' in prompt
    assert '"己方相邻棋块气数变化":"落子后新棋有 4 气"' in prompt
    assert "对方相邻棋块气数变化" not in prompt


def test_opening_prompt_uses_compact_four_point_runtime_contract():
    prompt = mentor._chat_prompt(
        "为什么这手不好？请比较实战手与AI首选。",
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        EVIDENCE,
        PURPOSE,
        {"kind": "comparison", "label": "两手比较"},
    )

    assert '"教学要点":[' in prompt
    assert "必须覆盖证据中的四项教学要点" in prompt
    assert "只返回JSON对象" in prompt
    assert len(prompt) < 7000


def test_opening_depth_accepts_four_semantic_sentences_without_headings():
    answer = (
        "J优先，当前角部争夺比边上扩张更急。"
        "S连接同侧两翼并发展宽框架，但框架不是确定地盘，仍可能被侵消。"
        "J触及对方已有角部，争夺开局次序和向两边发展的余地。"
        "S不是绝对坏棋，先处理角部再找边上扩张时机，具体得失仍需核对。"
    )

    result = mentor._validate_answer_depth(
        answer,
        "为什么这手不好？",
        {"kind": "comparison"},
        DUAL_POSITION,
    )

    assert result["status"] == "passed"
    assert result["sentences"] == 4


def test_readability_rejects_repeated_teaching_sentence():
    repeated = "S发展边上框架但仍可能被侵消。S发展边上框架但仍可能被侵消。"
    with pytest.raises(mentor.MentorProviderError, match="重复句"):
        mentor._validate_answer_readability(
            repeated,
            "为什么这手不好？",
            {"kind": "comparison"},
            DUAL_POSITION,
        )


def test_repeated_focused_followup_is_repaired_once(monkeypatch):
    evidence = {**EVIDENCE, "bestMove": "C17"}
    repeated = (
        "J点三三直接取得角地实空；S形成三连星，发展模样和外势。"
        "三连星收益偏缓，模样可能被侵消，外势缺少攻击对象时也可能落空。"
        "所以当前KataGo更重视J，但S并非坏棋。"
    )
    repaired = (
        "你追问的‘角为什么更急’，核心在兑现速度。J点三三把价值立即落成角地实空；"
        "S虽然组成三连星，却把价值押在未来的模样与外势上。"
        "可以理解为后者更偏缓：对手还能侵消模样，外势若找不到攻击对象也可能落空。"
        "因此KataGo当前先选J，S只是次序靠后。"
    )
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        return {
            "answer": repeated if len(calls) == 1 else repaired,
            "followUps": [],
            "source": "cloud",
            "sourceLabel": "云端增强老师",
            "model": "fake-cloud",
            "answerMode": "llm_inference",
            "latencyMs": 8,
        }

    monkeypatch.setattr(mentor, "_call_chat_provider", fake)
    result = mentor.chat(
        "cloud",
        "为什么角的优先级更高",
        [{"role": "assistant", "content": repeated}],
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        evidence,
        PURPOSE,
        "best",
    )

    assert len(calls) == 2
    assert result["degraded"] is False
    assert result["answerMode"] == "llm_inference"
    assert result["answer"].startswith(repaired)
    assert "重复上一轮" in result["context"]["answerValidation"]["repair"]["reason"]
    assert result["context"]["answerValidation"]["followUpNovelty"]["status"] == "passed"


def test_classical_principle_is_traceable_and_remains_heuristic():
    principle = classical_go.match_principle(
        "为什么要外搬？", "best", DUAL_POSITION["moveCandidates"]
    )

    assert principle["maxim"] == "入境侵疆，常存先手"
    assert principle["work"] == "敦煌棋经"
    assert principle["license"] == "public-domain"
    assert principle["confidence"] == "heuristic"
    assert principle["source"] == "classical_go.match_principle"


def test_explicit_actual_move_text_overrides_best_move_ui_intent():
    target = mentor._question_target(
        "实战 K4 为什么不好？",
        DUAL_POSITION,
        {**EVIDENCE, "bestMove": "C17"},
        "best",
    )

    assert target["kind"] == "actual"
    assert target["move"] == "K4"
    assert target["source"] == "explicit_question_text"
    prompt = mentor._chat_prompt(
        "实战 K4 为什么不好？",
        coach.DEFAULT_SETTINGS,
        DUAL_POSITION,
        {**EVIDENCE, "bestMove": "C17"},
        PURPOSE,
        target,
    )
    assert '"显示名":"S"' in prompt
    assert '"显示名":"J"' in prompt
    assert '"坐标":"K4"' not in prompt
    assert '"坐标":"C17"' not in prompt
    assert "用户问题：实战手 为什么不好？" in prompt


def test_readability_rejects_internal_arrays_and_unsolicited_classics():
    with pytest.raises(mentor.MentorProviderError, match="内部气数数组"):
        mentor._validate_answer_readability(
            "实战手的气数变化为[2,3]。", "为什么不好？", {"kind": "actual"}
        )
    with pytest.raises(mentor.MentorProviderError, match="无关的古训"):
        mentor._validate_answer_readability(
            "古训《棋经十三篇》说这手应补。", "为什么不好？", {"kind": "actual"}
        )

    validation = mentor._validate_supported_numbers(
        "1. 先看连接\n2、再看先手。", {"moveCandidates": {}}
    )
    assert validation["mentionedRuleNumbers"] == []
    coordinate_validation = mentor._validate_supported_numbers(
        "首选R11外搬。",
        {"moveCandidates": {"best": {"move": "R11", "rules": {}}}},
    )
    assert coordinate_validation["mentionedMoves"] == ["R11"]
    assert coordinate_validation["mentionedRuleNumbers"] == []


def test_variation_grounding_rejects_forced_reply_overclaim():
    evidence = {
        "variationEvidence": {
            "status": "ready",
            "branches": {
                "actual": {
                    "replies": [{
                        "ruleReplay": {
                            "summary": {
                                "capturedStones": 0,
                                "koEvents": 0,
                            },
                        },
                    }],
                },
            },
            "claimBoundary": {"notDirectlyProven": ["forced_reply"]},
        },
    }
    with pytest.raises(mentor.MentorProviderError, match="强制应手"):
        mentor._validate_variation_grounding(
            "J打吃后迫使对方应对，因此S的次序较差。", evidence
        )
    negated = mentor._validate_variation_grounding(
        "J是攻守转换点，但这不是J的强制应手；应比较双方次序和气。", evidence
    )
    assert negated["status"] == "passed"

    evidence["variationEvidence"]["claimBoundary"]["notDirectlyProven"] = [
        "thickness"
    ]
    with pytest.raises(mentor.MentorProviderError, match="厚薄启发式"):
        mentor._validate_variation_grounding(
            "J在变化中能保持厚势，次序优于S。", evidence
        )


def test_tactical_semantic_grounding_requires_go_shape_mechanism():
    evidence = {
        "variationEvidence": {
            "status": "ready",
            "tacticalSemantics": {
                "status": "ready",
                "comparison": {"mutualVitalPoint": True},
            },
        },
    }
    target = {"kind": "actual"}
    with pytest.raises(mentor.MentorProviderError, match="攻守角色反转"):
        mentor._validate_tactical_semantic_grounding(
            "S漏掉了双方共同急点J，变化里出现多次打吃。",
            "为什么S不好？", target, evidence,
        )
    passed = mentor._validate_tactical_semantic_grounding(
        "黑方先下J会打吃同一块两子棋；实战S后，对手抢J把同一块棋接长扩气。",
        "为什么S不好？", target, evidence,
    )
    assert passed["status"] == "passed"
    assert mentor._use_tactical_semantic_fast_path(
        "为什么S不好？", target, evidence
    ) is True

    numeric = mentor._validate_supported_numbers(
        "对手抢J后把同一块棋接成长为3子、扩到4气。",
        {"moveCandidates": {}},
        {
            "variationEvidence": {
                "tacticalSemantics": {
                    "opponentJAfterS": {
                        "groupStonesAfter": 3,
                        "groupLibertiesAfter": 4,
                    },
                },
            },
        },
    )
    assert numeric["mentionedRuleNumbers"] == [3.0, 4.0]

    evidence["variationEvidence"]["claimBoundary"] = {
        "notDirectlyProven": ["life_and_death"]
    }
    with pytest.raises(mentor.MentorProviderError, match="死活结果"):
        mentor._validate_variation_grounding(
            "J直接决定这块棋的生死。", evidence
        )
    negated_life = mentor._validate_variation_grounding(
        "J会攻击同一块棋，但不能据此断言这块棋已经死亡；仍应比较气和次序。",
        evidence,
    )
    assert negated_life["status"] == "passed"


def test_local_scope_allows_explicit_rejection_of_global_template():
    position = {
        "moveCandidates": {
            "actual": {
                "move": "K6",
                "heuristics": {
                    "localSituation": {
                        "scope": "local_fight",
                        "ownNearby": 3,
                        "enemyNearby": 3,
                    },
                },
            },
        },
    }
    result = mentor._validate_answer_scope(
        "这里是局部对杀，AI首选揭示了紧气次序；应算气、连接、切断和先手，"
        "而非讨论全局大场。",
        "为什么这手不好？",
        {"kind": "actual"},
        position,
    )
    assert result["status"] == "passed"


def test_tactical_answer_does_not_receive_unsolicited_classical_quote():
    tactical_position = {
        "moveCandidates": {
            "actual": {
                "move": "K6",
                "heuristics": {
                    "localSituation": {"scope": "local_fight"},
                },
            },
        },
    }
    answer, validation = mentor._attach_classical_guidance(
        "这手先处理局部急点。",
        "为什么不好？",
        {"kind": "actual"},
        tactical_position,
    )
    assert answer == "这手先处理局部急点。"
    assert validation["status"] == "not_requested"


def test_feedback_is_persisted_locally(tmp_path, monkeypatch):
    monkeypatch.setattr(mentor, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mentor, "FEEDBACK_DB", tmp_path / "feedback.db")
    saved = mentor.save_feedback({
        "gameId": "game-1", "turn": 28, "mode": "local", "provider": "local",
        "category": "helpful", "comment": "结合棋块以后更容易理解",
        "responseText": "测试讲解",
    })
    summary = mentor.feedback_summary()
    assert saved["saved"] is True
    assert summary["total"] == 1
    assert summary["items"][0] == {
        "provider": "local", "category": "helpful", "count": 1,
    }

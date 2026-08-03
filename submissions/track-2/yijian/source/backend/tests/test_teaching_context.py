# -*- coding: utf-8 -*-
"""服务端权威教学证据与瘦请求协议回归测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import app as api
import importers
import jobs
import library
import mentor
import reports
import teaching_context
from engine import KataGoEngine, MockKataGoEngine


SGF_TEXT = (
    "(;GM[1]FF[4]SZ[19]KM[7.5]PB[脱敏黑方]PW[脱敏白方]RE[B+R]"
    ";B[pd];W[dd];B[qp];W[dq])"
)


def _analysis(source: str = "katago", demo: bool = False) -> dict:
    positions = []
    for turn, (winrate, score) in enumerate(
        ((0.50, 0.0), (0.54, 1.2), (0.51, 0.4), (0.57, 2.1), (0.53, 1.0))
    ):
        positions.append(
            {
                "turn": turn,
                "winrateBlack": winrate,
                "scoreLeadBlack": score,
                "visits": 64,
                "bestMove": "Q16",
                "recommendations": [
                    {
                        "move": "Q16",
                        "winrateBlack": winrate,
                        "scoreLeadBlack": score,
                        "visits": 64,
                        "pv": ["Q16", "D16", "Q4"],
                    }
                ],
            }
        )
    return {
        "source": source,
        "demo": demo,
        "label": "真实测试分析" if not demo else "Mock 测试分析",
        "engineVersion": "test-1",
        "model": "test-network" if not demo else None,
        "backend": "OpenCL" if not demo else None,
        "scanVisits": 64,
        "criticalVisits": 128,
        "positions": positions,
    }


def _stored_game(tmp_path: Path, monkeypatch, *, source="katago", demo=False):
    monkeypatch.setattr(library, "DB_PATH", tmp_path / "teaching.db")
    imported = importers.import_bytes(SGF_TEXT.encode("utf-8"), "fixture.sgf")
    detail, _ = library.add_import(imported)
    raw = reports.build_raw_report(
        imported.game, _analysis(source=source, demo=demo), "B"
    )
    report_id = library.save_report(
        detail["id"], "B", f"fixture-{source}-{demo}", raw
    )
    return detail, report_id, raw


def test_server_rebuilds_stable_traceable_context(tmp_path, monkeypatch):
    detail, report_id, _ = _stored_game(tmp_path, monkeypatch)
    first = teaching_context.build_authoritative_context(
        detail["id"], 2, [], MockKataGoEngine(), report_id
    )
    second = teaching_context.build_authoritative_context(
        detail["id"], 2, [], MockKataGoEngine(), report_id
    )

    assert first["schemaVersion"] == "teaching-context-v6"
    assert first["authority"] == {
        "source": "server",
        "reconstructed": True,
        "clientEvidenceAccepted": False,
    }
    assert first["contextId"] == second["contextId"]
    assert first["positionHash"] == second["positionHash"]
    assert first["facts"]["analysis"]["source"] == "katago"
    assert first["facts"]["analysis"]["demo"] is False
    assert first["facts"]["analysis"]["winrate"] == pytest.approx(51.0)
    assert first["facts"]["analysis"]["bestMove"] == "Q16"
    assert first["facts"]["analysis"]["winrateDelta"] == pytest.approx(-3.0)
    assert first["facts"]["analysis"]["playerWinrateDelta"] == pytest.approx(3.0)
    relation = first["facts"]["analysis"]["decisionRelation"]
    assert relation["bestMoveBeforeActual"] == "Q16"
    assert relation["bestMoveAfterActual"] == "Q16"
    assert relation["missedBestBecameOpponentBestReply"] is True
    assert relation["source"] == "katago_pre_post_sequence"
    assert first["facts"]["rules"]["confidence"] == "deterministic"
    assert "winrateLoss" not in first["facts"]["rules"]
    assert "evidenceSummary" not in first["facts"]["heuristics"]
    assert first["expression"]["baselinePurpose"]["evidenceSummary"]
    assert first["reportRevision"]
    assert first["evidenceHash"]
    assert first["provenance"][0]["source"] == "goboard.py"
    prompt = mentor._chat_prompt(
        "这手如何？",
        {"studentRank": "amateur_5d", "persona": "principles"},
        *teaching_context.mentor_inputs(first),
    )
    assert '"来源":"katago","演示":false' in prompt


def test_chat_variation_adjudication_replays_both_branches_and_keeps_context_id(
    tmp_path, monkeypatch
):
    detail, report_id, _ = _stored_game(tmp_path, monkeypatch)
    context = teaching_context.build_authoritative_context(
        detail["id"], 2, [], MockKataGoEngine(), report_id
    )
    context["facts"]["moveCandidates"]["best"]["move"] = "Q4"
    context["facts"]["analysis"]["bestMove"] = "Q4"

    class BranchEngine:
        version = "test-branch-1"
        model_name = "test-network"

        def __init__(self):
            self.calls = []

        def analyze_position(self, game, turn, variation, visits=None, **_kwargs):
            self.calls.append((turn, tuple(variation), visits))
            forced = variation[-1]
            reply = "Q4" if forced == "D16" else "D16"
            follow = "D4"
            return {
                "winrateBlack": .51,
                "scoreLeadBlack": .3,
                "visits": visits,
                "recommendations": [
                    {
                        "move": reply,
                        "winrateBlack": .51,
                        "scoreLeadBlack": .3,
                        "visits": visits,
                        "pv": [reply, follow],
                    }
                ],
            }

    branch_engine = BranchEngine()
    enriched = teaching_context.enrich_with_variation_evidence(
        context, branch_engine, visits=64
    )
    repeated = teaching_context.enrich_with_variation_evidence(
        context, branch_engine, visits=64
    )

    assert enriched["contextId"] == context["contextId"]
    assert enriched["evidenceHash"] == context["evidenceHash"]
    assert enriched["adjudication"]["variationEvidenceHash"]
    evidence = enriched["adjudication"]["variationEvidence"]
    assert evidence["status"] == "ready"
    assert set(evidence["branches"]) == {"actual", "best"}
    assert evidence["comparison"]["bestBecameTopReplyAfterActual"] is True
    assert evidence["branches"]["actual"]["replies"][0]["line"] == [
        "D16", "Q4", "D4"
    ]
    first_event = evidence["branches"]["actual"]["replies"][0][
        "ruleReplay"
    ]["events"][0]
    assert first_event["source"] == "goboard"
    assert isinstance(first_event["newGroup"]["liberties"], int)
    assert len(branch_engine.calls) == 2
    assert repeated["adjudication"]["adjudicationId"] == enriched[
        "adjudication"
    ]["adjudicationId"]

    position, analysis, purpose = teaching_context.mentor_inputs(enriched)
    prompt = mentor._chat_prompt(
        "为什么S不如J？", {"studentRank": "amateur_5d"},
        position, analysis, purpose, {"kind": "comparison", "label": "两手比较"}
    )
    assert '"多分支变化裁决":{"状态":"已复核"' in prompt
    assert '"实战S"' in prompt and '"首选J"' in prompt
    assert all(move not in prompt for move in ("D16", "Q4", "D4"))


def test_tactical_semantics_links_j_attack_and_opponent_j_extension():
    actual_events = [
        {
            "move": "K6",
            "captures": 0,
            "joinedOwnGroups": 1,
            "newGroup": {"stones": 9, "liberties": 3, "stonePoints": ["K6"]},
            "adjacentOpponentGroups": [{
                "stones": 1, "liberties": 1,
                "stonePoints": ["K5"], "libertyPoints": ["J5"],
            }],
        },
        {
            "move": "L2",
            "captures": 0,
            "adjacentOwnGroupsBefore": [{
                "stones": 2, "liberties": 2,
                "stonePoints": ["L3", "L4"],
            }],
            "joinedOwnGroups": 1,
            "newGroup": {
                "stones": 3, "liberties": 3,
                "stonePoints": ["L2", "L3", "L4"],
            },
            "adjacentOpponentGroups": [],
        },
    ]
    best_events = [{
        "move": "L2",
        "captures": 0,
        "joinedOwnGroups": 0,
        "newGroup": {"stones": 1, "liberties": 3, "stonePoints": ["L2"]},
        "adjacentOpponentGroups": [{
            "stones": 2, "liberties": 1,
            "stonePoints": ["L3", "L4"], "libertyPoints": ["K3"],
        }],
    }]

    def branch(reply, events):
        return {
            "replies": [{
                "reply": reply,
                "ruleReplay": {"events": events, "summary": {}},
            }],
        }

    semantics = teaching_context._tactical_semantics(
        {
            "actual": branch("L2", actual_events),
            "best": {
                "replies": [
                    {
                        "reply": "P17",
                        "ruleReplay": {"events": best_events, "summary": {}},
                    },
                    {
                        "reply": "N10",
                        "ruleReplay": {"events": best_events, "summary": {}},
                    },
                ],
            },
        },
        "K6", "L2", 19,
    )

    assert semantics["status"] == "ready"
    assert semantics["actualSImmediate"]["atariTargetStones"] == 1
    assert semantics["bestJImmediate"]["atariTargetStones"] == 2
    assert semantics["opponentJAfterS"]["extendsSameGroupAttackedByJ"] is True
    assert semantics["opponentJAfterS"]["groupStonesBefore"] == 2
    assert semantics["opponentJAfterS"]["groupLibertiesBefore"] == 2
    assert semantics["opponentJAfterS"]["groupStonesAfter"] == 3
    assert semantics["comparison"]["mutualVitalPoint"] is True
    assert semantics["replyPriority"]["bestBranchTopRepliesAllElsewhere"] is True


def test_mainline_context_exposes_only_same_turn_cached_narrative(
    tmp_path, monkeypatch
):
    detail, _, raw = _stored_game(tmp_path, monkeypatch)
    node = next(item for item in raw["losses"] if item["turn"] == 1)
    node["narrative"] = {
        "source": "cloud",
        "model": "fixture-classical-go",
        "schemaVersion": "report-narrative-v1",
        "paragraphs": ["目的", "取舍", "下一步"],
    }
    report_id = library.save_report(
        detail["id"], "B", "fixture-with-narrative", raw
    )
    mainline = teaching_context.build_authoritative_context(
        detail["id"], 1, [], MockKataGoEngine(), report_id
    )
    variation = teaching_context.build_authoritative_context(
        detail["id"], 1, ["Q10"], MockKataGoEngine(), report_id
    )
    assert (
        mainline["expression"]["cachedNarrative"]["model"]
        == "fixture-classical-go"
    )
    assert variation["expression"]["cachedNarrative"] is None


def test_actual_and_best_move_have_separate_server_evidence(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(library, "DB_PATH", tmp_path / "dual-candidates.db")
    game_text = (
        "(;GM[1]FF[4]SZ[19]KM[7.5]PB[黑方]PW[白方]"
        ";B[dp];W[dd];B[pp];W[pd];B[jp])"
    )
    imported = importers.import_bytes(game_text.encode("utf-8"), "dual.sgf")
    detail, _ = library.add_import(imported)
    positions = []
    for turn in range(6):
        positions.append({
            "turn": turn,
            "winrateBlack": .50 - turn * .01,
            "scoreLeadBlack": -turn * .2,
            "visits": 128,
            "bestMove": "C17",
            "recommendations": [{
                "move": "C17",
                "winrateBlack": .52,
                "scoreLeadBlack": .4,
                "visits": 128,
                "pv": ["C17", "C16", "D17"],
            }],
        })
    analysis = {
        "source": "katago",
        "demo": False,
        "label": "真实测试分析",
        "engineVersion": "test-1",
        "model": "test-network",
        "backend": "OpenCL",
        "scanVisits": 64,
        "criticalVisits": 128,
        "positions": positions,
    }
    raw = reports.build_raw_report(imported.game, analysis, "B")
    report_id = library.save_report(
        detail["id"], "B", "dual-candidates", raw
    )

    context = teaching_context.build_authoritative_context(
        detail["id"], 5, [], MockKataGoEngine(), report_id
    )
    candidates = context["facts"]["moveCandidates"]
    actual, best = candidates["actual"], candidates["best"]

    assert context["schemaVersion"] == "teaching-context-v6"
    assert context["evidenceProjectionVersion"] == "dual-move-candidates-v5-variation-adjudication"
    assert actual["move"] == "K4"
    assert actual["player"] == "B"
    assert actual["region"] == {
        "label": "中央下方",
        "source": "coordinate_projection",
        "confidence": "deterministic",
    }
    assert actual["geometry"]["zone"] == "side"
    assert actual["geometry"]["sectorLabel"] == "下边"
    assert actual["heuristics"]["openingStrategy"]["strategicType"] == "side_framework_bridge"
    assert actual["heuristics"]["openingStrategy"]["framework"] == {
        "sameSideFriendlyStones": 2,
        "spansBothFlanks": True,
        "formation": "three_star_style",
        "description": "落点与同侧两翼己子构成三连星式宽框架",
    }
    assert best["move"] == "C17"
    assert best["player"] == "B"
    assert best["region"]["label"] == "左边上方"
    assert best["geometry"]["zone"] == "corner"
    assert best["geometry"]["sectorLabel"] == "左上角"
    assert best["heuristics"]["openingStrategy"]["strategicType"] == "corner_approach"
    assert "而非抢占空角" in best["heuristics"]["openingStrategy"]["cornerContext"]["description"]
    assert best["rules"]["legal"] is True
    assert best["heuristics"]["enemyNearby"] >= 1
    assert best["analysis"]["source"] == "katago"
    assert candidates["sameMove"] is False

    position, evidence, purpose = teaching_context.mentor_inputs(context)
    target = mentor._question_target("AI 首选在哪里？", position, evidence)
    assert target["kind"] == "best"
    assert target["move"] == "C17"
    prompt = mentor._chat_prompt(
        "AI 首选在哪里？",
        {"studentRank": "amateur_5d", "persona": "principles"},
        position,
        evidence,
        purpose,
        target,
    )
    assert '"目标":"AI 首选"' in prompt
    assert '"区域":"左边上方"' in prompt
    assert '"实战手（只作对照）"' not in prompt
    assert '"中央下方"' not in prompt
    assert '"边上框架":"落点与同侧两翼己子构成三连星式宽框架"' not in prompt
    assert '"角部现状":"对方已在该角落子，当前着法属于角部争夺而非抢占空角"' in prompt
    assert '"move":"C17"' not in prompt
    assert '"显示名":"J"' in prompt
    assert '"坐标":"C17"' not in prompt


def test_local_fight_scope_overrides_opening_geometry():
    profile = teaching_context._local_situation_profile(
        {
            "adjacentOpponentGroups": 1,
            "attack": True,
            "defense": True,
            "libertiesBeforeAfter": {
                "own": [2, 3],
                "opponent": [2, 1],
            },
        },
        own_count=9,
        enemy_count=8,
        phase="中盘",
    )

    assert profile["scope"] == "local_fight"
    assert profile["label"] == "局部对杀"
    assert profile["ownLibertiesBeforeAfter"] == [2, 3]
    assert profile["opponentLibertiesBeforeAfter"] == [2, 1]
    assert "角边中腹发展" in profile["scopeGuard"]


def test_http_contract_forbids_client_generated_facts():
    with pytest.raises(ValidationError):
        api.MentorExplainBody.model_validate(
            {
                "gameId": "game",
                "turn": 2,
                "variation": [],
                "mode": "baseline",
                "evidence": {"winrate": 99.9, "bestMove": "A1"},
                "purpose": {"role": "伪造结论"},
            }
        )


def test_explain_and_chat_share_same_authoritative_context(
    tmp_path, monkeypatch
):
    detail, report_id, _ = _stored_game(tmp_path, monkeypatch)
    monkeypatch.setattr(mentor, "FEEDBACK_DB", tmp_path / "feedback.db")
    explain = api.mentor_explain(
        api.MentorExplainBody(
            gameId=detail["id"],
            reportId=report_id,
            turn=2,
            mode="baseline",
        )
    )

    def fail(*_args, **_kwargs):
        raise mentor.MentorProviderError("测试中不启动模型")

    monkeypatch.setattr(mentor, "_call_chat_provider", fail)
    chat = api.mentor_chat(
        api.MentorChatBody(
            gameId=detail["id"],
            reportId=report_id,
            turn=2,
            question="为什么这手值得复盘？",
            provider="local",
        )
    )

    assert explain["teachingContext"]["contextId"] == chat["teachingContext"]["contextId"]
    assert explain["teachingContext"]["positionHash"] == chat["context"]["positionHash"]
    assert explain["evidence"]["winrate"] == pytest.approx(51.0)
    assert chat["degraded"] is True
    context = explain["teachingContext"]
    saved = api.mentor_feedback(
        api.MentorFeedbackBody(
            gameId=detail["id"],
            reportId=report_id,
            turn=2,
            variation=[],
            contextId=context["contextId"],
            positionHash=context["positionHash"],
            category="helpful",
        )
    )
    assert saved["saved"] is True
    with pytest.raises(api.HTTPException) as stale_feedback:
        api.mentor_feedback(
            api.MentorFeedbackBody(
                gameId=detail["id"],
                reportId=report_id,
                turn=2,
                variation=[],
                contextId="0" * 64,
                positionHash=context["positionHash"],
            )
        )
    assert stale_feedback.value.status_code == 409


def test_unknown_game_report_mismatch_and_turn_are_rejected(
    tmp_path, monkeypatch
):
    detail, report_id, _ = _stored_game(tmp_path, monkeypatch)
    with pytest.raises(teaching_context.TeachingContextError) as unknown:
        teaching_context.build_authoritative_context(
            "missing", 1, [], MockKataGoEngine()
        )
    assert unknown.value.status_code == 404

    with pytest.raises(teaching_context.TeachingContextError) as mismatch:
        teaching_context.build_authoritative_context(
            detail["id"], 1, [], MockKataGoEngine(), "wrong-report"
        )
    assert mismatch.value.code == "report_mismatch"

    with pytest.raises(teaching_context.TeachingContextError) as bad_turn:
        teaching_context.build_authoritative_context(
            detail["id"], 99, [], MockKataGoEngine(), report_id
        )
    assert bad_turn.value.code == "turn_out_of_range"
    with pytest.raises(api.HTTPException) as http_mismatch:
        api.mentor_explain(
            api.MentorExplainBody(
                gameId=detail["id"],
                reportId="wrong-report",
                turn=1,
            )
        )
    assert http_mismatch.value.detail["code"] == "report_mismatch"


def test_variation_is_legally_replayed_and_uses_sgf_color(
    tmp_path, monkeypatch
):
    detail, report_id, _ = _stored_game(tmp_path, monkeypatch)
    context = teaching_context.build_authoritative_context(
        detail["id"], 1, ["D16"], MockKataGoEngine(), report_id
    )
    assert context["subject"]["baseTurn"] == 1
    assert context["subject"]["variation"] == ["D16"]
    assert context["subject"]["player"] == "W"
    assert context["facts"]["analysis"]["source"] == "mock"
    assert context["facts"]["analysis"]["demo"] is True
    assert "evidenceSource" not in context["facts"]["rules"]

    with pytest.raises(teaching_context.TeachingContextError) as occupied:
        teaching_context.build_authoritative_context(
            detail["id"], 0, ["Q16", "Q16"], MockKataGoEngine(), report_id
        )
    assert occupied.value.code == "illegal_variation"


def test_mock_report_never_claims_katago(tmp_path, monkeypatch):
    detail, report_id, raw = _stored_game(
        tmp_path, monkeypatch, source="mock", demo=True
    )
    assert raw["engine"]["source"] == "mock"
    assert raw["engine"]["demo"] is True
    assert all(
        "katago" not in item["purposeEvidence"]["evidenceSource"]
        for item in raw["losses"]
    )
    context = teaching_context.build_authoritative_context(
        detail["id"], 1, [], MockKataGoEngine(), report_id
    )
    assert context["facts"]["analysis"]["demo"] is True
    assert context["provenance"][1]["confidence"] == "demo"
    raw["losses"][0]["purposeEvidence"]["evidenceSource"] = [
        "board_rules", "katago"
    ]
    rendered = reports.render_report(raw, "amateur_5d")
    assert "katago" not in rendered["losses"][0]["purposeEvidence"]["evidenceSource"]
    assert "mock" in rendered["losses"][0]["purposeEvidence"]["evidenceSource"]


def test_deep_result_updates_nested_and_position_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DB_PATH", tmp_path / "deep.db")
    imported = importers.import_bytes(SGF_TEXT.encode("utf-8"), "fixture.sgf")
    raw = reports.build_raw_report(imported.game, _analysis(), "B")
    detail, _ = library.add_import(imported)
    report_id = library.save_report(detail["id"], "B", "deep-fixture", raw)
    before_context = teaching_context.build_authoritative_context(
        detail["id"], 1, [], MockKataGoEngine(), report_id
    )
    pre = {
        "winrateBlack": 0.61,
        "scoreLeadBlack": 3.2,
        "recommendations": [{"move": "D4", "pv": ["D4", "Q16"]}],
    }
    post = {"winrateBlack": 0.49, "scoreLeadBlack": -0.2}
    reports.apply_deep_result(
        raw, 1, pre, post, visits=256, confidence="high"
    )
    node = next(item for item in raw["losses"] if item["turn"] == 1)
    assert raw["positions"][0]["winrateBlack"] == pytest.approx(0.61)
    assert raw["positions"][1]["winrateBlack"] == pytest.approx(0.49)
    assert node["purposeEvidence"]["bestMove"] == "D4"
    assert node["purposeEvidence"]["winrateLoss"] == node["winrateLoss"]
    assert node["purposeEvidence"]["deepVisits"] == 256
    same_report_id = library.save_report(detail["id"], "B", "deep-fixture", raw)
    after_context = teaching_context.build_authoritative_context(
        detail["id"], 1, [], MockKataGoEngine(), same_report_id
    )
    assert same_report_id == report_id
    assert after_context["reportRevision"] != before_context["reportRevision"]
    assert after_context["contextId"] != before_context["contextId"]
    assert after_context["evidenceHash"] != before_context["evidenceHash"]

    model_path = tmp_path / "network.bin.gz"
    config_path = tmp_path / "analysis.cfg"
    model_path.write_bytes(b"test-network")
    config_path.write_text("maxVisits = 64\n", encoding="utf-8")
    real_engine = object.__new__(KataGoEngine)
    real_engine.version = "test-1"
    real_engine.model = model_path
    real_engine.model_name = "test-network"
    real_engine.config = config_path
    real_engine.max_visits = 64
    real_engine.analyze_position = lambda *_args, **_kwargs: pytest.fail(
        "来源不匹配时不应启动单点深算"
    )
    manager = jobs.AnalysisManager(real_engine)
    try:
        with pytest.raises(ValueError, match="分析引擎不一致"):
            manager.deepen_node(detail["id"], "B", 1, visits=256)
    finally:
        manager.close()

    pass_game = importers.import_bytes(
        b"(;GM[1]FF[4]SZ[19]KM[7.5];B[])", "pass.sgf"
    ).game
    pass_raw = reports.build_raw_report(
        pass_game,
        {
            **_analysis(),
            "positions": _analysis()["positions"][:2],
        },
        "B",
    )
    pass_evidence = pass_raw["losses"][0]["purposeEvidence"]
    assert pass_evidence["move"] == "pass"
    assert "katago" in pass_evidence["evidenceSource"]
    assert pass_evidence["bestMove"] == "Q16"

from __future__ import annotations

import hashlib
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest

from creative_hub.shidu.evidence_extractor import EvidenceExtractionRequest
from creative_hub.shidu.glm_research_transport import (
    GlmAICompletionTransport,
    GlmEvidenceExtractionTransport,
    GlmRateLimitError,
    GlmResearchTransportError,
    GlmStructuredModelClient,
    GlmTrialScriptTransport,
)
from creative_hub.shidu.trial_script_compiler import (
    ActionSkeletonRequest,
    DeterministicTrialScriptTransport,
    NarrationRequest,
    TrialEvidenceInput,
)


class StructuredFixture:
    model_id = "fixture-model-v1"

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def complete(self, **request):
        self.calls.append(request)
        return self.payloads.pop(0)


def test_ai_completion_is_chinese_labeled_content_without_fake_sources():
    client = StructuredFixture({
        "plot_summary": "主人公在时代变化中经历多次选择与转折，在与亲友和现实处境的碰撞中，逐步确认自己愿意承担的人生方向。",
        "emotional_arc": "情绪从迟疑和失落转向理解与承担，保留人物处境中的复杂性。",
        "reader_fit": "适合关注人物命运、人生选择以及时代背景如何影响个体的读者。",
        "uncertainty_notice": "无法取得原文，具体细节需要以正式出版物为准。",
    })
    book = SimpleNamespace(
        title="测试之书",
        author="测试作者",
        language="zh-CN",
        edition="",
    )

    completed = GlmAICompletionTransport(client).complete(
        book=book,
        sources=(),
    )

    assert completed.model_id == client.model_id
    assert completed.content.startswith("情节梗概：")
    assert "不确定性说明：" in completed.content
    assert client.calls[0]["input_payload"]["verified_third_party_context"] == []
    assert "http" not in completed.content.casefold()


def test_evidence_adapter_derives_span_and_digest_from_exact_reader_bytes():
    document = "序言。Lincoln refused to abandon the decision. 尾声。"
    excerpt = "Lincoln refused to abandon the decision."
    client = StructuredFixture(
        {
            "claims": [
                {
                    "claim_type": "plot_node",
                    "normalized_claim": "林肯拒绝放弃这一决定",
                    "evidence_text": excerpt,
                    "spoiler_level": "light",
                    "confidence": 0.91,
                    "conflict_key": "model-must-not-assign-cross-source-conflict",
                    "conflict_severity": "critical",
                },
                {
                    "claim_type": "reader_fit",
                    "normalized_claim": "不在原文中的声明会被丢弃",
                    "evidence_text": "not in the document",
                    "spoiler_level": "none",
                    "confidence": 0.5,
                    "conflict_key": None,
                    "conflict_severity": None,
                },
            ]
        },
        {
            "assessments": [
                {"claim_index": 0, "supported": True}
            ]
        },
    )
    request = EvidenceExtractionRequest(
        model_id=client.model_id,
        prompt_version="prompt-v1",
        schema_version="schema-v1",
        system_prompt="fixed",
        document_revision_id=uuid4(),
        document_digest=hashlib.sha256(document.encode()).hexdigest(),
        document_bytes=document.encode(),
        response_schema="{}",
        tools=(),
    )

    output = GlmEvidenceExtractionTransport(client).extract(request)

    assert len(output["claims"]) == 1
    claim = output["claims"][0]
    start = document.index(excerpt)
    assert claim["source_span_start"] == start
    assert claim["source_span_end"] == start + len(excerpt)
    assert claim["excerpt_digest"] == hashlib.sha256(excerpt.encode()).hexdigest()
    assert claim["is_direct_quote"] is False
    assert claim["conflict_key"] is None
    assert claim["conflict_severity"] is None
    assert "document" in client.calls[0]["input_payload"]
    assert client.calls[1]["input_payload"]["claims"][0]["evidence_text"] == excerpt


def test_evidence_adapter_drops_exact_spans_that_fail_entailment_review():
    document = "Lincoln signed the document."
    excerpt = "Lincoln signed the document."
    client = StructuredFixture(
        {
            "claims": [
                {
                    "claim_type": "reader_fit",
                    "normalized_claim": "这证明所有读者都会喜欢本书",
                    "evidence_text": excerpt,
                    "spoiler_level": "none",
                    "confidence": 0.8,
                    "conflict_key": None,
                    "conflict_severity": None,
                }
            ]
        },
        {"assessments": [{"claim_index": 0, "supported": False}]},
    )
    request = EvidenceExtractionRequest(
        model_id=client.model_id,
        prompt_version="prompt-v1",
        schema_version="schema-v1",
        system_prompt="fixed",
        document_revision_id=uuid4(),
        document_digest=hashlib.sha256(document.encode()).hexdigest(),
        document_bytes=document.encode(),
        response_schema="{}",
        tools=(),
    )

    assert GlmEvidenceExtractionTransport(client).extract(request) == {"claims": []}


def test_evidence_adapter_drops_long_source_copy_before_verification():
    document = "林肯在会议结束以后独自走回房间并重新审视眼前的艰难选择。"
    client = StructuredFixture(
        {
            "claims": [
                {
                    "claim_type": "plot_node",
                    "normalized_claim": document,
                    "evidence_text": document,
                    "spoiler_level": "light",
                    "confidence": 0.9,
                    "conflict_key": None,
                    "conflict_severity": None,
                }
            ]
        }
    )
    request = EvidenceExtractionRequest(
        model_id=client.model_id,
        prompt_version="prompt-v1",
        schema_version="schema-v1",
        system_prompt="fixed",
        document_revision_id=uuid4(),
        document_digest=hashlib.sha256(document.encode()).hexdigest(),
        document_bytes=document.encode(),
        response_schema="{}",
        tools=(),
    )

    assert GlmEvidenceExtractionTransport(client).extract(request) == {"claims": []}
    assert len(client.calls) == 1


class ResponseFixture:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int):
        return self._body[:limit]


def test_glm_client_uses_fixed_json_envelope_without_proxy_or_redirect_authority():
    calls = []
    model_output = {"claims": []}
    body = json.dumps(
        {
            "choices": [
                {"message": {"content": json.dumps(model_output)}}
            ]
        }
    ).encode()

    def opener(request, timeout):
        calls.append((request, timeout))
        return ResponseFixture(body)

    client = GlmStructuredModelClient(
        api_key="test-key-do-not-log",
        _opener=opener,
    )
    assert "test-key-do-not-log" not in repr(client)

    result = client.complete(
        system_prompt="fixed policy",
        input_payload={"document": "reader data"},
        response_schema={"type": "object"},
    )

    assert result == model_output
    request, timeout = calls[0]
    assert request.full_url.endswith("/chat/completions")
    assert timeout == 120.0
    sent = json.loads(request.data)
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["stream"] is False
    assert sent["messages"][1]["content"] == '{"document":"reader data"}'


def test_glm_client_retries_one_transient_failure_with_bounded_delay():
    calls = []
    sleeps = []
    body = json.dumps(
        {
            "choices": [
                {"message": {"content": json.dumps({"decisions": []})}}
            ]
        }
    ).encode()

    def opener(request, timeout):
        calls.append((request, timeout))
        if len(calls) == 1:
            raise URLError("temporary")
        return ResponseFixture(body)

    client = GlmStructuredModelClient(
        api_key="test-key-do-not-log",
        _opener=opener,
        _sleeper=sleeps.append,
    )

    assert client.complete(
        system_prompt="fixed policy",
        input_payload={"evidence": []},
        response_schema={"type": "object"},
    ) == {"decisions": []}
    assert len(calls) == 2
    assert sleeps == [0.5]


def test_glm_client_surfaces_429_immediately_for_qwen_failover():
    calls = []
    sleeps = []

    def opener(request, timeout):
        calls.append((request, timeout))
        raise HTTPError(
            request.full_url,
            429,
            "rate limited",
            {},
            io.BytesIO(b"limited"),
        )

    client = GlmStructuredModelClient(
        api_key="test-key-do-not-log",
        _opener=opener,
        _sleeper=sleeps.append,
    )

    with pytest.raises(GlmRateLimitError):
        client.complete(
            system_prompt="fixed policy",
            input_payload={"evidence": []},
            response_schema={"type": "object"},
        )
    assert len(calls) == 1
    assert sleeps == []


def test_glm_trial_adapter_preserves_six_shot_lineage_and_requires_review():
    factual_id = uuid4()
    second_factual_id = uuid4()
    style_id = uuid4()
    reader_fit_id = uuid4()
    claims = (
        TrialEvidenceInput(
            evidence_id=factual_id,
            claim_type="plot_node",
            normalized_claim="冷雨、钥匙、门外和推开门构成人物眼前的选择",
            spoiler_level="light",
        ),
        TrialEvidenceInput(
            evidence_id=second_factual_id,
            claim_type="factual_context",
            normalized_claim="人物在雨中握住钥匙，停在门外审视自己的决定",
            spoiler_level="light",
        ),
        TrialEvidenceInput(
            evidence_id=style_id,
            claim_type="emotional_reaction",
            normalized_claim="读者感到紧张和克制",
            spoiler_level="light",
        ),
        TrialEvidenceInput(
            evidence_id=reader_fit_id,
            claim_type="reader_fit",
            normalized_claim="适合关注人物在压力下选择的读者",
            spoiler_level="light",
        ),
    )
    action_request = ActionSkeletonRequest(
        evidence_pack_revision_id=uuid4(),
        evidence_pack_digest="1" * 64,
        direction_revision_id=uuid4(),
        direction_digest="2" * 64,
        methodology_revision_id=uuid4(),
        methodology_digest="3" * 64,
        methodology_payload={},
        direction_payload={"title": "门槛上的选择"},
        claims=claims,
        model_version="fixture",
        prompt_version="fixture",
        primary_safety_category="biography",
        safety_cards_manifest_digest="4" * 64,
        pre_safety_decision_digest="5" * 64,
    )
    deterministic = DeterministicTrialScriptTransport()
    action_payload = deterministic.generate_action_skeleton(action_request)
    narration_request = NarrationRequest(
        evidence_pack_revision_id=action_request.evidence_pack_revision_id,
        direction_revision_id=action_request.direction_revision_id,
        methodology_revision_id=action_request.methodology_revision_id,
        action_skeleton=action_payload,
        action_skeleton_digest="6" * 64,
        claims=claims,
        model_version="fixture",
        prompt_version="fixture",
        primary_safety_category="biography",
        safety_cards_manifest_digest="4" * 64,
        pre_safety_decision_digest="5" * 64,
    )
    narration_payload = deterministic.generate_narration(narration_request)
    accepted = {
        "assessments": [
            {"item_index": index, "supported": True} for index in range(6)
        ]
    }
    client = StructuredFixture(
        action_payload,
        accepted,
        narration_payload,
        accepted,
    )
    adapter = GlmTrialScriptTransport(client)

    action = adapter.generate_action_skeleton(action_request)
    narration = adapter.generate_narration(narration_request)

    assert [item["ordinal"] for item in action["shots"]] == list(range(1, 7))
    assert all(
        item["factual_evidence_ids"] == [str(factual_id)]
        for item in action["shots"]
    )
    assert len(narration["narration_cues"]) == 6
    assert client.calls[0]["input_payload"]["book_category"] == "biography"
    assert client.calls[2]["input_payload"]["book_category"] == "biography"
    assert "人物传记" in client.calls[0]["system_prompt"]
    assert "人物传记" in client.calls[2]["system_prompt"]
    assert client.calls[0]["input_payload"]["shot_grounding_plan"][1] == {
        "ordinal": 2,
        "factual_evidence_id": str(factual_id),
        "factual_claim": "冷雨、钥匙、门外和推开门构成人物眼前的选择",
        "style_evidence_id": str(style_id),
        "style_claim": "读者感到紧张和克制",
    }
    assert client.calls[1]["input_payload"]["items"][1][
        "factual_evidence_id"
    ] == str(factual_id)
    assert client.calls[1]["input_payload"]["items"][1][
        "style_evidence_id"
    ] == str(style_id)
    assert client.calls[1]["input_payload"]["items"][1]["style_claim"] == (
        "读者感到紧张和克制"
    )
    serialized_plans = json.dumps(
        client.calls[0]["input_payload"]["shot_grounding_plan"]
    )
    assert str(second_factual_id) not in serialized_plans
    assert str(reader_fit_id) not in serialized_plans
    assert "review" in client.calls[1]["system_prompt"] or "核验" in client.calls[1]["system_prompt"]
    assert "review" in client.calls[3]["system_prompt"] or "核验" in client.calls[3]["system_prompt"]


def test_glm_trial_grounding_review_rejects_any_unsupported_style_or_fact():
    client = StructuredFixture(
        {
            "assessments": [
                {"item_index": index, "supported": index != 4}
                for index in range(6)
            ]
        }
    )
    items = [
        {
            "item_index": index,
            "generated_text": f"第{index + 1}项文本",
            "factual_claim": "人物停在门外",
            "factual_evidence_id": str(uuid4()),
            "style_claim": "读者感到克制和紧张",
            "style_evidence_id": str(uuid4()),
        }
        for index in range(6)
    ]

    with pytest.raises(GlmResearchTransportError, match="not evidence-grounded"):
        GlmTrialScriptTransport(client)._verify_grounding(items=items)

    assert client.calls[0]["input_payload"] == {"items": items}

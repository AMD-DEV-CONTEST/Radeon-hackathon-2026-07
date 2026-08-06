from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from creative_hub.shidu.mcp_transport import (
    BoundedMCPTransport,
    MCPResult,
    MCPTransportError,
    RecordedMCPTransport,
)
from creative_hub.shidu.providers import (
    CODING_PLAN_READER_SCHEMA_DIGEST,
    CODING_PLAN_READER_TOOL_NAME,
    CODING_PLAN_SEARCH_SCHEMA_DIGEST,
    CODING_PLAN_SEARCH_TOOL_NAME,
    QWEN_TTS_SCHEMA_DIGEST,
    QWEN_TTS_TOOL_NAME,
    CodingPlanPageReaderMCPProvider,
    CodingPlanSearchMCPProvider,
    ProviderContractError,
    QwenTTSDiscoveryProvider,
    ReadPageRequest,
    ReaderSecurityCapabilities,
    SearchRequest,
)


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "shidu"
APPROVED_ADDRESSES = ("93.184.216.34",)


def secure_reader_request(url: str) -> ReadPageRequest:
    return ReadPageRequest(
        url=url,
        approved_resolved_addresses=APPROVED_ADDRESSES,
        redirect_policy="forbid",
        prefetch_policy="connect-approved-address-only",
    )


@pytest.fixture()
def recorded_transport() -> RecordedMCPTransport:
    return RecordedMCPTransport.from_directory(FIXTURE_DIRECTORY)


def test_search_provider_returns_immutable_recorded_hits(recorded_transport) -> None:
    provider = CodingPlanSearchMCPProvider(recorded_transport)

    hits = provider.search(SearchRequest(query="活着 书评", max_results=10))

    assert isinstance(hits, tuple)
    assert [hit.title for hit in hits] == [
        "《活着》：苦难中的生命韧性",
        "余华《活着》读后感",
    ]
    with pytest.raises(ValidationError, match="frozen"):
        hits[0].title = "mutated"


def test_search_provider_rejects_schema_drift(recorded_transport) -> None:
    provider = CodingPlanSearchMCPProvider(
        recorded_transport,
        expected_schema_digest="a" * 64,
    )

    with pytest.raises(ProviderContractError, match="schema"):
        provider.search(SearchRequest(query="活着 书评", max_results=10))


def test_reader_provider_returns_recorded_document(recorded_transport) -> None:
    provider = CodingPlanPageReaderMCPProvider(recorded_transport)

    assert provider.security_capabilities == ReaderSecurityCapabilities.secure_default()
    document = provider.read(secure_reader_request("https://example.invalid/reviews/to-live"))

    assert document.title == "《活着》：苦难中的生命韧性"
    assert document.content_type == "text/plain"
    assert "合成的离线正文" in document.content
    assert document.content_digest == hashlib.sha256(
        document.content.encode("utf-8")
    ).hexdigest()
    assert document.security.resolved_address == "93.184.216.34"
    assert document.security.redirect_chain == (
        "https://example.invalid/reviews/to-live",
    )


@pytest.mark.parametrize(
    "security",
    [
        None,
        {
            "resolved_address": "1.1.1.1",
            "redirect_chain": ["https://example.invalid/page"],
            "redirect_policy": "forbid",
            "prefetch_policy": "connect-approved-address-only",
        },
        {
            "resolved_address": "93.184.216.34",
            "redirect_chain": [
                "https://example.invalid/page",
                "https://redirect.invalid/page",
            ],
            "redirect_policy": "forbid",
            "prefetch_policy": "connect-approved-address-only",
        },
    ],
)
def test_reader_provider_fails_closed_on_missing_or_mismatched_security_attestation(
    security,
) -> None:
    class UnsafeReaderTransport:
        def call(self, tool_name, arguments, timeout_seconds):
            payload = {
                "url": "https://example.invalid/page",
                "title": "Synthetic page",
                "content": "Synthetic body",
                "content_type": "text/plain",
            }
            if security is not None:
                payload["security"] = security
            return MCPResult(
                tool_name=tool_name,
                schema_digest=CODING_PLAN_READER_SCHEMA_DIGEST,
                payload=payload,
            )

    provider = CodingPlanPageReaderMCPProvider(UnsafeReaderTransport())
    with pytest.raises(ProviderContractError, match="security|contract"):
        provider.read(secure_reader_request("https://example.invalid/page"))


@pytest.mark.parametrize("content_digest", [None, "a" * 64])
def test_reader_provider_fails_closed_on_missing_or_mismatched_content_digest(
    content_digest,
) -> None:
    class DigestReaderTransport:
        def call(self, tool_name, arguments, timeout_seconds):
            payload = {
                "url": "https://example.invalid/page",
                "title": "Synthetic page",
                "content": "Synthetic body",
                "content_type": "text/plain",
                "security": {
                    "resolved_address": "93.184.216.34",
                    "redirect_chain": ["https://example.invalid/page"],
                    "redirect_policy": "forbid",
                    "prefetch_policy": "connect-approved-address-only",
                },
            }
            if content_digest is not None:
                payload["content_digest"] = content_digest
            return MCPResult(
                tool_name=tool_name,
                schema_digest=CODING_PLAN_READER_SCHEMA_DIGEST,
                payload=payload,
            )

    provider = CodingPlanPageReaderMCPProvider(DigestReaderTransport())
    with pytest.raises(ProviderContractError, match="digest|contract"):
        provider.read(secure_reader_request("https://example.invalid/page"))


def test_tts_discovery_requires_default_speakers(recorded_transport) -> None:
    capabilities = QwenTTSDiscoveryProvider(recorded_transport).discover()

    assert capabilities.model_id == "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    assert {"Serena", "Uncle_Fu"} <= set(capabilities.speakers)


@pytest.mark.parametrize(
    ("provider_factory", "tool_name", "schema_digest", "payload", "invoke"),
    [
        (
            CodingPlanSearchMCPProvider,
            CODING_PLAN_SEARCH_TOOL_NAME,
            CODING_PLAN_SEARCH_SCHEMA_DIGEST,
            {"hits": []},
            lambda provider: provider.search(SearchRequest(query="书评")),
        ),
        (
            CodingPlanPageReaderMCPProvider,
            CODING_PLAN_READER_TOOL_NAME,
            CODING_PLAN_READER_SCHEMA_DIGEST,
            {
                "url": "https://example.invalid/page",
                "title": "合成页面",
                "content": "正文",
                "content_type": "text/plain",
            },
            lambda provider: provider.read(
                secure_reader_request("https://example.invalid/page")
            ),
        ),
        (
            QwenTTSDiscoveryProvider,
            QWEN_TTS_TOOL_NAME,
            QWEN_TTS_SCHEMA_DIGEST,
            {
                "service_version": "v1",
                "model_id": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                "tool_name": QWEN_TTS_TOOL_NAME,
                "schema_digest": QWEN_TTS_SCHEMA_DIGEST,
                "speakers": ["Serena", "Uncle_Fu"],
            },
            lambda provider: provider.discover(),
        ),
    ],
)
def test_providers_reject_live_tool_name_drift(
    provider_factory,
    tool_name,
    schema_digest,
    payload,
    invoke,
) -> None:
    class DriftedTransport:
        def call(self, tool_name, arguments, timeout_seconds):
            return MCPResult(
                tool_name=f"{tool_name}.drifted",
                schema_digest=schema_digest,
                payload=payload,
            )

    with pytest.raises(ProviderContractError, match="tool"):
        invoke(provider_factory(DriftedTransport()))


def test_tts_discovery_rejects_missing_required_speaker() -> None:
    class MissingSpeakerTransport:
        def call(self, tool_name, arguments, timeout_seconds):
            return MCPResult(
                tool_name=tool_name,
                schema_digest=QWEN_TTS_SCHEMA_DIGEST,
                payload={
                    "service_version": "v1",
                    "model_id": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                    "tool_name": tool_name,
                    "schema_digest": QWEN_TTS_SCHEMA_DIGEST,
                    "speakers": ["Serena"],
                },
            )

    with pytest.raises(ProviderContractError, match="speaker"):
        QwenTTSDiscoveryProvider(MissingSpeakerTransport()).discover()


def test_recorded_transport_validates_arguments(recorded_transport) -> None:
    with pytest.raises(MCPTransportError, match="arguments"):
        recorded_transport.call(
            CODING_PLAN_SEARCH_TOOL_NAME,
            {"query": "different", "max_results": 10},
            timeout_seconds=1,
        )


def test_bounded_transport_rejects_oversized_response() -> None:
    transport = BoundedMCPTransport(
        lambda _tool, _arguments, _timeout: b"x" * 65,
        max_response_bytes=64,
    )

    with pytest.raises(MCPTransportError, match="size limit"):
        transport.call("tool", {}, timeout_seconds=1)


def test_bounded_transport_maps_errors_without_leaking_details() -> None:
    def raise_secret(_tool, _arguments, _timeout):
        raise RuntimeError("credential=super-secret")

    transport = BoundedMCPTransport(raise_secret)

    with pytest.raises(MCPTransportError) as captured:
        transport.call("tool", {}, timeout_seconds=1)

    assert "super-secret" not in str(captured.value)
    assert len(str(captured.value).encode("utf-8")) <= 256


def test_bounded_transport_rejects_timeout_above_configured_limit() -> None:
    called = False

    def invoke(_tool, _arguments, _timeout):
        nonlocal called
        called = True
        return {}

    transport = BoundedMCPTransport(invoke, max_timeout_seconds=2)

    with pytest.raises(MCPTransportError, match="timeout"):
        transport.call("tool", {}, timeout_seconds=2.1)

    assert called is False


def test_bounded_transport_hides_remote_error_payload() -> None:
    transport = BoundedMCPTransport(
        lambda _tool, _arguments, _timeout: {
            "error": "access_token=super-secret"
        }
    )

    with pytest.raises(MCPTransportError) as captured:
        transport.call("tool", {}, timeout_seconds=1)

    assert "super-secret" not in str(captured.value)


def test_mcp_result_payload_is_deeply_immutable() -> None:
    result = MCPResult(
        tool_name="tool",
        schema_digest="b" * 64,
        payload={"nested": {"items": ["one", "two"]}},
    )

    assert isinstance(result.payload, MappingProxyType)
    assert isinstance(result.payload["nested"], MappingProxyType)
    assert result.payload["nested"]["items"] == ("one", "two")
    with pytest.raises(TypeError):
        result.payload["new"] = "value"

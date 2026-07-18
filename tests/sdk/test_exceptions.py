from __future__ import annotations

from cortex.sdk.exceptions import (
    CortexPublishError,
    CortexQueryError,
    CortexSDKError,
    map_node_error,
)


def test_map_publish_error():
    class PublishSignatureError(Exception):
        pass

    mapped = map_node_error(PublishSignatureError("bad sig"))
    assert isinstance(mapped, CortexPublishError)
    assert "bad sig" in str(mapped)


def test_map_query_error():
    class QueryTimeoutError(Exception):
        pass

    mapped = map_node_error(QueryTimeoutError("broker deadline"))
    assert isinstance(mapped, CortexQueryError)


def test_map_unknown_error_returns_base():
    mapped = map_node_error(RuntimeError("mystery"))
    assert isinstance(mapped, CortexSDKError)
    assert not isinstance(mapped, (CortexPublishError, CortexQueryError))


def test_map_passthrough_for_already_sdk_error():
    err = CortexPublishError("already mapped")
    assert map_node_error(err) is err


def test_public_api_reexports():
    import cortex.sdk as sdk
    for name in [
        "CortexClient",
        "CortexRetriever",
        "CortexPublishTool",
        "CortexReader",
        "vLLMClient",
        "ScriptedReasoner",
        "agent_step",
        "CortexAgent",
        "ProvenanceHelpers",
        "CortexPublishError",
        "CortexQueryError",
        "CortexSDKError",
        "map_node_error",
    ]:
        assert hasattr(sdk, name), f"cortex.sdk missing re-export: {name}"

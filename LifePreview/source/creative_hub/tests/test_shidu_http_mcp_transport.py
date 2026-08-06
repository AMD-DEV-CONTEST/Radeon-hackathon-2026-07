from __future__ import annotations

import io
import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from creative_hub.shidu.mcp_transport import HttpMCPTransport, MCPTransportError


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = io.BytesIO(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)


def test_http_mcp_transport_posts_a_bounded_secret_free_envelope() -> None:
    requests: list[tuple[Request, float]] = []

    def open_request(request: Request, timeout: float):
        requests.append((request, timeout))
        return _Response(
            {
                "tool_name": "coding_plan.search",
                "schema_digest": "a" * 64,
                "payload": {"hits": []},
            }
        )

    transport = HttpMCPTransport(
        "http://127.0.0.1:18110/invoke", opener=open_request
    )
    result = transport.call(
        "coding_plan.search", {"query": "活着", "max_results": 5}, 3.0
    )

    assert result.tool_name == "coding_plan.search"
    assert result.schema_digest == "a" * 64
    assert dict(result.payload) == {"hits": ()}
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == "http://127.0.0.1:18110/invoke"
    assert request.method == "POST"
    assert request.headers["Content-type"] == "application/json"
    assert request.headers["Accept"] == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "tool_name": "coding_plan.search",
        "arguments": {"query": "活着", "max_results": 5},
    }
    assert timeout == 3.0


@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///tmp/mcp",
        "http://user:secret@127.0.0.1:18110/invoke",
        "http://127.0.0.1:18110/invoke?token=secret",
        "http://127.0.0.1:18110/other",
    ],
)
def test_http_mcp_transport_rejects_unsafe_endpoint_shapes(endpoint: str) -> None:
    with pytest.raises(ValueError, match="endpoint"):
        HttpMCPTransport(endpoint)


def test_http_mcp_transport_hides_remote_error_bodies() -> None:
    def fail(request: Request, timeout: float):
        raise HTTPError(
            request.full_url,
            500,
            "secret remote body",
            {},
            io.BytesIO(b"secret remote body"),
        )

    transport = HttpMCPTransport(
        "http://127.0.0.1:18110/invoke", opener=fail
    )

    with pytest.raises(MCPTransportError, match="failed") as caught:
        transport.call("coding_plan.search", {"query": "x"}, 1.0)

    assert "secret" not in str(caught.value)


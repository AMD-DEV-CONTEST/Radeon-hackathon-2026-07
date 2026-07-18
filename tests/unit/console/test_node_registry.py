import json
from pathlib import Path

import httpx
import pytest

from cortex.console.node_registry import NodeRegistry, load_tenants


def test_load_tenants_from_file(tmp_path: Path):
    reg = tmp_path / "org_registry.json"
    reg.write_text(json.dumps({"tenants": [{"org_did": "did:percq:org:test", "slug": "test"}]}))
    assert load_tenants(reg) == [{"org_did": "did:percq:org:test", "slug": "test"}]


def test_load_tenants_missing(tmp_path: Path):
    assert load_tenants(tmp_path / "nonexistent.json") == []


@pytest.mark.asyncio
async def test_node_registry_proxy(tmp_path: Path):
    async def handler(request):
        return httpx.Response(200, json={"ok": True})

    reg = NodeRegistry()
    reg.register("alpha", "http://127.0.0.1:9999", transport=httpx.MockTransport(lambda req: handler(req)))
    _, client = reg.get("alpha")
    r = await client.get("/test")
    assert r.json() == {"ok": True}
    assert "alpha" in reg.known

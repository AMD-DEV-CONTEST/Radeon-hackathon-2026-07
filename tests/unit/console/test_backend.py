import asyncio
import json
from pathlib import Path

import pytest
import httpx
from httpx import ASGITransport, AsyncClient
import websockets
from websockets.asyncio.client import connect

from cortex.console.backend import create_app, create_app_with_broker
from cortex.console.fanout import Fanout
from cortex.console.node_registry import NodeRegistry


@pytest.mark.asyncio
async def test_root_returns_placeholder_when_no_static(tmp_path: Path):
    app = create_app(static_dir=tmp_path, registry_path=Path("org_registry.json"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/")
    assert r.status_code == 200
    assert "Perciqa Cortex" in r.text


@pytest.mark.asyncio
async def test_tenants_reads_registry(tmp_path: Path):
    reg = tmp_path / "org_registry.json"
    reg.write_text(json.dumps({"tenants": [
        {"org_did": "did:percq:org:soc-alpha", "slug": "soc-alpha"},
        {"org_did": "did:percq:org:soc-beta", "slug": "soc-beta"},
    ]}))
    app = create_app(static_dir=tmp_path, registry_path=reg)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/tenants")
    assert r.status_code == 200
    body = r.json()
    assert body == {"tenants": [
        {"org_did": "did:percq:org:soc-alpha", "slug": "soc-alpha"},
        {"org_did": "did:percq:org:soc-beta", "slug": "soc-beta"},
    ]}


@pytest.mark.asyncio
async def test_ws_events_fanout(tmp_path: Path, unused_tcp_port: int):
    fanout = Fanout()
    app = create_app_with_broker(static_dir=tmp_path, registry_path=tmp_path / "r.json", fanout=fanout, broker_url=None)
    import uvicorn
    server = uvicorn.Config(app, host="127.0.0.1", port=unused_tcp_port, log_level="error")
    srv = uvicorn.Server(server)
    task = asyncio.create_task(srv.serve())
    try:
        await asyncio.sleep(1.5)
        async with connect(f"ws://127.0.0.1:{unused_tcp_port}/ws/events") as ws:
            fanout.publish_event({"event": "article.published", "data": {"id": "x1"}})
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert json.loads(raw) == {"type": "event", "payload": {"event": "article.published", "data": {"id": "x1"}}}
    finally:
        srv.should_exit = True
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_ws_metrics_fanout(tmp_path: Path, unused_tcp_port: int):
    fanout = Fanout()
    app = create_app_with_broker(static_dir=tmp_path, registry_path=tmp_path / "r.json", fanout=fanout, broker_url=None)
    import uvicorn
    server = uvicorn.Config(app, host="127.0.0.1", port=unused_tcp_port, log_level="error")
    srv = uvicorn.Server(server)
    task = asyncio.create_task(srv.serve())
    try:
        await asyncio.sleep(1.5)
        async with connect(f"ws://127.0.0.1:{unused_tcp_port}/ws/metrics") as ws:
            sample = {"node": "soc-alpha", "embeds_per_sec_radeon": 142.3, "embeds_per_sec_cpu": 18.6,
                      "queries_per_sec_radeon": 23.1, "queries_per_sec_cpu": 2.7,
                      "gpu_mem_util_pct": 86, "p95_query_latency_ms": 42}
            fanout.publish_metrics(sample)
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            env = json.loads(raw)
        assert env["type"] == "metrics"
        assert env["payload"]["node"] == "soc-alpha"
        assert env["payload"]["embeds_per_sec_radeon"] == 142.3
    finally:
        srv.should_exit = True
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_articles_endpoint_proxies_to_node_debug(tmp_path: Path):
    async def handler(request):
        return httpx.Response(200, json={"id": "a1", "content": "hello", "type": "finding"})

    transport = httpx.MockTransport(lambda req: handler(req))
    reg = NodeRegistry()
    reg.register("soc-alpha", "http://127.0.0.1:9999", transport=transport)
    fanout = Fanout()
    app = create_app_with_broker(static_dir=tmp_path, registry_path=tmp_path / "r.json",
                                 fanout=fanout, broker_url=None, node_registry=reg)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/articles/a1?node=soc-alpha")
    assert r.status_code == 200
    assert r.json()["id"] == "a1"
    assert r.json()["content"] == "hello"


@pytest.mark.asyncio
async def test_serves_built_dist_index(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><head><title>Perciqa Cortex</title></head><body>app</body></html>")
    (dist / "static").mkdir()
    (dist / "static" / "main.js").write_text("console.log('app');")
    app = create_app(static_dir=dist, registry_path=tmp_path / "r.json")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        idx = await ac.get("/")
        js = await ac.get("/static/main.js")
    assert idx.status_code == 200
    assert "<title>Perciqa Cortex</title>" in idx.text
    assert js.status_code == 200
    assert "app" in js.text

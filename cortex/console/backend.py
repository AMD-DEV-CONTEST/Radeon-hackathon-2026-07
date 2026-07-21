from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cortex.console.fanout import Fanout
from cortex.console.node_registry import load_tenants


def create_app(static_dir: Path, registry_path: Path, broker_url: str | None = None) -> FastAPI:
    return create_app_with_broker(static_dir=static_dir, registry_path=registry_path,
                                  fanout=Fanout(), broker_url=broker_url)


def create_app_with_broker(
    static_dir: Path,
    registry_path: Path,
    fanout: Fanout,
    broker_url: str | None,
    node_registry: NodeRegistry | None = None,
    attack_matrix: AttackMatrixTracker | None = None,
) -> FastAPI:
    app = FastAPI(title="cortex-console")
    if node_registry is None:
        from cortex.console.node_registry import NodeRegistry
        node_registry = NodeRegistry()
    if attack_matrix is None:
        from cortex.console.attack_matrix import AttackMatrixTracker
        attack_matrix = AttackMatrixTracker()
    state: dict[str, Any] = {"fanout": fanout, "registry_path": registry_path, "static_dir": static_dir, "nodes": node_registry}

    @app.get("/")
    async def root() -> HTMLResponse:
        idx = static_dir / "index.html"
        if idx.exists():
            return HTMLResponse(idx.read_text())
        return HTMLResponse("<html><head><title>Perciqa Cortex</title></head><body><h1>Perciqa Cortex</h1></body></html>")

    @app.get("/api/tenants")
    async def tenants() -> JSONResponse:
        return JSONResponse({"tenants": load_tenants(registry_path)})

    @app.get("/api/articles/{article_id}")
    async def article_detail(article_id: str, node: str | None = None) -> JSONResponse:
        if node is None or node not in node_registry.known:
            return JSONResponse({"error": "unknown_node", "known": node_registry.known}, status_code=404)
        _, client = node_registry.get(node)
        r = await client.get(f"/debug/articles/{article_id}")
        return JSONResponse(r.json(), status_code=r.status_code)

    @app.get("/api/attack-matrix")
    async def attack_matrix_endpoint() -> JSONResponse:
        return JSONResponse({"counts": attack_matrix.counts()})

    @app.get("/api/attack-matrix/{attack_id}")
    async def attack_matrix_articles(attack_id: str) -> JSONResponse:
        return JSONResponse({"attack_id": attack_id, "articles": attack_matrix.articles_for(attack_id)})

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        await ws.accept()
        q = fanout.add_event_client()
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30.0)
                except TimeoutError:
                    await ws.send_json({"type": "ping"})
                    continue
                await ws.send_json({"type": "event", "payload": payload})
        except WebSocketDisconnect:
            pass
        finally:
            fanout.remove_event_client(q)

    @app.websocket("/ws/metrics")
    async def ws_metrics(ws: WebSocket) -> None:
        await ws.accept()
        q = fanout.add_metrics_client()
        try:
            while True:
                payload = await asyncio.wait_for(q.get(), timeout=30.0)
                await ws.send_json({"type": "metrics", "payload": payload})
        except (TimeoutError, WebSocketDisconnect):
            pass
        finally:
            fanout.remove_metrics_client(q)

    static_dir_static = static_dir / "static"
    if static_dir_static.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir_static)), name="static")

    return app

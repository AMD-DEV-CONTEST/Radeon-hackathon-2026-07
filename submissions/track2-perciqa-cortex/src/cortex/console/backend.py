from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cortex.console.attack_matrix import AttackMatrixTracker
from cortex.console.fanout import Fanout
from cortex.console.node_registry import NodeRegistry, load_tenants
from cortex.console.ring_buffer import EventRingBuffer


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
    events_ring: EventRingBuffer | None = None,
) -> FastAPI:
    app = FastAPI(title="cortex-console")
    if node_registry is None:
        node_registry = NodeRegistry()
    if attack_matrix is None:
        attack_matrix = AttackMatrixTracker()
    if events_ring is None:
        events_ring = EventRingBuffer()

    @app.get("/")
    async def root() -> HTMLResponse:
        idx = static_dir / "index.html"
        if idx.exists():
            return HTMLResponse(idx.read_text())
        return HTMLResponse(
            "<html><head><title>Perciqa Cortex</title></head>"
            "<body><h1>Perciqa Cortex</h1></body></html>"
        )

    @app.get("/vite")
    @app.get("/vite/")
    async def vite_root() -> HTMLResponse:
        idx = static_dir / "index.html"
        if idx.exists():
            return HTMLResponse(idx.read_text())
        return HTMLResponse(
            "<html><head><title>Perciqa Cortex</title></head>"
            "<body><h1>Perciqa Cortex</h1></body></html>"
        )

    @app.get("/api/tenants")
    async def tenants() -> JSONResponse:
        return JSONResponse({"tenants": load_tenants(registry_path)})

    @app.get("/api/articles/{article_id}")
    async def article_detail(article_id: str, node: str | None = None) -> JSONResponse:
        if node is None or node not in node_registry.known:
            return JSONResponse(
                {"error": "unknown_node", "known": node_registry.known}, status_code=404,
            )
        _, client = node_registry.get(node)
        r = await client.get(f"/debug/articles/{article_id}")
        return JSONResponse(r.json(), status_code=r.status_code)

    @app.get("/api/attack-matrix")
    async def attack_matrix_endpoint() -> JSONResponse:
        return JSONResponse({"counts": attack_matrix.counts()})

    @app.get("/api/attack-matrix/{attack_id}")
    async def attack_matrix_articles(attack_id: str) -> JSONResponse:
        return JSONResponse(
            {"attack_id": attack_id, "articles": attack_matrix.articles_for(attack_id)},
        )

    @app.get("/api/rocm-info")
    async def rocm_info() -> JSONResponse:
        """Return live GPU device info from the running process.

        Used by the console bench panel to display a real-time confirmation
        that ROCm is active.  Falls back gracefully when running on CPU-only hosts.
        """
        from cortex.bench.gpu_sensor import GpuSensor

        sensor = GpuSensor()
        snap = sensor.snapshot()

        # Add HIP version from torch if available
        hip_version: str | None = None
        torch_version: str | None = None
        try:
            import torch
            hip_version = getattr(torch.version, "hip", None)
            torch_version = torch.__version__
        except Exception:
            pass

        return JSONResponse({
            "mem_util_pct": snap["mem_util_pct"],
            "vram_total_mb": snap.get("vram_total_mb"),
            "vram_used_mb": snap.get("vram_used_mb"),
            "device_name": snap.get("device_name", "unknown"),
            "sensor_backend": snap.get("backend", "none"),
            "hip_version": hip_version,
            "torch_version": torch_version,
            "rocm_active": snap.get("backend") in ("rocm-smi", "torch")
            and snap.get("device_name", "none") not in ("none", "unknown"),
        })

    @app.get("/api/llm-info")
    async def llm_info() -> JSONResponse:
        """Probe the vLLM inference pod and return model + health status.

        The console uses this to display a live LLM status card showing which
        model is running on the ROCm inference pod.  Falls back gracefully when
        the vLLM service is not available (e.g. running without --profiles gpu).
        """
        import os

        import httpx

        vllm_url = os.environ.get("VLLM_URL", "http://localhost:8000/v1").rstrip("/")
        model_name = os.environ.get("VLLM_MODEL", "perciqa/aurora-code-mini-v1")

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{vllm_url}/models")
                r.raise_for_status()
                data = r.json()
                # OpenAI /v1/models returns {"data": [{"id": "<model>", ...}]}
                served = [m["id"] for m in data.get("data", [])]
                active_model = served[0] if served else model_name
                return JSONResponse({
                    "status": "online",
                    "model": active_model,
                    "endpoint": vllm_url,
                    "served_models": served,
                })
        except Exception as exc:
            return JSONResponse({
                "status": "offline",
                "model": model_name,
                "endpoint": vllm_url,
                "error": str(exc)[:120],
            })

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        await ws.accept()
        for payload in events_ring.snapshot():
            await ws.send_json({"type": "event", "payload": payload})
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

    static_dir_assets = static_dir / "assets"
    if static_dir_assets.exists():
        app.mount("/assets", StaticFiles(directory=str(static_dir_assets)), name="assets")
        app.mount("/vite/assets", StaticFiles(directory=str(static_dir_assets)), name="vite-assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str) -> HTMLResponse:
        if path.startswith("api/") or path.startswith("ws/") or path.startswith("vite/"):
            return HTMLResponse("", status_code=404)
        idx = static_dir / "index.html"
        if idx.exists():
            return HTMLResponse(idx.read_text())
        return HTMLResponse(
            "<html><head><title>Perciqa Cortex</title></head>"
            "<body><h1>Perciqa Cortex</h1></body></html>"
        )

    return app

"""OpenAI-compatible gateway for Silent Core model services."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask


API_KEY = os.environ["SILENT_CORE_API_KEY"]
INTERNAL_API_KEY = os.environ["SILENT_CORE_INTERNAL_API_KEY"]
LLM_URL = os.getenv("LLM_URL", "http://127.0.0.1:8001")
IMAGE_URL = os.getenv("IMAGE_URL", "http://127.0.0.1:8002")
TTS_URL = os.getenv("TTS_URL", "http://127.0.0.1:8003")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
    yield
    await app.state.client.aclose()


app = FastAPI(title="Silent Core Model API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if request.url.path.startswith("/v1/"):
        expected = f"Bearer {API_KEY}"
        if request.headers.get("authorization") != expected:
            return JSONResponse(
                status_code=401,
                content={"error": {"message": "Invalid API key", "type": "authentication_error"}},
            )
    return await call_next(request)


async def proxy(request: Request, upstream: str, path: str, internal_auth: bool = False):
    headers = {"content-type": request.headers.get("content-type", "application/json")}
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get(
        "x-forwarded-host", request.headers.get("host", request.url.netloc)
    )
    headers["x-public-base-url"] = f"{forwarded_proto}://{forwarded_host}"
    if internal_auth:
        headers["authorization"] = f"Bearer {INTERNAL_API_KEY}"
    upstream_request = request.app.state.client.build_request(
        request.method,
        f"{upstream}{path}",
        headers=headers,
        content=await request.body(),
    )
    try:
        response = await request.app.state.client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Model service unavailable: {exc}") from exc
    media_type = response.headers.get("content-type")
    response_headers = {
        "Cache-Control": response.headers.get("cache-control", "no-cache"),
        "X-Accel-Buffering": "no",
    }
    if disposition := response.headers.get("content-disposition"):
        response_headers["Content-Disposition"] = disposition
    return StreamingResponse(
        response.aiter_raw(),
        status_code=response.status_code,
        media_type=media_type,
        headers=response_headers,
        background=BackgroundTask(response.aclose),
    )


@app.get("/health")
async def health():
    async def check(name: str, url: str):
        try:
            response = await app.state.client.get(f"{url}/health", timeout=3.0)
            return name, response.status_code == 200
        except httpx.RequestError:
            return name, False

    results = dict(await asyncio.gather(
        check("llm", LLM_URL), check("image", IMAGE_URL), check("tts", TTS_URL)
    ))
    if all(results.values()):
        status = "ok"
    elif any(results.values()):
        status = "degraded"
    else:
        status = "starting"
    return {"status": status, "services": results}


@app.get("/v1/models")
async def models():
    created = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": "silent-core/llm", "object": "model", "created": created, "owned_by": "silent-core"},
            {"id": "silent-core/image", "object": "model", "created": created, "owned_by": "silent-core"},
            {"id": "silent-core/tts", "object": "model", "created": created, "owned_by": "silent-core"},
        ],
    }


@app.api_route("/v1/chat/completions", methods=["POST"])
async def chat_completions(request: Request):
    return await proxy(request, LLM_URL, "/v1/chat/completions", internal_auth=True)


@app.api_route("/v1/completions", methods=["POST"])
async def completions(request: Request):
    return await proxy(request, LLM_URL, "/v1/completions", internal_auth=True)


@app.api_route("/v1/responses", methods=["POST"])
async def responses(request: Request):
    return await proxy(request, LLM_URL, "/v1/responses", internal_auth=True)


@app.api_route("/v1/images/generations", methods=["POST"])
async def image_generations(request: Request):
    return await proxy(request, IMAGE_URL, "/v1/images/generations")


@app.get("/files/images/{filename}")
async def image_file(request: Request, filename: str):
    return await proxy(request, IMAGE_URL, f"/files/images/{filename}")


@app.api_route("/v1/audio/speech", methods=["POST"])
async def audio_speech(request: Request):
    return await proxy(request, TTS_URL, "/v1/audio/speech")

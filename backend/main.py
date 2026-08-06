"""FastAPI entry point for the Explainable AI Radiology Assistant."""
import asyncio
import os
import sys
from contextlib import asynccontextmanager

# Allow running either from project root or backend/ directory.
if os.path.basename(os.path.dirname(os.path.abspath(__file__))) == "backend":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import router as api_router
from inference.pipeline import AnalysisPipeline

PIPELINE: AnalysisPipeline | None = None

def _resolve_device() -> str:
    """Resolve the torch device string to use.

    PyTorch has no separate "hip"/"rocm" device type: on a ROCm build,
    `torch.cuda` *is* the HIP backend, and tensors still move with
    `.to("cuda")`. A literal `DEVICE=rocm` would make every `.to(device)`
    call in the pipeline raise. Accept "rocm" as a friendly alias here so
    docs/env files that set it don't break.
    """
    raw = os.environ.get("DEVICE")
    if raw is None or raw == "":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if raw.lower() == "rocm":
        return "cuda"
    return raw    


@asynccontextmanager
async def lifespan(app: FastAPI):
    global PIPELINE
    device = _resolve_device()
    PIPELINE = AnalysisPipeline(device=device)
    yield
    PIPELINE = None


app = FastAPI(
    title="RibEye - Explainable AI Radiology Assistant",
    description="Multimodal chest X-ray analysis with explainable AI and ROCm ternary acceleration.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_http_requests(request, call_next):
    print(f"[http] {request.method} {request.url.path}")
    return await call_next(request)


@app.websocket("/api/chat-ws")
async def chat_websocket(websocket: WebSocket):
    """WebSocket chat endpoint that streams answer tokens as they are generated.

    Registered directly on the app so it is matched before the static files
    mount, avoiding Starlette static-file assertion errors for WebSocket scopes.
    """
    import time as _time

    await websocket.accept()
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            report = data.get("report", "")
            findings_data = data.get("findings", [])
            question = data.get("question", "")
            max_tokens = data.get("max_tokens")
            history = data.get("history")
            findings = [
                type("F", (), {"label": f["label"], "confidence": f["confidence"], "region": f.get("region")})()
                for f in findings_data
            ]
            print(f"[chat-ws] Received question: {question[:80]!r}")
            request_start = _time.time()

            # Wait up to 5 minutes for the chat backend to become available.
            if PIPELINE is None:
                await websocket.send_text("__ERROR__:Pipeline not initialized")
                continue
            if not PIPELINE.radiology_llm.is_chat_available():
                print("[chat-ws] Chat model not ready yet, waiting...")
                await websocket.send_text("__LOADING__")
                ready = await asyncio.wait_for(
                    asyncio.to_thread(PIPELINE.radiology_llm.wait_for_chat_available, timeout=300.0),
                    timeout=300.0,
                )
                if not ready:
                    print("[chat-ws] Dedicated chat backend is not available; using fallback")
                else:
                    print("[chat-ws] Chat backend became ready, starting generation")
            else:
                print("[chat-ws] Model available, starting generation")

            try:
                first_token = True
                token_count = 0
                for token in PIPELINE.radiology_llm.stream_chat(
                    report, findings, question, max_new_tokens=max_tokens, history=history,
                ):
                    if first_token:
                        first_token = False
                        print(
                            f"[chat-ws] Time to first token: "
                            f"{_time.time() - request_start:.2f}s"
                        )
                    await websocket.send_text(token)
                    token_count += 1
                print(
                    f"[chat-ws] Streaming finished: {token_count} tokens in "
                    f"{_time.time() - request_start:.2f}s"
                )
                await websocket.send_text("__DONE__")
            except Exception as exc:
                print(f"[chat-ws] Generation error: {exc}")
                await websocket.send_text(f"__ERROR__:{exc}")
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[chat-ws] WebSocket handler error: {exc}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


app.include_router(api_router, prefix="/api")

@app.websocket("/{path:path}")
async def catch_all_websocket(websocket: WebSocket):
    """Diagnostic catch-all for unmatched WebSocket paths."""
    await websocket.accept()
    path = websocket.scope.get("path", "unknown")
    print(f"[ws-catch-all] Unmatched WebSocket path: {path}")
    await websocket.send_text(f"__ERROR__:Unmatched WebSocket path: {path}")
    await websocket.close()


# Serve frontend build if present
frontend_build = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "build")
if os.path.isdir(frontend_build):
    app.mount("/", StaticFiles(directory=frontend_build, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=False)

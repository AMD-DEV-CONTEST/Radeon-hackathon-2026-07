"""
agent_server.py — FastAPI server for the RTL Verification Agent (v2).

Endpoints:
  POST /api/run          — start a new agent session
  GET  /api/stream/{id}  — SSE stream of agent events
  GET  /api/sessions     — list past sessions (metadata only)
  GET  /api/download/{id}/{filename}  — download a generated .sv file
  GET  /api/config       — runtime config info (mode, model, etc.)

New in v2:
  - Session metadata tracks lint_status and functional_status separately.
  - final_result event updates both status fields atomically.
  - /api/config exposes max_lint_iterations, max_functional_iterations, max_total_iterations.
  - sim_build_error is a first-class event type (Amendment 2).
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import agent as agent_module
from config import (
    MOCK_MODE, DEPLOY_MODE, MODEL_NAME, VLLM_BASE_URL,
    MAX_LINT_ITERATIONS, MAX_FUNCTIONAL_ITERATIONS, MAX_TOTAL_ITERATIONS,
    MAX_ITERATIONS,
    SERVER_HOST, SERVER_PORT, WORKSPACE_DIR, FRONTEND_DIR,
    print_config,
)


# ─── App Setup ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="RTL Verification Agent",
    description=(
        "Autonomous two-tier SystemVerilog generation and verification powered by "
        "local LLMs on AMD ROCm hardware via vLLM. "
        "Tier 1: lint (verilator --lint-only). Tier 2: functional simulation (verilator --binary)."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── In-memory session store ──────────────────────────────────────────────────
# session_id → {"queue": asyncio.Queue, "meta": {...}}
_sessions: Dict[str, dict] = {}


# ─── Pydantic Models ──────────────────────────────────────────────────────────
class RunRequest(BaseModel):
    spec: str = Field(..., min_length=1, description="Natural-language hardware specification")
    max_iterations: Optional[int] = Field(None, ge=1, le=10)


class RunResponse(BaseModel):
    session_id: str
    started_at: float
    mock_mode: bool
    model: str


# ─── Background task: run agent, push events into queue ───────────────────────
async def _run_agent_task(spec: str, session_id: str, max_iter: int):
    q: asyncio.Queue = _sessions[session_id]["queue"]
    meta: dict = _sessions[session_id]["meta"]
    meta["status"] = "running"

    try:
        async for event in agent_module.run_agent(spec, session_id, max_iter):
            await q.put(event)

            # Track last generated code file for download
            if event["type"] in ("code_generated", "success"):
                meta["last_filename"] = event.get("filename")

            # Track total iteration count from every event that carries it
            if "total_iterations" in event:
                meta["total_iterations"] = event["total_iterations"]

            # Handle legacy success event (v1 compat)
            if event["type"] == "success":
                meta["status"] = "success"
                meta["lint_status"] = "PASSED"
                meta["functional_status"] = "PASSED"
                meta["iterations"] = event.get("iterations", 0)

            # v2 final_result — canonical completion event
            if event["type"] == "final_result":
                meta["lint_status"] = event.get("lint_status", "UNKNOWN")
                meta["functional_status"] = event.get("functional_status", "UNKNOWN")
                meta["final_dut"] = event.get("final_dut")
                meta["final_tb"] = event.get("final_tb")
                if meta["lint_status"] == "PASSED" and meta["functional_status"] == "PASSED":
                    meta["status"] = "success"
                elif meta["lint_status"] == "PASSED":
                    meta["status"] = "partial"
                else:
                    meta["status"] = "failed"

            # Track testbench for download
            if event["type"] == "testbench_generated":
                meta["last_tb_filename"] = event.get("filename")

    except Exception as exc:
        await q.put({"type": "error", "ts": time.time(), "message": str(exc)})
        meta["status"] = "error"
    finally:
        await q.put(None)  # Sentinel: stream is done
        meta["completed_at"] = time.time()


# ─── Routes ───────────────────────────────────────────────────────────────────
@app.post("/api/run", response_model=RunResponse)
async def run_agent(req: RunRequest, background_tasks: BackgroundTasks):
    """Launch a new two-tier agent session for the given hardware specification."""
    if len(req.spec.strip()) < 5:
        raise HTTPException(
            status_code=422,
            detail="Specification is too short. Please enter more than 5 characters to describe your hardware design."
        )
    session_id = str(uuid.uuid4())
    max_iter = req.max_iterations or MAX_ITERATIONS

    _sessions[session_id] = {
        "queue": asyncio.Queue(),
        "meta": {
            "session_id": session_id,
            "spec": req.spec,
            "started_at": time.time(),
            "status": "queued",
            "max_iterations": max_iter,
            "max_lint_iterations": MAX_LINT_ITERATIONS,
            "max_functional_iterations": MAX_FUNCTIONAL_ITERATIONS,
            "max_total_iterations": MAX_TOTAL_ITERATIONS,
            "mock_mode": MOCK_MODE,
            "model": MODEL_NAME,
            "last_filename": None,
            "last_tb_filename": None,
            "iterations": 0,
            "total_iterations": 0,
            "lint_status": "NOT_RUN",
            "functional_status": "NOT_RUN",
            "final_dut": None,
            "final_tb": None,
            "completed_at": None,
        },
    }

    background_tasks.add_task(
        _run_agent_task, req.spec, session_id, max_iter
    )

    meta = _sessions[session_id]["meta"]
    return RunResponse(
        session_id=session_id,
        started_at=meta["started_at"],
        mock_mode=MOCK_MODE,
        model=MODEL_NAME,
    )


@app.get("/api/stream/{session_id}")
async def stream_events(session_id: str, request: Request):
    """
    Server-Sent Events stream for a running agent session.
    Connect immediately after POST /api/run.
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    q: asyncio.Queue = session["queue"]

    async def _generator():
        # Send initial heartbeat so the browser opens the connection immediately
        yield "data: {\"type\": \"connected\"}\n\n"

        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            if event is None:
                yield "data: {\"type\": \"stream_end\"}\n\n"
                break

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/sessions")
async def list_sessions():
    """Return metadata for all sessions (no queue objects)."""
    return {
        sid: {k: v for k, v in s["meta"].items() if k != "final_dut" and k != "final_tb"}
        for sid, s in _sessions.items()
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Return metadata for a single session."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {k: v for k, v in session["meta"].items() if k not in ("final_dut", "final_tb")}


@app.get("/api/download/{session_id}/{filename}")
async def download_sv(session_id: str, filename: str):
    """Download a generated .sv file."""
    sv_path = WORKSPACE_DIR / filename
    if not sv_path.exists() or not filename.startswith(session_id):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path=str(sv_path),
        media_type="text/plain",
        filename=filename,
    )


@app.get("/api/config")
async def get_config():
    """Expose runtime configuration for the UI and benchmark harness."""
    from config import (
        ENABLE_PREFIX_CACHING, GPU_MEMORY_UTILIZATION,
        MAX_NUM_SEQS, QUANTIZATION, VLLM_DTYPE, TENSOR_PARALLEL_SIZE,
    )
    return {
        "mock_mode": MOCK_MODE,
        "deploy_mode": DEPLOY_MODE,
        "model": MODEL_NAME,
        "api_url": VLLM_BASE_URL if not MOCK_MODE else "N/A (mock mode)",
        "max_iterations": MAX_ITERATIONS,
        "max_lint_iterations": MAX_LINT_ITERATIONS,
        "max_functional_iterations": MAX_FUNCTIONAL_ITERATIONS,
        "max_total_iterations": MAX_TOTAL_ITERATIONS,
        "version": "2.0.0",
        # ROCm optimization settings (40-point rubric bucket)
        "rocm_optimizations": {
            "enable_prefix_caching": ENABLE_PREFIX_CACHING,
            "gpu_memory_utilization": GPU_MEMORY_UTILIZATION,
            "max_num_seqs": MAX_NUM_SEQS,
            "quantization": QUANTIZATION or "none (fp16)",
            "vllm_dtype": VLLM_DTYPE,
            "tensor_parallel_size": TENSOR_PARALLEL_SIZE,
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok", "mock_mode": MOCK_MODE, "version": "2.0.0"}


# ─── Serve Static Frontend ────────────────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print_config()
    uvicorn.run(
        "agent_server:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False,
        log_level="info",
    )

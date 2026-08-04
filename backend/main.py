"""
THEMIS FastAPI Backend — Main Application Entry Point
Team: Alchemy | AMD AI DevMaster Hackathon 2026
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager
import logging

from backend.config import get_settings
from backend.routers import review, benchmark

settings = get_settings()
logger = logging.getLogger("themis")

# ── API Key Auth ──────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Depends(api_key_header)) -> str:
    if api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


# ── App Lifecycle ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("THEMIS backend starting up...")
    logger.info(f"vLLM endpoint: {settings.vllm_base_url}")
    logger.info(f"Qdrant endpoint: {settings.qdrant_url}")
    yield
    logger.info("THEMIS backend shutting down...")


# ── App Instance ──────────────────────────────────────────────
app = FastAPI(
    title="THEMIS API",
    description="Agentic AI Code Review powered by AMD Radeon W7900D — Team Alchemy",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────
app.include_router(
    review.router,
    prefix="/api/review",
    tags=["review"],
    dependencies=[Depends(verify_api_key)],
)
app.include_router(
    benchmark.router,
    prefix="/api/benchmark",
    tags=["benchmark"],
)


# ── Health Check ──────────────────────────────────────────────
@app.get("/api/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/", tags=["system"])
async def root():
    return {
        "message": "THEMIS API — Agentic Code Review by Team Alchemy",
        "docs": "/api/docs",
        "health": "/health",
    }

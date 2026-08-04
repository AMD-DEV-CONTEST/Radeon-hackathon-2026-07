"""
LaunchKart AI 2.0 — Root API Router

Aggregates all versioned API routers into a single include.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.agents import router as agents_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.auth import router as auth_router
from app.api.v1.gpu import router as gpu_router
from app.api.v1.launches import router as launches_router
from app.api.v1.marketplace import router as marketplace_router
from app.api.v1.memory import router as memory_router
from app.api.v1.products import router as products_router
from app.api.v1.websocket import router as websocket_router

api_router = APIRouter()

# v1 routes
api_router.include_router(auth_router, prefix="/v1/auth", tags=["Authentication"])
api_router.include_router(products_router, prefix="/v1/products", tags=["Products"])
api_router.include_router(launches_router, prefix="/v1/launches", tags=["Launches"])
api_router.include_router(agents_router, prefix="/v1/agents", tags=["Agents"])
api_router.include_router(marketplace_router, prefix="/v1/marketplace", tags=["Marketplace"])
api_router.include_router(memory_router, prefix="/v1/memory", tags=["Memory"])
api_router.include_router(gpu_router, prefix="/v1/gpu", tags=["GPU"])
api_router.include_router(analytics_router, prefix="/v1/analytics", tags=["Analytics"])
api_router.include_router(websocket_router, prefix="/v1/ws", tags=["WebSocket"])

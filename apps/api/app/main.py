"""
Botverse X Platform - FastAPI Backend
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    _SLOWAPI_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency in constrained envs
    Limiter = None  # type: ignore[assignment]
    _rate_limit_exceeded_handler = None  # type: ignore[assignment]
    get_remote_address = None  # type: ignore[assignment]
    RateLimitExceeded = None  # type: ignore[assignment]
    _SLOWAPI_AVAILABLE = False

from app.core.config import settings
from app.api.v1 import api_router
from app.api.v1.endpoints.trainings_ws import router as trainings_ws_router

# 创建FastAPI应用
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
)

# 速率限制
if _SLOWAPI_AVAILABLE:
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gzip压缩
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 注册路由
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
# WebSocket 不挂 prefix (ws 一般用无版本前缀, 对齐 /ws/playback)
app.include_router(trainings_ws_router)


@app.on_event("startup")
async def _on_startup() -> None:
    """M0 启动时确保 sqlite 表存在, 方便首次运行."""
    # TODO(M2): 切 alembic 迁移, 去掉 create_all
    from app.models.database import init_db

    init_db()


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "Botverse X Platform API",
        "version": "1.0.0",
        "docs": f"{settings.API_V1_PREFIX}/docs",
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )

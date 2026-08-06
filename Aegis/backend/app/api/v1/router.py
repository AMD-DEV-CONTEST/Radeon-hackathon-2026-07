from fastapi import APIRouter

from app.api.v1.endpoints import auth, benchmarks, health, incidents, knowledge

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(benchmarks.router, prefix="/benchmarks", tags=["benchmarks"])

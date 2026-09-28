import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.api.rocm import router as rocm_router
from app.core.config import (
    CORS_ORIGINS,
    STORAGE_ROOT,
    demo_auth_enabled,
    validate_experimental_configuration,
)
from app.services.rocm_jobs import rocm_jobs
from app.services.store import store

logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}')


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_experimental_configuration()
    recovered = store.recover_interrupted_jobs()
    if recovered:
        logging.getLogger("brandpilot.api").warning(
            "recovered_interrupted_experimental_jobs count=%s", recovered
        )
    yield
    rocm_jobs.shutdown()


app = FastAPI(
    title="BrandPilot Local API",
    version="0.2.0",
    description="Mock workflow with an opt-in experimental AMD Radeon ROCm path",
    docs_url=None if demo_auth_enabled() else "/docs",
    redoc_url=None if demo_auth_enabled() else "/redoc",
    openapi_url=None if demo_auth_enabled() else "/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
app.include_router(router)
app.include_router(rocm_router)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.compute import router as compute_router
from app.routes.dense_search import router as dense_search_router
from app.config import settings
from app.database import Base, engine
from app.database import models  # noqa: F401
from app.routes.catalog import router as catalog_router
from app.routes.extraction import router as extraction_router
from app.routes.graph import router as graph_router
from app.routes.health import router as health_router
from app.routes.ingestion import router as ingestion_router
from app.routes.search import router as search_router
from app.routes.worlds import router as worlds_router
from app.routes.world_environment import router as world_environment_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()

app = FastAPI(
    title="NexusAI API",
    description="Control plane for the NexusAI Universal Knowledge Intelligence Platform.",
    version="0.8.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(catalog_router, prefix="/api")
app.include_router(worlds_router, prefix="/api")
app.include_router(world_environment_router, prefix="/api")
app.include_router(graph_router, prefix="/api")
app.include_router(ingestion_router, prefix="/api")
app.include_router(extraction_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(dense_search_router, prefix="/api")
app.include_router(compute_router, prefix="/api")
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.system import router as system_router
from app.config import config
from app.dependencies import get_services
from app.services.sample_data import ensure_sample_data


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.ensure_directories()
    ensure_sample_data(config.sample_data_dir)
    get_services()
    yield


app = FastAPI(
    title="AgentFlow AI",
    version="1.0.0",
    description="Offline autonomous multi-agent task automation platform powered by Ollama, FastAPI, SQLite, and ChromaDB.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix=config.api_prefix)
app.include_router(conversations_router, prefix=config.api_prefix)
app.include_router(documents_router, prefix=config.api_prefix)
app.include_router(system_router, prefix=config.api_prefix)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "name": config.project_name,
        "status": "ok",
        "docs": "/docs",
        "api_prefix": config.api_prefix,
        "frontend": "Run npm run dev for the React interface.",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

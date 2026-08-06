"""IndusMind AI — Unified FastAPI backend."""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .database import init_db
from .routers import auth, documents, chat, assets, rca, analytics, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    init_db()
    print("[IndusMind] Backend ready on http://localhost:8000")
    yield
    # Shutdown
    print("[IndusMind] Shutting down.")


app = FastAPI(title="IndusMind AI", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(assets.router)
app.include_router(rca.router)
app.include_router(analytics.router)

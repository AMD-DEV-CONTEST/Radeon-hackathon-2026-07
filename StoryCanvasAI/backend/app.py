from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from StoryCanvasAI.backend.jobs import JobManager
from StoryCanvasAI.backend.api import routes
from StoryCanvasAI.backend.config import MODEL_CONFIG
from StoryCanvasAI.backend.services.qwen import QwenService
from StoryCanvasAI.backend.services.flux import FluxService
from StoryCanvasAI.backend.services.kokoro import KokoroService

from StoryCanvasAI.backend.pipeline.story_pipeline import StoryPipeline

app = FastAPI(
    title="StoryCanvas AI",
    version="1.0.0"
)
app.state.job_manager = JobManager()
app.mount(
    "/generated",
    StaticFiles(directory="StoryCanvasAI/backend/generated"),
    name="generated",
)

print("=" * 60)
print("Loading AI models...")
print("=" * 60)

# -------------------------
# Load Qwen
# -------------------------
qwen = QwenService(MODEL_CONFIG["qwen"]["name"])
qwen.load()

# -------------------------
# Load FLUX
# -------------------------
flux = FluxService(MODEL_CONFIG["flux"]["name"])
flux.load()

# -------------------------
# Load Kokoro
# -------------------------
kokoro = KokoroService()

print("=" * 60)
print("Creating StoryPipeline...")
print("=" * 60)

pipeline = StoryPipeline(
    qwen,
    flux,
    kokoro
)

routes.pipeline = pipeline

app.include_router(routes.router)

app.mount(
    "/assets",
    StaticFiles(directory="StoryCanvasAI/frontend/dist/assets"),
    name="assets",
)

@app.get("/")
async def frontend():
    return FileResponse(
        "StoryCanvasAI/frontend/dist/index.html"
    )
    
print("=" * 60)
print("✅ StoryCanvas AI Backend Ready")
print("=" * 60)
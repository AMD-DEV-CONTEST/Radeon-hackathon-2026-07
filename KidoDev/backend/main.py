"""
Kido Dev — Agentic AI Backend
FastAPI app powering the multi-agent system.

Deployment Modes (DEPLOY_MODE env var):
  local  — Both frontend & backend on localhost (no tunnel)
  ngrok  — Backend exposed via ngrok tunnel
  cloud  — Deployed to cloud (Railway/Render/etc.)

Agents:
  TutorAgent            — Multi-turn, memory-aware coding hints
  CurriculumPlanner     — Personalized learning path generation
  BusinessInsightsAgent — Growth & platform optimization advisor

Inference:
  Engine — Ollama (Qwen2.5), vLLM (AMD ROCm), or HuggingFace Transformers
"""
import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.agent_routes import router as agent_router
from inference import qwen_client

# ─── Deploy Mode ──────────────────────────────────────────────────────────────

DEPLOY_MODE = os.getenv("DEPLOY_MODE", "local").lower()

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Kido Dev Agentic AI Backend",
    description="Multi-agent system with flexible deployment (local / ngrok / cloud)",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS ─────────────────────────────────────────────────────────────────────

origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
origins = [o.strip() for o in origins_raw.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(agent_router)

# ─── Root & Health ────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
async def root():
    return {
        "service": "Kido Dev Agentic AI Backend",
        "version": "3.0.0",
        "status": "online",
        "deploy_mode": DEPLOY_MODE,
        "agents": ["TutorAgent", "CurriculumPlannerAgent", "BusinessInsightsAgent"],
        "inference": {
            "mode": qwen_client.INFERENCE_MODE,
            "provider": qwen_client.get_active_provider(),
        },
        "docs": "/docs",
    }

@app.get("/health", tags=["Health"])
async def health():
    inference_healthy = await qwen_client.check_health()
    return {
        "status": "healthy",
        "deploy_mode": DEPLOY_MODE,
        "inference_ready": inference_healthy,
        "inference_provider": qwen_client.get_active_provider(),
    }


# ─── Startup Banner ──────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_banner():
    provider = qwen_client.get_active_provider()
    healthy = await qwen_client.check_health()
    
    torch_status = "INSTALLED (AMD ROCm)"
    try:
        import torch
        if not torch.cuda.is_available():
            torch_status = "INSTALLED (CPU only)"
    except ImportError:
        torch_status = "NOT INSTALLED (Missing in active venv!)"

    print()
    print("=" * 65)
    print("  Kido Dev — Agentic AI Backend v3.0.0")
    print(f"  Deploy Mode  : {DEPLOY_MODE}")
    print(f"  Inference    : {provider}")
    print(f"  PyTorch GPU  : {torch_status}")
    print(f"  Health       : {'READY' if healthy else 'NOT AVAILABLE (fallback active)'}")
    print(f"  Docs         : http://localhost:{os.getenv('PORT', 8000)}/docs")

    if "NOT INSTALLED" in torch_status:
        print()
        print("  ⚠️ WARNING: You are running Uvicorn inside an environment without PyTorch!")
        print("  👉 FIX: Run: source /workspace/workspace/KidoDev/llm-env/bin/activate")

    print("=" * 65)
    print()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

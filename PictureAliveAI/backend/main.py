"""Picture Alive AI — Backend V2 (Gemma 4 + Kokoro TTS)."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config import CORS_ORIGINS
from routes import router

app = FastAPI(
    title="Picture Alive AI",
    description="Multimodal AI: image → Gemma 4 → text / Kokoro TTS → audio",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"]
)

# ==========================================================================
# 🎯 THE DIRECTORY ENFORCEMENT SHIELD: Dynamic Folder Creation Engine
# ==========================================================================
# Look up your absolute local workspace path boundaries safely
TARGET_OUTPUT_DIR = "outputs"

if not os.path.exists(TARGET_OUTPUT_DIR):
    print(f"📁 [System Initialization]: Directory '{TARGET_OUTPUT_DIR}' not detected. Instantiating folder mesh on disk...")
    # Enforce directory creation on your drive partition cleanly with system permission mappings
    os.makedirs(TARGET_OUTPUT_DIR, exist_ok=True)
    
    

app.include_router(router)

# 🎯 THE BACKEND EXPOSURE FIX: Expose your folder as an active web route asset track
# This maps your local 'outputs' folder to become visible under the URL path prefix "/audio_output
app.mount("/audio_output", StaticFiles(directory="outputs"), name="audio_output")


@app.get("/health")
async def health():
    return {"status": "ok", "version": app.version}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

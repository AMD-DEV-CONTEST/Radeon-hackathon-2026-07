#!/usr/bin/env python3
"""ww gen-video server — Start a FastAPI server that generates videos from markdown content.

Usage:
    ww gen-video server [--port PORT] [--host HOST]

API:
    GET    /                        Frontend UI (HTML page)
    POST   /api/generate-content    Generate markdown content from a topic
    POST   /api/generate-video      Submit a video generation job (returns job_id immediately)
    GET    /api/jobs/{job_id}       Query job status
    GET    /api/jobs/{job_id}/download  Download the completed video
    GET    /api/jobs                List all jobs
    GET    /health                  Health check
"""

import argparse
import json
import os
import threading
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from fluxreel.gen_video.video import generate_video_from_content

app = FastAPI(
    title="FluxReel API",
    description="Generate 15s vertical short-form videos (9:16) from markdown or a topic.",
    version="1.0.0",
)


# ── Request / Response models ─────────────────────────────────────────────


class GenerateContentRequest(BaseModel):
    topic: str
    model: str | None = None
    openrouter_api_key: str | None = None
    language: str | None = None  # 'en', 'zh', or None/'auto'


class GenerateVideoRequest(BaseModel):
    content: str
    model: str | None = None
    image_model: str = "black-forest-labs/flux.2-pro"
    provider: str = "openrouter"  # "openrouter", "local", "sdcpp", "auto"
    local_variant: str = "schnell"  # "schnell", "dev", "2-dev"
    openrouter_api_key: str | None = None
    language: str | None = None  # 'en', 'zh', or None/'auto'
    upload: bool = False
    privacy: str = "public"


OUTPUT_DIR = Path("/tmp/gen_video_server_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job store: {job_id: {status, output_path, youtube_url, error, ...}}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ── Helper: generate markdown content from a topic ────────────────────────


DEFAULT_LLM_MODEL = "openrouter/auto-beta"


def _generate_content_from_topic(
    topic: str,
    model: str | None = None,
    api_key: str | None = None,
    language: str | None = None,
) -> str:
    """Use the LLM to generate a short markdown article explaining a topic.

    Args:
        topic: The topic to explain.
        model: LLM model override.
        api_key: OpenRouter API key (falls back to env var).
        language: 'en', 'zh', or None/'auto' (follow the topic's language).

    Returns the markdown content string.
    """
    from fluxreel.gen_video.video import _openrouter_chat

    if model is None:
        model = os.getenv("MODEL") or DEFAULT_LLM_MODEL

    lang = (language or "auto").strip().lower()
    if lang in ("zh", "chinese", "中文", "cn", "zh-cn"):
        lang_rule = "Write the entire article in Simplified Chinese (中文)."
    elif lang in ("en", "english", "en-us"):
        lang_rule = "Write the entire article in English."
    else:
        lang_rule = (
            "Write the entire article in the SAME language as the topic "
            "(if the topic is in Chinese, write in Chinese; if in English, "
            "write in English)."
        )

    sys_prompt = (
        "You are a tech explainer writer. Given a topic, write a concise markdown article "
        "(300-500 words) that explains the topic clearly and engagingly. "
        "Use headings (##), bullet points, and simple language. "
        "The article will be turned into a 5-scene short video (15s total), "
        "so make it scannable and visual. "
        "Focus on key concepts, insights, and takeaways. "
        "Avoid trademarked brand names where possible. "
        + lang_rule
    )

    user_prompt = (
        f"Write a short, engaging markdown article explaining this topic:\n\n{topic}"
    )

    print(f"Generating content for topic: {topic}")
    print(f"  Using LLM model: {model}")
    print(f"  Language: {lang}")
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

    raw = _openrouter_chat(messages, model=model, max_tokens=4096, api_key=api_key)
    print(f"Generated {len(raw)} chars of content")
    return raw


# ── Background job runner ────────────────────────────────────────────────


def _run_generation(
    job_id: str,
    content: str,
    output_path: str,
    model: str | None,
    image_model: str,
    provider: str,
    local_variant: str,
    api_key: str | None,
    upload: bool,
    privacy: str,
    language: str | None = None,
):
    """Run the video generation pipeline in a background thread."""
    with _jobs_lock:
        _jobs[job_id]["status"] = "processing"

    try:
        success, out_path, error_msg = generate_video_from_content(
            content,
            output_path,
            model=model,
            image_model=image_model,
            verbose=True,
            provider=provider,
            local_variant=local_variant,
            api_key=api_key,
            language=language,
        )
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = str(e)
            _jobs[job_id]["completed_at"] = time.time()
        return

    if not (success and out_path and os.path.isfile(out_path)):
        with _jobs_lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = error_msg or "Unknown error"
            _jobs[job_id]["completed_at"] = time.time()
        return

    # ── Upload to YouTube if requested ──────────────────────────────────
    youtube_url = None
    if upload:
        from fluxreel.gen_video.youtube_upload import (
            prepare_video_metadata,
            upload_video,
        )

        print("\n── Uploading to YouTube ──")
        try:
            title, description, tags = prepare_video_metadata(
                content, api_key=api_key,
            )
            print(f"Title: {title}")
            print(f"Tags: {', '.join(tags) if tags else '(none)'}")
            print(f"Privacy: {privacy}")
            print(
                f"Video: {out_path} ({os.path.getsize(out_path) / 1024 / 1024:.1f} MB)"
            )
            print()

            video_id, url = upload_video(
                out_path, title, description, tags, privacy=privacy
            )
            youtube_url = url
            print(f"\nYouTube URL: {youtube_url}")
        except Exception as e:
            print(f"YouTube upload failed: {e}")

    with _jobs_lock:
        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["output_path"] = out_path
        _jobs[job_id]["youtube_url"] = youtube_url
        _jobs[job_id]["completed_at"] = time.time()


# ── API endpoints ─────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "jobs": len(_jobs),
        "local_models": _check_local_models(),
    }


def _check_local_models() -> list[str]:
    """Check which local FLUX models are available."""
    available = []
    model_paths = {
        "schnell": "/root/FLUX.1-schnell",
        "dev": "/root/FLUX.1-dev",
        "2-dev": "/root/FLUX.2-dev",
    }
    for variant, path in model_paths.items():
        if os.path.isdir(path):
            available.append(variant)
    # stable-diffusion.cpp setup on this machine (FLUX.1-schnell Q4_0 GGUF)
    sd_bin = os.path.join("/mnt/data/zz/flux", "sd_cpp", "build", "bin", "sd-cli")
    sd_models = os.path.join("/mnt/data/zz/flux", "models")
    if os.path.isfile(sd_bin) and os.path.isdir(sd_models):
        available.append("sdcpp")
    return available


@app.post("/api/generate-content")
async def generate_content(req: GenerateContentRequest):
    """Generate markdown content explaining a topic using the LLM.

    Returns the generated markdown text which can then be passed to /api/generate-video.
    """
    if not req.topic.strip():
        raise HTTPException(status_code=400, detail="topic cannot be empty")

    try:
        content = _generate_content_from_topic(
            req.topic,
            model=req.model,
            api_key=req.openrouter_api_key,
            language=req.language,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"topic": req.topic, "content": content, "length": len(content)}


@app.post("/api/generate-video")
async def submit_job(req: GenerateVideoRequest):
    """Submit a video generation job.

    Returns immediately with a job_id. Poll GET /api/jobs/{job_id} for status,
    then download from GET /api/jobs/{job_id}/download when completed.

    The `provider` field selects the image generation backend:
      - "openrouter": Use OpenRouter API (default)
      - "local": Use the local AMD GPU with FLUX models
      - "sdcpp": Use local stable-diffusion.cpp (FLUX.1-schnell Q4_0 GGUF)
      - "auto": Try local first, fall back to OpenRouter
    """
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="content cannot be empty")

    job_id = str(uuid.uuid4())[:8]
    output_path = str(OUTPUT_DIR / f"gen_video_{job_id}.mp4")

    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "pending",
            "output_path": None,
            "youtube_url": None,
            "error": None,
            "provider": req.provider,
            "local_variant": req.local_variant,
            "created_at": time.time(),
            "completed_at": None,
        }

    thread = threading.Thread(
        target=_run_generation,
        args=(
            job_id,
            req.content,
            output_path,
            req.model,
            req.image_model,
            req.provider,
            req.local_variant,
            req.openrouter_api_key,
            req.upload,
            req.privacy,
            req.language,
        ),
        daemon=True,
    )
    thread.start()

    return {
        "job_id": job_id,
        "status": "pending",
        "provider": req.provider,
        "language": req.language,
        "status_url": f"/api/jobs/{job_id}",
        "download_url": f"/api/jobs/{job_id}/download",
    }


@app.get("/api/jobs")
async def list_jobs():
    """List all jobs with their current status."""
    with _jobs_lock:
        jobs = []
        for jid, job in _jobs.items():
            entry = {
                "job_id": jid,
                "status": job["status"],
                "provider": job.get("provider"),
                "created_at": job["created_at"],
                "completed_at": job["completed_at"],
                "error": job["error"],
                "youtube_url": job.get("youtube_url"),
            }
            jobs.append(entry)
        jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return {"jobs": jobs}


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get the current status of a video generation job."""
    with _jobs_lock:
        job = _jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "provider": job.get("provider"),
        "error": job["error"],
        "youtube_url": job.get("youtube_url"),
        "created_at": job["created_at"],
        "completed_at": job["completed_at"],
        "download_url": f"/api/jobs/{job_id}/download"
        if job["status"] == "completed"
        else None,
    }


@app.post("/api/check-key")
async def check_key(req: GenerateContentRequest):
    """Validate an OpenRouter API key by calling the models endpoint."""
    import requests as _requests
    key = req.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise HTTPException(status_code=400, detail="No API key provided")
    try:
        resp = _requests.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            return {
                "valid": True,
                "label": data.get("label", "")[:20] + "...",
                "usage": f"${data.get('usage', 0):.2f}",
            }
        else:
            return {"valid": False, "error": resp.json().get("error", {}).get("message", "Invalid key")}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@app.get("/api/jobs/{job_id}/download")
async def download_video(job_id: str):
    """Download the completed video for a job."""
    with _jobs_lock:
        job = _jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is '{job['status']}', not yet completed",
        )

    out_path = job["output_path"]
    if not out_path or not os.path.isfile(out_path):
        raise HTTPException(status_code=500, detail="Output file not found on disk")

    return FileResponse(
        out_path,
        media_type="video/mp4",
        filename=f"gen_video_{job_id}.mp4",
    )


# ── Frontend ──────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def frontend():
    """Serve the main frontend page."""
    html = _get_frontend_html()
    return HTMLResponse(html)


def _get_frontend_html() -> str:
    """Return the frontend HTML page as a string."""
    return FRONTEND_HTML


# ── Main ──────────────────────────────────────────────────────────────────


def main():
    """CLI entry point: parse args and start the uvicorn server."""
    try:
        from fluxreel.env import load_env as _le

        _le()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Start the gen-video API server.")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code changes (development)",
    )

    args = parser.parse_args()

    print("🌸 FluxReel server starting...")
    print(f"  Host: {args.host}")
    print(f"  Port: {args.port}")
    print(f"  Frontend: http://{args.host}:{args.port}/")
    print(f"  Submit:   POST http://{args.host}:{args.port}/api/generate-video")
    print(f"  Status:   GET  http://{args.host}:{args.port}/api/jobs/{{job_id}}")
    print(
        f"  Download: GET  http://{args.host}:{args.port}/api/jobs/{{job_id}}/download"
    )
    print(f"  Health:   GET  http://{args.host}:{args.port}/health")
    print()

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


# ══════════════════════════════════════════════════════════════════════════
# FRONTEND HTML — Embedded single-page application
# ══════════════════════════════════════════════════════════════════════════

FRONTEND_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FluxReel — AI Video Generator</title>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --surface-2: #21262d;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --accent-hover: #79c0ff;
    --green: #3fb950;
    --orange: #d29922;
    --red: #f85149;
    --radius: 8px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    font-size: 17px;
  }
  .container { max-width: 960px; margin: 0 auto; padding: 24px 16px; width: 100%; }
  header {
    border-bottom: 1px solid var(--border);
    padding: 16px 0;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  header h1 { font-size: 26px; font-weight: 600; }
  header .badge {
    font-size: 14px;
    background: var(--surface-2);
    color: var(--text-muted);
    padding: 2px 8px;
    border-radius: 12px;
  }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    margin-bottom: 16px;
  }
  .card-title {
    font-size: 17px;
    font-weight: 600;
    color: var(--text-muted);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  label {
    display: block;
    font-size: 16px;
    color: var(--text-muted);
    margin-bottom: 6px;
    font-weight: 500;
  }
  input, textarea, select {
    width: 100%;
    padding: 10px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 17px;
    font-family: inherit;
    transition: border-color 0.2s;
  }
  input:focus, textarea:focus, select:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(88,166,255,0.15);
  }
  textarea { resize: vertical; min-height: 100px; font-family: monospace; }
  select { cursor: pointer; appearance: auto; }
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 12px 22px;
    border: none;
    border-radius: 6px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    text-decoration: none;
  }
  .btn-primary {
    background: var(--accent);
    color: #fff;
  }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-secondary {
    background: var(--surface-2);
    color: var(--text);
  }
  .btn-secondary:hover { background: #30363d; }
  .btn-danger {
    background: var(--red);
    color: #fff;
  }
  .btn-danger:hover { opacity: 0.9; }
  .btn-sm { padding: 8px 14px; font-size: 14px; }
  .btn-group { display: flex; gap: 8px; flex-wrap: wrap; }
  .row { display: flex; gap: 16px; flex-wrap: wrap; }
  .col { flex: 1; min-width: 200px; }
  .mt-2 { margin-top: 12px; }
  .mb-2 { margin-bottom: 12px; }
  .text-muted { color: var(--text-muted); font-size: 15px; }
  .text-sm { font-size: 15px; }
  .status-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
  }
  .status-pending { background: rgba(210,153,34,0.15); color: var(--orange); }
  .status-processing { background: rgba(88,166,255,0.15); color: var(--accent); }
  .status-completed { background: rgba(63,185,80,0.15); color: var(--green); }
  .status-failed { background: rgba(248,81,73,0.15); color: var(--red); }
  .provider-selector {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .provider-option {
    flex: 1;
    min-width: 120px;
    padding: 12px 16px;
    border: 2px solid var(--border);
    border-radius: var(--radius);
    cursor: pointer;
    text-align: center;
    transition: all 0.2s;
    background: var(--bg);
  }
  .provider-option:hover { border-color: var(--text-muted); }
  .provider-option.selected {
    border-color: var(--accent);
    background: rgba(88,166,255,0.1);
  }
  .provider-option .name { font-size: 18px; font-weight: 600; }
  .provider-option .desc { font-size: 14px; color: var(--text-muted); margin-top: 4px; }
  .variant-selector {
    margin-top: 8px;
    display: none;
  }
  .variant-selector.visible { display: block; }
  .log-box {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    font-family: monospace;
    font-size: 14px;
    max-height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
    color: var(--text-muted);
  }
  .log-box .info { color: var(--accent); }
  .log-box .success { color: var(--green); }
  .log-box .error { color: var(--red); }
  .log-box .warn { color: var(--orange); }
  .hidden { display: none; }
  .flex { display: flex; }
  .flex-1 { flex: 1; }
  .gap-2 { gap: 8px; }
  .items-center { align-items: center; }
  .justify-between { justify-content: space-between; }
  .video-preview {
    max-width: 100%;
    border-radius: var(--radius);
    border: 1px solid var(--border);
  }
  .video-preview source { max-width: 100%; }
  .spinner {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (max-width: 640px) {
    .container { padding: 16px 12px; }
    .card { padding: 14px; }
  }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>🌸 FluxReel</h1>
    <span class="badge">v0.2</span>
    <span class="badge" id="status-badge">checking...</span>
  </header>

  <!-- API Key -->
  <div class="card" id="api-key-card">
    <div class="flex items-center justify-between" style="cursor:pointer;" onclick="toggleApiKey()">
      <div class="card-title" style="margin-bottom:0;">🔑 API Key</div>
      <span id="api-key-toggle" class="text-muted">▾</span>
    </div>
    <div id="api-key-body" class="mt-2">
      <div class="row">
        <div class="col flex-1">
          <label for="api-key-input">OpenRouter API Key</label>
          <div class="flex gap-2">
            <input type="password" id="api-key-input" placeholder="sk-or-v1-..." class="flex-1" autocomplete="off">
            <button class="btn btn-sm btn-secondary" onclick="checkApiKey()">Check</button>
          </div>
        </div>
      </div>
      <div id="api-key-status" class="mt-2 text-sm hidden"></div>
      <div class="text-muted text-sm mt-2">
        Get one at <a href="https://openrouter.ai/keys" target="_blank" style="color:var(--accent)">openrouter.ai/keys</a>.
        Saved in browser localStorage.
      </div>
    </div>
  </div>

  <!-- Step 1: Topic -->
  <div class="card">
    <div class="card-title">Step 1: Enter a Topic</div>
    <div class="row">
      <div class="col flex-1">
        <label for="topic-input">What do you want to explain?</label>
        <div class="flex gap-2">
          <input type="text" id="topic-input" placeholder="e.g. How GPUs work, RISC-V vs ARM, Attention Mechanism..." class="flex-1">
          <button class="btn btn-primary" id="btn-generate-content" onclick="generateContent()">Generate ✨</button>
        </div>
      </div>
    </div>
    <div id="content-status" class="mt-2 hidden">
      <span class="text-muted">Generating content...</span>
      <div class="spinner" style="display:inline-block;vertical-align:middle;margin-left:8px;"></div>
    </div>
  </div>

  <!-- Step 2: Content Preview -->
  <div class="card hidden" id="content-card">
    <div class="flex items-center justify-between mb-2">
      <div class="card-title" style="margin-bottom:0;">Step 2: Review &amp; Edit Content</div>
      <div class="text-sm text-muted" id="content-length"></div>
    </div>
    <textarea id="content-textarea" rows="8"></textarea>
    <div class="btn-group mt-2">
      <button class="btn btn-secondary btn-sm" onclick="regenerateContent()">🔄 Regenerate</button>
      <button class="btn btn-primary btn-sm" id="btn-use-content" onclick="showStep3()">Use This Content →</button>
    </div>
  </div>

  <!-- Step 3: Provider & Generate -->
  <div class="card hidden" id="generate-card">
    <div class="card-title">Step 3: Choose Image Provider &amp; Generate</div>

    <label>Image Generation Backend</label>
    <div class="provider-selector mb-2" id="provider-selector">
      <div class="provider-option selected" data-provider="openrouter" onclick="selectProvider(this)">
        <div class="name">☁️ OpenRouter</div>
        <div class="desc">black-forest-labs/flux.2-pro</div>
      </div>
      <div class="provider-option" data-provider="local" onclick="selectProvider(this)">
        <div class="name">🖥️ Local GPU</div>
        <div class="desc">AMD GPU · FLUX.1-schnell</div>
      </div>
      <div class="provider-option" data-provider="sdcpp" onclick="selectProvider(this)">
        <div class="name">🖨️ Stable Diffusion</div>
        <div class="desc">FLUX.1-schnell Q4_0 · sd-cpp</div>
      </div>
      <div class="provider-option" data-provider="auto" onclick="selectProvider(this)">
        <div class="name">⚡ Auto</div>
        <div class="desc">Local → OpenRouter fallback</div>
      </div>
    </div>

    <!-- Local variant selector -->
    <div class="variant-selector hidden" id="variant-selector">
      <label for="local-variant">Local FLUX Variant</label>
      <select id="local-variant">
        <option value="schnell">FLUX.1-schnell (fast, 4 steps)</option>
        <option value="dev">FLUX.1-dev (quality, 28 steps)</option>
        <option value="2-dev">FLUX.2-dev (latest, 28 steps)</option>
      </select>
    </div>

    <div class="flex items-center gap-2 mt-2">
      <label style="margin-bottom:0;white-space:nowrap;">Upload to YouTube?</label>
      <input type="checkbox" id="upload-checkbox" style="width:auto;">
    </div>

    <div class="btn-group mt-2">
      <button class="btn btn-primary" id="btn-generate-video" onclick="generateVideo()">
        🎬 Generate Video
      </button>
    </div>

    <div id="video-status" class="mt-2 hidden">
      <div class="flex items-center gap-2">
        <span class="spinner"></span>
        <span id="video-status-text">Starting...</span>
      </div>
      <div class="log-box mt-2" id="video-log"></div>
    </div>
  </div>

  <!-- Result -->
  <div class="card hidden" id="result-card">
    <div class="flex items-center justify-between">
      <div class="card-title" style="margin-bottom:0;">🎉 Video Ready</div>
      <div class="btn-group">
        <button class="btn btn-primary btn-sm" id="btn-download" onclick="downloadVideo()">⬇ Download</button>
        <button class="btn btn-secondary btn-sm" onclick="resetAll()">🔄 New Video</button>
      </div>
    </div>
    <div class="mt-2">
      <video class="video-preview" id="video-preview" controls style="max-height:500px;width:100%;">
        <source id="video-source" src="" type="video/mp4">
      </video>
    </div>
    <div id="youtube-link" class="mt-2 hidden">
      <a id="youtube-url" href="#" target="_blank" class="btn btn-sm btn-secondary">▶ Watch on YouTube</a>
    </div>
  </div>

  <!-- Jobs list -->
  <div class="card hidden" id="jobs-card">
    <div class="flex items-center justify-between">
      <div class="card-title" style="margin-bottom:0;">Recent Jobs</div>
      <button class="btn btn-sm btn-secondary" onclick="listJobs()">🔄 Refresh</button>
    </div>
    <div id="jobs-list" class="mt-2"></div>
  </div>
</div>

<script>
// ── State ────────────────────────────────────────────────────────────────
let currentJobId = null;
let pollInterval = null;
let selectedProvider = 'openrouter';
let currentVideoUrl = null;

// ── API Key ──────────────────────────────────────────────────────────────
function toggleApiKey() {
  const body = document.getElementById('api-key-body');
  const toggle = document.getElementById('api-key-toggle');
  const isHidden = body.style.display === 'none';
  body.style.display = isHidden ? 'block' : 'none';
  toggle.textContent = isHidden ? '▾' : '▸';
}

function getApiKey() {
  const key = document.getElementById('api-key-input').value.trim();
  return key || null;
}

async function checkApiKey() {
  const key = getApiKey();
  if (!key) { showApiKeyStatus('enter a key first', 'warn'); return; }
  showApiKeyStatus('checking...', 'info');
  try {
    const resp = await fetch('/api/check-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic: '', openrouter_api_key: key }),
    });
    const data = await resp.json();
    if (data.valid) {
      showApiKeyStatus('✅ Valid · ' + (data.usage || '') + ' used', 'success');
      localStorage.setItem('fluxreel_api_key', key);
    } else {
      showApiKeyStatus('❌ ' + (data.error || 'Invalid'), 'error');
    }
  } catch(e) {
    showApiKeyStatus('❌ ' + e.message, 'error');
  }
}

function showApiKeyStatus(msg, type) {
  const el = document.getElementById('api-key-status');
  el.classList.remove('hidden', 'info', 'success', 'warn', 'error');
  el.classList.add(type);
  el.textContent = msg;
  el.classList.remove('hidden');
}

function loadSavedApiKey() {
  const saved = localStorage.getItem('fluxreel_api_key');
  if (saved) {
    document.getElementById('api-key-input').value = saved;
  }
}

// ── Init ─────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  loadSavedApiKey();
  await checkHealth();
});

async function checkHealth() {
  try {
    const resp = await fetch('/health');
    const data = await resp.json();
    const badge = document.getElementById('status-badge');
    badge.textContent = `✨ online · ${data.jobs || 0} jobs`;
    badge.style.background = 'rgba(63,185,80,0.15)';
    badge.style.color = '#3fb950';
  } catch (e) {
    document.getElementById('status-badge').textContent = '⚠ offline';
  }
}

// ── Step 1: Generate Content ─────────────────────────────────────────────
async function generateContent() {
  const topic = document.getElementById('topic-input').value.trim();
  if (!topic) { alert('Please enter a topic.'); return; }

  const btn = document.getElementById('btn-generate-content');
  const status = document.getElementById('content-status');
  btn.disabled = true;
  status.classList.remove('hidden');

  try {
    const resp = await fetch('/api/generate-content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, openrouter_api_key: getApiKey() }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || resp.statusText);
    }
    const data = await resp.json();
    const textarea = document.getElementById('content-textarea');
    textarea.value = data.content;
    document.getElementById('content-length').textContent = `${data.length} chars`;
    document.getElementById('content-card').classList.remove('hidden');
    document.getElementById('content-card').scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    btn.disabled = false;
    status.classList.add('hidden');
  }
}

function regenerateContent() {
  generateContent();
}

// ── Step 2: Use Content ──────────────────────────────────────────────────
function showStep3() {
  document.getElementById('generate-card').classList.remove('hidden');
  document.getElementById('generate-card').scrollIntoView({ behavior: 'smooth' });
}

// ── Step 3: Provider Selector ────────────────────────────────────────────
function selectProvider(el) {
  document.querySelectorAll('.provider-option').forEach(o => o.classList.remove('selected'));
  el.classList.add('selected');
  selectedProvider = el.dataset.provider;

  const variantSelector = document.getElementById('variant-selector');
  if (selectedProvider === 'local' || selectedProvider === 'auto') {
    variantSelector.classList.add('visible');
  } else {
    variantSelector.classList.remove('visible');
  }
}

// ── Generate Video ───────────────────────────────────────────────────────
async function generateVideo() {
  const content = document.getElementById('content-textarea').value.trim();
  if (!content) { alert('No content to generate video from.'); return; }

  const btn = document.getElementById('btn-generate-video');
  const status = document.getElementById('video-status');
  const log = document.getElementById('video-log');

  btn.disabled = true;
  status.classList.remove('hidden');
  log.innerHTML = '';
  document.getElementById('video-status-text').textContent = 'Starting job...';
  addLog('info', 'Submitting video generation job...');

  const localVariant = document.getElementById('local-variant').value;
  const doUpload = document.getElementById('upload-checkbox').checked;

  try {
    const resp = await fetch('/api/generate-video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content,
        provider: selectedProvider,
        local_variant: localVariant,
        upload: doUpload,
        openrouter_api_key: getApiKey(),
      }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || resp.statusText);
    }
    const data = await resp.json();
    currentJobId = data.job_id;
    addLog('info', `Job submitted: ${currentJobId} (provider: ${data.provider})`);
    addLog('info', 'Polling for completion...');
    startPolling(currentJobId);
  } catch (e) {
    addLog('error', `Failed: ${e.message}`);
    btn.disabled = false;
  }
}

function startPolling(jobId) {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    try {
      const resp = await fetch(`/api/jobs/${jobId}`);
      if (!resp.ok) { throw new Error('Not found'); }
      const job = await resp.json();
      updateJobStatus(job);
      if (job.status === 'completed' || job.status === 'failed') {
        clearInterval(pollInterval);
        pollInterval = null;
        document.getElementById('btn-generate-video').disabled = false;
      }
    } catch (e) {
      addLog('error', `Poll error: ${e.message}`);
    }
  }, 3000);
}

function updateJobStatus(job) {
  const statusText = document.getElementById('video-status-text');
  const log = document.getElementById('video-log');
  const badge = document.createElement('span');

  if (job.status === 'pending') {
    statusText.textContent = '⏳ Waiting in queue...';
    addLog('info', 'Status: pending');
  } else if (job.status === 'processing') {
    statusText.textContent = '🔄 Generating video... (this may take a few minutes)';
    addLog('info', 'Status: processing');
  } else if (job.status === 'completed') {
    statusText.textContent = '✅ Video generated successfully!';
    addLog('success', 'Job completed!');
    currentVideoUrl = `/api/jobs/${job.job_id}/download`;
    showResult(job);
  } else if (job.status === 'failed') {
    statusText.textContent = '❌ Generation failed';
    addLog('error', `Failed: ${job.error || 'Unknown error'}`);
  }
}

function showResult(job) {
  document.getElementById('result-card').classList.remove('hidden');
  document.getElementById('video-source').src = currentVideoUrl;
  document.getElementById('video-preview').load();
  document.getElementById('result-card').scrollIntoView({ behavior: 'smooth' });

  if (job.youtube_url) {
    document.getElementById('youtube-link').classList.remove('hidden');
    document.getElementById('youtube-url').href = job.youtube_url;
  }

  document.getElementById('jobs-card').classList.remove('hidden');
  listJobs();
}

function downloadVideo() {
  if (currentVideoUrl) {
    const a = document.createElement('a');
    a.href = currentVideoUrl;
    a.download = `gen_video_${currentJobId}.mp4`;
    a.click();
  }
}

function resetAll() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  currentJobId = null;
  currentVideoUrl = null;
  document.getElementById('topic-input').value = '';
  document.getElementById('content-textarea').value = '';
  document.getElementById('content-card').classList.add('hidden');
  document.getElementById('generate-card').classList.add('hidden');
  document.getElementById('result-card').classList.add('hidden');
  document.getElementById('video-status').classList.add('hidden');
  document.getElementById('jobs-card').classList.add('hidden');
  document.getElementById('video-log').innerHTML = '';
  document.getElementById('btn-generate-video').disabled = false;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Jobs List ────────────────────────────────────────────────────────────
async function listJobs() {
  try {
    const resp = await fetch('/api/jobs');
    const data = await resp.json();
    const container = document.getElementById('jobs-list');
    if (!data.jobs || data.jobs.length === 0) {
      container.innerHTML = '<div class="text-muted text-sm">No jobs yet.</div>';
      return;
    }
    let html = '';
    data.jobs.slice(0, 10).forEach(j => {
      const statusClass = `status-${j.status}`;
      const time = new Date(j.created_at * 1000).toLocaleString();
      html += `<div class="flex items-center justify-between" style="padding:8px 0;border-bottom:1px solid var(--border);">
        <div>
          <span class="text-sm">${j.job_id}</span>
          <span class="text-muted text-sm"> · ${time}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="status-badge ${statusClass}">${j.status}</span>
          ${j.status === 'completed' ? `<button class="btn btn-sm btn-secondary" onclick="downloadJobVideo('${j.job_id}')">⬇</button>` : ''}
        </div>
      </div>`;
    });
    container.innerHTML = html;
  } catch (e) {
    document.getElementById('jobs-list').innerHTML = '<div class="text-muted text-sm">Failed to load jobs.</div>';
  }
}

async function downloadJobVideo(jobId) {
  try {
    const resp = await fetch(`/api/jobs/${jobId}/download`);
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `gen_video_${jobId}.mp4`;
    a.click();
  } catch (e) {
    alert('Download failed');
  }
}

// ── Log helper ───────────────────────────────────────────────────────────
function addLog(type, msg) {
  const log = document.getElementById('video-log');
  const line = document.createElement('div');
  line.classList.add(type);
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()

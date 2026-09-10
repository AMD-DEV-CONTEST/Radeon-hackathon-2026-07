"""FastAPI server — serves the Web UI with Stripe-powered credit system."""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import aiofiles

from mko.webui.llm_router import (
    BASE_URL,
    CONFIG_FILE,
    CREDIT_PACKS,
    STRIPE_PUBLISHABLE_KEY,
    ADMIN_CONFIG_FILE,
    UniversalLLM,
    add_credits,
    create_session_token,
    create_stripe_checkout_session,
    deduct_credits,
    get_credits,
    get_credit_cost,
    handle_stripe_webhook,
    hash_password,
    invalidate_session,
    is_admin_authenticated,
    load_refund_codes,
    load_users,
    redeem_demo_code,
    save_refund_codes,
    save_users,
    verify_password,
    rag_query,
    run_moe_agent,
    _get_api_key_for_provider,
)

# ─── Paths ────────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = STATIC_DIR.parent.parent / "data"

# ─── Lifespan ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ensure_admin_exists()
    yield


app = FastAPI(title="MKO Universal AI Agents", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── Models ───────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    messages: list
    model: Optional[str] = None
    provider: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2048
    stream: bool = True
    use_agents: bool = False
    username: str = "demo"
    agent_type: str = "general"


class SettingsUpdate(BaseModel):
    provider: Optional[str] = None
    api_keys: Optional[dict] = None
    model: Optional[str] = None


class RedeemCodeRequest(BaseModel):
    code: str
    username: str = "demo"


class StripeCheckoutRequest(BaseModel):
    pack_id: str
    username: str = "demo"
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class AdminLoginRequest(BaseModel):
    password: str


class AdminChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AdminRefundRequest(BaseModel):
    username: str
    credits: int
    reason: str = ""


class MoEConfigRequest(BaseModel):
    experts: list
    weights: Optional[dict] = None
    synthesis_temperature: float = 0.3


# ─── Core helpers ─────────────────────────────────────────────────────────


def ensure_admin_exists():
    """Set up admin config if it doesn't exist."""
    if not ADMIN_CONFIG_FILE.exists():
        ADMIN_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ADMIN_CONFIG_FILE.write_text(
            json.dumps(
                {
                    "password_hash": hash_password("admin123"),
                    "session_tokens": {},
                    "is_setup": False,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"provider": "groq", "api_keys": {}, "model": "llama-3.3-70b-versatile"}


def save_config(config: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


# ─── Pages ────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    path = STATIC_DIR / "index.html"
    if not path.exists():
        return HTMLResponse("<h1>index.html not found</h1>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page():
    path = STATIC_DIR / "pricing.html"
    if not path.exists():
        return HTMLResponse("<h1>pricing.html not found</h1>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    path = STATIC_DIR / "admin.html"
    if not path.exists():
        return HTMLResponse("<h1>admin.html not found</h1>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


# ─── Config / Settings ────────────────────────────────────────────────────


@app.get("/api/config")
async def get_config():
    cfg = load_config()
    return {
        "provider": cfg.get("provider", "groq"),
        "model": cfg.get("model", ""),
        "providers": {
            "groq": bool(cfg.get("api_keys", {}).get("groq")),
            "ollama": True,
            "huggingface": bool(cfg.get("api_keys", {}).get("huggingface")),
            "openai": bool(cfg.get("api_keys", {}).get("openai")),
            "anthropic": bool(cfg.get("api_keys", {}).get("anthropic")),
        },
        "moe_config": cfg.get("moe_config", {
            "experts": ["ollama"],
            "weights": {"ollama": 1.0},
            "synthesis_temperature": 0.3,
        }),
    }


@app.post("/api/config")
async def update_config(update: SettingsUpdate):
    cfg = load_config()
    if update.provider is not None:
        cfg["provider"] = update.provider
    if update.api_keys is not None:
        cfg.setdefault("api_keys", {}).update(update.api_keys)
    if update.model is not None:
        cfg["model"] = update.model
    save_config(cfg)
    return {"status": "ok"}


@app.get("/api/models")
async def list_models():
    return {
        "ollama": ["llama3.2", "llama3.1:8b", "mistral", "mixtral:8x7b"],
        "groq": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ],
        "huggingface": [
            "HuggingFaceH4/zephyr-7b-beta",
            "mistralai/Mistral-7B-Instruct-v0.3",
            "microsoft/Phi-3-mini-4k-instruct",
        ],
        "openai": ["gpt-4o-mini", "gpt-4o", "gpt-5.5", "gpt-sol-5.6"],
        "anthropic": [
            "claude-3-5-haiku-20241022",
            "claude-3-5-sonnet-20241022",
            "claude-fable-5",
            "claude-opus-4.8",
        ],
    }


# ─── Agents ───────────────────────────────────────────────────────────────


AGENTS = [
    {
        "id": "general",
        "name": "General Assistant",
        "icon": "🧠",
        "description": "All-purpose AI assistant for conversation and Q&A",
    },
    {
        "id": "planner",
        "name": "Planner",
        "icon": "📋",
        "description": "Breaks down tasks into actionable step-by-step plans",
    },
    {
        "id": "research",
        "name": "Researcher",
        "icon": "🔍",
        "description": "Deep-dive research with structured findings",
    },
    {
        "id": "reasoner",
        "name": "Reasoner",
        "icon": "⚖️",
        "description": "Logical analysis and critical thinking",
    },
    {
        "id": "actor",
        "name": "Actor",
        "icon": "⚡",
        "description": "Task execution and workflow automation",
    },
    {
        "id": "memory",
        "name": "Memory",
        "icon": "💾",
        "description": "Contextual recall and persistent state tracking",
    },
    {
        "id": "rag",
        "name": "RAG Agent",
        "icon": "📚",
        "description": "Retrieval-augmented generation from uploaded documents",
    },
    {
        "id": "moe",
        "name": "MoE Agent",
        "icon": "🔀",
        "description": "Mixture of Experts — parallel calls to multiple models",
    },
]

AGENT_SYSTEM_PROMPTS = {
    "general": "You are a helpful, knowledgeable AI assistant.",
    "planner": (
        "You are a task planning expert. Break down the user's request into "
        "a clear, actionable step-by-step plan with time estimates and dependencies."
    ),
    "research": (
        "You are a research analyst. Provide thorough, well-structured findings "
        "with sources, key takeaways, and supporting evidence."
    ),
    "reasoner": (
        "You are a logical reasoning engine. Analyze problems step by step, "
        "consider multiple perspectives, and provide well-reasoned conclusions."
    ),
    "actor": (
        "You are a task execution specialist. Provide clear, actionable "
        "steps and output results in a structured format."
    ),
    "memory": (
        "You are a memory and context tracking agent. Maintain awareness "
        "of the conversation history and provide relevant context."
    ),
    "rag": (
        "You are a RAG (Retrieval-Augmented Generation) specialist. "
        "Use the provided document context to answer questions accurately. "
        "If you don't know, say so rather than making up information."
    ),
    "moe": (
        "You are a Mixture of Experts synthesis gate. Combine and weigh "
        "multiple expert perspectives into a coherent, nuanced response."
    ),
}


@app.get("/api/agents")
async def list_agents():
    return {"agents": AGENTS}


# ─── Chat ─────────────────────────────────────────────────────────────────


@app.post("/api/chat")
async def chat(request: ChatRequest):
    from fastapi.responses import StreamingResponse

    username = request.username or "demo"
    agent_type = request.agent_type or "general"
    model = request.model
    provider = request.provider
    cfg = load_config()

    # Resolve provider/model from config if not specified
    if not provider:
        provider = cfg.get("provider", "groq")
    if not model:
        model = cfg.get("model", "llama-3.3-70b-versatile")

    # ── MoE Agent ──
    if agent_type == "moe":
        moe_cfg = cfg.get("moe_config", {})
        experts = moe_cfg.get("experts", ["ollama"])
        weights = moe_cfg.get("weights", {})
        synthesis_temp = moe_cfg.get("synthesis_temperature", 0.3)

        # Check credits for MoE
        cost = get_credit_cost(model, agent_type="moe") * len(experts)
        if not deduct_credits(username, cost, f"moe:{','.join(experts)}"):
            return StreamingResponse(
                _error_stream(f"Insufficient credits. Need {cost}, have {get_credits(username)}."),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        async def moe_stream():
            yield f"data: {json.dumps({'type': 'info', 'content': f'🔀 MoE Agent running {len(experts)} experts in parallel...'})}\n\n"
            async for event in run_moe_agent(
                messages=request.messages,
                experts=experts,
                weights=weights,
                synthesis_temperature=synthesis_temp,
                username=username,
                debug=True,
            ):
                yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            moe_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── RAG Agent ──
    if agent_type == "rag":
        user_msg = request.messages[-1]["content"] if request.messages else ""
        context = await rag_query(user_msg, username=username)
        system_prompt = AGENT_SYSTEM_PROMPTS.get("rag", "")
        augmented_messages = [
            {"role": "system", "content": f"{system_prompt}\n\nContext:\n{context}"},
            *request.messages,
        ]
        cost = get_credit_cost(model)
        if not deduct_credits(username, cost, f"rag:{model}"):
            return StreamingResponse(
                _error_stream(f"Insufficient credits. Need {cost}, have {get_credits(username)}."),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        async def rag_stream():
            api_key = _get_api_key_for_provider(provider)
            llm = UniversalLLM(provider=provider, api_key=api_key)
            async for token in llm.chat(
                messages=augmented_messages,
                model=model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ):
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            rag_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Standard Chat ──
    # Check credits
    cost = get_credit_cost(model, agent_type)
    if not deduct_credits(username, cost, f"{agent_type}:{model}"):
        return StreamingResponse(
            _error_stream(f"Insufficient credits. Need {cost}, have {get_credits(username)}."),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Add system prompt for the selected agent
    system_prompt = AGENT_SYSTEM_PROMPTS.get(agent_type, "")
    augmented_messages = request.messages
    if system_prompt:
        has_system = any(m.get("role") == "system" for m in request.messages)
        if not has_system:
            augmented_messages = [
                {"role": "system", "content": system_prompt},
                *request.messages,
            ]

    async def chat_stream():
        api_key = _get_api_key_for_provider(provider)
        llm = UniversalLLM(provider=provider, api_key=api_key)
        async for token in llm.chat(
            messages=augmented_messages,
            model=model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        ):
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        chat_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _error_stream(message: str):
    yield f"data: {json.dumps({'type': 'error', 'content': message})}\n\n"
    yield "data: [DONE]\n\n"


# ─── Credits ──────────────────────────────────────────────────────────────


@app.get("/api/credits")
async def get_user_credits(username: str = "demo"):
    return {"credits": get_credits(username), "username": username}


@app.post("/api/credits/redeem")
async def redeem_code(req: RedeemCodeRequest):
    result = redeem_demo_code(req.username, req.code)
    if result is None:
        return JSONResponse(
            {"status": "error", "message": "Invalid or already redeemed code."},
            status_code=400,
        )
    return {"status": "ok", "credits_added": result, "total": get_credits(req.username)}


# ─── Stripe ───────────────────────────────────────────────────────────────


@app.get("/api/stripe/config")
async def get_stripe_config():
    return {
        "publishable_key": STRIPE_PUBLISHABLE_KEY,
        "enabled": bool(os.environ.get("STRIPE_SECRET_KEY", "")),
        "packs": [
            {
                "id": p["id"],
                "name": p["name"],
                "credits": p["credits"],
                "bonus": p["bonus"],
                "price_usd": p["price_usd"],
                "popular": p["popular"],
            }
            for p in CREDIT_PACKS
        ],
    }


@app.post("/api/stripe/create-checkout-session")
async def create_checkout(req: StripeCheckoutRequest):
    if not os.environ.get("STRIPE_SECRET_KEY"):
        return JSONResponse(
            {"status": "error", "message": "Stripe is not configured. Set STRIPE_SECRET_KEY env variable."},
            status_code=400,
        )

    base_url = req.success_url or os.environ.get("BASE_URL", "http://127.0.0.1:49239")
    success_url = req.success_url or f"{base_url}/pricing?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = req.cancel_url or f"{base_url}/pricing?canceled=true"

    result = create_stripe_checkout_session(
        pack_id=req.pack_id,
        username=req.username,
        success_url=success_url,
        cancel_url=cancel_url,
    )

    if result is None:
        return JSONResponse(
            {"status": "error", "message": f"Unknown pack: {req.pack_id}"},
            status_code=400,
        )

    return {"status": "ok", "url": result["url"], "session_id": result["session_id"]}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    from mko.webui.llm_router import STRIPE_WEBHOOK_SECRET

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    event_type = handle_stripe_webhook(payload, sig_header)
    if event_type is None:
        raise HTTPException(status_code=400, detail="Webhook verification failed")

    return {"received": True, "type": event_type}


@app.get("/api/stripe/packs")
async def list_packs():
    return {
        "packs": [
            {
                "id": p["id"],
                "name": p["name"],
                "credits": p["credits"],
                "bonus": p["bonus"],
                "total_credits": p["credits"] + p["bonus"],
                "price_usd": p["price_usd"],
                "popular": p["popular"],
                "credits_per_dollar": round((p["credits"] + p["bonus"]) / p["price_usd"], 1),
            }
            for p in CREDIT_PACKS
        ]
    }


# ─── RAG ──────────────────────────────────────────────────────────────────


@app.post("/api/rag/ingest")
async def rag_ingest(file: UploadFile, username: str = "demo"):
    """Upload a document for RAG indexing."""
    try:
        from qdrant_client import QdrantClient
        from sentence_transformers import SentenceTransformer

        content = await file.read()
        text = content.decode("utf-8", errors="replace")

        # Chunk text into segments
        chunks = []
        chunk_size = 500
        words = text.split()
        for i in range(0, len(words), chunk_size):
            chunks.append(" ".join(words[i : i + chunk_size]))

        if not chunks:
            return JSONResponse(
                {"status": "error", "message": "No readable text found in file."},
                status_code=400,
            )

        # Embed and index
        model = SentenceTransformer("all-MiniLM-L6-v2")
        client = QdrantClient(path=str(DATA_DIR / "qdrant_db"))

        collection_name = f"rag_{username}_{int(time.time())}"
        from qdrant_client.models import Distance, VectorParams

        client.recreate_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )

        vectors = model.encode(chunks).tolist()
        points = [
            {
                "id": i,
                "vector": vectors[i],
                "payload": {"text": chunks[i], "source": file.filename},
            }
            for i in range(len(chunks))
        ]
        client.upsert(collection_name=collection_name, points=points)

        return {
            "status": "ok",
            "chunks": len(chunks),
            "collection": collection_name,
            "filename": file.filename,
        }

    except ImportError as e:
        return JSONResponse(
            {"status": "error", "message": f"Missing dependency: {e.name}"},
            status_code=400,
        )
    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500,
        )


@app.get("/api/rag/collections")
async def list_rag_collections(username: str = "demo"):
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(path=str(DATA_DIR / "qdrant_db"))
        collections = client.get_collections().collections
        return {
            "collections": [
                {"name": c.name, "count": client.count(c.name).count}
                for c in collections
            ]
        }
    except ImportError:
        return {"collections": [], "error": "qdrant-client not installed"}
    except Exception as e:
        return {"collections": [], "error": str(e)}


# ─── Admin ────────────────────────────────────────────────────────────────


@app.post("/api/admin/login")
async def admin_login(req: AdminLoginRequest):
    if not ADMIN_CONFIG_FILE.exists():
        ensure_admin_exists()

    config = json.loads(ADMIN_CONFIG_FILE.read_text(encoding="utf-8"))
    if not verify_password(req.password, config["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_session_token()
    config.setdefault("session_tokens", {})[token] = time.time()
    config["is_setup"] = True
    ADMIN_CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")

    return {"status": "ok", "token": token, "is_setup": True}


@app.post("/api/admin/logout")
async def admin_logout(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    invalidate_session(token)
    return {"status": "ok"}


@app.post("/api/admin/change-password")
async def admin_change_password(req: AdminChangePasswordRequest, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not is_admin_authenticated(token):
        raise HTTPException(status_code=401, detail="Not authenticated")

    config = json.loads(ADMIN_CONFIG_FILE.read_text(encoding="utf-8"))
    if not verify_password(req.current_password, config["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    config["password_hash"] = hash_password(req.new_password)
    ADMIN_CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return {"status": "ok", "message": "Password changed successfully"}


@app.get("/api/admin/users")
async def admin_get_users(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not is_admin_authenticated(token):
        raise HTTPException(status_code=401, detail="Not authenticated")

    users = load_users()
    return {
        "users": [
            {
                "username": u,
                "credits": data.get("credits", 0),
                "total_purchased": data.get("total_purchased", 0),
                "requests": data.get("requests", {}),
                "created_at": data.get("created_at", 0),
            }
            for u, data in users.items()
        ]
    }


@app.post("/api/admin/refund")
async def admin_issue_refund(req: AdminRefundRequest, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not is_admin_authenticated(token):
        raise HTTPException(status_code=401, detail="Not authenticated")

    add_credits(req.username, req.credits, source="refund")

    # Also log as refund code
    refunds = load_refund_codes()
    code = f"REFUND-{req.username}-{int(time.time())}"
    refunds[code] = {
        "credits": req.credits,
        "reason": req.reason,
        "issued_by": "admin",
        "issued_at": time.time(),
        "redeemed": True,
        "redeemed_by": req.username,
        "redeemed_at": time.time(),
    }
    save_refund_codes(refunds)

    return {
        "status": "ok",
        "message": f"Added {req.credits} credits to {req.username}",
        "code": code,
    }


@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not is_admin_authenticated(token):
        raise HTTPException(status_code=401, detail="Not authenticated")

    users = load_users()
    total_users = len(users)
    total_credits = sum(u.get("credits", 0) for u in users.values())
    total_purchased = sum(u.get("total_purchased", 0) for u in users.values())
    total_requests = sum(
        sum(r.values()) for u in users.values() for r in [u.get("requests", {})]
    )

    # Per-model stats
    model_stats = {}
    for u, data in users.items():
        for model, count in data.get("requests", {}).items():
            if model not in model_stats:
                model_stats[model] = {"users": set(), "total_requests": 0}
            model_stats[model]["users"].add(u)
            model_stats[model]["total_requests"] += count

    return {
        "total_users": total_users,
        "total_credits": total_credits,
        "total_purchased": total_purchased,
        "total_requests": total_requests,
        "per_model": {
            m: {"users": len(d["users"]), "requests": d["total_requests"]}
            for m, d in sorted(model_stats.items())
        },
    }


# ─── MoE Config ───────────────────────────────────────────────────────────


@app.get("/api/moe/config")
async def get_moe_config():
    cfg = load_config()
    return cfg.get("moe_config", {
        "experts": ["ollama"],
        "weights": {"ollama": 1.0},
        "synthesis_temperature": 0.3,
    })


@app.post("/api/moe/config")
async def set_moe_config(config: MoEConfigRequest):
    cfg = load_config()
    weights = config.weights or {e: 1.0 for e in config.experts}
    cfg["moe_config"] = {
        "experts": config.experts,
        "weights": weights,
        "synthesis_temperature": config.synthesis_temperature,
    }
    save_config(cfg)
    return {"status": "ok"}


# ─── Benchmark ────────────────────────────────────────────────────────────


@app.post("/api/benchmark/run")
async def run_benchmark():
    """Run a simple compute benchmark with progress SSE."""
    from fastapi.responses import StreamingResponse
    import queue
    import threading
    import time as time_module
    import numpy as np

    def run_compute_bench(progress_queue: queue.Queue):
        """Run matrix multiplication benchmarks."""
        results = []
        sizes = [500, 1000, 2000, 3000]

        progress_queue.put({"type": "progress", "value": 0, "label": "Starting benchmark..."})

        for i, size in enumerate(sizes):
            progress_queue.put({
                "type": "progress",
                "value": (i / len(sizes)) * 100,
                "label": f"Testing {size}x{size} matrices...",
            })

            # CPU benchmark
            a_cpu = np.random.randn(size, size).astype(np.float32)
            b_cpu = np.random.randn(size, size).astype(np.float32)
            start = time_module.perf_counter()
            _ = a_cpu @ b_cpu
            cpu_time = (time_module.perf_counter() - start) * 1000

            # GPU benchmark if available
            gpu_time = None
            gpu_available = False
            try:
                import torch
                if torch.cuda.is_available():
                    gpu_available = True
                    a_gpu = torch.randn(size, size, device="cuda", dtype=torch.float32)
                    b_gpu = torch.randn(size, size, device="cuda", dtype=torch.float32)
                    torch.cuda.synchronize()
                    start = time_module.perf_counter()
                    _ = a_gpu @ b_gpu
                    torch.cuda.synchronize()
                    gpu_time = (time_module.perf_counter() - start) * 1000
                elif hasattr(torch, "hip") and torch.hip.is_available():
                    gpu_available = True
                    a_gpu = torch.randn(size, size, device="hip", dtype=torch.float32)
                    b_gpu = torch.randn(size, size, device="hip", dtype=torch.float32)
                    torch.hip.synchronize()
                    start = time_module.perf_counter()
                    _ = a_gpu @ b_gpu
                    torch.hip.synchronize()
                    gpu_time = (time_module.perf_counter() - start) * 1000
            except Exception:
                pass

            results.append({
                "size": size,
                "cpu_ms": round(cpu_time, 2),
                "gpu_ms": round(gpu_time, 2) if gpu_time else None,
                "speedup": round(cpu_time / gpu_time, 2) if gpu_time else None,
            })

        # GPU info
        gpu_name = "CPU Only"
        gpu_memory = 0
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1e9
            elif hasattr(torch, "hip") and torch.hip.is_available():
                gpu_name = torch.hip.get_device_name(0)
                gpu_memory = torch.hip.get_device_properties(0).total_memory / 1e9
        except Exception:
            pass

        avg_speedup = (
            round(
                sum(r["speedup"] for r in results if r["speedup"]),
                2,
            )
            if any(r["speedup"] for r in results)
            else 1.0
        )

        progress_queue.put({"type": "progress", "value": 100, "label": "Complete!"})

        final = {
            "backend": "cuda" if gpu_available else "rocm" if "hip" in str(gpu_name).lower() else "cpu",
            "gpu_name": gpu_name,
            "gpu_memory_gb": round(gpu_memory, 1),
            "matrix_results": results,
            "avg_speedup": avg_speedup,
            "llm_est_tokens_per_sec": round(avg_speedup * 30, 1),
            "timestamp": time_module.time(),
        }
        progress_queue.put({"type": "done", "data": final})

    q: queue.Queue = queue.Queue()
    thread = threading.Thread(target=run_compute_bench, args=(q,), daemon=True)
    thread.start()

    async def progress_stream():
        while True:
            try:
                item = q.get(timeout=0.5)
                if item["type"] == "done":
                    yield f"data: {json.dumps({'type': 'benchmark_result', 'data': item['data']})}\n\n"
                    break
                yield f"data: {json.dumps(item)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                continue

    return StreamingResponse(
        progress_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/benchmark/providers")
async def run_provider_benchmark():
    """Run latency benchmarks against configured providers."""
    from fastapi.responses import StreamingResponse
    import httpx
    import time as time_module

    cfg = load_config()
    api_keys = cfg.get("api_keys", {})

    providers_to_test = [
        {"id": "ollama", "name": "Ollama", "url": "http://127.0.0.1:11434", "model": "llama3.2"},
        {"id": "groq", "name": "Groq", "model": "llama-3.3-70b-versatile",
         "api_key": api_keys.get("groq", "")},
        {"id": "openai", "name": "OpenAI", "model": "gpt-4o-mini",
         "api_key": api_keys.get("openai", "")},
    ]

    async def provider_stream():
        results = []
        for i, prov in enumerate(providers_to_test):
            pct = (i / len(providers_to_test)) * 100
            label_text = f"Testing {prov['name']}..."
            yield f"data: {json.dumps({'type': 'progress', 'value': pct, 'label': label_text})}\n\n"

            result = {
                "provider": prov["id"],
                "model": prov["model"],
                "status": "pending",
                "time_to_first_token_ms": None,
                "total_time_ms": None,
                "error": None,
            }

            try:
                start = time_module.perf_counter()
                first_token_time = None
                received_any = False

                if prov["id"] == "ollama":
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        async with client.stream(
                            "POST",
                            f"{prov['url']}/api/chat",
                            json={
                                "model": prov["model"],
                                "messages": [{"role": "user", "content": "Say hello in one word."}],
                                "stream": True,
                                "options": {"temperature": 0},
                            },
                        ) as resp:
                            async for line in resp.aiter_lines():
                                if not line.strip():
                                    continue
                                if first_token_time is None:
                                    first_token_time = (time_module.perf_counter() - start) * 1000
                                try:
                                    chunk = json.loads(line)
                                    if chunk.get("done"):
                                        break
                                    token = chunk.get("message", {}).get("content", "")
                                    if token.strip():
                                        received_any = True
                                except json.JSONDecodeError:
                                    pass

                elif prov["id"] == "groq":
                    if not prov["api_key"]:
                        result["status"] = "error"
                        result["error"] = "No API key"
                    else:
                        async with httpx.AsyncClient(timeout=15.0) as client:
                            async with client.stream(
                                "POST",
                                "https://api.groq.com/openai/v1/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {prov['api_key']}",
                                    "Content-Type": "application/json",
                                },
                                json={
                                    "model": prov["model"],
                                    "messages": [{"role": "user", "content": "Say hello in one word."}],
                                    "temperature": 0,
                                    "max_tokens": 10,
                                    "stream": True,
                                },
                            ) as resp:
                                async for line in resp.aiter_lines():
                                    if not line.startswith("data: "):
                                        continue
                                    data = line[6:].strip()
                                    if data == "[DONE]":
                                        break
                                    if first_token_time is None:
                                        first_token_time = (time_module.perf_counter() - start) * 1000
                                    try:
                                        chunk = json.loads(data)
                                        token = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                        if token.strip():
                                            received_any = True
                                    except json.JSONDecodeError:
                                        pass

                elif prov["id"] == "openai":
                    if not prov["api_key"]:
                        result["status"] = "error"
                        result["error"] = "No API key"
                    else:
                        async with httpx.AsyncClient(timeout=15.0) as client:
                            async with client.stream(
                                "POST",
                                "https://api.openai.com/v1/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {prov['api_key']}",
                                    "Content-Type": "application/json",
                                },
                                json={
                                    "model": prov["model"],
                                    "messages": [{"role": "user", "content": "Say hello in one word."}],
                                    "temperature": 0,
                                    "max_tokens": 10,
                                    "stream": True,
                                },
                            ) as resp:
                                async for line in resp.aiter_lines():
                                    if not line.startswith("data: "):
                                        continue
                                    data = line[6:].strip()
                                    if data == "[DONE]":
                                        break
                                    if first_token_time is None:
                                        first_token_time = (time_module.perf_counter() - start) * 1000
                                    try:
                                        chunk = json.loads(data)
                                        token = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                        if token.strip():
                                            received_any = True
                                    except json.JSONDecodeError:
                                        pass

                total_time = (time_module.perf_counter() - start) * 1000

                if received_any:
                    result["status"] = "ok"
                    result["time_to_first_token_ms"] = round(first_token_time or total_time, 1)
                    result["total_time_ms"] = round(total_time, 1)
                else:
                    result["status"] = "error"
                    result["error"] = result.get("error") or "No response received"

            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)[:100]

            results.append(result)

        yield f"data: {json.dumps({'type': 'progress', 'value': 100, 'label': 'Benchmark complete!'})}\n\n"
        yield f"data: {json.dumps({'type': 'provider_benchmark_result', 'data': results})}\n\n"

    return StreamingResponse(
        provider_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

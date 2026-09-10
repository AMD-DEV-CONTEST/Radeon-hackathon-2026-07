"""LLM Router — provider routing, credit system with Stripe, user management."""

import json
import os
import time
import uuid
import hashlib
import hmac
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import stripe

# ─── Paths ────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"
CONFIG_FILE = DATA_DIR / "webui_config.json"
ADMIN_CONFIG_FILE = DATA_DIR / "admin_config.json"

# ─── Stripe Configuration ─────────────────────────────────────────────────
# Set your Stripe secret key via environment variable or .env
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get(
    "STRIPE_PUBLISHABLE_KEY",
    "pk_test_XXXXXXXXXXXXXXXXXXXXXXXX",  # Replace with your publishable key
)
STRIPE_PRICE_IDS = {}  # Will be populated by admin or env vars

# Base URL for Stripe redirects (configured per-request)
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:49239")

stripe.api_key = STRIPE_SECRET_KEY

# ─── Credit Packs ─────────────────────────────────────────────────────────
CREDIT_PACKS = [
    {
        "id": "starter",
        "name": "Starter Pack",
        "credits": 500,
        "price_usd": 10,
        "bonus": 0,
        "popular": False,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_STARTER", ""),
    },
    {
        "id": "essential",
        "name": "Essential Pack",
        "credits": 1500,
        "price_usd": 25,
        "bonus": 200,
        "popular": True,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_ESSENTIAL", ""),
    },
    {
        "id": "pro",
        "name": "Pro Pack",
        "credits": 3500,
        "price_usd": 50,
        "bonus": 500,
        "popular": False,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_PRO", ""),
    },
    {
        "id": "power",
        "name": "Power Pack",
        "credits": 8000,
        "price_usd": 100,
        "bonus": 1500,
        "popular": False,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_POWER", ""),
    },
    {
        "id": "ultimate",
        "name": "Ultimate Pack",
        "credits": 15000,
        "price_usd": 150,
        "bonus": 5000,
        "popular": False,
        "stripe_price_id": os.environ.get("STRIPE_PRICE_ULTIMATE", ""),
    },
]

# ─── Model Credit Costs (per request) ─────────────────────────────────────
MODEL_CREDIT_COSTS = {
    # Free / local models
    "ollama": 1,
    "groq": 1,
    "huggingface": 1,
    # Paid models
    "gpt-5.5": 5,
    "gpt-sol-5.6": 10,
    "claude-fable-5": 15,
    "claude-opus-4.8": 20,
    # MoE base cost
    "moe": 3,
}

# ─── Demo / Refund Codes ──────────────────────────────────────────────────
DEMO_CODES = {
    "MKO-TRIAL-50": 50,
    "MKO-STARTER-500": 500,
    "MKO-ESSENTIAL-1700": 1700,
    "MKO-PRO-4000": 4000,
    "MKO-POWER-9500": 9500,
    "MKO-ULTIMATE-20000": 20000,
}

REFUND_CODES_FILE = DATA_DIR / "refund_codes.json"


def load_refund_codes() -> dict:
    if REFUND_CODES_FILE.exists():
        return json.loads(REFUND_CODES_FILE.read_text(encoding="utf-8"))
    return {}


def save_refund_codes(codes: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REFUND_CODES_FILE.write_text(
        json.dumps(codes, indent=2), encoding="utf-8"
    )


# ─── User Management ──────────────────────────────────────────────────────


def load_users() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {}


def save_users(users: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


def get_or_create_user(username: str) -> dict:
    """Get user dict, creating a skeleton if they don't exist yet."""
    users = load_users()
    if username not in users:
        users[username] = {
            "credits": 0,
            "total_purchased": 0,
            "requests": {},
            "created_at": time.time(),
            "demo_codes_redeemed": [],
        }
        save_users(users)
    return users[username]


def get_credits(username: str) -> int:
    user = get_or_create_user(username)
    return user.get("credits", 0)


def add_credits(username: str, amount: int, source: str = "purchase") -> int:
    users = load_users()
    if username not in users:
        users[username] = {
            "credits": 0,
            "total_purchased": 0,
            "requests": {},
            "created_at": time.time(),
        }
    users[username]["credits"] = users[username].get("credits", 0) + amount
    if source == "purchase":
        users[username]["total_purchased"] = (
            users[username].get("total_purchased", 0) + amount
        )
    save_users(users)
    return users[username]["credits"]


def deduct_credits(username: str, amount: int, model: str) -> bool:
    """Deduct credits if sufficient. Returns True on success."""
    users = load_users()
    if username not in users:
        return False
    if users[username].get("credits", 0) < amount:
        return False
    users[username]["credits"] -= amount
    # Track per-model usage
    if "requests" not in users[username]:
        users[username]["requests"] = {}
    users[username]["requests"][model] = (
        users[username]["requests"].get(model, 0) + 1
    )
    save_users(users)
    return True


def log_user_request(username: str, model: str, credits_used: int) -> None:
    """Log a request for analytics without deducting (deduct separately)."""
    users = load_users()
    if username in users:
        if "requests" not in users[username]:
            users[username]["requests"] = {}
        users[username]["requests"][model] = (
            users[username]["requests"].get(model, 0) + 1
        )
    save_users(users)


def redeem_demo_code(username: str, code: str) -> Optional[int]:
    """Redeem a demo code. Returns credits added or None if invalid/already used."""
    code = code.strip()
    if code not in DEMO_CODES:
        # Check refund codes too
        refunds = load_refund_codes()
        if code in refunds and not refunds[code].get("redeemed", False):
            credits = refunds[code]["credits"]
            refunds[code]["redeemed"] = True
            refunds[code]["redeemed_at"] = time.time()
            refunds[code]["redeemed_by"] = username
            save_refund_codes(refunds)
            add_credits(username, credits, source="refund")
            return credits
        return None

    user = get_or_create_user(username)
    redeemed = user.get("demo_codes_redeemed", [])
    if code in redeemed:
        return None  # Already used

    credits = DEMO_CODES[code]
    add_credits(username, credits, source="demo")
    users = load_users()
    users[username].setdefault("demo_codes_redeemed", []).append(code)
    save_users(users)
    return credits


# ─── Stripe Helpers ───────────────────────────────────────────────────────


def create_stripe_checkout_session(
    pack_id: str,
    username: str,
    success_url: str,
    cancel_url: str,
) -> Optional[dict]:
    """Create a Stripe Checkout Session for a credit pack. Returns session dict or None."""
    if not STRIPE_SECRET_KEY:
        return None

    pack = next((p for p in CREDIT_PACKS if p["id"] == pack_id), None)
    if not pack:
        return None

    # Use Stripe Price ID if configured, otherwise create a one-time price
    if pack.get("stripe_price_id"):
        price_id = pack["stripe_price_id"]
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=username,
            metadata={
                "pack_id": pack_id,
                "username": username,
                "credits": pack["credits"] + pack["bonus"],
            },
        )
        return {"session_id": session.id, "url": session.url}

    # Dynamic price (for development/testing without Stripe dashboard setup)
    unit_amount = int(pack["price_usd"] * 100)  # cents
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"MKO {pack['name']}",
                        "description": f"{pack['credits']} credits"
                        + (f" + {pack['bonus']} bonus" if pack["bonus"] else ""),
                    },
                    "unit_amount": unit_amount,
                },
                "quantity": 1,
            }
        ],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=username,
        metadata={
            "pack_id": pack_id,
            "username": username,
            "credits": pack["credits"] + pack["bonus"],
        },
    )
    return {"session_id": session.id, "url": session.url}


def handle_stripe_webhook(payload: bytes, sig_header: str) -> Optional[str]:
    """Handle Stripe webhook event. Returns event type string or None on failure."""
    if not STRIPE_WEBHOOK_SECRET:
        # ⚠️ INSECURE FALLBACK: No signature verification!
        # Anyone can fake a checkout.session.completed event and credit themselves.
        # Set STRIPE_WEBHOOK_SECRET in production to verify webhook signatures.
        import logging
        logging.warning(
            "STRIPE_WEBHOOK_SECRET is not set! Webhook signatures will NOT be verified. "
            "This is INSECURE — set STRIPE_WEBHOOK_SECRET in production."
        )
        try:
            event = json.loads(payload)
            return event.get("type")
        except (json.JSONDecodeError, KeyError):
            return None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return None

    event_type = event.get("type")

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        username = session.get("metadata", {}).get("username", "")
        credits = int(session.get("metadata", {}).get("credits", 0))
        if username and credits > 0:
            add_credits(username, credits, source="stripe_purchase")
        return event_type

    if event_type == "checkout.session.expired":
        return event_type

    return event_type


# ─── Provider Routing ─────────────────────────────────────────────────────


class UniversalLLM:
    """Minimal LLM wrapper that streams from configured providers."""

    def __init__(self, provider: str = "groq", api_key: str = ""):
        self.provider = provider
        self.api_key = api_key

    async def chat(
        self,
        messages: list,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = True,
    ):
        """Stream chat completion from the configured provider.

        Yields token strings as they arrive.
        Falls back to a mock response when no API key is configured.
        """
        import httpx

        provider = self.provider.lower()
        # ── Ollama (local) ──
        if provider == "ollama":
            mdl = model or "llama3.2"
            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    async with client.stream(
                        "POST",
                        "http://127.0.0.1:11434/api/chat",
                        json={
                            "model": mdl,
                            "messages": messages,
                            "stream": True,
                            "options": {"temperature": temperature},
                        },
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                chunk = json.loads(line)
                                if chunk.get("done"):
                                    break
                                content = chunk.get("message", {}).get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
                except (httpx.ConnectError, httpx.TimeoutException):
                    yield f"\n\n*⚠️ Ollama not reachable at localhost:11434. Is the Ollama server running?*\n"

        # ── Groq ──
        elif provider == "groq":
            mdl = model or "llama-3.3-70b-versatile"
            api_key = self.api_key or os.environ.get("GROQ_API_KEY", "")
            if not api_key:
                yield "\n\n*⚠️ No Groq API key configured. Set GROQ_API_KEY or configure in UI.*\n"
                return
            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    async with client.stream(
                        "POST",
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": mdl,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "stream": True,
                        },
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[6:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                content = (
                                    chunk.get("choices", [{}])[0]
                                    .get("delta", {})
                                    .get("content", "")
                                )
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
                except httpx.TimeoutException:
                    yield "\n\n*⚠️ Groq request timed out.*\n"

        # ── HuggingFace ──
        elif provider == "huggingface":
            mdl = model or "HuggingFaceH4/zephyr-7b-beta"
            api_key = self.api_key or os.environ.get("HF_API_KEY", "")
            if not api_key:
                yield "\n\n*⚠️ No HuggingFace API key configured.*\n"
                return
            async with httpx.AsyncClient(timeout=120.0) as client:
                prompt = messages[-1]["content"] if messages else ""
                try:
                    resp = await client.post(
                        f"https://api-inference.huggingface.co/models/{mdl}",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "inputs": prompt,
                            "parameters": {
                                "temperature": temperature,
                                "max_new_tokens": max_tokens,
                            },
                        },
                        timeout=120.0,
                    )
                    if resp.status_code == 200:
                        result = resp.json()
                        if isinstance(result, list) and len(result) > 0:
                            text = result[0].get("generated_text", "")
                            # Remove the input prompt from output
                            if text.startswith(prompt):
                                text = text[len(prompt) :]
                            yield text.strip()
                        else:
                            yield str(result)
                    else:
                        yield f"\n\n*⚠️ HuggingFace API error: {resp.status_code}*\n"
                except httpx.TimeoutException:
                    yield "\n\n*⚠️ HuggingFace request timed out.*\n"

        # ── OpenAI ──
        elif provider == "openai":
            mdl = model or "gpt-4o-mini"
            api_key = self.api_key or os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                yield "\n\n*⚠️ No OpenAI API key configured.*\n"
                return
            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    async with client.stream(
                        "POST",
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": mdl,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "stream": True,
                        },
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[6:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                content = (
                                    chunk.get("choices", [{}])[0]
                                    .get("delta", {})
                                    .get("content", "")
                                )
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
                except httpx.TimeoutException:
                    yield "\n\n*⚠️ OpenAI request timed out.*\n"

        # ── Anthropic ──
        elif provider == "anthropic":
            mdl = model or "claude-3-5-haiku-20241022"
            api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                yield "\n\n*⚠️ No Anthropic API key configured.*\n"
                return
            # Build messages for Anthropic format
            system_msg = ""
            anthropic_messages = []
            for m in messages:
                if m.get("role") == "system":
                    system_msg = m["content"]
                else:
                    anthropic_messages.append({"role": m["role"], "content": m["content"]})
            if not anthropic_messages:
                anthropic_messages = [{"role": "user", "content": "Hello"}]

            body = {
                "model": mdl,
                "messages": anthropic_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
            }
            if system_msg:
                body["system"] = system_msg

            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    async with client.stream(
                        "POST",
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[6:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                if chunk.get("type") == "content_block_delta":
                                    delta = chunk.get("delta", {})
                                    content = delta.get("text", "")
                                    if content:
                                        yield content
                            except json.JSONDecodeError:
                                continue
                except httpx.TimeoutException:
                    yield "\n\n*⚠️ Anthropic request timed out.*\n"

        # ── Mock (fallback when no provider matches) ──
        else:
            yield f"\n\n*🤖 MKO Agent (using {provider})*\n\n"
            yield (
                "Hello! I'm your MKO Universal AI Agent. I'm currently running "
                "in demo mode. To use a real LLM provider, configure your API keys "
                "in the Settings panel.\n\n"
                "**Available providers:**\n"
                "- 🦙 **Ollama** — Local, free (requires Ollama server)\n"
                "- ⚡ **Groq** — Cloud, free tier available\n"
                "- 🤗 **HuggingFace** — Cloud, free tier available\n"
                "- 💬 **OpenAI** — GPT-5.5, GPT Sol 5.6 (paid)\n"
                "- 🎯 **Anthropic** — Claude Fable 5, Opus 4.8 (paid)\n"
            )


# ─── MoE Agent ────────────────────────────────────────────────────────────


async def run_moe_agent(
    messages: list,
    experts: list,
    weights: dict,
    synthesis_temperature: float = 0.3,
    username: str = "demo",
    debug: bool = False,
):
    """Run MoE: parallel expert calls followed by weighted synthesis.

    Yields SSE-formatted dicts with type: 'token' | 'moe_debug' | 'error'.
    """
    import asyncio
    import httpx

    if not experts:
        yield {"type": "error", "content": "No experts configured for MoE."}
        return

    # ── Step 1: Collect expert responses in parallel ──
    expert_responses = {}
    expert_times = {}
    expert_tokens = {}
    total_input_tokens = sum(len(m.get("content", "")) for m in messages)

    async def call_expert(provider: str):
        api_key = _get_api_key_for_provider(provider)
        llm = UniversalLLM(provider=provider, api_key=api_key)
        collected = []
        start = time.time()
        token_count = 0
        async for token in llm.chat(
            messages=messages,
            temperature=0.3,
            max_tokens=1024,
        ):
            collected.append(token)
            token_count += 1
        elapsed = round((time.time() - start) * 1000)
        return provider, "".join(collected), elapsed, token_count

    tasks = [call_expert(expert) for expert in experts]
    for coro in asyncio.as_completed(tasks):
        provider, text, elapsed_ms, num_tokens = await coro
        expert_responses[provider] = text
        expert_times[provider] = elapsed_ms
        expert_tokens[provider] = num_tokens

    # ── Step 2: Yield debug info if enabled ──
    if debug:
        details = []
        for expert in experts:
            resp = expert_responses.get(expert, "")
            t = expert_times.get(expert, 0)
            tok = expert_tokens.get(expert, 0)
            weight = weights.get(expert, 1.0)
            details.append({
                "provider": expert,
                "response": resp,
                "time_ms": t,
                "tokens": tok,
                "weight": weight,
            })

        # Estimate gate model tokens
        gate_input_tokens = total_input_tokens // 4
        for d in details:
            gate_input_tokens += d["tokens"] + 20  # separator tokens
        gate_output_tokens = 1  # minimal synthesis output

        yield {
            "type": "moe_debug",
            "content": {
                "details": details,
                "gate_input_tokens": gate_input_tokens,
                "gate_output_tokens": gate_output_tokens,
                "weights": weights,
            },
        }

    # ── Step 3: Weighted synthesis ──
    # Build a synthesis prompt that asks the gate to merge expert responses
    synthesis_parts = []
    for expert in experts:
        resp = expert_responses.get(expert, "")
        if resp.strip():
            label = f"{expert} (weight {weights.get(expert, 1.0)}x)"
            synthesis_parts.append(f"**Expert: {label}**\n{resp}")

    if not synthesis_parts:
        yield {"type": "error", "content": "All experts returned empty responses."}
        return

    synthesis_prompt = (
        "You are a synthesis gate. Combine the following expert responses into "
        "a single coherent answer. Weight more important insights higher.\n\n"
        + "\n\n---\n\n".join(synthesis_parts)
    )

    # Use Groq or first available expert as the gate
    gate_provider = "groq" if "groq" in experts else experts[0]
    gate_api_key = _get_api_key_for_provider(gate_provider)
    gate_llm = UniversalLLM(provider=gate_provider, api_key=gate_api_key)

    synthesis_full = ""
    async for token in gate_llm.chat(
        messages=[{"role": "user", "content": synthesis_prompt}],
        temperature=synthesis_temperature,
        max_tokens=2048,
    ):
        synthesis_full += token
        yield {"type": "token", "content": token}


def _get_api_key_for_provider(provider: str) -> str:
    """Get API key from config file for a given provider."""
    config = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    api_keys = config.get("api_keys", {})
    return api_keys.get(provider.lower(), "")


# ─── Get credit cost ──────────────────────────────────────────────────────


def get_credit_cost(model: str, agent_type: str = "general") -> int:
    """Return the credit cost for a given model, handling MoE multiplier."""
    if agent_type == "moe":
        base = MODEL_CREDIT_COSTS.get("moe", 3)
        # Each expert adds cost
        return base
    return MODEL_CREDIT_COSTS.get(model, 1)


# ─── Admin helpers ────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    return hash_password(password) == stored_hash


def create_session_token() -> str:
    return hashlib.sha256(
        f"{uuid.uuid4()}{time.time()}{os.urandom(16)}".encode()
    ).hexdigest()


def is_admin_authenticated(token: str) -> bool:
    if not ADMIN_CONFIG_FILE.exists():
        return False
    config = json.loads(ADMIN_CONFIG_FILE.read_text(encoding="utf-8"))
    sessions = config.get("session_tokens", {})
    if token in sessions:
        created_at = sessions[token]
        if time.time() - created_at < 86400:  # 24 hour expiry
            return True
        # Expired — clean it up
        del sessions[token]
        ADMIN_CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return False


def invalidate_session(token: str) -> None:
    if not ADMIN_CONFIG_FILE.exists():
        return
    config = json.loads(ADMIN_CONFIG_FILE.read_text(encoding="utf-8"))
    sessions = config.get("session_tokens", {})
    if token in sessions:
        del sessions[token]
        ADMIN_CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


# ─── RAG ──────────────────────────────────────────────────────────────────


async def rag_query(query: str, username: str = "demo") -> str:
    """Simple RAG query that searches Qdrant and returns context."""
    try:
        from qdrant_client import QdrantClient
        from sentence_transformers import SentenceTransformer

        client = QdrantClient(path=str(DATA_DIR / "qdrant_db"))
        model = SentenceTransformer("all-MiniLM-L6-v2")

        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if not collection_names:
            return "No documents have been uploaded. Use the RAG panel to upload files first."

        # Search all collections
        query_vector = model.encode(query).tolist()
        all_results = []
        for cname in collection_names:
            results = client.search(
                collection_name=cname,
                query_vector=query_vector,
                limit=3,
            )
            for r in results:
                all_results.append(r.payload.get("text", ""))

        if not all_results:
            return "No relevant documents found for your query."

        context = "\n\n".join(all_results[:5])
        return f"Based on uploaded documents:\n\n{context}"

    except ImportError:
        return "RAG dependencies not installed. Install qdrant-client and sentence-transformers."
    except Exception as e:
        return f"RAG query error: {e}"

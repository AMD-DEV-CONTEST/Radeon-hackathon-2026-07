"""
Ollama Client — Native Ollama API Integration
Talks to Ollama's /api/chat endpoint for inference and /api/tags for health checks.
Supports Qwen2.5 and any other Ollama-hosted model.
"""
import os
import time
import httpx

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")


async def get_completion(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.7,
    **kwargs,
) -> dict:
    """
    Call Ollama's native /api/chat endpoint.
    Returns a standardized result dict matching the project convention.
    """
    start_ms = time.time() * 1000

    url = f"{OLLAMA_HOST}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)

            if resp.status_code == 200:
                data = resp.json()
                end_ms = time.time() * 1000
                latency = int(end_ms - start_ms)

                content = data.get("message", {}).get("content", "")
                # Ollama reports eval_count (tokens generated) and eval_duration (ns)
                tokens_out = data.get("eval_count", len(content.split()))
                eval_duration_ns = data.get("eval_duration", 0)
                if eval_duration_ns > 0:
                    tps = round(tokens_out / (eval_duration_ns / 1e9), 1)
                else:
                    tps = round(tokens_out / max(latency / 1000, 0.001), 1)

                return {
                    "text": content,
                    "tokens_generated": tokens_out,
                    "latency_ms": latency,
                    "tokens_per_second": tps,
                    "model": OLLAMA_MODEL,
                    "gpu_type": "Ollama Local Inference",
                    "provider": "Ollama (local)",
                    "error": None,
                }

            # Non-200 response
            error_text = resp.text[:200]
            return {
                "text": "",
                "tokens_generated": 0,
                "latency_ms": int((time.time() * 1000) - start_ms),
                "tokens_per_second": 0.0,
                "model": OLLAMA_MODEL,
                "gpu_type": "Ollama Local Inference",
                "provider": "Ollama (local)",
                "error": f"Ollama returned {resp.status_code}: {error_text}",
            }

    except httpx.ConnectError:
        return {
            "text": "",
            "tokens_generated": 0,
            "latency_ms": int((time.time() * 1000) - start_ms),
            "tokens_per_second": 0.0,
            "model": OLLAMA_MODEL,
            "gpu_type": "Ollama Local Inference",
            "provider": "Ollama (local)",
            "error": f"Cannot connect to Ollama at {OLLAMA_HOST}. Is Ollama running?",
        }
    except Exception as e:
        return {
            "text": "",
            "tokens_generated": 0,
            "latency_ms": int((time.time() * 1000) - start_ms),
            "tokens_per_second": 0.0,
            "model": OLLAMA_MODEL,
            "gpu_type": "Ollama Local Inference",
            "provider": "Ollama (local)",
            "error": str(e),
        }


async def check_health() -> bool:
    """Check if Ollama is running and the target model is available."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags")
            if resp.status_code != 200:
                return False

            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            # Check if our model is available (Ollama names can be with or without tag)
            model_base = OLLAMA_MODEL.split(":")[0]
            for m in models:
                if m == OLLAMA_MODEL or m.startswith(model_base):
                    return True

            # Model not pulled yet but Ollama is running
            print(f"[OllamaClient] Ollama is running but model '{OLLAMA_MODEL}' not found. Available: {models}")
            return False
    except Exception:
        return False


async def list_models() -> list:
    """List all models available in Ollama."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        pass
    return []

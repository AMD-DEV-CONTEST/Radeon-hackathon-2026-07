"""
Qwen Inference Client — Multi-Provider Routing Engine
Supports: Ollama (local), vLLM/OpenAI-compat, HuggingFace Transformers.

INFERENCE_MODE controls provider selection:
  "ollama"       — Use Ollama's native /api/chat (default for local dev)
  "vllm"         — Use vLLM/OpenAI-compatible /v1/chat/completions
  "transformers" — Use local HuggingFace transformers pipeline
  "auto"         — Try Ollama → vLLM → Transformers in order (default)
"""
import os
import time
import httpx
from pathlib import Path
import traceback

INFERENCE_MODE = os.getenv("INFERENCE_MODE", "auto").lower()
QWEN_MODEL_PATH = os.getenv("QWEN_MODEL_PATH", "/workspace/workspace/KidoDev/models/qwen2.5-1.5b")
QWEN_HOST = os.getenv("QWEN_HOST", "http://localhost:11434")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen2.5-1.5b")

_model_cache = {}


def _get_local_pipeline():
    """Lazily load local HuggingFace model/pipeline for Qwen2.5 if transformers & torch are installed."""
    if "pipe" in _model_cache:
        return _model_cache["pipe"]

    model_dir = Path(QWEN_MODEL_PATH)
    if not model_dir.exists():
        print(f"[QwenClient] Local model directory not found at path: '{QWEN_MODEL_PATH}'. Check QWEN_MODEL_PATH env var.")
        return None

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

        print(f"[QwenClient] Loading Tokenizer from {model_dir}...")
        tokenizer = AutoTokenizer.from_pretrained(str(model_dir), trust_remote_code=True)
        print("[QwenClient] ✓ Tokenizer loaded successfully.")

        print(f"[QwenClient] Loading Model on AMD GPU (ROCm) from {model_dir}...")
        
        dtype_kwargs = {}
        if hasattr(torch, "float16"):
            dtype_kwargs["torch_dtype"] = torch.float16 if torch.cuda.is_available() else torch.float32

        model = AutoModelForCausalLM.from_pretrained(
            str(model_dir),
            device_map="auto" if torch.cuda.is_available() else "cpu",
            trust_remote_code=True,
            **dtype_kwargs
        )
        print(f"[QwenClient] ✓ Model loaded on device: {next(model.parameters()).device}")

        print("[QwenClient] Creating text-generation pipeline...")
        try:
            pipe = pipeline("text-generation", model=model, tokenizer=tokenizer)
            print("[QwenClient] ✓ HuggingFace Pipeline initialized successfully.")
            _model_cache["pipe"] = pipe
            return pipe
        except Exception as pipe_err:
            print(f"[QwenClient] Pipeline creation warning: {pipe_err}. Using direct model tuple fallback.")
            tuple_obj = (model, tokenizer)
            _model_cache["pipe"] = tuple_obj
            return tuple_obj

    except ImportError as e:
        print("\n" + "=" * 70)
        print("  ❌ [QwenClient CRITICAL ERROR] PyTorch ('torch') or 'transformers' is NOT installed in this Python environment!")
        print(f"  Error details: {e}")
        print("  👉 FIX: You must activate the 'llm-env' virtual environment before starting Uvicorn:")
        print("     1. deactivate")
        print("     2. source /workspace/workspace/KidoDev/llm-env/bin/activate")
        print("     3. cd /workspace/workspace/KidoDev/backend && uvicorn main:app --host 0.0.0.0 --port 8000")
        print("=" * 70 + "\n")
        return None
    except Exception as e:
        print(f"[QwenClient] Exception during local model load: {e}")
        traceback.print_exc()
        return None


async def _try_ollama(system_prompt, user_prompt, max_tokens, temperature):
    """Try Ollama's native /api/chat endpoint."""
    from inference import ollama_client
    result = await ollama_client.get_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if result.get("error") is None and result.get("text"):
        return result
    return None


async def _try_vllm(system_prompt, user_prompt, max_tokens, temperature):
    """Try vLLM or any OpenAI-compatible /v1/chat/completions endpoint."""
    start_ms = time.time() * 1000

    hosts_to_try = []
    if QWEN_HOST and "8000" not in QWEN_HOST:  # Avoid querying FastAPI app on 8000
        hosts_to_try.append(QWEN_HOST)
    hosts_to_try.append("http://localhost:11434")

    for host in list(dict.fromkeys(hosts_to_try)):
        url = f"{host}/v1/chat/completions"
        payload = {
            "model": QWEN_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    end_ms = time.time() * 1000
                    latency = int(end_ms - start_ms)
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    tokens_out = data.get("usage", {}).get("completion_tokens", len(content.split()))
                    tps = round(tokens_out / max(latency / 1000, 0.001), 1)

                    return {
                        "text": content,
                        "tokens_generated": tokens_out,
                        "latency_ms": latency,
                        "tokens_per_second": tps,
                        "model": QWEN_MODEL,
                        "gpu_type": "vLLM / OpenAI-Compatible Inference",
                        "provider": f"vLLM ({host})",
                        "error": None,
                    }
        except Exception:
            pass

    return None


def _try_transformers_sync(system_prompt, user_prompt, max_tokens, temperature):
    """Try local HuggingFace model/pipeline execution (synchronous)."""
    print(f"[QwenClient] Requesting HuggingFace Transformers execution on path: '{QWEN_MODEL_PATH}'")
    start_ms = time.time() * 1000

    obj = _get_local_pipeline()
    if obj is None:
        print("[QwenClient] Local model object is None (model missing or load error).")
        return None

    try:
        prompt_text = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
        
        if isinstance(obj, tuple):
            # Direct model.generate fallback
            model, tokenizer = obj
            import torch
            inputs = tokenizer(prompt_text, return_tensors="pt")
            if torch.cuda.is_available():
                inputs = {k: v.to("cuda") for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    do_sample=True,
                    temperature=temperature,
                    pad_token_id=tokenizer.eos_token_id
                )
            gen_text = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        else:
            # Standard pipeline execution
            out = obj(prompt_text, max_new_tokens=max_tokens, do_sample=True, temperature=temperature)
            gen_text = out[0]["generated_text"].replace(prompt_text, "").replace("<|im_end|>", "").strip()

        end_ms = time.time() * 1000
        latency = int(end_ms - start_ms)
        tokens_out = len(gen_text.split())
        tps = round(tokens_out / max(latency / 1000, 0.001), 1)

        print(f"[QwenClient] ✓ GPU Inference complete! Latency: {latency}ms | Speed: {tps} tok/s")

        return {
            "text": gen_text,
            "tokens_generated": tokens_out,
            "latency_ms": latency,
            "tokens_per_second": tps,
            "model": "qwen2.5-1.5b",
            "gpu_type": "HuggingFace Transformers (AMD ROCm GPU)",
            "provider": "HuggingFace Transformers",
            "error": None,
        }
    except Exception as e:
        print(f"[QwenClient] HuggingFace execution error: {e}")
        traceback.print_exc()
        return None


async def get_completion(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.7,
    **kwargs
) -> dict:
    """
    Route inference to the active provider based on INFERENCE_MODE.
    Modes: "ollama", "vllm", "transformers", "auto"
    """
    print("========== QWEN CLIENT CALLED ==========")
    print(f"[QwenClient] INFERENCE_MODE={INFERENCE_MODE} | Target Model={QWEN_MODEL_PATH}")
    start_ms = time.time() * 1000

    # ── Explicit mode routing ────────────────────────────────────────────────
    if INFERENCE_MODE == "ollama":
        result = await _try_ollama(system_prompt, user_prompt, max_tokens, temperature)
        if result:
            return result

    elif INFERENCE_MODE == "vllm":
        result = await _try_vllm(system_prompt, user_prompt, max_tokens, temperature)
        if result:
            return result

    elif INFERENCE_MODE == "transformers":
        result = _try_transformers_sync(system_prompt, user_prompt, max_tokens, temperature)
        if result:
            return result

    elif INFERENCE_MODE == "auto":
        # Auto mode: try Ollama → vLLM → Transformers
        result = await _try_ollama(system_prompt, user_prompt, max_tokens, temperature)
        if result:
            return result

        result = await _try_vllm(system_prompt, user_prompt, max_tokens, temperature)
        if result:
            return result

        result = _try_transformers_sync(system_prompt, user_prompt, max_tokens, temperature)
        if result:
            return result

    # ── Fallback — no provider succeeded ─────────────────────────────────────
    model_exists = Path(QWEN_MODEL_PATH).exists()
    return {
        "text": "",
        "tokens_generated": 0,
        "latency_ms": int((time.time() * 1000) - start_ms),
        "tokens_per_second": 0.0,
        "model": QWEN_MODEL,
        "gpu_type": "KidoBot Smart Context Engine (Fallback)",
        "provider": "KidoBot Fallback Engine",
        "error": None if model_exists else f"No inference provider available (mode={INFERENCE_MODE})",
    }


async def check_health() -> bool:
    """Check if any inference backend is ready."""
    # Check Ollama first
    from inference import ollama_client
    if await ollama_client.check_health():
        return True

    # Check local model path
    if Path(QWEN_MODEL_PATH).exists():
        return True

    # Check vLLM / OpenAI-compat endpoint
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{QWEN_HOST}/v1/models")
            return resp.status_code == 200
    except Exception:
        return False


def get_active_provider() -> str:
    """Return a human-readable string describing the active inference mode."""
    if INFERENCE_MODE == "ollama":
        from inference import ollama_client
        return f"Ollama ({ollama_client.OLLAMA_MODEL} @ {ollama_client.OLLAMA_HOST})"
    elif INFERENCE_MODE == "vllm":
        return f"vLLM ({QWEN_MODEL} @ {QWEN_HOST})"
    elif INFERENCE_MODE == "transformers":
        return f"HuggingFace Transformers ({QWEN_MODEL_PATH})"
    else:
        return f"Auto-detect (Ollama → vLLM → Transformers)"

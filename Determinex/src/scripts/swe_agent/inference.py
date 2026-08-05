"""
swe_agent/inference.py — Inference backend routing.

Routes calls to Ollama (local), vLLM (RunPod), DeepSeek API, or Anthropic API
based on per-role and global backend configuration.

Resolution order:
  Config A: DETERMINEX_INFERENCE_BACKEND=ollama    → all roles → local Ollama
  Config B: DETERMINEX_INFERENCE_BACKEND=deepseek  → all roles → DeepSeek API
  Config C: DETERMINEX_ARCHITECT_BACKEND=deepseek  → Architect → DeepSeek
            DETERMINEX_BUILDER_BACKEND=vllm         → Builder   → local 7B vLLM
  Config D: DETERMINEX_ARCHITECT_BACKEND=anthropic  → Architect → Claude API
            DETERMINEX_BUILDER_BACKEND=deepseek      → Builder   → DeepSeek API
"""

from __future__ import annotations

import json
import logging

from .constants import (
    _ANTHROPIC_KEY,
    _ANTHROPIC_MODEL,
    _ANTHROPIC_URL,
    _ARCHITECT_BACKEND,
    _BUILDER_BACKEND,
    _DEEPSEEK_ARCHITECT_MODEL,
    _DEEPSEEK_BUILDER_MODEL,
    _DEEPSEEK_KEY,
    _DEEPSEEK_MODEL,
    _DEEPSEEK_URL,
    _GEMINI_KEY,
    _GEMINI_MODEL,
    _GEMINI_URL,
    _INFERENCE_BACKEND,
    _OPENAI_KEY,
    _OPENAI_MODEL,
    _OPENAI_URL,
    _TASK_VECTOR_TO_LORA,
    _VLLM_MODEL,
    _VLLM_URL,
    BUILDER_MODEL,
    LOCAL_BUILDER_MODEL,
    OBSERVER_MODEL,
    OLLAMA_URL,
    USE_LOCAL_BUILDER,
)

log = logging.getLogger("determinex_swe")


def _openai_compat(
    url: str,
    api_key: str,
    model: str,
    prompt: str,
    system: str = "",
    temperature: float = 0.1,
    extra_body: dict | None = None,
    total_timeout: int = 180,
) -> str:
    """Generic OpenAI-compatible chat completion. Used by vLLM and DeepSeek.

    Uses a thread-based hard total-timeout (default 180s) in addition to the
    per-socket timeout. This prevents IncompleteRead stalls where the server
    sends a few bytes then goes silent — a socket timeout alone won't fire
    because each partial read resets the socket timer.
    """
    import threading
    import urllib.request

    messages = [
        {"role": "system", "content": system or "You are an expert software engineer."},
        {"role": "user", "content": prompt},
    ]
    body: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 8192,
        "stream": False,
    }
    if extra_body:
        body.update(extra_body)
    payload = json.dumps(body).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        f"{url}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )

    result: list[str] = []
    exc: list[Exception] = []

    def _do_request() -> None:
        try:
            # Socket timeout bounds individual read/write ops; total_timeout
            # (enforced by the joining thread) bounds the whole round-trip.
            with urllib.request.urlopen(req, timeout=total_timeout) as resp:
                data = json.loads(resp.read())
                result.append(data["choices"][0]["message"]["content"].strip())
        except Exception as e:
            exc.append(e)

    t = threading.Thread(target=_do_request, daemon=True)
    t.start()
    t.join(timeout=total_timeout)

    if t.is_alive():
        log.error("API call hard-timeout (%ds) — %s stalled mid-response", total_timeout, url)
        return ""
    if exc:
        log.error("API call failed (%s): %s", url, exc[0])
        return ""
    return result[0] if result else ""


def _anthropic_call(
    prompt: str,
    system: str = "",
    temperature: float = 0.1,
    total_timeout: int = 300,
) -> str:
    """Anthropic Messages API — raw HTTP, no SDK dependency.

    Same thread-based hard-timeout pattern as _openai_compat to guard against
    partial-read stalls (server sends a few bytes then goes silent).
    """
    import threading
    import urllib.error
    import urllib.request

    if not _ANTHROPIC_KEY:
        log.error("DETERMINEX_ANTHROPIC_KEY not set — falling back to Ollama")
        return ""
    body = {
        "model": _ANTHROPIC_MODEL,
        "max_tokens": 8192,
        "temperature": temperature,
        "system": system or "You are an expert software engineer.",
        "messages": [{"role": "user", "content": prompt}],
    }
    payload = json.dumps(body).encode()
    headers = {
        "Content-Type": "application/json",
        "x-api-key": _ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
    }
    req = urllib.request.Request(_ANTHROPIC_URL, data=payload, headers=headers, method="POST")

    result: list[str] = []
    exc: list[Exception] = []

    def _do_request() -> None:
        try:
            with urllib.request.urlopen(req, timeout=total_timeout) as resp:
                data = json.loads(resp.read())
                result.append(data["content"][0]["text"].strip())
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
                log.error("Anthropic API call failed HTTP %d: %s", e.code, err_body[:500])
            except Exception:
                log.error("Anthropic API call failed: %s", e)
        except Exception as e:
            exc.append(e)

    t = threading.Thread(target=_do_request, daemon=True)
    t.start()
    t.join(timeout=total_timeout)

    if t.is_alive():
        log.error("Anthropic API hard-timeout (%ds) — stalled mid-response", total_timeout)
        return ""
    if exc:
        log.error("Anthropic API call failed: %s", exc[0])
        return ""
    return result[0] if result else ""


def _ollama(
    model: str,
    prompt: str,
    system: str = "",
    temperature: float = 0.1,
    keep_alive: str | int = "5m",
    timeout: int = 180,
) -> str:
    """Ollama local model inference via HTTP /api/generate."""
    import urllib.request

    payload = json.dumps(
        {
            "model": model,
            "prompt": (
                f"<|im_start|>system\n{system or 'You are an expert software engineer.'}"
                f"<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n"
                f"<|im_start|>assistant\n"
            ),
            "stream": False,
            "keep_alive": keep_alive,
            "options": {
                "num_ctx": 16384,
                "temperature": temperature,
                "num_predict": 16384,
            },
        }
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "").strip()
    except Exception as e:
        log.error("Ollama call failed: %s", e)
        return ""


def _infer(
    model: str,
    prompt: str,
    system: str = "",
    temperature: float = 0.1,
    task_vector: str = "",
    keep_alive: str | int = "5m",
) -> str:
    """Route inference to the correct backend based on role and config."""
    if model == OBSERVER_MODEL and _ARCHITECT_BACKEND:
        backend = _ARCHITECT_BACKEND
    elif model == BUILDER_MODEL and _BUILDER_BACKEND:
        backend = _BUILDER_BACKEND
    else:
        backend = _INFERENCE_BACKEND

    if backend == "anthropic":
        result = _anthropic_call(prompt, system, temperature)
        if not result:
            # Hard-fail — do NOT fall back to Ollama.
            # A silent Ollama fallback would make Config D results
            # indistinguishable from Config A, invalidating the ablation.
            raise RuntimeError(
                "Anthropic API call returned empty. Check ANTHROPIC_API_KEY, "
                "rate limits, and network connectivity. Aborting — no Ollama fallback."
            )
        return result

    if backend == "deepseek":
        if not _DEEPSEEK_KEY:
            raise RuntimeError(
                "DEEPSEEK_API_KEY not set — cannot use DeepSeek backend. "
                "Aborting — no Ollama fallback."
            )
        # Per-role model selection: legacy DETERMINEX_DEEPSEEK_MODEL overrides both;
        # otherwise Flash for builder, Pro for architect.
        if _DEEPSEEK_MODEL:
            ds_model = _DEEPSEEK_MODEL
        elif model == OBSERVER_MODEL:
            ds_model = _DEEPSEEK_ARCHITECT_MODEL
        else:
            ds_model = _DEEPSEEK_BUILDER_MODEL
        log.debug("[deepseek] role=%s model=%s", model, ds_model)
        return _openai_compat(
            _DEEPSEEK_URL,
            _DEEPSEEK_KEY,
            ds_model,
            prompt,
            system,
            temperature,
        )

    if backend == "openai":
        if not _OPENAI_KEY:
            raise RuntimeError("OPENAI_API_KEY not set — cannot use OpenAI backend. Aborting.")
        log.debug("[openai] role=%s model=%s", model, _OPENAI_MODEL)
        return _openai_compat(_OPENAI_URL, _OPENAI_KEY, _OPENAI_MODEL, prompt, system, temperature)

    if backend == "gemini":
        if not _GEMINI_KEY:
            raise RuntimeError("GEMINI_API_KEY not set — cannot use Gemini backend. Aborting.")
        log.debug("[gemini] role=%s model=%s", model, _GEMINI_MODEL)
        return _openai_compat(_GEMINI_URL, _GEMINI_KEY, _GEMINI_MODEL, prompt, system, temperature)

    if backend == "vllm":
        lora = _TASK_VECTOR_TO_LORA.get(task_vector, "") if task_vector else ""
        extra = (
            {"lora_request": {"lora_name": lora, "lora_int_id": abs(hash(lora)) % 1000}}
            if lora
            else None
        )
        return _openai_compat(_VLLM_URL, "", _VLLM_MODEL, prompt, system, temperature, extra)

    return _ollama(model, prompt, system, temperature, keep_alive)


def _warm_local_builder() -> bool:
    """
    Pre-load LOCAL_BUILDER_MODEL into Ollama before the solve loop.
    Large models (32B Q4 ~18GB) take 3-8 minutes cold — pay once so
    the first generate_fix_local call doesn't hit per-attempt timeout.
    """
    if not USE_LOCAL_BUILDER:
        return False
    log.info("[LocalBuilder] Pre-warming %s ...", LOCAL_BUILDER_MODEL)
    result = _ollama(
        LOCAL_BUILDER_MODEL,
        "ready",
        system="You are ready.",
        temperature=0.0,
        keep_alive=-1,
        timeout=600,
    )
    if result:
        log.info("[LocalBuilder] Pre-warm complete")
        return True
    log.warning("[LocalBuilder] Pre-warm failed — model may be unavailable")
    return False

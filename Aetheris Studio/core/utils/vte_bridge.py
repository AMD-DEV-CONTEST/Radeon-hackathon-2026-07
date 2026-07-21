"""Bridge to VTE (github.com/kyuubyN/VTE), the from-scratch AMD HIP inference
engine used as Aetheris's local model provider instead of Ollama.

VTE runs as its own subprocess (`vte-server`, vte/server/http_server.py in
the VTE repo) speaking a standard OpenAI-compatible chat/completions API,
spawned and owned by this module. Aetheris no longer embeds a VTEModel
directly inside its own process; this trades a small per-call loopback HTTP
hop for real crash isolation: if VTE hits a GPU/driver-level fault, only
vte-server dies, not the whole Aetheris backend. Since vte-server does its
own chat-template rendering server-side (given a plain `messages` list),
this module no longer needs to touch `VTEModel.tokenizer` at all; messages
go straight into the request body.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# VTE's `vte://` scheme is a pure in-process sentinel: it is never resolved
# as a real network address. The real model name travels in the existing
# `model` parameter every call site already takes, no need to encode it
# into the URL too.
VTE_URL_SCHEME = "vte"
VTE_DEFAULT_URL = "vte://local"
# The model the user chose for this Aetheris revival (already registered
# and measured in VTE's own MODEL_REGISTRY). Llama 3.1 8B Instruct, not
# Granite 4.1 30B: Granite was tried first and reproducibly defaults to
# Portuguese/Spanish greetings on short replies once the real tool-doc
# system prompt is in context, regardless of the "reply in the same
# language" instruction's position (see VTE/docs/LIMITATIONS.md). Llama
# 3.1 8B was verified directly against the identical system prompt and
# correctly mirrors the user's input language every time, at a fraction
# of Granite 30B's VRAM/latency cost.
VTE_DEFAULT_MODEL = "llama3.1:8b-instruct-q4_k_m"

_SERVER_HOST = "127.0.0.1"
_SERVER_PORT = 8011
_SERVER_BASE_URL = f"http://{_SERVER_HOST}:{_SERVER_PORT}"
_READY_TIMEOUT_SECONDS = 90.0

# Single-model policy: VTE runs on one consumer GPU with a real VRAM budget,
# so only one vte-server subprocess (one resident model) runs at a time;
# switching models terminates the old subprocess and spawns a new one. A
# context_length change needs exactly the same treatment: it sizes the KV
# cache at model-load time (vte/server/http_server.py's --context-length),
# so it can't be adjusted on a running server -- only a fresh load applies it.
_lock = threading.Lock()
_process: Optional[subprocess.Popen] = None
_model_name: Optional[str] = None
_context_length: Optional[int] = None


def is_vte_url(url: str) -> bool:
    """True for the `vte://` sentinel scheme used to route through this
    module instead of an HTTP request to some other provider."""
    return (url or "").strip().lower().startswith(f"{VTE_URL_SCHEME}://")


def _resolve_gguf_path(model_name: str) -> str:
    """Mirrors VTEModel.from_pretrained's own path resolution (registered
    MODEL_REGISTRY name, falling back to dynamic discovery by file stem),
    without loading the model: vte-server takes an already-resolved
    --gguf-path, it doesn't do this lookup itself."""
    from vte.core.model import VTEModel, _REPO_ROOT

    if model_name in VTEModel.MODEL_REGISTRY:
        filename = VTEModel.MODEL_REGISTRY[model_name]
        candidates = [Path("Model") / filename, _REPO_ROOT / "Model" / filename]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate.resolve())
        checked = "\n".join(f"  - {p.resolve()}" for p in candidates)
        raise FileNotFoundError(f"Arquivo do modelo não encontrado:\n{checked}")

    discovered = VTEModel.discover_models()
    if model_name in discovered:
        return str(discovered[model_name].resolve())

    available = ", ".join(VTEModel.MODEL_REGISTRY.keys()) or "(nenhum)"
    raise ValueError(f"Modelo '{model_name}' não encontrado.\nNomes registrados: {available}")


def _wait_until_ready(timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{_SERVER_BASE_URL}/health", timeout=2.0)
            if resp.status_code == 200 and resp.json().get("status") == "ready":
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def _stop_server_locked() -> None:
    global _process, _model_name, _context_length
    if _process is not None:
        try:
            _process.terminate()
            _process.wait(timeout=5)
        except Exception:
            try:
                _process.kill()
            except Exception:
                pass
    _process = None
    _model_name = None
    _context_length = None


def _start_server_locked(model_name: str, context_length: int) -> None:
    global _process, _model_name, _context_length
    gguf_path = _resolve_gguf_path(model_name)
    logger.info("Iniciando vte-server para %s (%s), context_length=%d...", model_name, gguf_path, context_length)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    _process = subprocess.Popen(
        [
            sys.executable, "-m", "vte.server.http_server",
            "--gguf-path", gguf_path,
            "--port", str(_SERVER_PORT),
            "--host", _SERVER_HOST,
            "--context-length", str(context_length),
            # This process (app.py) owns the model lifecycle explicitly via
            # ensure_server()/unload(); vte-server's own idle-unload timer
            # would fight that, so it's disabled.
            "--idle-timeout", "0",
            # If app.py dies without a clean shutdown, vte-server's own
            # parent-watchdog notices and frees the VRAM instead of leaking
            # an orphaned process (see http_server.py's docstring).
            "--parent-pid", str(os.getpid()),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    if not _wait_until_ready(_READY_TIMEOUT_SECONDS):
        _process.terminate()
        _process = None
        raise RuntimeError(f"vte-server não ficou pronto a tempo para o modelo '{model_name}'.")
    _model_name = model_name
    _context_length = context_length


def _resolve_context_length(context_length: Optional[int]) -> int:
    if context_length is not None:
        return context_length
    from core.utils.settings import get_setting
    return get_setting("context_length", 2048)


def ensure_server(model_name: str, context_length: Optional[int] = None) -> None:
    """Starts the vte-server subprocess for `model_name` if it isn't already
    serving it at the right context_length (restarting it on a model switch
    OR a context_length change -- see the module-level docstring above for
    why the latter needs a full restart too). `context_length=None` (every
    existing caller) reads the persisted setting, so nothing has to change
    at call sites for this to take effect. Thread-safe, idempotent.
    Blocking, so callers on the asyncio event loop should wrap this in
    `asyncio.to_thread`."""
    with _lock:
        resolved_context_length = _resolve_context_length(context_length)
        if (
            _process is not None
            and _process.poll() is None
            and _model_name == model_name
            and _context_length == resolved_context_length
        ):
            return
        if _process is not None:
            _stop_server_locked()
        _start_server_locked(model_name, resolved_context_length)


def unload() -> None:
    """Terminate the resident vte-server subprocess, if any."""
    with _lock:
        _stop_server_locked()


def get_telemetry() -> Dict:
    """Real GPU/model telemetry for the status-bar footer: queries
    vte-server's own /telemetry (a live hipMemGetInfo read, not cached), and
    reports whether that server is reachable at all. Never raises: an
    unreachable vte-server (not started yet, model still loading) is a
    normal, displayable state, not an error condition worth crashing a
    polling loop over."""
    try:
        resp = httpx.get(f"{_SERVER_BASE_URL}/telemetry", timeout=3.0)
        if resp.status_code != 200:
            return {"connected": False}
        data = resp.json()
        data["connected"] = True
        return data
    except httpx.HTTPError:
        return {"connected": False}


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_once(model_name: str, messages: List[Dict], temperature: float = 0.3, max_tokens: int = 512) -> str:
    """Synchronous, non-streaming generation, for callers outside the
    async chat-streaming path (e.g. context_compressor.py's history
    summarization, which runs synchronously)."""
    ensure_server(model_name)
    resp = httpx.post(
        f"{_SERVER_BASE_URL}/v1/chat/completions",
        json={
            "model": model_name, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens, "stream": False,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


async def stream_generate(
    model_name: str, messages: List[Dict], temperature: float = 0.3, max_tokens: int = 4096
) -> AsyncGenerator[str, None]:
    """Async generator yielding text deltas from vte-server's OpenAI-shaped
    streaming endpoint (`data: {"choices":[{"delta":{"content": "..."}}]}`,
    ending on `data: [DONE]`)."""
    await asyncio.to_thread(ensure_server, model_name)
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
        async with client.stream(
            "POST", f"{_SERVER_BASE_URL}/v1/chat/completions",
            json={
                "model": model_name, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens, "stream": True,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                if payload == "[DONE]":
                    return
                chunk = json.loads(payload)
                if "error" in chunk:
                    raise RuntimeError(chunk["error"].get("message", "Erro no vte-server"))
                choices = chunk.get("choices") or []
                content = choices[0].get("delta", {}).get("content") if choices else None
                if content:
                    yield content

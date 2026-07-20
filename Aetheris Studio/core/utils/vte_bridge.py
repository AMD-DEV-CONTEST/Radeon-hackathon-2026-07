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
# and measured in VTE's own MODEL_REGISTRY).
VTE_DEFAULT_MODEL = "qwen2.5:1.5b-q4_k_m"

_SERVER_HOST = os.environ.get("VTE_SERVER_HOST", "127.0.0.1")
_SERVER_PORT = int(os.environ.get("VTE_SERVER_PORT", "8011"))
_SERVER_BASE_URL = f"http://{_SERVER_HOST}:{_SERVER_PORT}"
_READY_TIMEOUT_SECONDS = 90.0

# Remote-GPU mode (VTE_REMOTE_SERVER=1): a vte-server is already running
# elsewhere (typically a cloud GPU instance, reached through an SSH -L
# tunnel so it still shows up as 127.0.0.1 here; see the root README's
# "Run the app locally, infer on a remote GPU" section). ensure_server()
# then only *waits* for that existing server instead of spawning a local
# subprocess, and unload() becomes a no-op: this process doesn't own that
# server's lifecycle and has no business killing someone else's model.
REMOTE_SERVER_MODE = bool(os.environ.get("VTE_REMOTE_SERVER"))

# Single-model policy: VTE runs on one consumer GPU with a real VRAM budget,
# so only one vte-server subprocess (one resident model) runs at a time;
# switching models terminates the old subprocess and spawns a new one.
_lock = threading.Lock()
_process: Optional[subprocess.Popen] = None
_model_name: Optional[str] = None


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
    global _process, _model_name
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


def _start_server_locked(model_name: str) -> None:
    global _process, _model_name
    gguf_path = _resolve_gguf_path(model_name)
    logger.info("Iniciando vte-server para %s (%s)...", model_name, gguf_path)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    _process = subprocess.Popen(
        [
            sys.executable, "-m", "vte.server.http_server",
            "--gguf-path", gguf_path,
            "--port", str(_SERVER_PORT),
            "--host", _SERVER_HOST,
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


def _ensure_remote_locked(model_name: str) -> None:
    """Remote-GPU mode: never spawns anything, just confirms a vte-server is
    actually reachable at _SERVER_BASE_URL (through the SSH tunnel) and logs
    which model it's actually serving, so a mismatch is visible in the logs
    instead of silently talking to the wrong model. Not a strict equality
    check: vte-server's own /v1/models reports the GGUF filename stem (e.g.
    'Qwen2.5-1.5B-Instruct-Q4_K_M'), while `model_name` here is Aetheris's
    registry name (e.g. 'qwen2.5:1.5b-q4_k_m'); the two naming schemes don't
    map onto each other without duplicating VTEModel.MODEL_REGISTRY, so this
    only informs, it doesn't assert. Switching models remotely means SSHing
    in and restarting vte-server by hand; this process has no way to do
    that itself."""
    global _model_name
    if not _wait_until_ready(_READY_TIMEOUT_SECONDS):
        raise RuntimeError(
            f"Nenhum vte-server remoto respondeu em {_SERVER_BASE_URL}. "
            "Confirme que o tunel SSH esta ativo e que o vte-server foi "
            "iniciado na maquina remota (ver README.md)."
        )
    try:
        resp = httpx.get(f"{_SERVER_BASE_URL}/v1/models", timeout=5.0)
        resp.raise_for_status()
        remote_model = resp.json()["data"][0]["id"]
        logger.info("vte-server remoto conectado, servindo '%s'.", remote_model)
    except Exception as e:
        logger.warning("Nao foi possivel confirmar o modelo do vte-server remoto: %s", e)
    _model_name = model_name


def ensure_server(model_name: str) -> None:
    """Starts the vte-server subprocess for `model_name` if it isn't already
    serving it (restarting it on a model switch). Thread-safe, idempotent,
    and blocking; callers on the asyncio event loop should wrap this in
    `asyncio.to_thread`. In remote-GPU mode (see REMOTE_SERVER_MODE), waits
    for an already-running remote server instead of spawning a local one."""
    with _lock:
        if REMOTE_SERVER_MODE:
            _ensure_remote_locked(model_name)
            return
        if _process is not None and _process.poll() is None and _model_name == model_name:
            return
        if _process is not None:
            _stop_server_locked()
        _start_server_locked(model_name)


def unload() -> None:
    """Terminate the resident vte-server subprocess, if any. No-op in
    remote-GPU mode: this process never spawned that server, so it has no
    business terminating it (see REMOTE_SERVER_MODE)."""
    if REMOTE_SERVER_MODE:
        return
    with _lock:
        _stop_server_locked()


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

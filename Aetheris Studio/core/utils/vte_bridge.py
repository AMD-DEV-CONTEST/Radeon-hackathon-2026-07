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
from typing import AsyncGenerator, Dict, List, Optional, Tuple

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
# How long _wait_until_ready() polls /health before giving up on the
# vte-server subprocess (process spawn + GGUF weights loaded into VRAM,
# a cold-start cost that scales with model size -- a 70B load can
# plausibly approach 120s on its own, before any generation request is
# even sent). 90s cut that too close; 240s gives real margin without
# meaningfully delaying the failure case (the process is either making
# progress or it's actually hung, and the point of a deadline is just to
# not wait forever, not to be tight).
_READY_TIMEOUT_SECONDS = 240.0

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


def get_server_pid() -> Optional[int]:
    """PID of the resident vte-server subprocess, or None if not running.
    Used by core.audit.egress_monitor (Fase B) to scope network-connection
    sampling to processes Aetheris actually owns, rather than reaching
    into the private `_process` global directly from another module."""
    with _lock:
        return _process.pid if _process is not None and _process.poll() is None else None


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


# Idle-timeout for the streaming HTTP read (Camada 1): generous enough to
# never trip during a normal generation burst (real traffic emits a chunk
# every ~20-25ms), only on a genuine stall -- a dead connection, a hung
# backend, or a cold start slower than this. Applied to the httpx read
# itself, never to agent.py's token_gen.__anext__() -- wrapping THAT in
# asyncio.wait_for is a proven bug in this codebase (see stream_agent's
# own comment on why it uses asyncio.wait() instead): cancelling an
# in-flight __anext__() on our own hand-rolled generator corrupts it.
# httpx's own aiter_lines() is a plain network read, safe to cancel this
# way. 120s (not the original 45s): flagged directly by the Lemonade team
# -- a heavy model's prefill/TTFT on a cold or large context can
# legitimately take longer than 45s, and that's not a hang.
#
# NOTE on the "async with client.stream(...) tears the response down
# cleanly either way" claim this comment used to make: measured false for
# the shared/pooled client below. Repro'd directly (scratchpad
# repro_idle_timeout_disconnect.py): with keepalive pooling
# (max_keepalive_connections>0), letting asyncio.wait_for's TimeoutError
# propagate through `async with` does NOT close the underlying TCP
# connection -- vte-server's own request.is_disconnected() poll
# (http_server.py's sse_stream()) never fires, so the generation thread
# runs to completion instead of stopping, even though the client has long
# since given up and shown the user an error. A non-pooled client closes
# the socket immediately and the server detects it within ~10ms; a pooled
# one holds the connection open indefinitely. See the explicit
# network_stream.aclose() below, which fixes this on the pooled client
# without giving up the pooling for the (common) non-timeout case.
_IDLE_TIMEOUT_S = 120.0

_shared_client: Optional[httpx.AsyncClient] = None
_shared_client_lock = threading.Lock()


def _get_shared_client() -> httpx.AsyncClient:
    """Module-level httpx client, created once and reused across every
    stream_generate() call instead of opening a fresh connection per call
    (Camada 3). Matters most for the external-Model-API experiment path
    (a real internet TLS handshake per call); for the local vte-server
    (loopback, no TLS) the saving is negligible, but reusing one client is
    free and backend-agnostic, so there's no reason to special-case it."""
    global _shared_client
    if _shared_client is None:
        with _shared_client_lock:
            if _shared_client is None:
                _shared_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(None, connect=10.0),
                    limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=120.0),
                )
    return _shared_client


async def stream_generate(
    model_name: str, messages: List[Dict], temperature: float = 0.3, max_tokens: int = 4096,
    guided_choices: Optional[List[str]] = None, guided_choice_trigger: str = "```",
) -> AsyncGenerator[Tuple[str, str], None]:
    """Async generator yielding (kind, text) pairs from vte-server's
    OpenAI-shaped streaming endpoint (`data: {"choices":[{"delta":{...}}]}`,
    ending on `data: [DONE]`). `kind` is "content" (the real reply) or
    "reasoning" (a reasoning-capable backend's internal chain-of-thought,
    read from `delta.reasoning`).

    Previously yielded plain str deltas from `delta.content` only, with
    `delta.reasoning` silently dropped. Confirmed directly against the
    external Model API bridge that this is a real, costly gap: a
    reasoning-heavy model can spend its ENTIRE max_tokens budget on
    `reasoning` and never produce a single `content` token -- under the
    old contract that meant total silence for the whole generation (up to
    122s measured), indistinguishable from a hang. vte-server itself never
    populates `delta.reasoning`, so the local/production path only ever
    yields ("content", ...) tuples here -- behavior identical to before
    this became a tuple, just wrapped. Callers (agent.py::
    _generate_with_retry) unpack the tuple and route "reasoning" text to
    its own SSE event instead of mixing it into the real reply or the
    tool-call-parsing buffer.

    `guided_choices` (optional): passed straight through as vte-server's
    non-standard `guided_choices`/`guided_choice_trigger` extension (see
    VTE/vte/core/constrained_decoding.py) -- when set, VTE masks logits at
    the token level so generation can only complete one of these exact
    strings once `guided_choice_trigger` appears in the output. Used by
    agent.py to make it structurally impossible for VTE-served local
    models to hallucinate a tool name that isn't in TOOL_REGISTRY (a real,
    reproducible failure mode confirmed against Qwen3.6-35B-A3B -- see
    find_unmatched_tool_attempt in tools.py, which stays in place as a
    second layer for whatever this can't cover, e.g. non-VTE model
    providers with no logit access at all)."""
    await asyncio.to_thread(ensure_server, model_name)
    body = {
        "model": model_name, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens, "stream": True,
    }
    if guided_choices:
        body["guided_choices"] = guided_choices
        body["guided_choice_trigger"] = guided_choice_trigger
    client = _get_shared_client()

    # Camada 4 telemetry: same naming convention as VTE's own generate()
    # stats (prefill_duration_ttft/decoding_speed_tps, the FastFlowLM/
    # Lemonade-compatible convention), extended with a reasoning/content
    # split that only means something for a backend that actually emits
    # delta.reasoning. Chunk counts, not exact tokenizer counts -- this
    # bridge never tokenizes (vte-server/the external API do that
    # server-side), but one SSE delta chunk approximates one token closely
    # enough for a log line, not billed/exact accounting. Logged once,
    # via a `finally` so it fires on every exit path (normal [DONE],
    # dropped connection, or the generator being cancelled/.aclose()'d
    # mid-stream by a caller), not just the happy path.
    t_start = time.perf_counter()
    first_reasoning_ts: Optional[float] = None
    first_content_ts: Optional[float] = None
    reasoning_chunks = 0
    content_chunks = 0
    try:
        async with client.stream(
            "POST", f"{_SERVER_BASE_URL}/v1/chat/completions",
            json=body,
        ) as resp:
            resp.raise_for_status()
            line_iter = resp.aiter_lines()
            while True:
                try:
                    line = await asyncio.wait_for(line_iter.__anext__(), timeout=_IDLE_TIMEOUT_S)
                except StopAsyncIteration:
                    return
                except asyncio.TimeoutError:
                    # Force the actual TCP connection closed instead of
                    # relying on `async with client.stream(...)`'s normal
                    # exit -- on the shared/pooled client that leaves the
                    # connection alive and vte-server never notices we're
                    # gone (see the module-level note on _IDLE_TIMEOUT_S).
                    # Reaching into extensions like this only bypasses
                    # httpx's return-to-pool bookkeeping for THIS
                    # connection; the shared client and its pool of other
                    # connections are unaffected for subsequent calls.
                    net_stream = resp.extensions.get("network_stream")
                    if net_stream is not None:
                        await net_stream.aclose()
                    raise TimeoutError(
                        f"Nenhum token recebido em {_IDLE_TIMEOUT_S:.0f}s -- geração travou ou a conexão caiu."
                    )
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                if payload == "[DONE]":
                    return
                chunk = json.loads(payload)
                if "error" in chunk:
                    raise RuntimeError(chunk["error"].get("message", "Erro no vte-server"))
                choices = chunk.get("choices") or []
                delta = (choices[0].get("delta") or {}) if choices else {}
                reasoning = delta.get("reasoning")
                if reasoning:
                    if first_reasoning_ts is None:
                        first_reasoning_ts = time.perf_counter()
                    reasoning_chunks += 1
                    yield ("reasoning", reasoning)
                content = delta.get("content")
                if content:
                    if first_content_ts is None:
                        first_content_ts = time.perf_counter()
                    content_chunks += 1
                    yield ("content", content)
    finally:
        if first_reasoning_ts is not None or first_content_ts is not None:
            ttft_reasoning_ms = (first_reasoning_ts - t_start) * 1000 if first_reasoning_ts else None
            ttft_content_ms = (first_content_ts - t_start) * 1000 if first_content_ts else None
            logger.info(
                "vte_bridge stream stats: ttft_reasoning_ms=%s ttft_content_ms=%s "
                "reasoning_tokens=%d content_tokens=%d model=%s",
                f"{ttft_reasoning_ms:.0f}" if ttft_reasoning_ms is not None else "n/a",
                f"{ttft_content_ms:.0f}" if ttft_content_ms is not None else "n/a",
                reasoning_chunks, content_chunks, model_name,
            )

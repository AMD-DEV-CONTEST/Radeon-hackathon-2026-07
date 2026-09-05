"""ScrewShell relay — the single OpenAI-compatible entry point in front of one
llama.cpp server, owned by the InferenceCoordinator.

Responsibilities (Layer2_Implementation_Map.md §2, relay layer):
  * OpenAI-compatible /v1/models, /v1/chat/completions, /v1/completions.
  * Per request: decide the LoRA expert (trusted X-Expert header from the
    UI Orchestrator -- authenticated by X-Relay-Token -- else SkillRouter
    keyword heuristics), then hand off to the Coordinator which serializes
    the global LoRA switch.
  * Correlation ids (X-Request-Id / X-Run-Id) for audit.
  * NEVER expose the raw /lora-adapters control endpoint (security boundary).

Non-goals for v1: config generation, concurrency, sub-agent S0/S1 (Phase 1
does add the observability panel behind /v1/observ/* -- see below).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from screwshell.core.inference_coordinator import InferenceCoordinator
from screwshell.observ import (
    recent_events,
    recent_events_filtered,
    recent_gpu,
    record_gpu_sample,
    summarize,
)

log = logging.getLogger("screwshell.relay")

LLAMA_SERVER_URL = os.getenv("RELAY_LLAMA_URL", "http://127.0.0.1:8080")
MAX_PENDING = int(os.getenv("RELAY_MAX_PENDING", "4"))
# Bind address. Default is loopback: the relay is reached by the local UI and
# by frontends (opencode/pi) via an SSH tunnel (ssh -L 18090:127.0.0.1:18090),
# never exposed on a public interface. Override with RELAY_BIND_ADDR only if
# you deliberately front it with a reverse proxy / need LAN exposure -- in
# that case also set RELAY_TRUST_TOKEN so the observ + X-Expert surfaces are
# authenticated.
RELAY_BIND_ADDR = os.getenv("RELAY_BIND_ADDR", "127.0.0.1")
# Shared secret gating the trusted X-Expert header AND the observ read
# endpoints. The in-process UI Orchestrator stamps X-Expert + X-Relay-Token;
# the relay honors X-Expert ONLY when the token matches, and serves
# /v1/observ/* ONLY when the token matches. If unset, the relay trusts
# X-Expert (legacy loopback-only) AND serves observ read-only (acceptable
# because the default bind is 127.0.0.1). Production MUST set this, or keep
# the bind on loopback, to stop a network client from spoofing an expert or
# reading request history.
RELAY_TRUST_TOKEN = os.getenv("RELAY_TRUST_TOKEN", "")


def _observ_authorized(request: Request) -> bool:
    """Whether a request may read the observability endpoints.

    Unset RELAY_TRUST_TOKEN => legacy mode: allow (loopback deployments only).
    Set token => caller must present the matching X-Relay-Token.
    """
    if not RELAY_TRUST_TOKEN:
        return True
    return request.headers.get("X-Relay-Token") == RELAY_TRUST_TOKEN


def _trusts_expert_header(token: Optional[str]) -> bool:
    """Whether an X-Expert header may be honored on this request.

    Unset RELAY_TRUST_TOKEN => legacy mode: trust (loopback deployments).
    Set token => caller must present the matching X-Relay-Token.
    """
    if not RELAY_TRUST_TOKEN:
        return True
    return token == RELAY_TRUST_TOKEN


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(coord.load_base)
    # Best-effort semantic-router embedder (plan Phase 2b). Reuses the RAG
    # Qwen3-Embedding-0.6B model so Chinese / paraphrased queries that NO
    # keyword matched route semantically instead of defaulting to agent. Load
    # is lazy and failure-tolerant: if the model or its deps are unavailable
    # (e.g. the instance is air-gapped and the model is not cached) the relay
    # stays up in pure-regex mode (byte-identical to before 2b). We probe
    # HF reachability up front and bound the load in a timeout thread, because
    # transformers' internal retry loop will otherwise hang relay startup for
    # minutes when offline. Toggle off with RELAY_EMBEDDER=0 for regex-only.
    if os.getenv("RELAY_EMBEDDER", "1") != "0":
        try:
            import socket
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TE
            # Fast pre-check: do not even attempt the (slow, retrying) model
            # load if HuggingFace is unreachable -- that is the air-gapped box.
            s = socket.create_connection(("huggingface.co", 443), timeout=3)
            s.close()
            from screwshell.rag.pipeline import LocalEmbedder

            def _build():
                return LocalEmbedder()

            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_build)
                try:
                    emb = fut.result(timeout=45.0)
                    coord.router.set_embedder(emb.encode)
                    log.info("relay semantic router enabled (Qwen3-Embedding)")
                except _TE:
                    log.warning("relay semantic router load timed out (regex-only)")
                except Exception as e:  # noqa: BLE001
                    log.warning("relay semantic router unavailable (regex-only): %s", e)
        except Exception as e:  # noqa: BLE001 - never block relay startup
            log.warning("relay semantic router skipped (regex-only): %s", e)
    # Background GPU sampler: record rocm-smi telemetry into the observ store
    # every 2s so the UI GPU chart survives a relay/UI restart (R3). Best-
    # effort: if rocm-smi is unavailable or OBSERV_DIR is unset, it just no-ops.
    _threading.Thread(target=_gpu_sampler_loop, daemon=True).start()
    yield


app = FastAPI(title="ScrewShell Relay", lifespan=lifespan)
coord = InferenceCoordinator(llama_server_url=LLAMA_SERVER_URL,
                             max_pending=MAX_PENDING)


@app.get("/health")
async def health():
    return {"ok": True, "adapters": list(coord.engine.adapters),
            "current_expert": coord._current_expert}


@app.get("/v1/models")
async def models():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(coord.engine.server_url + "/v1/models")
            return JSONResponse(r.json())
    except Exception as e:  # noqa: BLE001 - surface upstream failure as 502
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/v1/completions")
async def completions(request: Request):
    # Legacy text-completion endpoint. Route on the prompt text; we wrap the
    # prompt as a single user turn and reuse the chat coordinator.
    body = await request.json()
    prompt = body.get("prompt", "")
    decision = coord.router.route(prompt if isinstance(prompt, str) else "")
    chat_body = dict(body)
    chat_body["messages"] = [{"role": "user",
                              "content": prompt if isinstance(prompt, str) else ""}]
    chat_body.pop("prompt", None)
    return await _handle(chat_body, bool(body.get("stream", False)),
                         decision.adapter, request)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    # Trusted callers (the UI Orchestrator, authenticated via X-Relay-Token)
    # stamp the already-decided expert so the relay does NOT double-route.
    # External callers (opencode/pi) omit X-Expert and get SkillRouter keyword
    # routing. We only honor X-Expert when the caller proves it is the trusted
    # internal Orchestrator; otherwise a network client could forge an expert
    # and bypass routing.
    header_expert = request.headers.get("X-Expert")
    if header_expert is not None and _trusts_expert_header(
            request.headers.get("X-Relay-Token")):
        expert = header_expert or None
    else:
        if header_expert is not None and RELAY_TRUST_TOKEN:
            log.warning("X-Expert ignored: missing/invalid X-Relay-Token "
                        "(possible spoof); re-routing via SkillRouter")
        query = _last_user_text(body.get("messages", []))
        decision = coord.router.route(query)
        expert = decision.adapter
    return await _handle(body, bool(body.get("stream", False)), expert, request)


async def _handle(body: dict, is_stream: bool, expert: Optional[str],
                 request: Request):
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
    run_id = request.headers.get("X-Run-Id")
    # Optional stress/benchmark tagging: a caller that stamps X-Benchmark: 1
    # marks this request's event benchmark=True so it is EXCLUDED from the
    # interactive health judgment (§5.3.5). Harmless when absent.
    benchmark_hdr = request.headers.get("X-Benchmark", "").strip().lower()
    benchmark = benchmark_hdr in ("1", "true", "yes")
    result = await coord.request(expert, body, is_stream,
                                 request_id=request_id, run_id=run_id,
                                 benchmark=benchmark)
    if result is None:
        return JSONResponse(
            status_code=429,
            content={"error": "inference queue full; retry later"},
            headers={"Retry-After": "5"})
    return result


def _last_user_text(messages) -> str:
    if not isinstance(messages, list):
        return ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content", "")
            return c if isinstance(c, str) else ""
    return ""


# ----- security boundary: never expose the raw LoRA control endpoint -----
@app.api_route("/lora-adapters", methods=["GET", "POST", "PUT", "DELETE"])
async def block_lora_adapters():
    return JSONResponse(status_code=404, content={"error": "not found"})


# ----- observability (Phase 1): the panel polls these for a global view -----
@app.get("/v1/observ/summary")
async def observ_summary(request: Request,
                         run_id: Optional[str] = None,
                         session_id: Optional[str] = None,
                         window_s: Optional[int] = None,
                         exclude_benchmark: bool = False):
    if not _observ_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    # All filter params are OPTIONAL; no-arg call returns the legacy global
    # summary (back-compat). session_id scopes to one operational session;
    # run_id to one browser/UI conversation; window_s to a recent time window;
    # exclude_benchmark drops stress/benchmark traffic from the aggregation.
    return JSONResponse(summarize(
        run_id=run_id, operational_session_id=session_id,
        time_window_s=window_s, exclude_benchmark=exclude_benchmark))


@app.get("/v1/observ/events")
async def observ_events(request: Request, n: int = 20,
                        run_id: Optional[str] = None,
                        session_id: Optional[str] = None,
                        window_s: Optional[int] = None,
                        exclude_benchmark: bool = False):
    if not _observ_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    if n < 1 or n > 200:
        n = 20
    return JSONResponse({"events": recent_events_filtered(
        n, run_id=run_id, operational_session_id=session_id,
        time_window_s=window_s, exclude_benchmark=exclude_benchmark)})


# ----- GPU telemetry (rocm-smi), cached so the 2s UI poll does not spawn a
# subprocess every tick -----
import threading as _threading

_gpu_lock = _threading.Lock()
_gpu_cache: dict = {"ts": 0.0, "data": None}


def _read_gpu() -> dict:
    """VRAM used/total + utilization via rocm-smi (empty dict when unavailable)."""
    try:
        out = subprocess.run(
            ["rocm-smi", "--showuse", "--showmeminfo", "vram"],
            capture_output=True, text=True, timeout=10).stdout
        used = total = use = None
        for line in out.splitlines():
            # rocm-smi prints "VRAM Total Memory (B): 51522830336" -- parse
            # the integer AFTER "): " (splitting on "(" yields "B", not a number)
            if "VRAM Total Memory" in line and "):" in line:
                try:
                    total = int(line.split("):")[1].replace(",", "").strip())
                except (IndexError, ValueError):
                    pass
            elif "VRAM Total Used Memory" in line and "):" in line:
                try:
                    used = int(line.split("):")[1].replace(",", "").strip())
                except (IndexError, ValueError):
                    pass
            elif "GPU use" in line and ":" in line:
                try:
                    use = float(line.split(":")[-1].replace("%", "").strip())
                except ValueError:
                    pass
        return {"used_b": used, "total_b": total,
                "use_pct": use, "ok": used is not None}
    except Exception as e:  # noqa: BLE001 - rocm-smi may not exist
        return {"ok": False, "error": str(e),
                "used_b": None, "total_b": None, "use_pct": None}


def _read_gpu_detailed() -> dict:
    """Full rocm-smi telemetry (util + VRAM + temp + power) via --json.

    The legacy ``_read_gpu`` only parses the text table (VRAM + util) and is
    kept for the existing ``/v1/observ/gpu`` endpoint. This one pulls the JSON
    form that also carries temperature / power, and is what the background
    sampler records into the store (R3).

    Field names are anchored to the validation report (card0 / 'GPU use (%)' /
    'VRAM Total Memory (B)' / temperature.edge / 'Average Graphics Package
    Power (W)'). If a real machine differs, print the raw JSON once and adjust
    the parse keys — do NOT fabricate values.
    """
    try:
        out = subprocess.run(
            ["rocm-smi", "--showuse", "--showmeminfo", "vram",
             "--showtemp", "--showpower", "--json"],
            capture_output=True, text=True, timeout=10).stdout
        d = json.loads(out)
        card = next((k for k in d if k.startswith("card")), "card0")
        info = d[card]
        return {
            "ts": time.time(), "card": card,
            "use_pct": float(info.get("GPU use (%)") or 0),
            "vram_used_b": int(info.get("VRAM Total Used Memory (B)") or 0),
            "vram_total_b": int(info.get("VRAM Total Memory (B)") or 0),
            "temp_c": float(info.get("Temperature (Sensor edge) (C)") or 0),
            "power_w": float(info.get("Average Graphics Package Power (W)") or 0),
            "ok": True,
        }
    except Exception as e:  # noqa: BLE001 - rocm-smi may not exist
        return {"ok": False, "error": str(e)}


def _gpu_sampler_loop() -> None:
    """Daemon loop: sample GPU telemetry every 2s and record it (R3)."""
    while True:
        try:
            s = _read_gpu_detailed()
            if s.get("ok"):
                record_gpu_sample(s)
        except Exception as e:  # noqa: BLE001 - sampling failure must not kill relay
            log.warning("gpu sample failed: %s", e)
        time.sleep(2.0)


@app.get("/v1/observ/gpu")
async def observ_gpu(request: Request):
    if not _observ_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    now = time.time()
    with _gpu_lock:
        if now - _gpu_cache["ts"] > 3.0:
            _gpu_cache["data"] = _read_gpu()
            _gpu_cache["ts"] = now
        return JSONResponse(_gpu_cache["data"])


@app.get("/v1/observ/gpu_history")
async def observ_gpu_history(request: Request, n: int = 180):
    """GPU time-series from the store (R3). UI rebuilds its chart from this so
    history survives a relay/UI restart. Newest-first."""
    if not _observ_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    if n < 1 or n > 1800:
        n = 180
    return JSONResponse({"samples": recent_gpu(n)})


@app.get("/v1/observ/slots")
async def observ_slots(request: Request):
    """Forward llama.cpp's /slots so the UI can show what the model is doing
    (R1). Field names are llama.cpp's own: is_processing / n_prompt_tokens*."""
    if not _observ_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(coord.engine.server_url + "/slots")
            return JSONResponse(r.json())
    except Exception as e:  # noqa: BLE001 - surface upstream failure as 502
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/v1/observ/expert")
async def observ_expert(request: Request):
    """Authoritative current-expert view (R4). Mirrors /health but on the
    observ path; UI prefers this and falls back to /health."""
    if not _observ_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    return JSONResponse({"current_expert": coord._current_expert,
                         "adapters": list(coord.engine.adapters)})


@app.get("/v1/observ/llama_metrics")
async def observ_llama_metrics(request: Request):
    """Server-wide counters from llama.cpp /metrics (R2, optional --metrics).

    Metric names are anchored to the validation report but enumerated on the
    real box after restart; if the server has no /metrics (501) this returns
    ok:False and the UI shows 'n/a' rather than fabricating a number.
    """
    if not _observ_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(coord.engine.server_url + "/metrics")
        text = r.text
        counters: dict = {}
        for key in ("cache_hits_total", "prompt_tokens_total",
                    "tokens_predicted_total", "n_busy_slots_per_decode"):
            # llama.cpp emits the prefix as `llamacpp:` on current builds (the
            # older `llama:` form is kept for compatibility). Some builds expose
            # no KV cache-hit counter at all -> that key stays None (never
            # fabricated).
            m = re.search(rf"^(?:llama|llamacpp):{key}\s+([0-9.]+)", text, re.M)
            counters[key] = float(m.group(1)) if m else None
        return JSONResponse({"ok": True, "counters": counters})
    except Exception as e:  # noqa: BLE001 - upstream down / no /metrics
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/v1/observ/props")
async def observ_props(request: Request):
    """Read-only forward of llama-server /props (P4 config-version snapshots).

    D3 decision: config history is collected by polling llama-server's native
    ``/props`` — zero storage, zero schema migration. The UI reaches the relay
    only, so the relay forwards this read-only endpoint (observ-gated) instead
    of the UI bypassing the relay to hit llama-server directly. If the server
    has no /props (older build) or is down, this returns {} and the UI shows
    "no snapshot" rather than fabricating config.
    """
    if not _observ_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(coord.engine.server_url + "/props")
        if r.status_code == 200:
            return JSONResponse(r.json())
        return JSONResponse({})
    except Exception:  # noqa: BLE001 - upstream down / no /props
        return JSONResponse({})


# ----------------------------- one-click autotune (tune-loop plan, Todo 6) ---
# Change-type endpoints: they restart llama-server. Auth is the SAME shared
# secret as observ (RELAY_TRUST_TOKEN / X-Relay-Token) but these are MUTATING
# operations, so the guard is explicit and the 401 body names the operation.
import threading

from screwshell.autotune.cycle import TuneCycle, DONE, ABORT
from screwshell.autotune.mapper import preset as _map_preset, TuneGoal
from screwshell.autotune.governor import LlamaServerLifecycle, _health_ok
from screwshell.autotune.scorer import score as _autotune_score
from screwshell.gateway.config import ServerConfig

_TUNE_LOCK = threading.Lock()
_tune_cycle: TuneCycle | None = None
_tune_state_path = os.path.join(os.getenv("OBSERV_DIR", "."), "tune_state.json")
_TUNE_PORT = int(os.getenv("RELAY_LLAMA_PORT", "8080"))
_TUNE_LLAMA_URL = os.getenv("RELAY_LLAMA_URL", "http://127.0.0.1:8080")
# Full path to the llama-server binary the tune cycle restarts. The bare
# "llama-server" is usually NOT on PATH on the instance, so start_argv's Popen
# would fail to find it. Configurable via env for other deployments.
_TUNE_LLAMA_BIN = os.getenv(
    "LLAMA_SERVER_BIN", "/opt/llama.cpp/build/bin/llama-server")
# LoRA lineup the tune cycle MUST preserve on every restart (阵容铁律). The
# baseline /props usually lists the loaded adapters; fall back to a comma-
# separated env list (default = the W7900 production roster).
_TUNE_LORA_PATHS = [
    p for p in os.getenv("LLAMA_LORA_PATHS", "").split(",") if p
] or [
    "/workspace/persistent/screwshell_run/loras/btl3/adapter.gguf",
    "/workspace/persistent/screwshell_run/loras/cybersec/adapter.gguf",
    "/workspace/persistent/screwshell_run/loras/rag_n7/adapter.gguf",
]


def _tune_authorized(request: Request) -> bool:
    """Auth for the MUTATING tune endpoints. Same secret as observ, but these
    restart llama-server so we keep the guard explicit (change-type)."""
    if not RELAY_TRUST_TOKEN:
        return True
    return request.headers.get("X-Relay-Token") == RELAY_TRUST_TOKEN


class _RelayLifecycle:
    """Adapter so TuneCycle can drive the real server via LlamaServerLifecycle.

    Only ``start_argv`` / ``health_ok`` are used by the cycle (no direct Popen).
    """

    def __init__(self):
        self._lc = LlamaServerLifecycle("dummy --lora {lora}", port=_TUNE_PORT,
                                        log_path="llama_server.log")

    def start_argv(self, argv, takeover: bool = False):
        return self._lc.start_argv(list(argv), takeover=takeover)

    def health_ok(self):
        return _health_ok(self._lc.health_url)


def _flatten_props(props: dict) -> dict:
    """Flatten a llama-server /props blob so the tuning cycle can mutate a
    single flat spec.

    llama-server nests the tunable generation params under
    ``default_generation_settings``. We merge those into the top level so the
    cycle's flat ``_apply_goal`` writes (n_ctx / n_batch / ...) are seen by
    ``_tune_argv_builder`` / ``_tune_planner``.

    Precedence: a top-level key ALREADY present (i.e. the cycle has applied a
    TuneGoal) wins over the stale nested default — otherwise the nested value
    would clobber an applied override.
    """
    out = dict(props or {})
    dgs = out.pop("default_generation_settings", None)
    if isinstance(dgs, dict):
        for k, v in dgs.items():
            out.setdefault(k, v)   # only fill keys not already overridden
    return out


def _tune_argv_builder(spec: dict) -> list[str]:
    """Build a safe llama-server argv from a FLAT spec (cycle-mutated).

    Always emits --jinja and a finite reasoning-budget (iron rules). Unmapped
    keys fall back to ServerConfig defaults.
    """
    spec = _flatten_props(spec) if isinstance(spec, dict) else {}
    cfg = ServerConfig(
        model_path=spec.get("model_path") or os.getenv("LLAMA_MODEL_PATH", "/model.gguf"),
        lora_paths=list(_TUNE_LORA_PATHS),
        port=int(spec.get("port", _TUNE_PORT)),
        ctx_tokens=int(spec.get("n_ctx", 8192)) if spec.get("n_ctx") else None,
        threads=int(spec.get("n_threads", 24)) if spec.get("n_threads") else 24,
        n_gpu_layers=int(spec.get("n_gpu_layers")) if spec.get("n_gpu_layers") else None,
        reasoning_budget=int(spec.get("reasoning_budget", 4096)),
        parallel=int(spec.get("n_parallel", 2)) if spec.get("n_parallel") else 2,
        n_batch=int(spec.get("n_batch")) if spec.get("n_batch") else None,
        cache_type_k=spec.get("cache_type_k"),
        cache_type_v=spec.get("cache_type_v"),
        flash_attn=str(spec.get("flash_attn", "on") or "on"),
        extra_args=[],
    )
    return cfg.to_argv(binary=_TUNE_LLAMA_BIN)


def _tune_planner(preset: str, current_spec: dict, param: str) -> TuneGoal:
    """Per-param planner walking PARAM_ORDER. Delegates the preset's primary
    lever to mapper.preset; applies deterministic nudges for the rest so the
    cycle can still exercise each parameter (phase-1 single-param tuning)."""
    spec = _flatten_props(current_spec) if isinstance(current_spec, dict) else {}
    goal = _map_preset(preset, spec)
    if goal.param == param or goal.param == "__none__":
        return goal
    if param == "n-batch":
        return TuneGoal("n_batch", max(int(spec.get("n_batch", 256)) * 2, 512),
                        "tune n_batch up")
    if param == "ctx":
        return TuneGoal("n_ctx", int(spec.get("n_ctx", 8192)), "tune ctx")
    if param == "flash-attn":
        return TuneGoal("flash_attn", "on", "ensure flash-attn on")
    if param == "parallel":
        return TuneGoal("parallel", max(int(spec.get("n_parallel", 2)) + 1, 2),
                        "tune parallel up")
    if param == "threads":
        return TuneGoal("threads", int(spec.get("n_threads", 24)), "keep threads")
    if param == "n-gpu-layers":
        return TuneGoal("n_gpu_layers", int(spec.get("n_gpu_layers", 999)),
                        "keep n_gpu_layers")
    if param == "reasoning-budget":
        return TuneGoal("reasoning_budget", 4096, "keep finite reasoning budget")
    if param == "cache-type":
        return TuneGoal("cache_type_k", spec.get("cache_type_k", "q8_0"),
                        "tune KV cache type")
    return TuneGoal("__none__", None, "skip")


def _tune_benchmark(n: int) -> None:
    """Drive n X-Benchmark:1 chat-completions through the relay so the scorer
    has real, attributable traffic. Hits the relay's own chat endpoint on
    loopback (never the orchestrator)."""
    try:
        with httpx.Client(timeout=60.0) as client:
            for _ in range(n):
                client.post(
                    f"http://127.0.0.1:{os.getenv('RELAY_PORT', '18090')}/v1/chat/completions",
                    json={"model": "m", "messages": [{"role": "user",
                          "content": "ping"}], "max_tokens": 16, "temperature": 0.0},
                    headers={"X-Benchmark": "1",
                              "X-Relay-Token": RELAY_TRUST_TOKEN or ""})
    except Exception as e:  # noqa: BLE001 - benchmark generation is best-effort
        log.warning("tune benchmark generation failed: %s", e)


def _tune_collect() -> list[dict]:
    """Collect benchmark events for scoring (poll until enough land).

    Fetches a WIDE window (n=200) so interleaved non-benchmark events do not
    starve the count — the last 16 raw events might not all be benchmark even
    when 16+ benchmark events exist.
    """
    import screwshell.observ as _obs
    for _ in range(30):
        evs = _obs.recent_events_filtered(200, exclude_benchmark=False)
        bench = [e for e in evs if e.get("benchmark")]
        if len(bench) >= MIN_N_SAFE:
            return bench[:MIN_N_SAFE]
        time.sleep(1.0)
    return [e for e in _obs.recent_events_filtered(200, exclude_benchmark=False)
            if e.get("benchmark")][:MIN_N_SAFE]


MIN_N_SAFE = 16  # mirror cycle.MIN_N; local constant to avoid import cycle churn


async def _run_tune_cycle(preset: str, window_min: int,
                          min_restart_interval_s: float, max_rounds: int) -> None:
    """Background worker: build the cycle, fetch baseline from /props, run it
    off the event loop (asyncio.to_thread) so /v1/tune/status stays responsive."""
    global _tune_cycle
    lc = _RelayLifecycle()
    cyc = TuneCycle(
        lifecycle=lc, scorer=_autotune_score, planner=_tune_planner,
        benchmark_generator=_tune_benchmark, event_collector=_tune_collect,
        state_path=_tune_state_path, max_rounds=max_rounds,
        min_restart_interval_s=min_restart_interval_s)
    with _TUNE_LOCK:
        _tune_cycle = cyc
    # baseline from llama-server /props (read-only forward), flattened so the
    # cycle's flat _apply_goal writes line up with _tune_argv_builder/planner.
    baseline: dict = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(_TUNE_LLAMA_URL + "/props")
            if r.status_code == 200:
                baseline = _flatten_props(r.json())
    except Exception:  # noqa: BLE001 - fall back to empty baseline
        baseline = {}
    await asyncio.to_thread(cyc.run, preset, baseline, _tune_argv_builder)
    with _TUNE_LOCK:
        _tune_cycle = None


@app.post("/v1/tune/start")
async def tune_start(request: Request):
    if not _tune_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    with _TUNE_LOCK:
        if _tune_cycle is not None:
            return JSONResponse(status_code=409,
                                content={"error": "tune cycle already running",
                                         "status": _tune_cycle.status})
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    preset = str(body.get("preset", "balance"))
    window_min = int(body.get("window_min", 10))
    min_restart_interval_s = float(body.get("min_restart_interval_s", 60.0))
    max_rounds = int(body.get("max_rounds", 8))
    # fire-and-forget in the background; cycle.run is blocking I/O
    asyncio.create_task(_run_tune_cycle(
        preset, window_min, min_restart_interval_s, max_rounds))
    return JSONResponse(status_code=202,
                        content={"status": "running", "preset": preset})


@app.post("/v1/tune/stop")
async def tune_stop(request: Request):
    if not _tune_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    with _TUNE_LOCK:
        if _tune_cycle is None:
            return JSONResponse(content={"status": "idle", "note": "no running cycle"})
        _tune_cycle.stop()
    return JSONResponse(content={"status": "stopping"})


@app.get("/v1/tune/status")
async def tune_status(request: Request):
    if not _tune_authorized(request):
        return JSONResponse(status_code=401,
                            content={"error": "missing/invalid X-Relay-Token"})
    with _TUNE_LOCK:
        if _tune_cycle is None:
            # recover from persisted state (relay restart mid-run)
            return JSONResponse(content={"status": "idle", "history": [],
                                         "server_may_be_down": False})
        return JSONResponse(content={
            "status": _tune_cycle.status,
            "history": [vars(h) for h in _tune_cycle.history],
            "server_may_be_down": _tune_cycle.server_may_be_down,
            "last_good_argv": _tune_cycle.last_good_argv,
            "original_argv": _tune_cycle.original_argv,
        })


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("RELAY_PORT", "18090"))
    uvicorn.run(app, host=RELAY_BIND_ADDR, port=port)

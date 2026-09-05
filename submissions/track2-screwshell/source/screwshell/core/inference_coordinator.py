"""InferenceCoordinator — single owner of the global LoRA state for one
llama.cpp server, behind the ScrewShell relay.

Why this exists (Layer2_Implementation_Map.md §1.4 / §2):
  llama.cpp exposes LoRA switching as a *server-global* control
  (``POST /lora-adapters``). With several frontends (web agent, opencode, pi)
  sharing one server, a naive per-request switch corrupts that global state
  (kv_reprefill_report P0: experts silently fall back to base, HTTP 0 error).
  This coordinator serializes every switch+generate behind one asyncio.Lock,
  so at most one request drives the global LoRA at a time. The relay layer
  above it never touches /lora-adapters directly.

Phase 0 scope: global switch + single serial queue + lock-held streaming
+ 429 on queue overflow.
Phase 1 scope (this file): emit one thread-safe ``RequestEvent`` per request
to the observability store (route / adapter / switch / TTFT / llama.cpp
timings / KV hit / thinking / error / run_id). Never fabricates a measurement.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from screwshell.core.mol_engine_llamacpp import MoLLlamaCpp
from screwshell.core.router import SkillRouter, is_forbidden
from screwshell.observ import RequestEvent, record_event
from screwshell.observ.event import new_id

log = logging.getLogger("screwshell.coordinator")


def _ms(v) -> Optional[float]:
    return round(float(v), 3) if isinstance(v, (int, float)) else None


def _fill_from_body(ev: RequestEvent, body: dict, payload: dict) -> None:
    """Backfill token + timing fields from a llama.cpp chat-completion body.

    Strictly observational: only copies numbers the server actually sent.
    Missing ``timings`` leaves prefill/decode/KV at ``None`` (no fabrication).
    """
    usage = body.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    ev.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    ev.completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    ev.cached_tokens = int(details.get("cached_tokens", 0) or 0)

    t = body.get("timings") or {}
    ev.prefill_ms = _ms(t.get("prompt_ms"))
    ev.decode_ms = _ms(t.get("predicted_ms"))
    ev.decode_tps = t.get("predicted_per_second")
    if not ev.cached_tokens and isinstance(t.get("cache_n"), int):
        ev.cached_tokens = int(t["cache_n"])
    # cached_tokens == 0 is a REAL measurement (e.g. just switched expert ->
    # KV invalidated), not "unknown" -- surface it as 0.0, never leave it
    # implied-missing. Only skip when the server gave no prompt token count.
    if ev.prompt_tokens:
        ev.kv_hit_rate = round(ev.cached_tokens / ev.prompt_tokens, 4)
    # cache_signal_valid: the cached_tokens reading is trustworthy for the
    # session-boundary heuristic ONLY when accounting is valid (prompt_tokens>0).
    # A 0-prompt request must never trigger a no_reusable_prefix boundary.
    ev.cache_signal_valid = bool(ev.prompt_tokens > 0)

    ctk = payload.get("chat_template_kwargs")
    if isinstance(ctk, dict):
        ev.thinking = bool(ctk.get("enable_thinking"))


class InferenceCoordinator:
    def __init__(self, llama_server_url: str = "http://127.0.0.1:8080",
                 max_pending: int = 4, request_timeout_s: float = 150.0,
                 startup_timeout_s: float = 30.0):
        # This engine is the ONLY component allowed to call /lora-adapters on
        # the real server. It is never in relay_mode.
        self.engine = MoLLlamaCpp("llamacpp",
                                  server_url=llama_server_url.rstrip("/"))
        self.router = SkillRouter()
        self.lock = asyncio.Lock()
        self._pending = 0
        self.max_pending = max_pending
        self.request_timeout_s = float(
            os.getenv("RELAY_REQUEST_TIMEOUT_S", str(request_timeout_s)) or request_timeout_s)
        # Startup readiness budget: how long to keep probing the llama-server
        # for its preloaded LoRA list before giving up. Refusing to start when
        # no adapter is reachable is deliberate -- starting "silent base" is
        # exactly the P0 bug class this layer exists to prevent.
        self.startup_timeout_s = float(
            os.getenv("RELAY_STARTUP_TIMEOUT_S", str(startup_timeout_s)) or startup_timeout_s)
        self._current_expert: Optional[str] = None
        # Current operational session id (cache-reuse segment). None until the
        # first request assigns one. Mutated ONLY inside the serial lock, so the
        # coordinator is the single writer (no concurrent-session race, §5.2).
        self._op_session_id: Optional[str] = None

    # ----- lifecycle -----
    def load_base(self) -> None:
        """Probe the llama-server for its preloaded LoRA list, then force BASE.

        Forcing base on startup fixes the live bug where the server launched
        without ``--lora-init-without-apply`` and therefore had all three
        LoRAs pinned at scale 1.0 (a silent blend, not MoL).

        Startup readiness gate: the relay MUST NOT come up in a state where
        ``resolve_expert`` degrades every expert to base (the silent-fallback
        P0 class). If the server is unreachable or exposes no preloaded LoRAs
        within ``startup_timeout_s``, we raise instead of starting silent --
        the operator then sees a hard failure and starts llama-server first.
        """
        deadline = time.monotonic() + self.startup_timeout_s
        while time.monotonic() < deadline:
            try:
                self.engine.load_base()
            except Exception as e:  # engine.load_base normally swallows; be safe
                log.warning("engine.load_base raised (will retry): %s", e)
            if self.engine.adapters:
                break
            log.warning("llama-server %s not ready (no preloaded LoRAs); "
                        "retrying until t+%.0fs", self.engine.server_url,
                        self.startup_timeout_s)
            time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
        if not self.engine.adapters:
            raise RuntimeError(
                f"InferenceCoordinator: llama-server at "
                f"{self.engine.server_url} unreachable or exposed no preloaded "
                f"LoRAs after {self.startup_timeout_s:.0f}s. Refusing to start "
                f"the relay in silent-base mode (that is the P0 bug class this "
                f"layer exists to prevent). Start llama-server with "
                f"`--lora <...> --lora-init-without-apply` before the relay, or "
                f"raise RELAY_STARTUP_TIMEOUT_S.")
        self.engine.activate(None)
        self._current_expert = None
        log.info("InferenceCoordinator ready; adapters=%s",
                 list(self.engine.adapters))

    # ----- routing resolution -----
    def resolve_expert(self, decision_adapter: Optional[str]) -> Optional[str]:
        """Map a routed logical expert name to a switchable adapter, or None.

        None means 'pure base' and is the safe fallback for:
          * an explicitly forbidden expert (TRUTH §6);
          * an expert never preloaded via --lora (e.g. teichai_plan has no GGUF
            on this box) — switching would silently run base.
        """
        if decision_adapter is None:
            return None
        if is_forbidden(decision_adapter):
            log.warning("refusing forbidden expert %s -> base", decision_adapter)
            return None
        if decision_adapter not in self.engine.adapters:
            log.warning("expert %s not preloaded -> base", decision_adapter)
            return None
        return decision_adapter

    # ----- operational session (cache-reuse segment) assignment -----
    def _assign_operational_session(self, ev: "RequestEvent") -> None:
        """Assign ``operational_session_id`` + ``boundary_reason`` to ``ev``.

        MUST be called while holding ``self.lock`` (single writer). Boundary
        rule (§5.2), controlled signal only:

          no_reusable_prefix_observed =
              ev.cache_signal_valid            # prompt_tokens > 0
              AND ev.cached_tokens == 0

        NOTE: ``no_reusable_prefix_observed`` is a HEURISTIC — "no reusable
        prefix OBSERVED", NOT proof of a physical cold start. cache disabled /
        slot eviction / template change can also yield cached_tokens==0. The
        ``cache_signal_valid`` guard prevents a 0-prompt request from being
        mistaken for a boundary. v1 does not plumb llama.cpp's cache_prompt
        flag, so the heuristic stands; documented here on purpose.
        """
        # Explicit boundary already pinned (e.g. reset/model_reload) wins.
        reason = ev.boundary_reason if ev.boundary_reason not in ("", "first") \
            else None
        if reason is None:
            no_reusable_prefix_observed = (
                ev.cache_signal_valid and ev.cached_tokens == 0)
            if no_reusable_prefix_observed:
                reason = "no_reusable_prefix"
            elif self._op_session_id is None:
                reason = "first"
            else:
                reason = ""  # warm continuation
        is_boundary = reason in ("no_reusable_prefix", "explicit_reset",
                                 "model_reload", "first")
        if is_boundary:
            self._op_session_id = new_id()
        ev.operational_session_id = self._op_session_id or ""
        ev.boundary_reason = reason

    def reset_operational_session(self) -> None:
        """Force the next request to start a fresh operational session.

        Call on an explicit user reset or a model/expert reload that invalidates
        the warm KV prefix. The next ``_assign_operational_session`` call will
        mint a new id (boundary_reason "first" unless an explicit reason is set).
        """
        self._op_session_id = None

    # ----- the serial request -----
    async def request(self, expert: Optional[str], payload: dict,
                      is_stream: bool,
                      request_id: Optional[str] = None,
                      run_id: Optional[str] = None,
                      benchmark: bool = False):
        """Run one inference request through the serial switch+generate.

        Returns a FastAPI response (StreamingResponse / JSONResponse), or
        ``None`` when the pending queue is full (the relay turns that into 429).
        Emits exactly one ``RequestEvent`` to the observability store.
        """
        if self._pending >= self.max_pending:
            return None
        self._pending += 1
        t_enqueue = time.time()
        target = self.resolve_expert(expert)
        ev = RequestEvent(request_id=request_id or "", run_id=run_id,
                          route=expert, adapter=target, stream=is_stream,
                          model=payload.get("model", "m"),
                          benchmark=benchmark)
        # Activity-stream fields: what the client actually asked (truncated)
        # and which tools it invoked, so the panel shows opencode/pi requests
        # as readable activity, not just opaque metrics. No raw content stored.
        msgs = payload.get("messages") or []
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str):
                    ev.user_msg = c[:120].replace("\n", " ")
                break
        for m in msgs:
            if not isinstance(m, dict):
                continue
            for tc in (m.get("tool_calls") or []):
                fn = (tc.get("function") or {})
                ev.tool_calls.append({
                    "name": (fn.get("name") or "")[:40],
                    "args": (fn.get("arguments") or "")[:160]})
            if m.get("role") == "tool":
                content = m.get("content")
                if isinstance(content, str):
                    ev.tool_calls.append({"name": "→tool_result",
                                          "args": content[:120]})

        # Defense in depth: never forward a per-request "lora" override. The
        # coordinator owns switching; a stray key would re-introduce the P0 mix
        # of global (D) + request-level (C) paths.
        clean = {k: v for k, v in payload.items() if k != "lora"}
        # Default thinking OFF for OpenAI-standard clients (opencode / pi send
        # no chat_template_kwargs). Qwen3.6 defaults thinking ON, and with the
        # standard protocol that makes every completion come back as
        # reasoning_content with an EMPTY content -- and, worse, tool calls
        # never fire (the budget is eaten by the reasoning chain). VERIFIED on
        # the W7900 box (2026-08-04): llama-server only honors
        # `chat_template_kwargs.enable_thinking`; the top-level `thinking`
        # field is silently ignored. Explicit per-request control wins.
        if "thinking" not in clean and "chat_template_kwargs" not in clean:
            clean["chat_template_kwargs"] = {"enable_thinking": False}
        if is_stream:
            # Ask the server to attach a usage object to the final SSE chunk so
            # the panel can show prompt/completion/KV token counts for streams
            # too (OpenAI-standard flag; does not change generation).
            clean = {**clean, "stream_options": {"include_usage": True}}

        # Bound generation length. The relay is single-expert-serial by design
        # (one global LoRA lock), so an UNBOUNDED generation would monopolize
        # the lock for minutes and make the whole panel appear frozen -- every
        # other request (including the next chat turn) queues behind it. A sane
        # ceiling keeps each call bounded; the orchestrator can still raise it
        # up to the cap via max_tokens. Tunable via RELAY_MAX_GEN_TOKENS.
        _CAP = int(os.getenv("RELAY_MAX_GEN_TOKENS", "1024"))
        try:
            _mt = int(clean.get("max_tokens") or 0)
        except (TypeError, ValueError):
            _mt = 0
        if _mt <= 0 or _mt > _CAP:
            clean["max_tokens"] = _CAP

        url = self.engine.server_url + "/v1/chat/completions"

        if is_stream:
            async def gen():
                t0 = time.time()
                ttft_set = False
                last_body: dict = {}
                buf = bytearray()
                try:
                    async with self.lock:
                        ev.queue_wait_ms = round((time.time() - t_enqueue) * 1000, 1)
                        switched = (target != self._current_expert)
                        if switched:
                            t0 = time.time()
                            await asyncio.to_thread(self.engine.activate, target)
                            self._current_expert = target
                            ev.switch_ms = round((time.time() - t0) * 1000, 1)
                        ev.switched = switched
                        ev.adapter = target
                        self._assign_operational_session(ev)
                        async with httpx.AsyncClient(
                                timeout=self.request_timeout_s) as client:
                            async with client.stream(
                                    "POST", url, json=clean) as r:
                                ev.status_code = r.status_code
                                if r.status_code >= 400:
                                    # httpx stream() does not raise on status;
                                    # an upstream 4xx/5xx would otherwise be
                                    # forwarded as a (broken) SSE stream and the
                                    # error silently dropped. Emit one SSE error
                                    # event instead so clients see the failure.
                                    err_text = ""
                                    try:
                                        err_text = (await r.aread()).decode(
                                            "utf-8", "replace")
                                    except Exception:  # noqa: BLE001
                                        pass
                                    ev.ok = False
                                    ev.error = (f"upstream {r.status_code}: "
                                                f"{err_text[:200]}")
                                    yield b"data: " + json.dumps(
                                        {"error": ev.error}).encode(
                                        "utf-8") + b"\n\n"
                                    return
                                async for raw in r.aiter_raw():
                                    buf.extend(raw)
                                    text = buf.decode("utf-8", "replace")
                                    for line in text.split("\n"):
                                        if not line.startswith("data:"):
                                            continue
                                        chunk_s = line[5:].strip()
                                        if not chunk_s or chunk_s == "[DONE]":
                                            continue
                                        try:
                                            chunk = json.loads(chunk_s)
                                        except Exception:  # noqa: BLE001
                                            continue
                                        last_body = chunk
                                        if not ttft_set:
                                            for ch in (chunk.get("choices") or []):
                                                d = (ch.get("delta") or {}).get(
                                                    "content")
                                                if isinstance(d, str) and d:
                                                    ev.ttft_ms = round(
                                                        (time.time() - t0) * 1000, 1)
                                                    ttft_set = True
                                                    break
                                    # keep only the trailing partial SSE line
                                    idx = buf.rfind(b"\n")
                                    if idx >= 0:
                                        del buf[:idx + 1]
                                    yield raw
                    # stream consumed -> backfill timings from the last chunk
                    _fill_from_body(ev, last_body, clean)
                    ev.ok = True
                except httpx.HTTPError as e:
                    ev.ok = False
                    ev.error = f"upstream error: {e}"
                    ev.status_code = 502
                    yield b"data: " + json.dumps(
                        {"error": ev.error}).encode("utf-8") + b"\n\n"
                except Exception as e:  # noqa: BLE001
                    ev.ok = False
                    ev.error = f"{type(e).__name__}: {e}"
                    ev.status_code = 500
                    # e.g. the LoRA switch failed inside engine.activate()
                    # (P0 hard-fail): the client must SEE that the request did
                    # not run, not just watch the SSE stream end silently.
                    yield b"data: " + json.dumps(
                        {"error": ev.error}).encode("utf-8") + b"\n\n"
                finally:
                    self._pending -= 1
                    # Offload the (blocking) JSONL + SQLite write to a worker
                    # thread so it never stalls the asyncio event loop. The
                    # store guards its own I/O with a threading.Lock, so it is
                    # safe to invoke from the loop's default executor.
                    await asyncio.to_thread(record_event, ev)
            return StreamingResponse(gen(), media_type="text/event-stream")

        # non-stream: fully buffered, lock held for the whole call
        try:
            async with self.lock:
                ev.queue_wait_ms = round((time.time() - t_enqueue) * 1000, 1)
                switched = (target != self._current_expert)
                if switched:
                    t0 = time.time()
                    await asyncio.to_thread(self.engine.activate, target)
                    self._current_expert = target
                    ev.switch_ms = round((time.time() - t0) * 1000, 1)
                ev.switched = switched
                ev.adapter = target
                self._assign_operational_session(ev)
                async with httpx.AsyncClient(
                        timeout=self.request_timeout_s) as client:
                    try:
                        r = await client.post(url, json=clean)
                    except httpx.HTTPError as e:
                        ev.ok = False
                        ev.error = f"upstream error: {e}"
                        ev.status_code = 502
                        return JSONResponse(
                            {"error": f"upstream error: {e}"}, status_code=502)
                    body = None
                    try:
                        body = r.json()
                    except Exception:
                        # llama.cpp error bodies are not always JSON; surface
                        # the raw text so the failure is never silently masked.
                        body = {"error": r.text}
                    ev.status_code = r.status_code
                    if r.status_code >= 400:
                        # upstream failure must not be recorded as a success
                        # in the panel (ev.ok defaults True)
                        ev.ok = False
                        err_text = (body or {}).get("error")
                        if isinstance(err_text, str) and err_text:
                            ev.error = err_text[:300]
                    _fill_from_body(ev, body, clean)
            return JSONResponse(body, status_code=r.status_code)
        except Exception as e:  # noqa: BLE001
            ev.ok = False
            ev.error = f"{type(e).__name__}: {e}"
            return JSONResponse(
                {"error": f"{type(e).__name__}: {e}"}, status_code=500)
        finally:
            self._pending -= 1
            # Offload the (blocking) JSONL + SQLite write to a worker thread
            # so it never stalls the asyncio event loop.
            await asyncio.to_thread(record_event, ev)

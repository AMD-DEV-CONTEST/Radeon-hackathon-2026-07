"""llama.cpp server backend for ScrewShell's MoL inference core (path D).

This module implements the same interface contract as `MoLEngine` (peft version)
so the Orchestrator and Skill Router can switch backends with zero code changes:

    load_base()            -> no local load; just records server URL
    load_adapter(name,path)-> registers {name: gguf_path} (server preloads via --lora)
    activate(name)         -> POST /lora-adapters (set global scale; name=None = base)
    chat(messages,...)     -> POST /v1/chat/completions (forwards messages)
    status()               -> base / active_adapter / adapters / vram / switches

Design notes:
- This class is intentionally NOT a subclass of `MoLEngine`: the peft version
  imports torch and calls CUDA APIs. The llama.cpp backend is pure HTTP and must
  not pull torch/CUDA into the process (it runs against a remote server over SSH
  tunnel, or a local `llama-server`).
- LoRA ids are assigned by the order of `--lora` flags at server startup
  (id=0,1,2...). We map adapter name -> id via GET /lora-adapters on load_base.
- SwitchRecord / GenStats are reused from mol_engine to keep the data contract
  identical across backends.

Requires no third-party deps: uses urllib from the standard library.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from screwshell.core.mol_types import SwitchRecord, GenStats, CAP_KEYS
from screwshell.core.router import is_forbidden, logical_expert_name

log = logging.getLogger("screwshell.mol.llamacpp")

# 1-token probe payload used by capabilities(). Deliberately tiny: it costs one
# decode step on a 27B model, and it runs at most once per process.
_PROBE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {"name": "screwshell_probe", "strict": True,
                    "schema": {"type": "object",
                               "properties": {"ok": {"type": "boolean"}},
                               "required": ["ok"]}},
}
_PROBE_GRAMMAR = 'root ::= "a"'

# Thin-adapter config revision (P1): identifies the deployment/gateway contract
# this engine speaks. Surfaced in status() and request audit so a run can be
# tied back to the exact adapter config that served it. Override via
# SCREWSHELL_CONFIG_REVISION; the default marks the P1 baseline.
CONFIG_REVISION = os.getenv("SCREWSHELL_CONFIG_REVISION", "p1-adapter-cf4cb9a")


class MoLLlamaCpp:
    """Frozen base served by llama.cpp server + hot-swappable GGUF LoRA experts.

    Mirrors `MoLEngine`'s public surface so Router/Orchestrator are backend-agnostic.
    """

    def __init__(self, base_path: str, server_url: str = "http://127.0.0.1:8080",
                 timeout: float = 120.0, relay_mode: bool = False):
        self.base_path = base_path
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        # relay_mode (env MOL_RELAY_MODE): this engine sits *behind* the
        # ScrewShell relay. The relay owns the global LoRA state, so activate()
        # becomes a no-op that only records intent (stamped on X-Expert), and
        # chat() forwards to the relay instead of touching /lora-adapters.
        self.relay_mode = bool(relay_mode) or \
            os.getenv("MOL_RELAY_MODE", "").lower() in ("1", "true", "yes", "on")
        # POC gate fix (gateway-poc-handoff review, P0): when ScrewShell sits
        # behind llama-swap, requests must carry the gateway API key and a model
        # id the gateway recognizes. Both are opt-in via env so the direct
        # llama-server path (no key, model="m") keeps working unchanged.
        #   MOL_LLAMACPP_API_KEY : bearer token for the gateway (empty = none).
        #   MOL_LLAMACPP_MODEL   : gateway model id; unset keeps "m" (direct server).
        self.api_key = os.getenv("MOL_LLAMACPP_API_KEY", "") or ""
        self.model = os.getenv("MOL_LLAMACPP_MODEL", "m") or "m"
        # Thin-adapter (P1) state:
        #   config_revision : deployment/gateway contract id for audit/panel.
        #   request_audit   : lightweight per-request log for the UI panel
        #                     (request_id, run_id, model, status, latency, ts).
        #                     NOT the safety AuditLog -- that records permission
        #                     decisions; this records inference transport only.
        self.config_revision = CONFIG_REVISION
        self.request_audit: list[dict] = []
        self.adapters: dict[str, dict] = {}      # name -> {"path":..., "id": int}
        self.active_adapter: Optional[str] = None
        self.switch_log: list[SwitchRecord] = []
        self.gen_log: list[GenStats] = []
        self._lock = threading.Lock()
        # VRAM read cache (rocm-smi is a subprocess; don't shell out per gen)
        self._vram_cache: Optional[tuple[float, float]] = None
        self._vram_cache_t: float = 0.0
        # Server capability probe result (ADR-5). None == not probed yet.
        self._caps: Optional[dict] = None
        self._warned: set[str] = set()

    # ---------- helpers ----------

    def _auth_headers(self, headers: dict | None = None) -> dict:
        """Return `headers` plus a bearer token when a gateway key is set.

        No key configured (direct llama-server) => headers untouched. This keeps
        the gateway opt-in: only deployments that set MOL_LLAMACPP_API_KEY pay
        for auth, and the gateway's 401 path is never tripped by local runs.
        """
        out = dict(headers or {})
        if self.api_key:
            out["Authorization"] = f"Bearer {self.api_key}"
        return out

    def _request_headers(self, run_id: Optional[str],
                         headers: dict | None = None) -> dict:
        """Thin-adapter request headers (P1): auth + correlation ids.

        `X-Request-Id` is freshly minted per call so every gateway log line and
        ScrewShell audit entry can be correlated. `X-Run-Id` groups requests that
        share a ScrewShell run/session when the caller supplies one.
        """
        request_id = uuid.uuid4().hex
        out = self._auth_headers(headers)
        out["X-Request-Id"] = request_id
        if run_id:
            out["X-Run-Id"] = run_id
        return out, request_id

    def _warn_once(self, key: str, msg: str, *args) -> None:
        """Log a degradation exactly once per engine instance.

        A per-call WARN on a 5-step investigation is 20 identical lines that
        train the operator to ignore the log; a silent degradation is worse.
        Once per instance is the honest middle.
        """
        if key in self._warned:
            return
        self._warned.add(key)
        log.warning(msg, *args)

    def _post(self, path: str, payload, timeout: Optional[float] = None) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.server_url}{path}", data=data,
            headers=self._auth_headers({"Content-Type": "application/json"}),
            method="POST")
        with urllib.request.urlopen(
                req, timeout=self.timeout if timeout is None else timeout) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}

    def _get(self, path: str, timeout: Optional[float] = None) -> object:
        req = urllib.request.Request(
            f"{self.server_url}{path}",
            headers=self._auth_headers(), method="GET")
        with urllib.request.urlopen(
                req, timeout=self.timeout if timeout is None else timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _adapter_id(self, name: str) -> int:
        if name not in self.adapters:
            raise KeyError(f"adapter {name} not registered")
        return self.adapters[name]["id"]

    # ---------- lifecycle ----------

    def load_base(self):
        """No local model load. Resolve preloaded LoRA ids from the server."""
        if self.relay_mode:
            # Behind the relay: /lora-adapters is not exposed to this client and
            # the coordinator owns LoRA state. Assume the full feature set (the
            # relay forwards capabilities transparently) and just mark ready.
            self._caps = {k: True for k in CAP_KEYS}
            self._caps.update({"build": "", "probed": True, "reachable": True})
            log.info("llama.cpp backend ready (relay_mode); server=%s",
                     self.server_url)
            return self
        try:
            remote = self._get("/lora-adapters")
        except Exception as e:  # server not up yet / SSH tunnel not forwarded
            log.warning("cannot reach llama.cpp server at %s: %s",
                        self.server_url, e)
            remote = []
        for item in remote:
            # Name the adapter by its PARENT DIRECTORY (e.g. btl3 from
            # /persistent/loras/btl3/adapter.gguf), which matches the lora_dir
            # glob used by build_app and the router skill_map. Using the .gguf
            # filename ("adapter") would collapse every expert into one key and
            # break roomy-mode activate(), which addresses experts by name.
            raw = (item.get("path") or "").replace("\\", "/").rstrip("/")
            parts = [p for p in raw.split("/") if p]
            disk = parts[-2] if len(parts) >= 2 else (parts[-1] if parts else "")
            # SAME naming authority as lora_scan.discover_adapters(). If these
            # two ever name adapters independently, one LoRA ends up under two
            # keys (disk name here, logical name there) and one of them carries
            # a bogus id -- which activate() then silently turns into "mounted
            # nothing". See router.logical_expert_name.
            name = logical_expert_name(disk)
            if not name:
                log.warning("skipping preloaded adapter with unusable path %r",
                            item.get("path"))
                continue
            if is_forbidden(name):
                # TRUTH section 6: the ban is enforced at every registration
                # layer, not just routing -- including LoRAs the server was
                # launched with.
                log.error("server preloaded FORBIDDEN expert %s (id=%s); "
                          "refusing to register it", name, item.get("id"))
                continue
            self.adapters[name] = {"path": item.get("path"), "id": item["id"]}
        log.info("llama.cpp backend ready; server=%s; preloaded=%s",
                 self.server_url, list(self.adapters))
        return self

    def load_adapter(self, name: str, path: str):
        """Register an adapter by name. The actual GGUF is preloaded by the
        server via --lora; we only need its id (resolved in load_base) here."""
        if name in self.adapters:
            self.adapters[name]["path"] = path
        else:
            # not preloaded by server: record by name, id resolved lazily
            self.adapters[name] = {"path": path, "id": -1}
        log.info("adapter %s registered (path=%s)", name, path)
        return self.adapters[name]

    # ---------- hot swap ----------

    def activate(self, name: Optional[str]) -> SwitchRecord:
        if self.relay_mode:
            # Relay owns the global LoRA state. Record intent only so chat()
            # can stamp it on X-Expert; no HTTP call, no lock contention.
            prev = self.active_adapter
            self.active_adapter = name
            rec = SwitchRecord(time.time(), prev, name, 0.0, "relay_noop")
            self.switch_log.append(rec)
            return rec
        with self._lock:
            prev = self.active_adapter
            if name == prev:
                rec = SwitchRecord(time.time(), prev, name, 0.0, "noop")
                self.switch_log.append(rec)
                return rec
            t0 = time.time()
            landed: Optional[str] = name
            if name is None:
                # disable all adapters -> pure base (planning native fallback)
                body = [{"id": a["id"], "scale": 0.0}
                        for a in self.adapters.values() if a["id"] >= 0]
                mode = "disable"
            else:
                # roomy mode: enable ONLY the target expert, zero all others so
                # multiple preloaded LoRAs do not blend. tight mode never reaches
                # here; it restart-swaps the whole server instead.
                tid = self._adapter_id(name)
                if tid < 0:
                    # Registered but never preloaded by the server (the id=-1
                    # fallback in load_adapter). "Target 1.0, everything else
                    # 0.0" would then zero EVERY adapter; the server accepts it
                    # happily and we would record active_adapter=<name> while
                    # actually running the bare base. That is a silent quality
                    # regression -- the expert is simply absent and nothing in
                    # the report says so. Fail LOUDLY and report base instead.
                    log.error(
                        "adapter %s has no server-side id (not preloaded via "
                        "--lora): cannot hot-swap. Running pure base instead; "
                        "the expert is NOT active.", name)
                    landed = None
                    mode = "mount_failed_base"
                else:
                    mode = "set_adapter"
                body = [{"id": a["id"],
                         "scale": 1.0 if a["id"] == tid else 0.0}
                        for a in self.adapters.values() if a["id"] >= 0]
            try:
                self._post("/lora-adapters", body)
            except Exception as e:
                # Fail LOUDLY: the server never applied the scale change (HTTP
                # error) or never received it (network error). Recording
                # active_adapter=<name> here would claim the expert is mounted
                # while the server actually runs the previous state (possibly
                # the bare base) -- the silent-fallback P0 resurrected on the
                # HTTP-failure path. Record the TRUTH (landed on base) and
                # raise, so callers such as InferenceCoordinator never update
                # their _current_expert and every status()/event stays
                # consistent with what the server actually runs.
                latency = (time.time() - t0) * 1000
                landed = None
                mode = "switch_failed_base"
                self.active_adapter = None
                rec = SwitchRecord(time.time(), prev, None,
                                   round(latency, 2), mode)
                self.switch_log.append(rec)
                log.error("switch %s -> %s FAILED (recorded %s): %s",
                          prev, name, mode, e)
                raise RuntimeError(
                    f"LoRA switch to {name!r} failed on the server "
                    f"(HTTP/network error: {e}); refusing to record a switch "
                    f"that did not happen") from e
            latency = (time.time() - t0) * 1000
            # `landed` (not `name`) is what is really active, so status() and
            # the switch log never claim an expert that was not mounted.
            self.active_adapter = landed
            rec = SwitchRecord(time.time(), prev, landed, round(latency, 2), mode)
            self.switch_log.append(rec)
            log.info("switch %s -> %s in %.1fms (%s)", prev, landed, latency, mode)
            return rec

    # ---------- capability probing (ADR-5) ----------

    def _probe_chat(self, extra: dict, timeout: float) -> tuple[bool, dict]:
        """One max_tokens=1 completion with `extra` merged in.

        Returns (ok, body). Never raises: a probe that explodes is itself the
        answer ("this server cannot do that"), not an error to propagate.
        """
        payload = {"model": self.model, "max_tokens": 1, "temperature": 0.0,
                   "messages": [{"role": "user", "content": "hi"}]}
        payload.update(extra)
        try:
            body = self._post("/v1/chat/completions", payload, timeout=timeout)
            return True, (body if isinstance(body, dict) else {})
        except urllib.error.HTTPError as e:
            log.debug("capability probe rejected (%s): %s", e.code, sorted(extra))
            return False, {}
        except Exception as e:
            log.debug("capability probe failed (%s): %s", type(e).__name__,
                      sorted(extra))
            return False, {}

    def _probe_stream(self, timeout: float) -> bool:
        """True when the server answers with a text/event-stream SSE body."""
        payload = {"model": self.model, "max_tokens": 1, "temperature": 0.0,
                    "stream": True,
                    "messages": [{"role": "user", "content": "hi"}]}
        req = urllib.request.Request(
            f"{self.server_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._auth_headers({"Content-Type": "application/json"}),
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "event-stream" in ctype:
                    return True
                head = resp.read(64).decode("utf-8", "replace")
                return head.lstrip().startswith("data:")
        except Exception:
            return False

    def capabilities(self) -> dict:
        """What this particular llama.cpp build actually supports.

        ``{'json_schema': bool, 'grammar': bool, 'timings': bool,
           'cache_prompt': bool, 'stream': bool, 'build': str,
           'probed': bool, 'reachable': bool}``

        Probed once and cached in ``self._caps``. Strategy:

          1. ``GET /props`` for the build string.
          2. A ladder of 1-token probes, most capable first, degrading one
             feature at a time. The first probe that returns 200 decides.
          3. Independent probes for grammar and SSE streaming.

        Never raises. If the server is unreachable every capability is False,
        which means every caller takes exactly today's code path -- an unknown
        server must never be *assumed* capable, because a 400 in the middle of
        a run looks identical to a genuine engine failure (risk R3).
        """
        if self._caps is not None:
            return dict(self._caps)

        caps: dict = {k: False for k in CAP_KEYS}
        caps.update({"build": "", "probed": False, "reachable": False})
        timeout = min(self.timeout, 10.0)

        try:
            props = self._get("/props", timeout=timeout)
        except Exception as e:
            props = None
            log.debug("GET /props unavailable: %s", e)
        if isinstance(props, dict):
            caps["reachable"] = True
            caps["build"] = str(props.get("build_info")
                                or props.get("build") or "")
            defaults = props.get("default_generation_settings")
            if isinstance(defaults, dict) and "cache_prompt" in defaults:
                # The field exists in this build's generation settings, so the
                # server understands it. The probe below can still confirm.
                caps["cache_prompt"] = True

        ladder: list[tuple[dict, tuple[str, ...]]] = [
            ({"response_format": _PROBE_SCHEMA, "cache_prompt": True},
             ("json_schema", "cache_prompt")),
            ({"cache_prompt": True}, ("cache_prompt",)),
            ({}, ()),
        ]
        for extra, granted in ladder:
            ok, body = self._probe_chat(extra, timeout)
            if not ok:
                continue
            caps["reachable"] = True
            caps["probed"] = True
            for key in granted:
                caps[key] = True
            # A 200 without a `timings` object means this build simply does not
            # report the prefill/decode split. We record that as False rather
            # than guessing -- downstream `coverage.timings` then tells the
            # truth instead of the report silently looking complete.
            caps["timings"] = isinstance(body.get("timings"), dict)
            break

        if caps["reachable"]:
            ok, _body = self._probe_chat({"grammar": _PROBE_GRAMMAR}, timeout)
            caps["grammar"] = bool(ok)
            caps["stream"] = self._probe_stream(timeout)

        if not caps["probed"]:
            self._warn_once(
                "caps_unreachable",
                "capability probe could not reach %s; running with every "
                "server feature assumed OFF (today's code path)",
                self.server_url)
        self._caps = caps
        log.info("llama.cpp capabilities: %s", caps)
        return dict(caps)

    # ---------- generation ----------

    @staticmethod
    def _apply_timings(stats: GenStats, out: dict) -> None:
        """Backfill the real prefill/decode split from llama.cpp `timings`.

        Absent or malformed `timings` leaves every field at its ``None``
        default. We never substitute wall-clock time for prefill: a fabricated
        split is the exact "it ran, therefore it is right" failure this whole
        instrumentation pass exists to prevent (blueprint §6.2 rule 9).
        """
        t = out.get("timings")
        if not isinstance(t, dict):
            return

        prompt_ms = t.get("prompt_ms")
        if isinstance(prompt_ms, (int, float)):
            stats.prefill_ms = round(float(prompt_ms), 3)
        predicted_ms = t.get("predicted_ms")
        if isinstance(predicted_ms, (int, float)):
            stats.decode_ms = round(float(predicted_ms), 3)

        pps = t.get("prompt_per_second")
        if isinstance(pps, (int, float)):
            stats.prefill_tps = round(float(pps), 2)
        dps = t.get("predicted_per_second")
        if isinstance(dps, (int, float)):
            stats.decode_tps = round(float(dps), 2)

        # THE key measurement: llama.cpp counts only the tokens it actually had
        # to prefill in `prompt_n` -- KV cache hits are excluded. The
        # subtraction below is therefore a free, exact cache-hit probe.
        prompt_n = t.get("prompt_n")
        if isinstance(prompt_n, int) and prompt_n >= 0:
            stats.cached_tokens = max(0, stats.prompt_tokens - prompt_n)
            if stats.prefill_tps is None and stats.prefill_ms:
                stats.prefill_tps = round(prompt_n / (stats.prefill_ms / 1000.0), 2)

    def _stream_completion(self, payload: dict, on_token,
                            t0: float, run_id: Optional[str] = None,
                            request_id: Optional[str] = None,
                            req_headers: Optional[dict] = None) -> tuple[str, dict]:
        """Consume an SSE completion, returning (text, synthetic_body).

        `synthetic_body` is shaped like the non-streaming JSON body so the same
        usage/timings backfill applies to both paths. When `req_headers` is
        supplied (thin-adapter P1) the correlation ids are propagated upstream.
        """
        body = dict(payload)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        hdrs = req_headers or self._auth_headers()
        hdrs = {**hdrs, "Content-Type": "application/json",
                "Accept": "text/event-stream"}
        req = urllib.request.Request(
            f"{self.server_url}/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers=hdrs, method="POST")

        parts: list[str] = []
        usage: dict = {}
        timings: dict = {}
        finish_reason: Optional[str] = None
        ttft_ms: Optional[float] = None

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                chunk_raw = line[5:].strip()
                if chunk_raw == "[DONE]":
                    break
                try:
                    chunk = json.loads(chunk_raw)
                except ValueError:
                    continue
                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
                if isinstance(chunk.get("timings"), dict):
                    timings = chunk["timings"]
                for choice in chunk.get("choices") or []:
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    piece = (choice.get("delta") or {}).get("content") or ""
                    if not piece:
                        continue
                    if ttft_ms is None:
                        ttft_ms = round((time.time() - t0) * 1000.0, 2)
                    parts.append(piece)
                    if on_token is not None:
                        try:
                            on_token(piece)
                        except Exception as e:   # a bad sink must not kill gen
                            self._warn_once("on_token",
                                            "on_token callback raised %s; "
                                            "dropping further callbacks",
                                            type(e).__name__)
                            on_token = None

        text = "".join(parts)
        synthetic = {
            "choices": [{"message": {"content": text},
                         "finish_reason": finish_reason}],
            "usage": usage,
            "_ttft_ms": ttft_ms,
        }
        if timings:
            synthetic["timings"] = timings
        return text, synthetic

    def chat(self, messages: list[dict], max_new_tokens: int = 512,
              temperature: float = 0.0,
              enable_thinking: bool = False,
              response_format: Optional[dict] = None,
              json_schema: Optional[dict] = None,
              grammar: Optional[str] = None,
              cache_prompt: bool = True,
              stream: bool = False,
              on_token: Optional[Callable[[str], None]] = None,
              run_id: Optional[str] = None,
              ) -> tuple[str, GenStats]:
        """One chat completion.

        The four leading parameters are the original contract. Everything after
        them is opt-in and defaults to today's behaviour, so an untouched call
        site produces a byte-identical request apart from `cache_prompt`
        (which llama.cpp has accepted for a long time and older builds ignore).

        Unsupported server features degrade instead of failing: the request is
        sent without them, `_warn_once` records why, and `GenStats.constrained`
        stays False so the report never claims a constraint that never ran.
        """
        # json_schema is the convenience door into the same OAI-shaped field;
        # an explicit response_format always wins.
        if json_schema is not None and response_format is None:
            response_format = {"type": "json_schema",
                               "json_schema": {"name": "screwshell",
                                               "strict": True,
                                               "schema": json_schema}}

        # Only probe when a new feature is actually requested. A plain call on
        # an un-probed engine must not pay for three extra HTTP round trips.
        wants_feature = (response_format is not None or grammar is not None
                         or stream)
        caps = self.capabilities() if wants_feature else (self._caps or {})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_new_tokens,
            "temperature": temperature,
            # Qwen3.6 thinking toggle. VERIFIED on the W7900 (2026-08-04):
            # llama-server ONLY honors `chat_template_kwargs.enable_thinking`;
            # the top-level `thinking` field is silently ignored, so sending
            # it left thinking ON and every reply burned its budget on
            # reasoning_content with empty content.
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }

        constrained = False
        if response_format is not None:
            if caps.get("json_schema"):
                payload["response_format"] = response_format
                constrained = True
            else:
                self._warn_once("json_schema",
                                "server %s does not accept response_format; "
                                "falling back to unconstrained decoding",
                                self.server_url)
        if grammar is not None:
            if caps.get("grammar"):
                payload["grammar"] = grammar
                constrained = True
            else:
                self._warn_once("grammar",
                                "server %s does not accept GBNF grammar; "
                                "falling back to unconstrained decoding",
                                self.server_url)

        # Unknown fields are ignored by older builds, so this is safe to send
        # unless the probe positively told us the field is rejected.
        if cache_prompt and not (caps.get("probed") and not caps.get("cache_prompt")):
            payload["cache_prompt"] = True

        use_stream = bool(stream)
        if use_stream and not caps.get("stream", False):
            self._warn_once("stream",
                            "server %s did not answer an SSE probe; "
                            "falling back to a blocking completion",
                            self.server_url)
            use_stream = False

        # P0 fix (Phase 0): NEVER inject a per-request LoRA override here.
        # The coordinator (relay) owns the global LoRA switch via
        # POST /lora-adapters (path D). Mixing this request-level "lora" (path C)
        # with the global switch is the silent base-fallback bug
        # (kv_reprefill_report P0). Single path only.

        t0 = time.time()
        req_headers, request_id = self._request_headers(run_id)
        if self.relay_mode:
            # Stamp the already-decided expert so the relay does not re-route.
            req_headers["X-Expert"] = self.active_adapter or ""
            # Authenticate the trusted X-Expert header (see relay.py
            # RELAY_TRUST_TOKEN). Without a matching token the relay re-routes
            # via SkillRouter, so spoofing an expert from another process is
            # impossible.
            _tok = os.getenv("RELAY_TRUST_TOKEN", "")
            if _tok:
                req_headers["X-Relay-Token"] = _tok
        try:
            if use_stream:
                text, out = self._stream_completion(
                    payload, on_token, t0, run_id=run_id,
                    request_id=request_id, req_headers=req_headers)
            else:
                req = urllib.request.Request(
                    f"{self.server_url}/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={**req_headers,
                             "Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    out = json.loads(resp.read().decode("utf-8"))
                choice = (out.get("choices") or [{}])[0]
                text = (choice.get("message") or {}).get("content", "") or ""
        except urllib.error.HTTPError as e:
            log.error("chat completion failed: HTTP %s", e.code)
            stats = GenStats(self.active_adapter, 0, 0,
                              round(time.time() - t0, 3),
                              constrained=constrained, ok=False,
                              error=f"HTTP {e.code}",
                              request_id=request_id, run_id=run_id)
            self.gen_log.append(stats)
            self._audit(request_id, run_id, False, e.code, t0)
            return "", stats
        except Exception as e:
            log.error("chat completion failed: %s", e)
            stats = GenStats(self.active_adapter, 0, 0,
                              round(time.time() - t0, 3),
                              constrained=constrained, ok=False,
                              error=f"{type(e).__name__}: {e}",
                              request_id=request_id, run_id=run_id)
            self.gen_log.append(stats)
            self._audit(request_id, run_id, False, type(e).__name__, t0)
            return "", stats

        dt = time.time() - t0
        usage = out.get("usage") or {}
        finish_reason = None
        for choice in (out.get("choices") or []):
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
                break
        stats = GenStats(self.active_adapter,
                          int(usage.get("prompt_tokens", 0) or 0),
                          int(usage.get("completion_tokens", 0) or 0),
                          round(dt, 3),
                          finish_reason=finish_reason,
                          constrained=constrained,
                          ok=True,
                          request_id=request_id, run_id=run_id)
        self._audit(request_id, run_id, True, finish_reason, t0)
        ttft = out.get("_ttft_ms")
        if isinstance(ttft, (int, float)):
            stats.ttft_ms = float(ttft)
        self._apply_timings(stats, out)
        if stats.decode_tps is None and stats.new_tokens and dt > 0:
            # End-to-end throughput is a genuine measurement, just a coarser
            # one; unlike a synthesised prefill split it does not lie.
            stats.decode_tps = round(stats.new_tokens / dt, 2)
        self.gen_log.append(stats)
        return text, stats

    # ---------- introspection ----------

    @staticmethod
    def _read_vram() -> Optional[tuple[float, float]]:
        """Query AMD VRAM (used_gb, total_gb) via rocm-smi. None if absent.

        The orchestrator drives the llama-server on the same host, so we can
        read the card's real memory pressure and feed it to the governor's
        KV-quant safety net. Falls back to None when rocm-smi is unavailable
        (e.g. a local dev box without a Radeon) — the governor then assumes
        headroom rather than firing KV-quant on a phantom number.
        """
        try:
            out = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram"],
                capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return None
        used = re.search(r"VRAM Used Memory \(B\):\s*(\d+)", out)
        total = re.search(r"VRAM Total Memory \(B\):\s*(\d+)", out)
        if not (used and total):
            return None
        u, t = int(used.group(1)), int(total.group(1))
        if t <= 0:
            return None
        return (u / 1e9, t / 1e9)

    def _query_vram(self, ttl: float = 2.0) -> Optional[tuple[float, float]]:
        """Cached (used_gb, total_gb); one rocm-smi call per `ttl` seconds."""
        now = time.time()
        if self._vram_cache is not None and (now - self._vram_cache_t) < ttl:
            return self._vram_cache
        val = self._read_vram()
        self._vram_cache = val
        self._vram_cache_t = now
        return val

    def vram_gb(self) -> Optional[float]:
        """Used VRAM in GB (real, from rocm-smi). None if not measurable."""
        q = self._query_vram()
        return round(q[0], 2) if q else None

    def vram_total_gb(self) -> Optional[float]:
        """Total VRAM in GB (real, from rocm-smi). None if not measurable."""
        q = self._query_vram()
        return round(q[1], 2) if q else None

    def vram_pct(self) -> Optional[float]:
        """VRAM usage as a real 0-100 percentage. None if not measurable."""
        q = self._query_vram()
        if not q:
            return None
        return round(q[0] / q[1] * 100.0, 2)

    def _audit(self, request_id: Optional[str], run_id: Optional[str],
                ok: bool, status: object, t0: float) -> None:
        """Append one inference-transport audit entry (thin-adapter P1).

        Lightweight and in-memory only: the safety AuditLog records permission
        decisions; this records gateway/transport correlation so a failed run
        can be traced to a request_id without scraping gateway /logs.
        """
        self.request_audit.append({
            "ts": round(t0, 3),
            "request_id": request_id,
            "run_id": run_id,
            "model": self.model,
            "gateway_mode": bool(self.api_key),
            "ok": ok,
            "status": str(status),
            "latency_ms": round((time.time() - t0) * 1000.0, 2),
            "config_revision": self.config_revision,
        })
        # Bound memory: keep the last 200 entries (a panel needs recent, not all).
        if len(self.request_audit) > 200:
            self.request_audit = self.request_audit[-200:]

    def status(self) -> dict:
        return {
            "base": self.base_path,
            "active_adapter": self.active_adapter,
            "adapters": {n: {"id": a["id"], "path": a.get("path")}
                         for n, a in self.adapters.items()},
            "vram_gb": self.vram_gb(),
            "vram_pct": self.vram_pct(),
            "switches": len(self.switch_log),
            "last_switch_ms": self.switch_log[-1].latency_ms if self.switch_log else None,
            "backend": "llamacpp",
            # Lands in RunResult.stats["engine"]["caps"] so every eval report
            # states, on its first screen, what the server under test could
            # actually do -- an optimisation that silently never ran is the
            # failure mode this key exists to expose.
            "caps": self.capabilities(),
        }

    def adapter_status(self) -> dict:
        """Thin-adapter panel data (P1): gateway contract, degradation flags,
        LoRA/MoL state, and config revision -- everything the UI panel needs
        without re-deriving it from raw caps/audit.

        Degradation is *stated*, never hidden: `gateway_mode` is False when no
        API key is set (direct server), and `model_alias_resolved` is False when
        the engine still speaks the bare "m" id (direct server, or misconfig).
        """
        return {
            "backend": "llamacpp",
            "gateway_mode": bool(self.api_key),
            "model_alias_resolved": self.model != "m",
            "model": self.model,
            "config_revision": self.config_revision,
            "active_adapter": self.active_adapter,
            "adapter_count": len(self.adapters),
            "adapters": list(self.adapters.keys()),
            # LoRA/MoL: degraded when no adapter is registered/active but the
            # router expects expert routing. The flag is the honest signal; it
            # does not claim a capability that is not wired up.
            "lora_degraded": (len(self.adapters) == 0
                              and self.active_adapter is not None),
            "recent_requests": len(self.request_audit),
            "last_request_ok": (self.request_audit[-1]["ok"]
                                if self.request_audit else None),
        }

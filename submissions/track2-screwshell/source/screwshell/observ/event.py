"""One immutable record per relay-served inference request.

This is the canonical "what the user's request actually did" event. It is
emitted by ``InferenceCoordinator`` (the single owner of the global LoRA
state) and persisted by ``ObservStore``. Everything here is either a
deterministic routing fact (route / adapter / switched) or a measurement the
upstream llama.cpp server handed us (timings / usage / KV cache). We never
compute a prefill/decode split ourselves.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional


def new_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass
class RequestEvent:
    # --- correlation ---
    ts: float = 0.0                     # epoch seconds, set on creation
    request_id: str = ""                # per-HTTP-request id (X-Request-Id)
    run_id: Optional[str] = None        # orchestrator run id (X-Run-Id), if any

    # --- routing / MoL facts ---
    route: Optional[str] = None         # expert the relay decided/trusted
    adapter: Optional[str] = None       # adapter actually switched to (None=base)
    switched: bool = False              # a global LoRA switch happened this request
    stream: bool = False                # streaming response?

    # --- request shape ---
    model: str = "m"
    thinking: Optional[bool] = None     # enable_thinking requested? (None=unknown)
    # What the panel can show about a request WITHOUT storing raw content:
    # the last user message (truncated), and the tool calls the client made
    # (name + truncated args), so external frontends (opencode/pi) become
    # visible as an activity stream too, not just opaque metrics.
    user_msg: Optional[str] = None      # last user message, truncated
    tool_calls: list = field(default_factory=list)  # [{"name","args"}...]
    queue_wait_ms: Optional[float] = None  # time waiting for the serial LoRA lock

    # --- token accounting (from usage) ---
    prompt_tokens: int = 0
    cached_tokens: int = 0              # KV cache hits (prompt tokens served from KV)
    completion_tokens: int = 0

    # --- latency / throughput (from llama.cpp timings; None == not measured) ---
    ttft_ms: Optional[float] = None     # time to first token (measured for stream)
    prefill_ms: Optional[float] = None  # timings.prompt_ms
    decode_ms: Optional[float] = None   # timings.predicted_ms
    decode_tps: Optional[float] = None  # timings.predicted_per_second
    kv_hit_rate: Optional[float] = None # cached_tokens / prompt_tokens
    thinking_ms: Optional[float] = None # not separable from decode in v1 -> None
    switch_ms: Optional[float] = None   # time the global LoRA switch took (ms)

    # --- session-scoped observability (two-tier granularity, 2026-08-05) ---
    # operational_session_id: a "cache-reuse segment" — one id spans multiple
    # requests that share a warm KV prefix. Distinct from run_id (browser/UI
    # identity) and request_id (single call). Assigned by the InferenceCoordinator
    # under its serial lock (single writer).
    operational_session_id: str = ""
    # Why this request starts a new operational session. One of:
    #   "no_reusable_prefix" -> cached_tokens==0 with a valid (non-empty) prompt.
    #       NOTE: this is a HEURISTIC ("no reusable prefix OBSERVED"), NOT proof
    #       of a physical cold start — cache disabled / slot eviction / template
    #       change can also yield cached_tokens==0. Guarded by cache_signal_valid.
    #   "explicit_reset"      -> caller forced a new session.
    #   "model_reload"        -> base/expert reload invalidated the prefix.
    #   "first"               -> very first request (no prior session yet).
    #   ""                    -> warm continuation of the current session.
    boundary_reason: str = "first"
    # Whether this request's cached_tokens reading is trustworthy for the
    # boundary heuristic: True only when prompt_tokens > 0 (accounting valid).
    # A 0-prompt request must NOT trigger a no_reusable_prefix boundary.
    cache_signal_valid: bool = False
    # Whether this request is stress/benchmark traffic. Such traffic is excluded
    # from the interactive health judgment (§5.3.5) but retained for drill-down.
    benchmark: bool = False

    # --- outcome ---
    ok: bool = True
    error: Optional[str] = None
    status_code: int = 200

    def __post_init__(self) -> None:
        if self.ts == 0.0:
            self.ts = time.time()
        if not self.request_id:
            self.request_id = new_id()

    @property
    def entry(self) -> str:
        """'ui' when an orchestrator run id is present, else 'api' (opencode/pi)."""
        return "ui" if self.run_id else "api"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entry"] = self.entry
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RequestEvent":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

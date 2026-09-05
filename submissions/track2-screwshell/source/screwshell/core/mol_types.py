"""Shared data contracts for the MoL inference core.

Kept torch-free on purpose: both the peft backend (`mol_engine.py`) and the
llama.cpp backend (`mol_engine_llamacpp.py`) import these so they share an
identical data contract without forcing torch into the llama.cpp process.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Keys of the dict returned by every backend's ``capabilities()``. Declared in
# the shared contract module so the llama.cpp probe and the peft stub cannot
# drift into reporting different shapes -- a report that is missing a key looks
# exactly like a capability that is switched off.
CAP_KEYS = ("json_schema", "grammar", "timings", "cache_prompt", "stream")


@dataclass
class SwitchRecord:
    ts: float
    from_adapter: Optional[str]
    to_adapter: Optional[str]
    latency_ms: float
    mode: str  # "set_adapter" | "disable" | "noop"


@dataclass
class GenStats:
    """One generation call's measurements.

    The first four fields are POSITIONAL and their order is frozen: several
    call sites (and two tests) construct ``GenStats(adapter, prompt_tokens,
    new_tokens, seconds)`` positionally. Everything appended below carries a
    default, so those constructors keep working untouched.

    Honesty rule (blueprint §6.2 rule 9): the timing fields are ``None`` when
    the backend did not report them. We NEVER substitute wall-clock time for a
    prefill/decode split -- a plausible-but-wrong number is worse than a
    visible gap, because the report would silently look complete. Aggregation
    in ``core/metrics.py`` tracks ``coverage.timings`` for exactly this reason.
    """

    # ---- existing four positional fields; order is frozen ----
    adapter: Optional[str]
    prompt_tokens: int
    new_tokens: int
    seconds: float

    # ---- appended fields: all defaulted, always at the tail ----

    #: Prompt-processing wall time in ms (llama.cpp ``timings.prompt_ms``).
    #: ``None`` when the server sent no ``timings`` object.
    prefill_ms: Optional[float] = None
    #: Token-generation wall time in ms (``timings.predicted_ms``).
    decode_ms: Optional[float] = None
    #: Prefill throughput tok/s (``timings.prompt_per_second``).
    prefill_tps: Optional[float] = None
    #: Decode throughput tok/s (``timings.predicted_per_second``); falls back
    #: to ``new_tokens / seconds`` which is a genuine end-to-end measurement,
    #: not a fabricated split.
    decode_tps: Optional[float] = None
    #: Prompt tokens served from the KV cache, i.e. NOT re-prefilled.
    #: ``max(0, usage.prompt_tokens - timings.prompt_n)``.
    cached_tokens: int = 0
    #: Time to first token in ms; only meaningful when ``stream=True``.
    ttft_ms: Optional[float] = None
    #: Upstream ``choices[0].finish_reason`` -- "stop" | "length" | ...
    finish_reason: Optional[str] = None
    #: True when this call ran under a grammar / JSON-schema constraint.
    constrained: bool = False
    #: False when the call failed (transport error, HTTP error, empty body).
    #: This is the signal source for the A2 error-surfacing work (T4).
    ok: bool = True
    #: Failure reason (HTTP code / exception class name) when ``ok`` is False.
    error: Optional[str] = None
    #: Per-request correlation id, propagated as `X-Request-Id` to the gateway
    #: (thin-adapter layer, P1). None when the caller did not assign one.
    request_id: Optional[str] = None
    #: Run/session correlation id, propagated as `X-Run-Id`; groups many
    #: requests that belong to one ScrewShell run. None when ungrouped.
    run_id: Optional[str] = None

    # ---- derived ----

    @property
    def tokens_per_s(self) -> float:
        return self.new_tokens / self.seconds if self.seconds > 0 else 0.0

    @property
    def kv_hit_rate(self) -> float:
        """Fraction of the prompt served from the KV cache, in [0.0, 1.0].

        Note: ``cached_tokens`` defaults to 0, so a backend that reports no
        ``timings`` yields 0.0 here. That is intentional per the blueprint --
        the *honesty* signal lives one level up, in
        ``RunMetrics.summary()["coverage"]["timings"]``, which only counts
        calls that carried a real server-side measurement.
        """
        if self.prompt_tokens <= 0:
            return 0.0
        rate = self.cached_tokens / self.prompt_tokens
        # A server reporting prompt_n > prompt_tokens must not yield >1 / <0.
        return min(1.0, max(0.0, rate))

    @property
    def prefilled_tokens(self) -> int:
        """Prompt tokens actually recomputed this call (KV hits excluded)."""
        return max(0, self.prompt_tokens - self.cached_tokens)

    @property
    def has_timings(self) -> bool:
        """True only when the backend reported a real prefill/decode split."""
        return self.prefill_ms is not None and self.decode_ms is not None

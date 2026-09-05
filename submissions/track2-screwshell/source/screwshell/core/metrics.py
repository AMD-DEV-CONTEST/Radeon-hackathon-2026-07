"""Per-query LLM / tool accounting for ScrewShell (blueprint T2).

One ``RunMetrics`` instance per ``Orchestrator.run()``. Pure accumulation, zero
IO, stdlib only -- it must be importable on a torch-free box and cheap enough to
leave permanently on.

The single most important rule in this file (blueprint §6.2 rule 9):

    **Never fabricate a measurement.**

llama.cpp reports real prefill/decode split in its ``timings`` object. When the
server does not send one, the corresponding field stays ``None`` and the run's
``coverage.timings`` drops below 1.0. We do *not* substitute wall-clock time for
prefill -- a plausible-looking number that is actually wrong is worse than a
visible gap, and "it ran" is not "it measured".
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

# Canonical phase names. `other` is the catch-all so an un-tagged call is still
# counted (an invisible call is how a token bill goes missing).
PHASES = ("preflight", "plan", "react", "final", "quick", "other")

# Canonical phase-timer keys, always present in `phases()` even when zero, so a
# report can diff two runs without KeyError gymnastics.
PHASE_TIMERS = ("preflight", "plan", "steps", "final")


def _r(x: Optional[float], nd: int = 3) -> Optional[float]:
    return None if x is None else round(x, nd)


def _div(num: float, den: float) -> float:
    return num / den if den else 0.0


@dataclass
class CallRecord:
    """One engine.chat() round trip."""

    phase: str = "other"
    step_idx: Optional[int] = None
    adapter: Optional[str] = None
    prompt_tokens: int = 0
    cached_tokens: int = 0
    new_tokens: int = 0
    seconds: float = 0.0
    prefill_ms: Optional[float] = None
    decode_ms: Optional[float] = None
    ttft_ms: Optional[float] = None
    ok: bool = True
    error: Optional[str] = None
    constrained: bool = False
    json_ok: Optional[bool] = None   # None == this phase does not expect JSON

    @property
    def has_timings(self) -> bool:
        """True only when the SERVER gave us a real prefill/decode split."""
        return self.prefill_ms is not None and self.decode_ms is not None

    @property
    def prefilled_tokens(self) -> int:
        """Tokens actually pushed through prefill (KV hits excluded)."""
        return max(0, self.prompt_tokens - self.cached_tokens)

    def to_dict(self) -> dict:
        return {
            "phase": self.phase, "step_idx": self.step_idx,
            "adapter": self.adapter, "prompt_tokens": self.prompt_tokens,
            "cached_tokens": self.cached_tokens, "new_tokens": self.new_tokens,
            "seconds": _r(self.seconds), "prefill_ms": _r(self.prefill_ms, 1),
            "decode_ms": _r(self.decode_ms, 1), "ttft_ms": _r(self.ttft_ms, 1),
            "ok": self.ok, "error": self.error,
            "constrained": self.constrained, "json_ok": self.json_ok,
        }


@dataclass
class ToolRecord:
    """One toolkit.run() call."""

    name: str
    ok: bool = True
    seconds: float = 0.0
    parallel: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok,
                "seconds": _r(self.seconds), "parallel": self.parallel}


def _bucket(records: list[CallRecord]) -> dict:
    """Aggregate a set of calls. Shared by the global / phase / adapter views."""
    n = len(records)
    if n == 0:
        return {"calls": 0, "failed_calls": 0, "prompt_tokens": 0,
                "cached_tokens": 0, "new_tokens": 0, "seconds": 0.0,
                "prefill_s": 0.0, "decode_s": 0.0, "unaccounted_s": 0.0,
                "prefill_pct": 0.0, "decode_pct": 0.0,
                "prefill_tps": None, "decode_tps": None,
                "kv_hit_rate": 0.0, "json_ok_rate": None,
                "constrained_rate": 0.0,
                "coverage": {"timings": 0.0}}

    prompt = sum(c.prompt_tokens for c in records)
    cached = sum(c.cached_tokens for c in records)
    new = sum(c.new_tokens for c in records)
    seconds = sum(c.seconds for c in records)

    with_prefill = [c for c in records if c.prefill_ms is not None]
    with_decode = [c for c in records if c.decode_ms is not None]
    prefill_s = sum(c.prefill_ms for c in with_prefill) / 1000.0
    decode_s = sum(c.decode_ms for c in with_decode) / 1000.0
    # Wall clock the server did NOT attribute to prefill or decode (queueing,
    # HTTP, tokenizer, sampling overhead). Surfaced instead of buried so a
    # 30%-unaccounted run is visibly suspicious rather than silently averaged in.
    unaccounted = max(0.0, seconds - prefill_s - decode_s)

    judged = [c for c in records if c.json_ok is not None]

    return {
        "calls": n,
        "failed_calls": sum(1 for c in records if not c.ok),
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "new_tokens": new,
        "seconds": round(seconds, 3),
        "prefill_s": round(prefill_s, 3),
        "decode_s": round(decode_s, 3),
        "unaccounted_s": round(unaccounted, 3),
        "prefill_pct": round(_div(prefill_s, seconds) * 100.0, 2),
        "decode_pct": round(_div(decode_s, seconds) * 100.0, 2),
        # Rates are computed ONLY over the calls that carried a real
        # measurement -- mixing measured and unmeasured calls would silently
        # deflate the throughput figures.
        "prefill_tps": (round(_div(sum(c.prefilled_tokens for c in with_prefill),
                                   prefill_s), 2) if with_prefill and prefill_s
                        else None),
        "decode_tps": (round(_div(sum(c.new_tokens for c in with_decode),
                                  decode_s), 2) if with_decode and decode_s
                       else None),
        "kv_hit_rate": round(_div(cached, prompt), 4),
        "json_ok_rate": (round(_div(sum(1 for c in judged if c.json_ok),
                                    len(judged)), 4) if judged else None),
        "constrained_rate": round(_div(sum(1 for c in records if c.constrained),
                                       n), 4),
        "coverage": {"timings": round(_div(sum(1 for c in records
                                               if c.has_timings), n), 4)},
    }


class RunMetrics:
    """Accumulator for one ``Orchestrator.run()``.

    Not thread-safe by design: today's ReAct loop is strictly serial. T7 adds
    parallel *tools* only, and ``tool()`` calls are made from the collecting
    thread after the executor joins.
    """

    def __init__(self, clock: Callable[[], float] = time.perf_counter):
        self._clock = clock
        self.t0: float = clock()
        self.calls: list[CallRecord] = []
        self.tools: list[ToolRecord] = []
        self._marks: dict[str, float] = {}
        self._last_mark: float = self.t0
        self._parallel_batches: int = 0

    # ------------------------------------------------------------- record --

    def record(self, stats: object, *, phase: str = "other",
               step_idx: Optional[int] = None,
               json_ok: Optional[bool] = None) -> CallRecord:
        """Fold one ``GenStats`` into the run.

        ``stats`` is duck-typed on purpose: engines are duck-typed everywhere
        else in this codebase (the 5-method contract), and a mock engine that
        predates the extended ``GenStats`` must not crash the meter.
        """
        rec = CallRecord(
            phase=phase or "other",
            step_idx=step_idx,
            adapter=getattr(stats, "adapter", None),
            prompt_tokens=int(getattr(stats, "prompt_tokens", 0) or 0),
            cached_tokens=int(getattr(stats, "cached_tokens", 0) or 0),
            new_tokens=int(getattr(stats, "new_tokens", 0) or 0),
            seconds=float(getattr(stats, "seconds", 0.0) or 0.0),
            prefill_ms=getattr(stats, "prefill_ms", None),
            decode_ms=getattr(stats, "decode_ms", None),
            ttft_ms=getattr(stats, "ttft_ms", None),
            ok=bool(getattr(stats, "ok", True)),
            error=getattr(stats, "error", None),
            constrained=bool(getattr(stats, "constrained", False)),
            json_ok=json_ok,
        )
        self.calls.append(rec)
        return rec

    def note_json(self, ok: bool) -> Optional[CallRecord]:
        """Tag the most recent call with whether its output parsed as JSON.

        The JSON verdict is only known *after* the caller tries to parse, which
        is one statement later than ``record()``. Keeping it as a follow-up
        write beats threading a callback through ``_llm``.
        """
        if not self.calls:
            return None
        self.calls[-1].json_ok = bool(ok)
        return self.calls[-1]

    def tool(self, name: str, ok: bool, seconds: float,
             parallel: bool = False) -> ToolRecord:
        rec = ToolRecord(name=name, ok=bool(ok), seconds=float(seconds),
                         parallel=bool(parallel))
        self.tools.append(rec)
        return rec

    def parallel_batch(self, size: int = 1) -> None:
        """Record that `size` tools were dispatched as one parallel batch (T7)."""
        if size > 1:
            self._parallel_batches += 1

    def mark(self, name: str) -> float:
        """Close the current phase timer and open the next one.

        Accumulative: calling ``mark("steps")`` once per step sums the step
        wall clock instead of overwriting it.
        """
        now = self._clock()
        dt = max(0.0, now - self._last_mark)
        self._last_mark = now
        self._marks[name] = self._marks.get(name, 0.0) + dt
        return dt

    # ------------------------------------------------------------ readout --

    def phases(self) -> dict:
        """``{"preflight_s":.., "plan_s":.., "steps_s":.., "final_s":..}``."""
        out = {f"{k}_s": 0.0 for k in PHASE_TIMERS}
        for name, secs in self._marks.items():
            out[f"{name}_s"] = round(secs, 3)
        out["total_s"] = round(max(0.0, self._clock() - self.t0), 3)
        return out

    def tools_summary(self) -> dict:
        return {
            "calls": len(self.tools),
            "ok": sum(1 for t in self.tools if t.ok),
            "seconds": round(sum(t.seconds for t in self.tools), 3),
            "parallel_batches": self._parallel_batches,
            "by_tool": {
                name: {
                    "calls": sum(1 for t in self.tools if t.name == name),
                    "ok": sum(1 for t in self.tools if t.name == name and t.ok),
                    "seconds": round(sum(t.seconds for t in self.tools
                                         if t.name == name), 3),
                }
                for name in sorted({t.name for t in self.tools})
            },
        }

    def summary(self) -> dict:
        """The dict that lands in ``RunResult.stats["llm"]``."""
        out = _bucket(self.calls)
        out["by_phase"] = {
            phase: _bucket([c for c in self.calls if c.phase == phase])
            for phase in sorted({c.phase for c in self.calls})
        }
        out["by_adapter"] = {
            (adapter or "base"): _bucket([c for c in self.calls
                                          if c.adapter == adapter])
            for adapter in sorted({c.adapter for c in self.calls},
                                  key=lambda a: (a is not None, a or ""))
        }
        errs = [c.error for c in self.calls if not c.ok and c.error]
        if errs:
            out["errors"] = errs[:12]
        return out

    def as_dict(self) -> dict:
        """Full readout including the raw per-call trace (report / debugging)."""
        return {
            "summary": self.summary(),
            "phases": self.phases(),
            "tools": self.tools_summary(),
            "calls": [c.to_dict() for c in self.calls],
        }

    # -------------------------------------------------------------- helpers --

    def extend(self, records: Iterable[CallRecord]) -> None:
        """Merge externally produced records (e.g. a preflight sub-run)."""
        self.calls.extend(records)

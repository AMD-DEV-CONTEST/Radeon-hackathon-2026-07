"""Autotune preset mapper (tune-loop plan, Todo 4).

Pure stdlib. Maps the 4 phase-1 preset gears (speed / vram / ctx / balance) to a
single-parameter TuneGoal. Deterministic: same input -> same output, so it is
unit-testable without a server.

Phase 1 is RULE-BASED only. Natural-language intent parsing is deferred to
phase 2 and raises NotImplementedError here (no engine/LLM call — avoids the
orchestrator/engine conflict called out in the plan).
"""
from __future__ import annotations

from dataclasses import dataclass

from screwshell.gateway.capacity import MAX_CTX_TOKENS

CTX_FLOOR = 4096  # capacity.py floors ctx at 4096


@dataclass
class TuneGoal:
    """One parameter to change, its target value, and why."""
    param: str
    target: object
    reason: str


def preset(name: str, current: dict) -> TuneGoal:
    """Return a TuneGoal for one of the 4 phase-1 presets.

    ``name``   : "speed" | "vram" | "ctx" | "balance"
    ``current``: snapshot of current server params (keys like n_ctx, n_batch,
                 threads, cache_type_k, cache_type_v, parallel, n_gpu_layers,
                 reasoning_budget). Missing keys are treated as None.

    Phase 1 tunes a SINGLE parameter per call (the cycle walks them in order);
    the mapper returns the most impactful lever for each preset.
    """
    name = (name or "").lower()
    if name == "speed":
        # Faster decode: bigger prompt batch + more threads, drop KV quant so
        # the compute path stays on the full-precision tensor.
        cur_batch = current.get("n_batch") or 256
        return TuneGoal(
            param="n_batch",
            target=max(int(cur_batch) * 2, 512),
            reason="speed: double prompt batch + ensure no KV quant to maximize decode tps",
        )
    if name == "vram":
        # Free VRAM: shrink ctx (>= floor) and quantize KV cache.
        cur_ctx = int(current.get("n_ctx") or MAX_CTX_TOKENS)
        new_ctx = max(int(cur_ctx * 0.75), CTX_FLOOR)
        return TuneGoal(
            param="n_ctx",
            target=new_ctx,
            reason="vram: shrink context window to 75% (>=4096) to reclaim VRAM",
        )
    if name == "ctx":
        # Maximize context: push toward the capacity ceiling.
        cap = MAX_CTX_TOKENS
        cur_ctx = int(current.get("n_ctx") or 0)
        # only grow; never exceed the hard ceiling
        new_ctx = cap if cur_ctx < cap else cur_ctx
        return TuneGoal(
            param="n_ctx",
            target=min(new_ctx, cap),
            reason="ctx: grow context window up to the capacity ceiling (MAX_CTX_TOKENS)",
        )
    if name == "balance":
        return TuneGoal(
            param="__none__",
            target=None,
            reason="balance: keep current configuration (no change)",
        )
    raise ValueError(f"unknown preset: {name!r} (expected speed/vram/ctx/balance)")


def parse_natural_language(text: str) -> TuneGoal:
    """Phase 2 only. Intent parsing from free text is NOT implemented yet."""
    raise NotImplementedError(
        "natural-language preset parsing is deferred to phase 2; "
        "use preset() with an explicit gear for now"
    )

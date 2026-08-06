"""Gateway Layer 1 — capacity planning: VRAM -> safe context-window size.

Implements the W7900 VRAM model from docs/Layer2_Implementation_Map.md §8.4
and docs/TRUTH.md §8.3:

    总显存 = 参数量(十亿) × 量化GB × 1.05        (权重, 含 5% 余量)
           + 层数 × 0.00075 × ctx(K)            (KV cache, 随 ctx 线性增长)
           + 3GB                                 (runtime / CUDA-context overhead)

The old autotune tuner capped ctx at a hardcoded 8192 regardless of VRAM; this
module derives the real ceiling from the detected GPU so a 48 GB W7900 can run a
large context without OOM. Stdlib-only (no torch/CUDA) so it runs over SSH on
the deploy host and in unit tests with a mocked profile.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from dataclasses import dataclass

from screwshell.autotune.hardware import HardwareProfile, QUANT_VRAM_GB

# Qwen3.6-27B (dense) architecture constants used by the capacity formula.
# params_billions here IS the "参数量 / 10亿" term (27 for a 27B model).
BASE_PARAMS_BILLIONS = 27.0
BASE_LAYERS = 48
# runtime / driver overhead that we never count as usable for weights or KV.
_OVERHEAD_GB = 3.0
# KV-cache coefficient from the documented formula (GB per (layer·K context)).
_KV_COEF = 0.00075
# never push VRAM to the absolute edge: keep this much headroom (GB) on top of
# the 3 GB fixed overhead so transient allocation spikes don't OOM.
_SAFETY_GB = 4.0
# Hard ceiling on the planned context. The §8.4 KV coefficient is a planning
# estimate and trends optimistic at the extreme; we never auto-select more than
# this even when the math says VRAM allows it, to keep real allocation margin.
MAX_CTX_TOKENS = 200_000


@dataclass
class CapacityResult:
    vram_total_gb: float
    quant: str
    weight_gb: float
    kv_gb: float
    overhead_gb: float
    ctx_tokens: int
    notes: list[str] = None  # type: ignore[assignment]

    def report(self) -> str:
        notes = self.notes or []
        lines = [
            "== 容量规划 (gateway/capacity) ==",
            f"总显存：{self.vram_total_gb} GB",
            f"量化：{self.quant}（权重 ≈ {self.weight_gb} GB，含 5% 余量）",
            f"KV cache（ctx={self.ctx_tokens}）：≈ {self.kv_gb} GB",
            f"固定开销：{self.overhead_gb} GB",
            f"→ 推荐上下文窗口：{self.ctx_tokens} tokens",
        ]
        for n in notes:
            lines.append(f"· {n}")
        return "\n".join(lines)


def weight_gb(quant: str, quant_map: dict | None = None) -> float:
    """Weight footprint for the frozen base at a given quant (5% slack).

    The §8.4 formula writes ``参数量 × 量化GB/10亿``; for a 27B model the
    ``参数量/10亿`` term (27) collapses with the per-billion weight, so the
    total weight in GB is simply the quant table value × 1.05 (5% slack).
    """
    qmap = quant_map or QUANT_VRAM_GB
    q = qmap.get(quant, 18.9)
    return round(q * 1.05, 2)


def _kv_gb_for(ctx_k: float) -> float:
    return BASE_LAYERS * _KV_COEF * ctx_k


def max_ctx_tokens(vram_total_gb: float,
                   quant: str,
                   quant_map: dict | None = None,
                   safety_gb: float = _SAFETY_GB) -> int:
    """Largest K-context that fits in total VRAM without OOM.

    Solves the §8.4 formula for ctx given the available budget:
        budget = vram - weight - overhead - safety
        ctx_K  = budget / (layers × 0.00075)
    Returns 0 if even the base + overhead does not fit (caller should refuse to
    launch rather than OOM).
    """
    w = weight_gb(quant, quant_map)
    fixed = w + _OVERHEAD_GB + safety_gb
    budget = vram_total_gb - fixed
    if budget <= 0:
        return 0
    ctx_k = budget / (BASE_LAYERS * _KV_COEF)
    # floor to a friendly 1024-multiple, but keep at least 4096 for usability
    ctx = int(ctx_k // 1.024) * 1024
    return max(4096, min(ctx, MAX_CTX_TOKENS))


def plan(vram_total_gb: float,
          quant: str | None = None,
          profile: HardwareProfile | None = None,
          quant_map: dict | None = None) -> CapacityResult:
    """Resolve quant (from a profile if not given) and compute the ctx ceiling.

    Uses the self-written VRAM formula documented in Layer2 §8.4 (no external
    binary). Falls back to Q4_K_M when no quant can be recommended (e.g.
    headless test / unknown GPU) so we still produce a conservative, safe plan.

    For the authoritative per-model/per-GPU capacity (including ngl), see
    :func:`plan_fit`, which calls ``llama-fit-params`` and falls back to this
    function on any failure.
    """
    notes: list[str] = []
    if quant is None:
        if profile is not None:
            quant = profile.recommend_quant(quant_map)
        if quant is None:
            quant = "Q4_K_M"
            notes.append("未探测到 GPU 量化建议，按 Q4_K_M 保守规划。")
    q = quant
    w = weight_gb(q, quant_map)
    ctx = max_ctx_tokens(vram_total_gb, q, quant_map)
    if ctx == 0:
        notes.append("⚠️ 显存不足以装载底模 + 固定开销，无法安全启动（阵容铁律）。")
    kv = round(_kv_gb_for(ctx / 1024.0), 2)
    if vram_total_gb >= 48 and ctx >= 131072:
        notes.append("48GB 级显卡：ctx 已拉到 ≥131072 且 KV 分配未超余量。")
    return CapacityResult(
        vram_total_gb=vram_total_gb, quant=q, weight_gb=w,
        kv_gb=kv, overhead_gb=_OVERHEAD_GB, ctx_tokens=ctx, notes=notes,
    )


def fit_params(model_path: str,
               wanted_ctx: int = 131072,
               binary: str | None = None,
               timeout: float = 30.0) -> dict | None:
    """Call llama.cpp ``llama-fit-params`` and parse its ``-c``/``-ngl`` output.

    Invoked as ``llama-fit-params -m <model> -c <wanted_ctx>`` with NO ``-ngl``
    (fit rejects a user-set ngl). Returns ``{"ctx": int, "ngl": int}`` on a
    successful, parseable run, or ``None`` if the binary is missing, times out,
    errors, or the output cannot be parsed. Callers must fall back to the
    self-written formula when this returns ``None``.

    ``binary`` may be a path or bare name (default ``"llama-fit-params"``); a
    ``None`` is treated as the default name so callers can pass an optional
    resolved path through unchanged.
    """
    if binary is None:
        binary = "llama-fit-params"
    if not (os.path.sep in binary or shutil.which(binary)):
        return None
    try:
        proc = subprocess.run(
            [binary, "-m", model_path, "-c", str(wanted_ctx)],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    # llama-fit-params prints space-separated flags: "-c 131072 -ngl 53".
    # We match the exact flag tokens ("-c"/"-ngl") and read the NEXT token, which
    # is robust to other flags (e.g. -ctx / -context) and avoids the fragile
    # prefix-stripping that could mis-parse "-context". If the value is missing
    # (bare "-ngl" with no number while VRAM is mid-release) the lookups below
    # simply leave the field unresolved.
    tokens = out.split()
    ctx = ngl = None
    try:
        ctx = int(tokens[tokens.index("-c") + 1])
    except (ValueError, IndexError):
        pass
    try:
        ngl = int(tokens[tokens.index("-ngl") + 1])
    except (ValueError, IndexError):
        pass
    if ctx is None:
        return None
    # A non-positive ngl means fit could not actually compute an offload count
    # (e.g. it ran while the previous llama-server had not yet released VRAM and
    # reported "-ngl -1"). Treat that as "fit unusable" rather than forwarding a
    # meaningless -1 to llama-server, so the caller falls back to a sane value.
    if ngl is None or ngl <= 0:
        return None
    return {"ctx": ctx, "ngl": ngl}


def plan_fit(model_path: str,
             vram_total_gb: float,
             quant: str | None = None,
             profile: HardwareProfile | None = None,
             quant_map: dict | None = None,
             wanted_ctx: int = 131072) -> CapacityResult:
    """Plan using llama-fit-params as the authoritative source when available.

    Falls back to :func:`plan` (self-written formula, capped at MAX_CTX_TOKENS)
    when fit is unavailable. The fallback ctx for a 48 GB card never exceeds
    131072 so a stale formula cannot over-commit VRAM (OOM guard).
    """
    notes: list[str] = []
    if quant is None:
        if profile is not None:
            quant = profile.recommend_quant(quant_map)
        if quant is None:
            quant = "Q4_K_M"
    q = quant
    w = weight_gb(q, quant_map)

    fit = fit_params(model_path, wanted_ctx=wanted_ctx)
    if fit is not None:
        ctx = fit["ctx"]
        notes.append(f"llama-fit-params 实测：ctx={ctx} ngl={fit['ngl']}（权威值）。")
        method = "fit"
    else:
        res = plan(vram_total_gb, q, profile, quant_map)
        ctx = min(res.ctx_tokens, 131072)  # hard OOM guard on fallback
        if res.ctx_tokens > 131072:
            notes.append("回退公式高估 ctx，已收敛到 131072 防 OOM。")
        elif res.ctx_tokens == 0:
            notes.append("⚠️ 回退公式判定显存不足，无法安全启动（阵容铁律）。")
        method = "fallback"
    kv = round(_kv_gb_for(ctx / 1024.0), 2)
    return CapacityResult(
        vram_total_gb=vram_total_gb, quant=q, weight_gb=w,
        kv_gb=kv, overhead_gb=_OVERHEAD_GB, ctx_tokens=ctx, notes=notes,
    )

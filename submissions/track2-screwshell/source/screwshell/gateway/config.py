"""Gateway Layer 2 — config generation: produce a safe llama-server argv.

Every known W7900 footgun is baked into the defaults so the operator never has
to hand-write an error-prone shell line:

  * --jinja            REQUIRED. Without it tool/function calling silently
                       breaks (HANDOFF_GATEWAY_RELOCATION §3 root cause).
  * --lora a,b,c       comma-joined SINGLE value. Repeated --lora flags are
                       deprecated in current llama.cpp (only the last wins).
  * --reasoning-budget a FINITE value (never -1). -1 means unlimited thinking,
                       which deadlocks agentic tool calls (HANDOFF §6: one "hi"
                       ran 133s).
  * --alias screwshell-base   stable alias the router matches against.
  * --ctx-size         derived from gateway.capacity / llama-fit-params (real VRAM).
  * --n-gpu-layers     derived from llama-fit-params when available (no 999
                        hardcoded to bypass --fit); falls back to the documented
                        roomy default only if fit is unavailable. --threads 24.
  * --host 127.0.0.1 --port 8080         loopback-only (security boundary).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from screwshell.gateway.capacity import plan as capacity_plan
from screwshell.gateway.capacity import fit_params

# Finite reasoning budget for agentic / tool-dense requests. Never -1.
DEFAULT_REASONING_BUDGET = 4096
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_THREADS = 24
# Sentinel: when n_gpu_layers is ``None`` we derive it from llama-fit-params
# (the authoritative per-model/per-GPU value) instead of hardcoding 999. 999
# was bypassing ``--fit`` and over-committing layers; we no longer hardcode it.
DEFAULT_GPU_LAYERS = 999


@dataclass
class ServerConfig:
    model_path: str
    lora_paths: list[str] = field(default_factory=list)
    quant: str | None = None
    lora_alias: str = "screwshell-base"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    threads: int = DEFAULT_THREADS
    n_gpu_layers: int | None = None        # None -> derive from llama-fit-params
    reasoning_budget: int = DEFAULT_REASONING_BUDGET

    def __post_init__(self):
        # HANDOFF §6: a -1 (unlimited) reasoning budget deadlocks agentic tool
        # calls (one "hi" ran 133s). Coerce -1 to the finite default so a bad
        # caller input can never reintroduce the deadlock.
        if self.reasoning_budget is None or self.reasoning_budget < 0:
            self.reasoning_budget = DEFAULT_REASONING_BUDGET
    ctx_tokens: int | None = None          # None -> derived from capacity
    vram_total_gb: float | None = None     # for ctx derivation
    # Autotune first-class fields (tune-loop plan, Todo 1). None = do not emit
    # the flag (let llama-server use its own default). These are surfaced so
    # the cycle's argv builder reuses to_argv() instead of shell templates.
    cache_type_k: str | None = None        # --cache-type-k (KV cache quant)
    cache_type_v: str | None = None        # --cache-type-v
    flash_attn: str = "on"                 # --flash-attn (always emitted when truthy)
    parallel: int = 2                       # --parallel (concurrent sequences)
    n_batch: int | None = None             # --batch (prompt batch size)
    extra_args: list[str] = field(default_factory=list)
    # Optional precomputed llama-fit-params result ({'ctx':int,'ngl':int}). When
    # set by the orchestrator it is reused for every argv/command_line build so
    # fit runs at most once; otherwise resolve_n_gpu_layers computes it lazily.
    fit_result: dict | None = None

    def resolve_ctx(self) -> int:
        if self.ctx_tokens:
            return self.ctx_tokens
        if self.vram_total_gb:
            return capacity_plan(self.vram_total_gb, self.quant).ctx_tokens
        # conservative default when nothing is known
        return 8192

    def resolve_n_gpu_layers(self, binary: str | None = None) -> int:
        """Resolve the n_gpu_layers value for the argv.

        When ``n_gpu_layers`` is explicitly set we honor it. Otherwise we use the
        precomputed ``fit_result`` if supplied, else ask ``llama-fit-params`` for
        the authoritative value (no ``-ngl`` passed so fit runs); if fit is
        unavailable we fall back to the documented W7900 roomy default rather
        than silently hardcoding 999 into the path that bypasses ``--fit``.

        ``binary`` lets the caller pin the fit executable (e.g. the one living
        next to the llama-server binary) so resolution does not depend on PATH.
        """
        if self.n_gpu_layers is not None:
            return self.n_gpu_layers
        fit = self.fit_result
        if fit is None and binary is not None:
            fit = fit_params(self.model_path, binary=binary)
        if fit is not None and fit.get("ngl"):
            return fit["ngl"]
        return DEFAULT_GPU_LAYERS

    def to_argv(self, binary: str = "llama-server",
                fit_binary: str | None = None) -> list[str]:
        """Build the full llama-server argv (list form, no shell injection)."""
        argv = [binary, "--model", self.model_path]
        if self.lora_paths:
            # single comma-joined value — current llama.cpp honors only this
            argv += ["--lora", ",".join(self.lora_paths)]
        argv += [
            "--jinja",
            "--alias", self.lora_alias,
            "--host", self.host,
            "--port", str(self.port),
            "--ctx-size", str(self.resolve_ctx()),
            "--n-gpu-layers", str(self.resolve_n_gpu_layers(fit_binary)),
            "--threads", str(self.threads),
            "--reasoning-budget", str(self.reasoning_budget),
        ]
        # Autotune first-class flags (tune-loop plan, Todo 1). Conditional so a
        # None/empty/falsy value means "leave llama-server default". Emitted
        # AFTER reasoning-budget and BEFORE extra_args (which stays last).
        if self.flash_attn:
            argv += ["--flash-attn", self.flash_attn]
        if self.cache_type_k is not None:
            argv += ["--cache-type-k", self.cache_type_k]
        if self.cache_type_v is not None:
            argv += ["--cache-type-v", self.cache_type_v]
        if self.parallel:
            argv += ["--parallel", str(self.parallel)]
        if self.n_batch is not None:
            # llama-server flag is --batch-size (verified against --help on the
            # W7900 build; --batch is NOT accepted). -b/--batch-size N.
            argv += ["--batch-size", str(self.n_batch)]
        argv += list(self.extra_args)
        return argv

    def command_line(self, binary: str = "llama-server") -> str:
        """Human-readable command line (for logging / runbooks only)."""
        import shlex
        return " ".join(shlex.quote(a) for a in self.to_argv(binary))

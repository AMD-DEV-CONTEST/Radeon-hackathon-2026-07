"""Global feature flags for the ScrewShell end-to-end optimization program.

ADR-2 (see ``docs/_e2e_plan/ARCHITECT_BLUEPRINT.md`` §1.3): *every* optimization
must be switchable. Without a switch there is no A/B; without an A/B the
measurement gate (T3) degrades into a scoreboard that cannot attribute a single
second or token to a single change.

This module is the SINGLE source of truth for those switches. Rules:

* env variable names are always ``SCREWSHELL_<FIELD_IN_UPPER_CASE>``;
* every flag defaults to *today's* behavior, so an unconfigured process behaves
  byte-for-byte like the pre-optimization build;
* stdlib only -- no torch / gradio / numpy / third party (blueprint §6.2 rule 6).

Two configuration channels, in increasing priority:

    E2EConfig()                       # dataclass defaults == today's behavior
    E2EConfig.from_env()              # SCREWSHELL_* environment overrides
    cfg.apply_flags("gbnf=1,...")     # CLI --flags, used by bench/eval_e2e.py
"""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, fields
from typing import Any, Mapping, Optional

ENV_PREFIX = "SCREWSHELL_"

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f", ""}


def _as_bool(raw: Any, default: bool) -> bool:
    """Parse a permissive truthy/falsy token; unknown text keeps `default`."""
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    token = str(raw).strip().lower()
    if token in _TRUE:
        return True
    if token in _FALSE:
        return False
    return default


def _as_int(raw: Any, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _as_float(raw: Any, default: float) -> float:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class E2EConfig:
    """Feature flags for the whole optimization program.

    Every field defaults to the behavior shipped before the program started, so
    ``E2EConfig()`` is the control group of every A/B.
    """

    # ---- T2 measurement (on by default: pure accounting, no behavior change) --
    metrics: bool = True
    """Collect per-call LLM accounting into RunResult.stats['llm']."""

    capabilities_probe: bool = True
    """Allow MoLLlamaCpp.capabilities() to probe the server once (ADR-5)."""

    # ---- T4 citations / error surfacing -------------------------------------
    citations: bool = False
    citations_mode: str = "annotate"      # off | annotate | strip
    error_surfacing: bool = False

    # ---- T5 constrained decoding --------------------------------------------
    gbnf: bool = False

    # ---- T6 prefill slimming -------------------------------------------------
    prefill_slim: bool = False
    prefill_budget_chars: int = 2400
    prefill_keep_last: int = 2
    prefill_digest_cap: int = 900
    stable_history: bool = False
    ctx_tokens: int = 8192

    # ---- T7 budget / parallel tools -----------------------------------------
    max_actions: int = 5                  # today's Orchestrator default
    tool_parallel: bool = False
    tool_parallel_max: int = 3

    # ---- T9 RAG preflight ----------------------------------------------------
    preflight: bool = False
    preflight_top_k: int = 5

    # ---- T11 / T13 / T14 -----------------------------------------------------
    mixture: bool = False
    stream: bool = False
    router_cache: bool = False

    # ---- misc ----------------------------------------------------------------
    seed: int = 0

    # ------------------------------------------------------------------ env --

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return tuple(f.name for f in fields(cls))

    @classmethod
    def env_name(cls, field_name: str) -> str:
        return ENV_PREFIX + field_name.upper()

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "E2EConfig":
        """Build a config from ``SCREWSHELL_*`` variables.

        Unset variables keep the dataclass default; unparsable values keep the
        default too (a typo must never silently flip a flag the other way).
        """
        src = os.environ if env is None else env
        cfg = cls()
        for f in fields(cls):
            raw = src.get(cls.env_name(f.name))
            if raw is None:
                continue
            setattr(cfg, f.name, cls._coerce(f.name, raw, getattr(cfg, f.name)))
        return cfg

    @classmethod
    def _coerce(cls, name: str, raw: Any, current: Any) -> Any:
        if isinstance(current, bool):
            return _as_bool(raw, current)
        if isinstance(current, int):
            return _as_int(raw, current)
        if isinstance(current, float):
            return _as_float(raw, current)
        return str(raw)

    # ---------------------------------------------------------------- flags --

    def apply_flags(self, flags: Optional[str]) -> "E2EConfig":
        """Return a COPY with ``"a=1,b=0,c=text"`` applied.

        This is the ``bench/eval_e2e.py --flags`` entry point: one command line
        switch per optimization means one command can produce both arms of an
        A/B. Unknown keys raise -- a silently ignored flag would make an A/B
        report a difference that was never actually applied.
        """
        cfg = self.copy()
        if not flags:
            return cfg
        known = set(cfg.field_names())
        for chunk in flags.replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "=" in chunk:
                key, _, value = chunk.partition("=")
            else:
                key, value = chunk, "1"
            key = key.strip().lower().replace("-", "_")
            if key not in known:
                raise ValueError(
                    f"unknown flag {key!r}; known flags: "
                    f"{', '.join(sorted(known))}")
            setattr(cfg, key, self._coerce(key, value.strip(),
                                           getattr(cfg, key)))
        return cfg

    # ---------------------------------------------------------------- utils --

    def copy(self) -> "E2EConfig":
        return dataclasses.replace(self)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def non_default(self) -> dict:
        """Only the flags that differ from the shipped baseline.

        This is what a report header should print: a 25-line flag dump hides
        the one flag that actually changed.
        """
        base = E2EConfig()
        return {f.name: getattr(self, f.name)
                for f in fields(self)
                if getattr(self, f.name) != getattr(base, f.name)}

    def describe(self) -> str:
        diff = self.non_default()
        return ", ".join(f"{k}={v}" for k, v in sorted(diff.items())) or "baseline"


_DEFAULT: Optional[E2EConfig] = None


def get_config() -> E2EConfig:
    """Process-wide config, built from env on first use."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = E2EConfig.from_env()
    return _DEFAULT


def set_config(cfg: Optional[E2EConfig]) -> Optional[E2EConfig]:
    """Override (or, with ``None``, reset) the process-wide config."""
    global _DEFAULT
    _DEFAULT = cfg
    return _DEFAULT

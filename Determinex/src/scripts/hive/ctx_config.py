"""
scripts/hive/ctx_config.py - Sprint 5: Context-Window Expansion (config layer)
================================================================================
Single source of truth for per-role context-window sizing and hierarchical
summarization. Designed to be **additive** to the existing locked compiler-loop
files (rosetta_bridge.py, executor.py, workspace.py, compiler.py): callers
opt in by reading from this module instead of hard-coding `n_ctx=512`.

What this gives us:

  1. Per-role n_ctx tuning via env vars - the breakdown's "n_ctx=512 ceiling"
     critique. Engineer/Observer/Sentinel can each have different ceilings
     based on the host VRAM budget.

  2. Hierarchical summarization: when a payload exceeds the Engineer's hard
     ceiling, the Observer (3B, larger context) is invoked to produce a
     compressed spec the Engineer can ingest.

  3. Rosetta Layer 2 ("soft prefix injection") opt-in flag - the CLAUDE.md
     v1.5 milestone. Whether the runtime actually injects the soft prefix is
     decided here, so we don't have to thread the boolean through the call
     graph.

Defaults are CHOSEN to be safe on a 6 GB VRAM laptop card:
  Engineer (1.5B):  4096   (up from 512 in legacy code)
  Observer (3B):    8192
  Sentinel (7B):   16384

Override with DETERMINEX_*_NCTX env vars (see below). Setting any to <=0 means
"use the value baked into the Ollama Modelfile".

Usage:
    from hive.ctx_config import effective_n_ctx, summarize_if_needed
    n_ctx = effective_n_ctx("engineer")
    spec = summarize_if_needed(spec_text, role="engineer")
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger("hive.ctx_config")

Role = Literal["engineer", "observer", "sentinel"]


# --- Per-role n_ctx defaults (override via env) -------------------------------
_DEFAULT_N_CTX: dict[Role, int] = {
    "engineer": 4096,
    "observer": 8192,
    "sentinel": 16384,
}

_ENV_KEYS: dict[Role, str] = {
    "engineer": "DETERMINEX_ENGINEER_NCTX",
    "observer": "DETERMINEX_OBSERVER_NCTX",
    "sentinel": "DETERMINEX_SENTINEL_NCTX",
}

_MODEL_TAGS: dict[Role, str] = {
    "engineer": os.getenv("DETERMINEX_BUILDER_MODEL", "determinex-engineer-v11-dsl"),
    "observer": os.getenv("DETERMINEX_OBSERVER_MODEL", "determinex-observer-v6-dsl"),
    "sentinel": os.getenv("DETERMINEX_ARCHITECT_MODEL", "determinex-sentinel-v5-dsl"),
}

# Approx chars-per-token used for cheap, deterministic budget estimation.
# Real tokenizers vary; this is a safe ceiling (Qwen/Mistral BPE averages ~3.5).
_CHARS_PER_TOKEN = float(os.getenv("DETERMINEX_CHARS_PER_TOKEN", "3.5"))

# Reserve tokens for system prompt + completion within the model's n_ctx.
_SYSTEM_RESERVE = int(os.getenv("DETERMINEX_SYSTEM_RESERVE_TOKENS", "256"))
_COMPLETION_RESERVE = int(os.getenv("DETERMINEX_COMPLETION_RESERVE_TOKENS", "512"))

# --- Rosetta Layer 2 opt-in ---------------------------------------------------
ROSETTA_LAYER2_ENABLED = os.getenv("DETERMINEX_ROSETTA_LAYER2", "0") == "1"
ROSETTA_PT_PATH = os.getenv(
    "DETERMINEX_ROSETTA_WEIGHTS",
    os.path.join(os.getenv("DETERMINEX_MODELS_DIR", "T:/determinex-models"), "rosetta_v1.pt"),
)


@dataclass
class RosettaPrefixConfig:
    """Carrier for Layer 2 (soft-prefix injection) config. Returned by
    `effective_prefix_config(role)`; callers that haven't been migrated to
    Layer 2 simply ignore it."""

    enabled: bool
    weights_path: str
    target_role: Role
    source_role: Role | None = None  # set when prefix originates from another role


# --- API ----------------------------------------------------------------------


def effective_n_ctx(role: Role) -> int:
    """Resolve the n_ctx for `role` from env (priority) or default.

    Returns 0 if the env var is explicitly set to <=0, meaning "let the
    Modelfile decide". Callers should pass 0 through to Ollama's options.
    """
    if role not in _DEFAULT_N_CTX:
        raise ValueError(f"unknown role '{role}', expected one of {list(_DEFAULT_N_CTX)}")
    raw = os.getenv(_ENV_KEYS[role])
    if raw is None:
        return _DEFAULT_N_CTX[role]
    try:
        val = int(raw)
    except ValueError:
        log.warning("invalid %s=%r, using default %d", _ENV_KEYS[role], raw, _DEFAULT_N_CTX[role])
        return _DEFAULT_N_CTX[role]
    return max(val, 0)


def usable_input_tokens(role: Role) -> int:
    """How many input tokens a role's prompt can use after reserving system +
    completion budget. Returns 0 when n_ctx is 0 (Modelfile-controlled)."""
    n_ctx = effective_n_ctx(role)
    if n_ctx == 0:
        return 0
    return max(0, n_ctx - _SYSTEM_RESERVE - _COMPLETION_RESERVE)


def estimate_tokens(text: str) -> int:
    """Cheap chars/CHARS_PER_TOKEN estimator (safe upper bound for English/code)."""
    return int(len(text) / _CHARS_PER_TOKEN) if text else 0


def fits_in_role(text: str, role: Role) -> bool:
    """True if `text` fits within the input budget for `role`."""
    budget = usable_input_tokens(role)
    if budget == 0:
        return True  # Modelfile-controlled; assume caller-side handling
    return estimate_tokens(text) <= budget


def effective_prefix_config(role: Role, source_role: Role | None = None) -> RosettaPrefixConfig:
    """Return the Layer-2 prefix config. Enabled = (env flag set) AND
    (weights file readable). Callers that don't support prefix injection should
    just ignore the returned `enabled=True` case for now."""
    if not ROSETTA_LAYER2_ENABLED:
        return RosettaPrefixConfig(False, ROSETTA_PT_PATH, role, source_role)
    if not os.path.isfile(ROSETTA_PT_PATH):
        log.warning("DETERMINEX_ROSETTA_LAYER2=1 but weights not at %s", ROSETTA_PT_PATH)
        return RosettaPrefixConfig(False, ROSETTA_PT_PATH, role, source_role)
    return RosettaPrefixConfig(True, ROSETTA_PT_PATH, role, source_role)


# --- Hierarchical summarization helper ----------------------------------------

_SUMMARIZE_SYSTEM = (
    "You are Determinex Observer. Compress the input into a structured spec that "
    "preserves: goal, language, hard constraints, signatures, acceptance criteria, "
    "and any concrete examples. Drop prose, explanations, and historical context. "
    "Output ONLY the compressed spec, in <= {budget_tokens} tokens."
)


def _ollama_complete(
    model: str, system: str, user: str, num_ctx: int, num_predict: int, timeout_s: int = 60
) -> str:
    url = os.getenv("DETERMINEX_OLLAMA_URL", "http://localhost:11434")
    parsed = urllib.parse.urlparse(url)
    if (parsed.hostname or "") not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(f"DETERMINEX_OLLAMA_URL host '{parsed.hostname}' not allowed")
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "temperature": 0.1,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (localhost-only)
            payload = json.loads(resp.read().decode("utf-8"))
        return (payload.get("message", {}).get("content") or "").strip()
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        log.warning("ollama call failed: %s", e)
        return ""


def summarize_if_needed(text: str, role: Role = "engineer", target_role: Role = "observer") -> str:
    """If `text` fits in `role`'s budget, return as-is. Otherwise compress
    via `target_role` (default Observer 3B) and return the compression.

    Returns the original text untouched when summarization fails - the caller
    can then decide between truncation, splitting, or failing the request.
    """
    if fits_in_role(text, role):
        return text

    target_budget = usable_input_tokens(role)
    if target_budget <= 0:
        return text  # role uses Modelfile n_ctx, nothing to compress against

    summary_token_budget = max(256, target_budget - 512)  # leave headroom for prompt scaffolding
    log.info(
        "hierarchical compression: %d est. tokens > %d budget for '%s'; "
        "summarizing via '%s' to <= %d tokens",
        estimate_tokens(text),
        target_budget,
        role,
        target_role,
        summary_token_budget,
    )

    target_n_ctx = effective_n_ctx(target_role) or 8192
    summary = _ollama_complete(
        model=_MODEL_TAGS[target_role],
        system=_SUMMARIZE_SYSTEM.format(budget_tokens=summary_token_budget),
        user=text,
        num_ctx=target_n_ctx,
        num_predict=summary_token_budget,
    )
    if not summary:
        log.warning("summarization failed; returning original text (caller must truncate)")
        return text
    return summary


def report() -> dict:
    """Diagnostic dict suitable for `determinex-ask where --explain` to surface."""
    return {
        "n_ctx_by_role": {role: effective_n_ctx(role) for role in _DEFAULT_N_CTX},
        "model_tags": dict(_MODEL_TAGS),
        "rosetta_layer2": {
            "enabled": ROSETTA_LAYER2_ENABLED,
            "weights_path": ROSETTA_PT_PATH,
            "weights_present": os.path.isfile(ROSETTA_PT_PATH),
        },
        "system_reserve_tokens": _SYSTEM_RESERVE,
        "completion_reserve_tokens": _COMPLETION_RESERVE,
        "chars_per_token": _CHARS_PER_TOKEN,
    }


if __name__ == "__main__":
    import sys as _sys

    print(json.dumps(report(), indent=2))
    _sys.exit(0)

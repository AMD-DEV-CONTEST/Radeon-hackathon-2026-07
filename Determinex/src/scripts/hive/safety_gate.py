"""
scripts/hive/safety_gate.py — Pipeline Safety Gate Integration
==============================================================
Thin adapter that wires determinex_safety into every pipeline stage.

Call sites:
  pre_spec_gate(spec_text)         — determinex_hive.py new-session / run-session
  pre_api_gate(messages, provider) — api_client.py before every cloud call
  post_generation_gate(code, lang) — executor.py after Builder returns code
  corpus_gate_sign(entry)          — wherever verdict corpus entries are written
  corpus_gate_verify(entry)        — wherever corpus entries are read for training

Cloak enforcement:
  Cloud API calls (non-Ollama) require Cloak to be active when
  DETERMINEX_REQUIRE_CLOAK=1 (default: 1).
  If Cloak is inactive and the requirement is set, the call is blocked
  with a hard error — the caller must enable DETERMINEX_CLOAK=1.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("hive.safety")

# Bootstrap: ensure scripts/ is importable as a package root
_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

try:
    from determinex_safety import (
        CorpusTamperError,
        SafetyDenied,
        SafetyVerdict,
    )
    from determinex_safety import (
        check_egress as _check_egress,
    )
    from determinex_safety import (
        check_output as _check_output,
    )
    from determinex_safety import (
        check_spec as _check_spec,
    )
    from determinex_safety import (
        sign_corpus_entry as _sign,
    )
    from determinex_safety import (
        verify_corpus_entry as _verify,
    )

    _SAFETY_AVAILABLE = True
except ImportError as _e:
    log.error("[SAFETY GATE] determinex_safety import failed: %s — safety checks DISABLED", _e)
    _SAFETY_AVAILABLE = False

# ── Cloak enforcement config ──────────────────────────────────────────────────
# DETERMINEX_REQUIRE_CLOAK=1 (default) means any cloud-tier API call that does
# not have Cloak active will be blocked. Set to 0 only in local-only Ollama
# deployments where no cloud API is in use.
_REQUIRE_CLOAK = os.environ.get("DETERMINEX_REQUIRE_CLOAK", "1") == "1"
_CLOAK_ACTIVE = bool(os.environ.get("DETERMINEX_CLOAK", ""))

# Cloud provider prefixes that require Cloak
_CLOUD_PROVIDERS = {
    "anthropic",
    "openai",
    "deepseek",
    "openrouter",
    "gemini",
    "google",
    "azure",
    "mistral",
    "cohere",
}


def _is_cloud_model(model: str) -> bool:
    """Return True if the model string refers to a cloud-hosted provider.

    THIS BLOCKED EVERY LOCAL CALL ON A FRESH INSTALL (found 2026-07-30).

    The test used to be `not m.startswith("ollama/")`, but callers pass the CONFIGURED ALIAS, not the
    resolved provider name -- `api_client._effective_model = kwargs.get("model", model)`, which is
    `determinex/engineer`. That does not start with `ollama/`, so a model running on the user's own
    machine was classified as cloud. With `DETERMINEX_REQUIRE_CLOAK=1` (the documented default) and
    Cloak inactive, `pre_api_gate` then raises:

        [SAFETY GATE] Cloud API call to 'determinex/engineer' blocked:
        DETERMINEX_REQUIRE_CLOAK=1 but Cloak is not active.

    Reproduced directly with the env cleared: `determinex/engineer` and the bare ctx_config default
    `determinex-engineer-v11-dsl` were both BLOCKED; only the fully-qualified `ollama/...` passed. So a
    new user's entirely local, offline build session was refused as a cloud call. It works on the
    development box only because `.env` sets `DETERMINEX_REQUIRE_CLOAK=0` -- and `.env` is not shipped
    in the installer, which is what made this invisible.

    Same defect as the api_client OOM timeout guard and the budget pricer before it: one locality
    question, answered by hand in three places, wrong in two. `budget.is_local_model` is the canonical
    answer -- it knows ollama/, ollama_chat/, hosted_vllm/, text-completion-openai/, determinex/,
    local/ and the bare `determinex-` family.

    The explicit provider-substring check is kept ahead of it, so an unrecognised string still errs
    toward "cloud, therefore require Cloak" rather than toward silently skipping obfuscation.
    """
    m = model.lower()
    if any(p in m for p in _CLOUD_PROVIDERS):
        return True
    try:
        from hive.budget import is_local_model
    except Exception:
        # Locality is unknowable here; treat as cloud so Cloak enforcement is not skipped.
        return not m.startswith("ollama/")
    return not is_local_model(model)


# ─────────────────────────────────────────────────────────────────────────────
# Gate functions
# ─────────────────────────────────────────────────────────────────────────────


def pre_spec_gate(spec_text: str, source: str = "cli") -> None:
    """
    L0 + L1 gate: run content policy + intent classifier on a user spec.

    Raises SafetyDenied (in strict mode) or logs warning (in warn mode).
    Always call before the spec reaches generate-dag or run-session.

    Args:
        spec_text: Full text of the user's spec file or inline spec string.
        source: Label for logging ('cli', 'api', 'frontend').
    """
    if not _SAFETY_AVAILABLE:
        log.warning("[SAFETY GATE] Safety module unavailable — spec check skipped")
        return

    log.debug(
        "[SAFETY GATE] pre_spec_gate: checking spec from '%s' (%d chars)", source, len(spec_text)
    )
    verdict = _check_spec(spec_text)

    if not verdict.safe:
        log.error(
            "[SAFETY GATE] Spec DENIED [%s] %s: %s",
            verdict.layer,
            verdict.category,
            verdict.reason,
        )
        # SafetyDenied already raised by engine in strict mode;
        # in warn mode, re-raise here so callers always get the exception
        raise SafetyDenied(verdict)

    log.debug("[SAFETY GATE] Spec passed L0+L1 safety check")


def pre_api_gate(messages: list[dict], model: str, cloak_active: bool = False) -> None:
    """
    L2 gate: run egress filter on all message content before a cloud API call.
    Also enforces Cloak requirement for cloud providers.

    Raises SafetyDenied if secrets detected or Cloak enforcement fails.
    Raises RuntimeError if Cloak is required but inactive.

    Args:
        messages: The full messages list that will be sent to the API.
        model:    The model string (e.g. 'claude-sonnet-4-6', 'ollama/qwen').
        cloak_active: Whether Project Cloak is currently active for this call.
    """
    if not _SAFETY_AVAILABLE:
        return

    # ── Cloak enforcement for cloud models ───────────────────────────────────
    if _REQUIRE_CLOAK and _is_cloud_model(model) and not cloak_active and not _CLOAK_ACTIVE:
        raise RuntimeError(
            f"[SAFETY GATE] Cloud API call to '{model}' blocked: "
            f"DETERMINEX_REQUIRE_CLOAK=1 but Cloak is not active. "
            f"Set DETERMINEX_CLOAK=1 to enable obfuscation, or "
            f"DETERMINEX_REQUIRE_CLOAK=0 to disable this enforcement."
        )

    # ── Egress scan on all message content ───────────────────────────────────
    full_text = " ".join(
        msg.get("content", "") for msg in messages if isinstance(msg.get("content"), str)
    )
    verdict = _check_egress(full_text)
    if not verdict.safe:
        log.error(
            "[SAFETY GATE] Egress BLOCKED [%s] %s: %s",
            verdict.layer,
            verdict.category,
            verdict.reason,
        )
        raise SafetyDenied(verdict)

    log.debug("[SAFETY GATE] pre_api_gate passed for model='%s'", model)


def post_generation_gate(code: str, lang: str, step_name: str = "") -> None:
    """
    L3 gate: scan Builder-generated production code for malicious patterns.

    Raises SafetyDenied if the generated code contains exfiltration patterns,
    keylogging APIs, persistence mechanisms, anti-analysis tricks, etc.

    Args:
        code:      The raw code string returned by the Builder.
        lang:      Language tag ('python', 'rust', 'go', 'c', 'typescript', etc.)
        step_name: Step identifier for logging.
    """
    if not _SAFETY_AVAILABLE:
        return

    log.debug(
        "[SAFETY GATE] post_generation_gate: scanning %s code (%d chars) for step='%s'",
        lang,
        len(code),
        step_name,
    )
    verdict = _check_output(code, lang)
    if not verdict.safe:
        log.error(
            "[SAFETY GATE] Builder output BLOCKED [%s] %s: %s (step='%s')",
            verdict.layer,
            verdict.category,
            verdict.reason,
            step_name,
        )
        raise SafetyDenied(verdict)

    log.debug("[SAFETY GATE] Builder output passed L3 scan (step='%s')", step_name)


def corpus_gate_sign(entry: dict) -> None:
    """
    L4 gate: HMAC-sign a verdict corpus entry before it is written to disk.
    Mutates entry in-place by adding '_sig' key.
    """
    if not _SAFETY_AVAILABLE:
        return
    _sign(entry)


def corpus_gate_verify(entry: dict) -> bool:
    """
    L4 gate: verify HMAC signature on a corpus entry read from disk.
    Returns True if valid. Raises CorpusTamperError if invalid or missing.
    """
    if not _SAFETY_AVAILABLE:
        log.warning("[SAFETY GATE] Safety module unavailable — corpus verify skipped")
        return True
    return _verify(entry)


# ─────────────────────────────────────────────────────────────────────────────
# Utility: redact secrets from text for safe logging
# ─────────────────────────────────────────────────────────────────────────────

import re as _re

_REDACT_RE = _re.compile(
    r"(sk-[A-Za-z0-9]{10,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{20,}"
    r"|AIza[A-Za-z0-9]{20,}|xoxb-[A-Za-z0-9\-]{20,}"
    r"|-----BEGIN [A-Z ]* PRIVATE KEY)",
    _re.IGNORECASE,
)


def redact_secrets(text: str) -> str:
    """Replace known secret patterns with [REDACTED] for safe log output."""
    return _REDACT_RE.sub("[REDACTED]", text)

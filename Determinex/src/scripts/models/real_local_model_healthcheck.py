"""Bounded real local-model healthcheck.

POSTs a trivial fixed prompt to the local model and records whether
the daemon answered within a strict timeout. Output is always
treated as untrusted. NO source/repo content is ever included in
the prompt. No patch is generated. No training row is written.

Gates (fail closed):
  - canonical selection must be SELECTED
  - endpoint must be localhost (default transport)
  - bounded timeout (default 5 s)
  - pluggable transport so tests exercise gates without sockets

Decisions:
  - PASSED                            — daemon answered with text
  - BLOCKED_NOT_SELECTED              — upstream selection didn't pick a model
  - BLOCKED_MODEL_NOT_PULLED          — daemon reported missing model
  - BLOCKED_PROVIDER_UNAVAILABLE      — daemon not reachable
  - BLOCKED_TIMEOUT                   — answer exceeded timeout
  - BLOCKED_PROVIDER_ERROR            — non-2xx, malformed json, etc.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from .canonical_local_model_id_selection_record import (
    CanonicalLocalModelIdSelectionRecord,
)
from .real_local_model_healthcheck_record import (
    REAL_LOCAL_MODEL_HEALTHCHECK_STATUS_TOKENS,
    RealLocalModelHealthcheckRecord,
)

_LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})

# Trivial fixed prompt — never contains source/repo content. The
# prompt is intentionally context-free so the healthcheck cannot
# accidentally leak workspace state into the model.
_HEALTHCHECK_PROMPT = "Reply with the single word 'OK'."
_HEALTHCHECK_SYSTEM = "You are a healthcheck. Output is recorded as untrusted."
_RESPONSE_CAP = 256


@dataclass(frozen=True)
class _GenResult:
    ok: bool
    timed_out: bool
    not_pulled: bool
    not_reachable: bool
    text: str = ""
    error: str = ""


GenTransport = Callable[[str, str, str, str, float], _GenResult]


def _default_transport(
    endpoint: str,
    model_id: str,
    prompt: str,
    system: str,
    timeout_seconds: float,
) -> _GenResult:
    """Stdlib urllib POST to /api/generate, localhost-bound by caller."""
    import json as _json
    import urllib.error
    import urllib.request

    body = _json.dumps(
        {
            "model": model_id,
            "prompt": prompt,
            "system": system,
            "stream": False,
        }
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            url=endpoint.rstrip("/") + "/api/generate",
            method="POST",
            data=body,
            headers={
                "User-Agent": "determinex-model-healthcheck/1",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            if resp.status == 404:
                return _GenResult(
                    ok=False,
                    timed_out=False,
                    not_pulled=True,
                    not_reachable=False,
                    error=f"status {resp.status}",
                )
            if not (200 <= resp.status < 300):
                return _GenResult(
                    ok=False,
                    timed_out=False,
                    not_pulled=False,
                    not_reachable=False,
                    error=f"status {resp.status}",
                )
            raw = resp.read().decode("utf-8") or "{}"
            try:
                payload = _json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                return _GenResult(
                    ok=False,
                    timed_out=False,
                    not_pulled=False,
                    not_reachable=False,
                    error=f"malformed json: {exc}",
                )
            # Ollama returns an error payload with `error` key when
            # the model isn't pulled.
            if isinstance(payload, dict) and isinstance(payload.get("error"), str):
                err = payload["error"].lower()
                if "not found" in err or "no such file" in err or "pull" in err:
                    return _GenResult(
                        ok=False,
                        timed_out=False,
                        not_pulled=True,
                        not_reachable=False,
                        error=payload["error"],
                    )
                return _GenResult(
                    ok=False,
                    timed_out=False,
                    not_pulled=False,
                    not_reachable=False,
                    error=payload["error"],
                )
            text = ""
            if isinstance(payload, dict):
                t = payload.get("response")
                if isinstance(t, str):
                    text = t
            return _GenResult(
                ok=True, timed_out=False, not_pulled=False, not_reachable=False, text=text
            )
    except TimeoutError:
        return _GenResult(
            ok=False, timed_out=True, not_pulled=False, not_reachable=False, error="socket timeout"
        )
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc)).lower()
        if "timed out" in reason:
            return _GenResult(
                ok=False, timed_out=True, not_pulled=False, not_reachable=False, error=str(exc)
            )
        if "refused" in reason:
            return _GenResult(
                ok=False, timed_out=False, not_pulled=False, not_reachable=True, error=str(exc)
            )
        return _GenResult(
            ok=False, timed_out=False, not_pulled=False, not_reachable=False, error=str(exc)
        )
    except OSError as exc:
        return _GenResult(
            ok=False, timed_out=False, not_pulled=False, not_reachable=False, error=str(exc)
        )


def _host_is_local(endpoint: str) -> bool:
    return (urlparse(endpoint).hostname or "").lower() in _LOCAL_HOSTS


def run(
    *,
    selection: CanonicalLocalModelIdSelectionRecord | None,
    endpoint: str = "http://127.0.0.1:11434",
    timeout_seconds: float = 5.0,
    transport: GenTransport | None = None,
) -> RealLocalModelHealthcheckRecord:
    if selection is None or not selection.is_selected:
        return _blocked(
            "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_NOT_SELECTED",
            model_id=getattr(selection, "selected_model_id", "") if selection else "",
            provider=getattr(selection, "provider", "") if selection else "",
            endpoint=endpoint,
            note="selection record missing or not SELECTED",
        )

    if transport is None and not _host_is_local(endpoint):
        return _blocked(
            "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_PROVIDER_UNAVAILABLE",
            model_id=selection.selected_model_id,
            provider=selection.provider,
            endpoint=endpoint,
            note="endpoint host not in local set",
        )

    use_transport: GenTransport = transport or _default_transport
    start = time.monotonic()
    result = use_transport(
        endpoint,
        selection.selected_model_id,
        _HEALTHCHECK_PROMPT,
        _HEALTHCHECK_SYSTEM,
        timeout_seconds,
    )
    elapsed = int((time.monotonic() - start) * 1000)

    if result.timed_out:
        return _blocked(
            "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_TIMEOUT",
            model_id=selection.selected_model_id,
            provider=selection.provider,
            endpoint=endpoint,
            elapsed_ms=elapsed,
            note=result.error or "timed out",
        )

    if result.not_pulled:
        return _blocked(
            "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_MODEL_NOT_PULLED",
            model_id=selection.selected_model_id,
            provider=selection.provider,
            endpoint=endpoint,
            elapsed_ms=elapsed,
            note=result.error or "model not pulled",
        )

    if result.not_reachable:
        return _blocked(
            "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_PROVIDER_UNAVAILABLE",
            model_id=selection.selected_model_id,
            provider=selection.provider,
            endpoint=endpoint,
            elapsed_ms=elapsed,
            note=result.error or "provider not reachable",
        )

    if not result.ok:
        return _blocked(
            "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_PROVIDER_ERROR",
            model_id=selection.selected_model_id,
            provider=selection.provider,
            endpoint=endpoint,
            elapsed_ms=elapsed,
            note=result.error or "provider error",
        )

    body = (result.text or "")[:_RESPONSE_CAP]
    return RealLocalModelHealthcheckRecord(
        decision="REAL_LOCAL_MODEL_HEALTHCHECK_PASSED",
        model_id=selection.selected_model_id,
        provider=selection.provider,
        endpoint=endpoint,
        prompt=_HEALTHCHECK_PROMPT,
        response_chars=len(result.text or ""),
        elapsed_ms=elapsed,
        output_trusted=False,
        network_provider_admitted=False,
        patch_generated=False,
        repo_source_inputted=False,
        training_eligible=False,
        source_mutation_authorized=False,
        statuses_seen=(
            "REAL_LOCAL_MODEL_HEALTHCHECK_PASSED",
            "REAL_LOCAL_MODEL_HEALTHCHECK_OUTPUT_UNTRUSTED",
        ),
        notes=(
            "healthcheck passed; response captured as untrusted text",
            f"response preview: {body!r}",
            "no repo source inputted; no patch generated; no training row",
        ),
    )


def _blocked(
    decision: str,
    *,
    model_id: str,
    provider: str,
    endpoint: str,
    note: str,
    elapsed_ms: int = 0,
) -> RealLocalModelHealthcheckRecord:
    return RealLocalModelHealthcheckRecord(
        decision=decision,
        model_id=model_id,
        provider=provider,
        endpoint=endpoint,
        prompt=_HEALTHCHECK_PROMPT,
        response_chars=0,
        elapsed_ms=elapsed_ms,
        output_trusted=False,
        network_provider_admitted=False,
        patch_generated=False,
        repo_source_inputted=False,
        training_eligible=False,
        source_mutation_authorized=False,
        statuses_seen=(decision, "REAL_LOCAL_MODEL_HEALTHCHECK_OUTPUT_UNTRUSTED"),
        notes=(note,),
    )


__all__ = [
    "run",
    "REAL_LOCAL_MODEL_HEALTHCHECK_STATUS_TOKENS",
    "RealLocalModelHealthcheckRecord",
]

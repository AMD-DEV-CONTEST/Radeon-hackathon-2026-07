"""Real live-diagnose runner — advisory output only.

Calls a real local model (default: Ollama at localhost:11434/api/generate)
to produce a *diagnose* summary. The output is recorded as advisory only:
verifier remains the source of truth, no patch is generated, no source
is mutated, no training row is written.

Gates (fail closed):
  - admission must be REAL_LOCAL_MODEL_ADMITTED
  - caller must pass opt_in=True
  - endpoint must be localhost (when default transport is used)
  - bounded timeout
  - empty / oversize / network-error responses → BLOCKED_*

Pluggable transport: tests supply a fake transport so the runner's
gate ladder is exercised without spawning a real socket.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from .real_live_diagnose_only_record import (
    REAL_LIVE_DIAGNOSE_ONLY_STATUS_TOKENS,
    RealLiveDiagnoseOnlyRecord,
)
from .real_local_model_admission_record import (
    RealLocalModelAdmissionRecord,
)

_LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})

# Max characters from the model's response we save in the record's
# advisory_summary. Keeping it bounded prevents storing oversize
# untrusted strings in evidence files.
_ADVISORY_SUMMARY_CAP = 1024


@dataclass(frozen=True)
class _GenResult:
    ok: bool
    timed_out: bool
    error: str = ""
    text: str = ""


GenTransport = Callable[[str, str, str, str, float], _GenResult]


def _default_transport(
    endpoint: str,
    model_id: str,
    prompt: str,
    system: str,
    timeout_seconds: float,
) -> _GenResult:
    """Stdlib urllib POST to /api/generate. Localhost-bound by caller."""
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
                "User-Agent": "determinex-live-diagnose/1",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            if not (200 <= resp.status < 300):
                return _GenResult(ok=False, timed_out=False, error=f"status {resp.status}")
            try:
                payload = _json.loads(resp.read().decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError) as exc:
                return _GenResult(ok=False, timed_out=False, error=f"malformed json: {exc}")
            text = ""
            if isinstance(payload, dict):
                t = payload.get("response")
                if isinstance(t, str):
                    text = t
            return _GenResult(ok=True, timed_out=False, text=text)
    except TimeoutError:
        return _GenResult(ok=False, timed_out=True, error="socket timeout")
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc)).lower()
        if "timed out" in reason:
            return _GenResult(ok=False, timed_out=True, error=str(exc))
        return _GenResult(ok=False, timed_out=False, error=str(exc))
    except OSError as exc:
        return _GenResult(ok=False, timed_out=False, error=str(exc))


def _host_is_local(endpoint: str) -> bool:
    return (urlparse(endpoint).hostname or "").lower() in _LOCAL_HOSTS


def run(
    *,
    workspace: str,
    admission: RealLocalModelAdmissionRecord | None,
    task_class: str = "BUILD_DIAGNOSIS",
    opt_in: bool = False,
    prompt: str = "Summarize the diagnostic observation in one short paragraph.",
    system: str = "You are an advisory diagnostic. Output is untrusted.",
    endpoint: str = "http://127.0.0.1:11434",
    timeout_seconds: float = 5.0,
    transport: GenTransport | None = None,
) -> RealLiveDiagnoseOnlyRecord:
    """Run a real live diagnose. Advisory output only."""
    # 1. Admission gate.
    if admission is None or not admission.is_admitted:
        return _blocked(
            "REAL_LIVE_DIAGNOSE_BLOCKED_NO_MODEL",
            workspace=workspace,
            model_id=getattr(admission, "model_id", ""),
            provider=getattr(admission, "provider", ""),
            task_class=task_class,
            note="admission record missing or not admitted",
        )

    # 2. Opt-in.
    if not opt_in:
        return _blocked(
            "REAL_LIVE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
            workspace=workspace,
            model_id=admission.model_id,
            provider=admission.provider,
            task_class=task_class,
            note="explicit opt_in=True is required",
        )

    # 3. Task class must be in the admitted set.
    if task_class not in admission.task_classes_admitted:
        return _blocked(
            "REAL_LIVE_DIAGNOSE_BLOCKED_NO_MODEL",
            workspace=workspace,
            model_id=admission.model_id,
            provider=admission.provider,
            task_class=task_class,
            note=f"task_class {task_class!r} not in admitted set",
        )

    # 4. Endpoint must be local (only when default transport is in use;
    #    callers passing a custom transport for tests bypass this — but
    #    even then no real network can happen).
    if transport is None and not _host_is_local(endpoint):
        return _blocked(
            "REAL_LIVE_DIAGNOSE_BLOCKED_PROVIDER_ERROR",
            workspace=workspace,
            model_id=admission.model_id,
            provider=admission.provider,
            task_class=task_class,
            note="endpoint host not in local set",
        )

    use_transport: GenTransport = transport or _default_transport
    start = time.monotonic()
    result = use_transport(endpoint, admission.model_id, prompt, system, timeout_seconds)
    elapsed = int((time.monotonic() - start) * 1000)

    if result.timed_out:
        return _blocked(
            "REAL_LIVE_DIAGNOSE_BLOCKED_TIMEOUT",
            workspace=workspace,
            model_id=admission.model_id,
            provider=admission.provider,
            task_class=task_class,
            note=result.error or "timed out",
            elapsed_ms=elapsed,
        )

    if not result.ok:
        return _blocked(
            "REAL_LIVE_DIAGNOSE_BLOCKED_PROVIDER_ERROR",
            workspace=workspace,
            model_id=admission.model_id,
            provider=admission.provider,
            task_class=task_class,
            note=result.error or "provider error",
            elapsed_ms=elapsed,
        )

    advisory_summary = (result.text or "")[:_ADVISORY_SUMMARY_CAP]

    return RealLiveDiagnoseOnlyRecord(
        decision="REAL_LIVE_DIAGNOSE_WRITTEN",
        workspace=workspace,
        model_id=admission.model_id,
        provider=admission.provider,
        task_class=task_class,
        advisory_summary=advisory_summary,
        response_chars=len(result.text or ""),
        elapsed_ms=elapsed,
        output_trusted=False,
        advisory_only=True,
        patch_generated=False,
        source_mutation_authorized=False,
        training_eligible=False,
        network_provider_admitted=False,
        statuses_seen=(
            "REAL_LIVE_DIAGNOSE_WRITTEN",
            "REAL_LIVE_DIAGNOSE_ADVISORY_ONLY",
        ),
        notes=(
            "live diagnose completed; output is advisory only",
            "verifier remains the source of truth",
            "no patch generated; no source mutation; no training row",
        ),
    )


def _blocked(
    decision: str,
    *,
    workspace: str,
    model_id: str,
    provider: str,
    task_class: str,
    note: str,
    elapsed_ms: int = 0,
) -> RealLiveDiagnoseOnlyRecord:
    return RealLiveDiagnoseOnlyRecord(
        decision=decision,
        workspace=workspace,
        model_id=model_id,
        provider=provider,
        task_class=task_class,
        advisory_summary="",
        response_chars=0,
        elapsed_ms=elapsed_ms,
        output_trusted=False,
        advisory_only=True,
        patch_generated=False,
        source_mutation_authorized=False,
        training_eligible=False,
        network_provider_admitted=False,
        statuses_seen=(decision, "REAL_LIVE_DIAGNOSE_ADVISORY_ONLY"),
        notes=(note,),
    )


__all__ = [
    "run",
    "REAL_LIVE_DIAGNOSE_ONLY_STATUS_TOKENS",
    "RealLiveDiagnoseOnlyRecord",
]

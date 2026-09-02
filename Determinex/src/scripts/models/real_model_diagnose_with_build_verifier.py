"""Real model diagnose with build-adapter verifier context.

Composes:
  - REAL_LOCAL_MODEL_HEALTHCHECK_LOCK_001 (must be PASSED)
  - BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_LOCK_001 (must be SELECTED)
  - explicit opt_in

to produce a real-model diagnosis prompt that carries the verifier
context (build system id + verifier argv) only — NEVER any source
content. Output is recorded as untrusted advisory text. The
verifier remains the source of truth; this rung does not run the
verifier and does not generate a patch.

Pluggable transport so tests exercise the gate without sockets.
"""

from __future__ import annotations

import sys as _sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path as _Path
from urllib.parse import urlparse

from .real_local_model_healthcheck_record import (
    RealLocalModelHealthcheckRecord,
)
from .real_model_diagnose_with_build_verifier_record import (
    REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_STATUS_TOKENS,
    RealModelDiagnoseWithBuildVerifierRecord,
)

_HERE = _Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS))

from repair.build_adapter_backed_verifier_selection_record import (  # noqa: E402
    BuildAdapterBackedVerifierSelectionRecord,
)

_LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})
_ADVISORY_CAP = 2048


_SYSTEM = (
    "You are an advisory diagnostic. Output is untrusted. "
    "The verifier remains the source of truth. Do NOT propose "
    "patches; describe the suspected diagnostic class only."
)


def _opacify_workspace_identity(raw: str) -> str:
    """CLAUDE-AUTH-007 remediation: enforce opacity at the function
    boundary. The raw identity is hashed with sha256 and truncated;
    no caller-supplied content reaches the model prompt verbatim."""
    import hashlib

    if not isinstance(raw, str):
        raw = str(raw)
    h = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    # 16 hex chars = 64 bits is plenty for an opaque identity tag.
    return f"ws-{h[:16]}"


def _build_prompt(
    *,
    build_system_id: str,
    verifier_argv: tuple[str, ...],
    workspace_identity: str,
) -> str:
    """Verifier-context prompt. Carries no source content.

    workspace_identity is opacified at the function boundary
    (CLAUDE-AUTH-007 remediation): regardless of what the caller
    supplied, only a 16-hex sha256 digest is embedded in the prompt.
    """
    argv_str = " ".join(verifier_argv) if verifier_argv else ""
    opaque_id = _opacify_workspace_identity(workspace_identity)
    return (
        "A workspace under repair triage is described below. Provide a "
        "single short paragraph describing the most likely diagnostic "
        "class for a verifier failure on this workspace.\n\n"
        f"workspace identity (opaque): {opaque_id}\n"
        f"build system: {build_system_id}\n"
        f"verifier command (argv): {argv_str}\n\n"
        "Do NOT produce a patch. Do NOT reference any code. Output one "
        "short paragraph only."
    )


@dataclass(frozen=True)
class _GenResult:
    ok: bool
    timed_out: bool
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
                "User-Agent": "determinex-diagnose-with-verifier/1",
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


def diagnose(
    *,
    workspace_identity: str,
    healthcheck: RealLocalModelHealthcheckRecord | None,
    verifier_selection: BuildAdapterBackedVerifierSelectionRecord | None,
    opt_in: bool = False,
    endpoint: str = "http://127.0.0.1:11434",
    timeout_seconds: float = 30.0,
    transport: GenTransport | None = None,
) -> RealModelDiagnoseWithBuildVerifierRecord:
    if healthcheck is None or not healthcheck.is_passed:
        return _blocked(
            "REAL_MODEL_DIAGNOSE_BLOCKED_HEALTHCHECK_FAILED",
            workspace=workspace_identity,
            model_id=getattr(healthcheck, "model_id", "") if healthcheck else "",
            provider=getattr(healthcheck, "provider", "") if healthcheck else "",
            build_system_id=getattr(verifier_selection, "build_system_id", "")
            if verifier_selection
            else "",
            verifier_argv=tuple(getattr(verifier_selection, "verifier_command", ()))
            if verifier_selection
            else (),
            note="healthcheck missing or not passed",
        )

    if verifier_selection is None or not verifier_selection.is_selected:
        return _blocked(
            "REAL_MODEL_DIAGNOSE_BLOCKED_NO_VERIFIER",
            workspace=workspace_identity,
            model_id=healthcheck.model_id,
            provider=healthcheck.provider,
            build_system_id="",
            verifier_argv=(),
            note="verifier selection missing or not selected",
        )

    if not opt_in:
        return _blocked(
            "REAL_MODEL_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
            workspace=workspace_identity,
            model_id=healthcheck.model_id,
            provider=healthcheck.provider,
            build_system_id=verifier_selection.build_system_id,
            verifier_argv=verifier_selection.verifier_command,
            note="explicit opt_in=True is required",
        )

    if transport is None and not _host_is_local(endpoint):
        return _blocked(
            "REAL_MODEL_DIAGNOSE_BLOCKED_PROVIDER_ERROR",
            workspace=workspace_identity,
            model_id=healthcheck.model_id,
            provider=healthcheck.provider,
            build_system_id=verifier_selection.build_system_id,
            verifier_argv=verifier_selection.verifier_command,
            note="endpoint host not in local set",
        )

    prompt = _build_prompt(
        build_system_id=verifier_selection.build_system_id,
        verifier_argv=verifier_selection.verifier_command,
        workspace_identity=workspace_identity,
    )

    use_transport = transport or _default_transport
    start = time.monotonic()
    result = use_transport(endpoint, healthcheck.model_id, prompt, _SYSTEM, timeout_seconds)
    elapsed = int((time.monotonic() - start) * 1000)

    if result.timed_out:
        return _blocked(
            "REAL_MODEL_DIAGNOSE_BLOCKED_TIMEOUT",
            workspace=workspace_identity,
            model_id=healthcheck.model_id,
            provider=healthcheck.provider,
            build_system_id=verifier_selection.build_system_id,
            verifier_argv=verifier_selection.verifier_command,
            note=result.error or "timed out",
            elapsed_ms=elapsed,
        )

    if not result.ok:
        return _blocked(
            "REAL_MODEL_DIAGNOSE_BLOCKED_PROVIDER_ERROR",
            workspace=workspace_identity,
            model_id=healthcheck.model_id,
            provider=healthcheck.provider,
            build_system_id=verifier_selection.build_system_id,
            verifier_argv=verifier_selection.verifier_command,
            note=result.error or "provider error",
            elapsed_ms=elapsed,
        )

    advisory_summary = (result.text or "")[:_ADVISORY_CAP]

    return RealModelDiagnoseWithBuildVerifierRecord(
        decision="REAL_MODEL_DIAGNOSE_WITH_VERIFIER_WRITTEN",
        workspace=workspace_identity,
        model_id=healthcheck.model_id,
        provider=healthcheck.provider,
        build_system_id=verifier_selection.build_system_id,
        verifier_command=verifier_selection.verifier_command,
        advisory_summary=advisory_summary,
        response_chars=len(result.text or ""),
        elapsed_ms=elapsed,
        output_trusted=False,
        advisory_only=True,
        patch_generated=False,
        source_mutation_authorized=False,
        training_eligible=False,
        verifier_remains_source_of_truth=True,
        statuses_seen=(
            "REAL_MODEL_DIAGNOSE_WITH_VERIFIER_WRITTEN",
            "REAL_MODEL_DIAGNOSE_ADVISORY_ONLY",
        ),
        notes=(
            "advisory diagnosis written; verifier remains source of truth",
            "no source content was included in the prompt",
            "no patch generated; no source mutation; no training row",
        ),
    )


def _blocked(
    decision: str,
    *,
    workspace: str,
    model_id: str,
    provider: str,
    build_system_id: str,
    verifier_argv: tuple[str, ...],
    note: str,
    elapsed_ms: int = 0,
) -> RealModelDiagnoseWithBuildVerifierRecord:
    return RealModelDiagnoseWithBuildVerifierRecord(
        decision=decision,
        workspace=workspace,
        model_id=model_id,
        provider=provider,
        build_system_id=build_system_id,
        verifier_command=verifier_argv,
        advisory_summary="",
        response_chars=0,
        elapsed_ms=elapsed_ms,
        output_trusted=False,
        advisory_only=True,
        patch_generated=False,
        source_mutation_authorized=False,
        training_eligible=False,
        verifier_remains_source_of_truth=True,
        statuses_seen=(decision, "REAL_MODEL_DIAGNOSE_ADVISORY_ONLY"),
        notes=(note,),
    )


__all__ = [
    "diagnose",
    "REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_STATUS_TOKENS",
    "RealModelDiagnoseWithBuildVerifierRecord",
]

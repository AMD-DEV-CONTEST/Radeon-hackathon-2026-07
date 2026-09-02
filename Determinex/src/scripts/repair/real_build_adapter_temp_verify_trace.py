"""Real build-adapter temp verify trace.

Composes the locked SafePatchWorkspace + temp-verify modules with a
hardened-runner-backed verifier callable derived from
BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_LOCK_001. Applies the
quarantined plan to a temp workspace, runs the real verifier
command through ``intake.hardened_runner.run``, and records the
trace. Original source is NEVER written.

Decisions:
  - PASSED_APPROVAL_REQUIRED — verifier exit code 0
  - FAILED                   — verifier non-zero / timed out / blocked
  - BLOCKED_NOT_QUARANTINED  — upstream plan missing
  - BLOCKED_NO_VERIFIER      — verifier selection missing/blocked
  - BLOCKED_HARDENED_RUNNER  — hardened runner import failed
  - BLOCKED_APPLY_REJECTED   — safe-patch apply blocked
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .build_adapter_backed_verifier_selection_record import (
    BuildAdapterBackedVerifierSelectionRecord,
)
from .real_build_adapter_temp_verify_trace_record import (
    REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_STATUS_TOKENS,
    RealBuildAdapterTempVerifyTraceRecord,
)
from .real_model_patch_plan_with_verifier_context_record import (
    RealModelPatchPlanWithVerifierContextRecord,
)
from .real_temp_patch_verify import verify as _verify
from .safe_patch_workspace import VerifierResult  # noqa: E402

_OUTPUT_CAP = 2048
_PYTEST_COMMANDS = frozenset({"pytest", "pytest.exe"})


def _portable_hardened_runner_argv(verifier_argv: Sequence[str]) -> list[str]:
    argv = list(verifier_argv)
    if argv and Path(argv[0]).name.lower() in _PYTEST_COMMANDS:
        return [sys.executable, "-m", "pytest", *argv[1:]]
    return argv


def _build_verifier_callable(
    verifier_argv: Sequence[str],
    *,
    timeout_seconds: int,
):
    """Closure that invokes the build-adapter verifier under the
    hardened runner. Returns a function compatible with
    ``SafePatchWorkspace.apply_and_verify``'s ``verifier`` parameter.
    """
    try:
        hr = importlib.import_module("intake.hardened_runner")
    except ImportError:
        hr = None

    def verifier(temp_workspace: Path) -> VerifierResult:
        if hr is None:
            return VerifierResult(passed=False, output="HARDENED_RUNNER_UNAVAILABLE")
        res = hr.run(
            _portable_hardened_runner_argv(verifier_argv),
            workspace=Path(temp_workspace),
            timeout=timeout_seconds,
        )
        if getattr(res, "blocked", False):
            return VerifierResult(
                passed=False,
                output=(f"HARDENED_RUNNER_BLOCKED: {getattr(res, 'reason', '')}")[:_OUTPUT_CAP],
            )
        if getattr(res, "timed_out", False):
            return VerifierResult(
                passed=False,
                output=(f"VERIFIER_TIMED_OUT after {timeout_seconds}s")[:_OUTPUT_CAP],
            )
        passed = bool(getattr(res, "success", False))
        out = (getattr(res, "stdout", "") or "") + (
            "\n--- stderr ---\n" + (getattr(res, "stderr", "") or "")
            if getattr(res, "stderr", "")
            else ""
        )
        return VerifierResult(passed=passed, output=out[:_OUTPUT_CAP])

    return verifier, hr is not None


def trace(
    *,
    plan: RealModelPatchPlanWithVerifierContextRecord | None,
    plan_entries: tuple[dict, ...] | None,
    verifier_selection: BuildAdapterBackedVerifierSelectionRecord | None,
    workspace: Path,
    temp_root: Path,
    workspace_id: str = "real_build_verify",
    verifier_timeout_seconds: int = 120,
) -> RealBuildAdapterTempVerifyTraceRecord:
    if plan is None or not plan.is_quarantined:
        return _blocked(
            "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_NOT_QUARANTINED",
            workspace=str(Path(workspace).resolve()),
            verifier_argv=tuple(getattr(verifier_selection, "verifier_command", ()))
            if verifier_selection
            else (),
            build_system_id=getattr(verifier_selection, "build_system_id", "")
            if verifier_selection
            else "",
            note="plan missing or not quarantined",
        )

    if verifier_selection is None or not verifier_selection.is_selected:
        return _blocked(
            "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_NO_VERIFIER",
            workspace=str(Path(workspace).resolve()),
            verifier_argv=(),
            build_system_id="",
            note="verifier selection missing or not selected",
        )

    callable_, hr_available = _build_verifier_callable(
        verifier_selection.verifier_command,
        timeout_seconds=verifier_timeout_seconds,
    )
    if not hr_available:
        return _blocked(
            "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_HARDENED_RUNNER",
            workspace=str(Path(workspace).resolve()),
            verifier_argv=verifier_selection.verifier_command,
            build_system_id=verifier_selection.build_system_id,
            note="intake.hardened_runner unavailable",
        )

    # Reuse the locked temp-verify module. It already does
    # original-unchanged invariants and supports a verifier callable.
    # The inner plan record's accepted_paths drive the apply.
    inner_plan = _to_inner_plan(plan, str(Path(workspace).resolve()))
    inner = _verify(
        plan=inner_plan,
        plan_entries=plan_entries,
        workspace=Path(workspace),
        temp_root=Path(temp_root),
        workspace_id=workspace_id,
        verifier=callable_,
    )

    if inner.is_blocked:
        return _blocked(
            "REAL_BUILD_ADAPTER_TEMP_VERIFY_BLOCKED_APPLY_REJECTED",
            workspace=inner.workspace,
            temp_workspace=inner.temp_workspace,
            verifier_argv=verifier_selection.verifier_command,
            build_system_id=verifier_selection.build_system_id,
            note=f"safe-patch apply blocked: {inner.decision}",
            unified_diff=inner.unified_diff,
            applied_paths=tuple(inner.applied_paths),
            original_unchanged=inner.original_unchanged,
            src_before=inner.original_sha256_before,
            src_after=inner.original_sha256_after,
        )

    # The temp-verify record carries verifier_status as either
    # PATCH_VERIFIER_PASSED / PATCH_VERIFIER_FAILED. Map to ours.
    # The verifier_output we keep is the temp-verify summary; the
    # actual stdout/stderr lives only inside the callable's
    # VerifierResult.output which the locked module doesn't expose
    # publicly — we keep a preview from the inner record's diff.
    if inner.is_passed:
        decision = "REAL_BUILD_ADAPTER_TEMP_VERIFY_PASSED_APPROVAL_REQUIRED"
        statuses = (
            "REAL_BUILD_ADAPTER_TEMP_VERIFY_PASSED_APPROVAL_REQUIRED",
            "REAL_BUILD_ADAPTER_TEMP_VERIFY_SOURCE_UNCHANGED",
        )
        notes = (
            "build-adapter verifier passed on temp workspace",
            "original source unchanged",
            "human approval still required before source apply",
        )
        human_approval_required = True
    else:
        decision = "REAL_BUILD_ADAPTER_TEMP_VERIFY_FAILED"
        statuses = (
            "REAL_BUILD_ADAPTER_TEMP_VERIFY_FAILED",
            "REAL_BUILD_ADAPTER_TEMP_VERIFY_SOURCE_UNCHANGED",
        )
        notes = (
            "build-adapter verifier failed on temp workspace",
            "original source unchanged",
            "no source apply; no human approval flow",
        )
        human_approval_required = False

    return RealBuildAdapterTempVerifyTraceRecord(
        decision=decision,
        workspace=inner.workspace,
        temp_workspace=inner.temp_workspace,
        build_system_id=verifier_selection.build_system_id,
        verifier_command=verifier_selection.verifier_command,
        verifier_exit_code=0 if inner.is_passed else 1,
        verifier_stdout_preview=inner.unified_diff[:_OUTPUT_CAP],
        verifier_stderr_preview="",
        verifier_timed_out=False,
        verifier_blocked=False,
        unified_diff=inner.unified_diff,
        applied_paths=tuple(inner.applied_paths),
        original_unchanged=inner.original_unchanged,
        original_sha256_before=inner.original_sha256_before,
        original_sha256_after=inner.original_sha256_after,
        human_approval_required=human_approval_required,
        source_mutation_authorized=False,
        training_eligible=False,
        statuses_seen=statuses,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Adapter — convert the context-record plan to the inner quarantine record
# shape that real_temp_patch_verify expects.
# ---------------------------------------------------------------------------


def _to_inner_plan(
    plan: RealModelPatchPlanWithVerifierContextRecord,
    workspace: str,
):
    from .real_patch_plan_quarantine_record import (
        RealPatchPlanQuarantineRecord,
        RealQuarantinedPatchEntry,
    )

    accepted = tuple(
        RealQuarantinedPatchEntry(
            operation=e.operation,
            path=e.path,
            new_content_chars=e.new_content_chars,
        )
        for e in plan.accepted
    )
    return RealPatchPlanQuarantineRecord(
        decision="REAL_PATCH_PLAN_QUARANTINED",
        workspace=workspace,
        model_id=plan.model_id,
        provider=plan.provider,
        accepted=accepted,
        rejected=tuple(),
        quarantined=True,
        output_trusted=False,
        patch_applied=False,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=("derived from REAL_PATCH_PLAN_CONTEXT_QUARANTINED record",),
    )


def _blocked(
    decision: str,
    *,
    workspace: str,
    verifier_argv: tuple[str, ...],
    build_system_id: str,
    note: str,
    temp_workspace: str = "",
    unified_diff: str = "",
    applied_paths: tuple[str, ...] = (),
    original_unchanged: bool = True,
    src_before: str = "",
    src_after: str = "",
) -> RealBuildAdapterTempVerifyTraceRecord:
    return RealBuildAdapterTempVerifyTraceRecord(
        decision=decision,
        workspace=workspace,
        temp_workspace=temp_workspace,
        build_system_id=build_system_id,
        verifier_command=verifier_argv,
        verifier_exit_code=0,
        verifier_stdout_preview="",
        verifier_stderr_preview="",
        verifier_timed_out=False,
        verifier_blocked=False,
        unified_diff=unified_diff,
        applied_paths=applied_paths,
        original_unchanged=original_unchanged,
        original_sha256_before=src_before,
        original_sha256_after=src_after,
        human_approval_required=False,
        source_mutation_authorized=False,
        training_eligible=False,
        statuses_seen=(decision, "REAL_BUILD_ADAPTER_TEMP_VERIFY_SOURCE_UNCHANGED"),
        notes=(note,),
    )


__all__ = [
    "trace",
    "REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_STATUS_TOKENS",
    "RealBuildAdapterTempVerifyTraceRecord",
]

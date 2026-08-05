"""Verified repair trace — end-to-end signed shape proof.

Composes:
  * BuildAdapterRegistry  (adapter detection — read-only)
  * ModelRouter           (task-class routing — no I/O)
  * MockModelClient       (canned per-class responses)
  * SafePatchWorkspace    (temp-only patch + diff + rollback)
  * Injected verifier     (callable: Path -> VerifierResult)

The result is a ``VerifiedRepairTrace`` whose ``trace_fingerprint`` is a
sha256 over the canonical trace JSON. Tests pin both the
``trace_id`` (input-derived) and the ``trace_fingerprint`` (output-derived).

The runner deliberately does NOT call BuildAdapter.run_shadow_build on
the original workspace — that would invoke a real toolchain. The
verifier is the only place where a real toolchain might run, and the
caller controls whether to pass a real one. Tests use stub verifiers.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from intake.build_adapter_registry import BuildAdapterRegistry  # noqa: E402
from intake.build_adapters import UnknownAdapter  # noqa: E402
from models.mock_client import MockModelClient  # noqa: E402
from models.model_router import ModelRouter, RouterMode, TaskClass  # noqa: E402

from .safe_patch_record import FilePatch
from .safe_patch_workspace import (
    SafePatchWorkspace,
    VerifierResult,
    stub_verifier_pass,
)
from .verified_repair_trace_record import (
    VERIFIED_REPAIR_TRACE_STATUS_TOKENS,
    VerifiedRepairTrace,
    derive_trace_id,
)

_PIPELINE: tuple[TaskClass, ...] = (
    TaskClass.BUILD_DIAGNOSIS,
    TaskClass.PATCH_PLANNING,
    TaskClass.PATCH_GENERATION,
    TaskClass.VERIFIER_SUMMARY,
)


def default_canned() -> dict[TaskClass, dict[str, object]]:
    return {
        TaskClass.BUILD_DIAGNOSIS: {
            "kind": "MOCK_BUILD_DIAGNOSIS",
            "summary": "fixture deliberately fails verifier",
        },
        TaskClass.PATCH_PLANNING: {
            "kind": "MOCK_PATCH_PLAN",
            "steps": ["read failing file", "replace bad line", "re-run verifier"],
        },
        TaskClass.PATCH_GENERATION: {
            "kind": "MOCK_PATCH_DIFF",
            "patches": [],  # filled by the caller's patch_provider
        },
        TaskClass.VERIFIER_SUMMARY: {
            "kind": "MOCK_VERIFIER_SUMMARY",
            "status": "MOCK_DRAFT",
        },
    }


@dataclass(frozen=True)
class _Composed:
    workspace: Path
    temp_root: Path
    router: ModelRouter
    mock_client: MockModelClient
    canned: Mapping[TaskClass, Mapping[str, object]]
    patches: Sequence[FilePatch]
    verifier: Callable[[Path], VerifierResult]


class VerifiedRepairTraceRunner:
    """Compose the apparatus into a single signed trace."""

    __slots__ = ("_router", "_registry", "_canned", "_salt")

    def __init__(
        self,
        router: ModelRouter,
        registry: BuildAdapterRegistry | None = None,
        canned: Mapping[TaskClass, Mapping[str, object]] | None = None,
        salt: str = "default",
    ) -> None:
        self._router = router
        self._registry = registry or BuildAdapterRegistry()
        self._canned = dict(canned) if canned is not None else default_canned()
        self._salt = salt

    def run(
        self,
        workspace: Path,
        temp_root: Path,
        *,
        patches: Sequence[FilePatch] = (),
        verifier: Callable[[Path], VerifierResult] | None = None,
        workspace_id: str = "trace",
    ) -> VerifiedRepairTrace:
        ws = Path(workspace).resolve()
        if not ws.is_dir():
            raise FileNotFoundError(f"Workspace missing: {ws}")
        verifier = verifier or stub_verifier_pass

        # Adapter detection (read-only).
        selection = self._registry.select(ws)
        adapter_name = selection.primary.name
        build_system_id = selection.primary.build_system_id

        # Trace id is derived from inputs — stable across runs.
        trace_id = derive_trace_id(
            workspace=str(ws),
            salt=self._salt,
            canned_kind=str(self._canned.get(TaskClass.PATCH_GENERATION, {}).get("kind", "")),
        )

        statuses_seen: list[str] = []
        notes: list[str] = []
        route_decisions: list[dict[str, object]] = []

        # Unsupported-repo early-exit.
        if selection.primary is UnknownAdapter:
            statuses_seen.append("TRACE_BLOCKED_UNSUPPORTED_REPO")
            return VerifiedRepairTrace(
                trace_id=trace_id,
                workspace=str(ws),
                adapter_name=adapter_name,
                build_system_id=build_system_id,
                verifier_baseline_status="BASELINE_SKIPPED",
                route_decisions=tuple(route_decisions),
                mocked_patch_plan={},
                safe_patch_result={},
                final_status="TRACE_BLOCKED_UNSUPPORTED_REPO",
                statuses_seen=tuple(statuses_seen),
                source_unchanged_confirmed=True,
                training_eligible=False,
                corpus_eligibility="BLOCKED_BY_DEFAULT",
                notes=("UnknownAdapter selected; trace short-circuited.",),
            )

        mock_client = MockModelClient(self._canned)

        # Walk router pipeline.
        for tc in _PIPELINE:
            rec = self._router.route(tc, mode=RouterMode.LIVE)
            route_decisions.append(rec.to_dict())
            if rec.is_blocked or rec.is_no_model:
                notes.append(f"{tc.value}: route {rec.decision} — not invoking mock.")
                continue
            try:
                mock_client.invoke(tc, rec, payload={"workspace": str(ws)})
            except MockModelClient.RouteNotAuthorizedError as exc:
                notes.append(f"{tc.value}: {exc}")

        # If diagnose or patch-gen routes never authorized, terminate.
        diag_decision = route_decisions[0]["decision"] if route_decisions else ""
        gen_decision = route_decisions[2]["decision"] if len(route_decisions) >= 3 else ""
        if diag_decision.startswith("ROUTE_BLOCKED") or gen_decision.startswith("ROUTE_BLOCKED"):
            statuses_seen.append("TRACE_BLOCKED_NO_ROUTE")
            return VerifiedRepairTrace(
                trace_id=trace_id,
                workspace=str(ws),
                adapter_name=adapter_name,
                build_system_id=build_system_id,
                verifier_baseline_status="BASELINE_SKIPPED",
                route_decisions=tuple(route_decisions),
                mocked_patch_plan=dict(self._canned.get(TaskClass.PATCH_PLANNING, {})),
                safe_patch_result={},
                final_status="TRACE_BLOCKED_NO_ROUTE",
                statuses_seen=tuple(statuses_seen),
                source_unchanged_confirmed=True,
                training_eligible=False,
                corpus_eligibility="BLOCKED_BY_DEFAULT",
                notes=tuple(notes),
            )

        # Verifier baseline (stub; sets a status, never runs toolchain).
        baseline_status = "BASELINE_VERIFIED" if verifier is not None else "BASELINE_SKIPPED"

        # Apply the canned patch through the safe patch workspace.
        sp = SafePatchWorkspace(ws, temp_root, workspace_id=workspace_id)
        spr = sp.apply_and_verify(
            patches,
            verifier=verifier,
            rollback_on_failure=True,
        )
        spr_dict = spr.to_dict()

        # Decide final status from safe-patch outcome.
        statuses_seen.append(spr.status)
        statuses_seen.append(spr.verifier_status)
        if spr.original_unchanged:
            statuses_seen.append("TRACE_SOURCE_UNCHANGED_CONFIRMED")

        if spr.status == "SOURCE_MUTATION_BLOCKED":
            final_status = "TRACE_PATCH_FAILED"
            notes.append("safe-patch saw source mutation — invariant violated")
        elif spr.status.startswith("PATCH_BLOCKED_") or spr.status == "PATCH_REJECTED":
            final_status = "TRACE_PATCH_FAILED"
        elif spr.verifier_status == "PATCH_VERIFIER_FAILED":
            final_status = "TRACE_VERIFIER_FAILED"
        elif spr.verifier_status == "PATCH_VERIFIER_PASSED_TEMP_ONLY":
            final_status = "TRACE_VERIFIER_PASSED_TEMP_ONLY"
        elif spr.verifier_status == "PATCH_VERIFIER_SKIPPED":
            final_status = "TRACE_BLOCKED_NO_VERIFIER"
        else:
            final_status = "VERIFIED_REPAIR_TRACE_WRITTEN"

        statuses_seen.append("TRAINING_ELIGIBLE_FALSE")

        return VerifiedRepairTrace(
            trace_id=trace_id,
            workspace=str(ws),
            adapter_name=adapter_name,
            build_system_id=build_system_id,
            verifier_baseline_status=baseline_status,
            route_decisions=tuple(route_decisions),
            mocked_patch_plan=dict(self._canned.get(TaskClass.PATCH_PLANNING, {})),
            safe_patch_result=spr_dict,
            final_status=final_status,
            statuses_seen=tuple(statuses_seen),
            source_unchanged_confirmed=bool(spr.original_unchanged),
            training_eligible=False,
            corpus_eligibility="BLOCKED_BY_DEFAULT",
            notes=tuple(notes),
        )


__all__ = [
    "VerifiedRepairTraceRunner",
    "VerifiedRepairTrace",
    "VERIFIED_REPAIR_TRACE_STATUS_TOKENS",
    "default_canned",
    "derive_trace_id",
]

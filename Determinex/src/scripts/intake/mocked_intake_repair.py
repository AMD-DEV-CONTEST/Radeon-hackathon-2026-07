"""Mocked intake → diagnose → patch-plan loop.

Composes the model router with the build-adapter registry and a
``MockModelClient`` to prove the apparatus shape end-to-end *without*
ever calling a real model and *without* mutating user source.

The loop is pure and deterministic:

    workspace
      → BuildAdapterRegistry.select()       (read-only)
      → ModelRouter.route(BUILD_DIAGNOSIS, LIVE)
      → MockModelClient.invoke(BUILD_DIAGNOSIS)
      → ModelRouter.route(PATCH_PLANNING, LIVE)
      → MockModelClient.invoke(PATCH_PLANNING)
      → ModelRouter.route(PATCH_GENERATION, LIVE)
      → MockModelClient.invoke(PATCH_GENERATION)
      → ModelRouter.route(VERIFIER_SUMMARY, LIVE)
      → MockModelClient.invoke(VERIFIER_SUMMARY)
      → Trace assembled

No real toolchain is invoked. No source file is mutated. No corpus
row is written. Training eligibility is False on every path. The
trace carries the canonical status tokens the lock asserts against.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Path hygiene so this works when imported either as ``intake.*``
# (under scripts/) or directly from a test that has scripts/ on sys.path.
_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.mock_client import MockModelClient  # noqa: E402
from models.model_router import (  # noqa: E402
    ModelRouter,
    RouterMode,
    TaskClass,
)
from models.model_router_record import RouteRecord  # noqa: E402

from intake.build_adapter_registry import BuildAdapterRegistry, SelectionResult  # noqa: E402
from intake.build_adapters import UnknownAdapter  # noqa: E402

MOCKED_LOOP_STATUS_TOKENS = (
    "DIAGNOSE_MOCK_ROUTE_SELECTED",
    "PATCH_PLAN_MOCK_GENERATED",
    "PATCH_NOT_APPLIED_TO_SOURCE",
    "VERIFIER_RESULT_CAPTURED",
    "TRAINING_ELIGIBLE_FALSE",
    "EVIDENCE_WRITTEN",
    "UNSUPPORTED_REPO_BLOCKED",
    "NO_NETWORK_CALL_MADE",
    "NO_SUBPROCESS_CALL_MADE",
    "NO_SOURCE_MUTATION",
)

TASK_CLASS_PIPELINE: tuple[TaskClass, ...] = (
    TaskClass.BUILD_DIAGNOSIS,
    TaskClass.PATCH_PLANNING,
    TaskClass.PATCH_GENERATION,
    TaskClass.VERIFIER_SUMMARY,
)


@dataclass(frozen=True)
class MockedTraceStep:
    task_class: str
    route_decision: str
    selected_model_id: str
    execution_authorized: bool
    invoked_mock: bool
    mock_response_kind: str = ""
    skipped_reason: str = ""


@dataclass(frozen=True)
class MockedIntakeRepairTrace:
    workspace: str
    build_system_id: str
    adapter_name: str
    selection_multi_match: bool
    selection_note: str
    steps: tuple[MockedTraceStep, ...]
    diagnose_mock_route_selected: bool
    patch_plan_mock_generated: bool
    patch_not_applied_to_source: bool
    verifier_result_captured: bool
    training_eligible: bool
    evidence_written: bool
    terminus: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["steps"] = [asdict(s) for s in self.steps]
        d["notes"] = list(self.notes)
        return d


class _SourceMutationError(RuntimeError):
    """Raised if the loop ever tries to write to a fixture path."""


def _hash_workspace_tree(root: Path) -> dict[str, str]:
    import hashlib

    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            h = hashlib.sha256(p.read_bytes()).hexdigest()
        except (OSError, PermissionError):
            continue
        rel = p.relative_to(root).as_posix()
        out[rel] = h
    return out


class MockedIntakeRepairLoop:
    """Drive a fixture repo through the mocked pipeline.

    Construct with a router and a mock client. Call ``run(workspace)``
    to produce a ``MockedIntakeRepairTrace``.
    """

    __slots__ = ("_router", "_mock_client", "_registry")

    def __init__(
        self,
        router: ModelRouter,
        mock_client: MockModelClient,
        registry: BuildAdapterRegistry | None = None,
    ) -> None:
        self._router = router
        self._mock_client = mock_client
        self._registry = registry or BuildAdapterRegistry()

    def run(self, workspace: Path) -> MockedIntakeRepairTrace:
        ws = Path(workspace).resolve()
        if not ws.is_dir():
            raise FileNotFoundError(f"Workspace does not exist: {ws}")

        tree_before = _hash_workspace_tree(ws)

        notes: list[str] = []
        selection: SelectionResult = self._registry.select(ws)
        steps: list[MockedTraceStep] = []

        # Unsupported terminus: UnknownAdapter selected.
        if selection.primary is UnknownAdapter:
            for tc in TASK_CLASS_PIPELINE:
                steps.append(
                    MockedTraceStep(
                        task_class=tc.value,
                        route_decision="ROUTE_SKIPPED_UNSUPPORTED_REPO",
                        selected_model_id="",
                        execution_authorized=False,
                        invoked_mock=False,
                        skipped_reason="unsupported_repo",
                    )
                )
            notes.append("UnknownAdapter selected; no model routes consulted.")
            tree_after = _hash_workspace_tree(ws)
            patch_not_applied = tree_after == tree_before
            return MockedIntakeRepairTrace(
                workspace=str(ws),
                build_system_id=selection.primary.build_system_id,
                adapter_name=selection.primary.name,
                selection_multi_match=selection.multi_match,
                selection_note=selection.note or "",
                steps=tuple(steps),
                diagnose_mock_route_selected=False,
                patch_plan_mock_generated=False,
                patch_not_applied_to_source=patch_not_applied,
                verifier_result_captured=False,
                training_eligible=False,
                evidence_written=False,
                terminus="UNSUPPORTED_REPO",
                notes=tuple(notes),
            )

        # Supported terminus: walk the canonical pipeline.
        for tc in TASK_CLASS_PIPELINE:
            rec: RouteRecord = self._router.route(tc, mode=RouterMode.LIVE)
            invoked = False
            mock_kind = ""
            skipped_reason = ""
            if rec.is_blocked:
                skipped_reason = rec.decision
                notes.append(f"Task {tc.value} route blocked ({rec.decision}); mock not invoked.")
            elif rec.is_no_model:
                skipped_reason = "ROUTE_NO_MODEL_REQUIRED"
                notes.append(f"Task {tc.value} resolved to NO_MODEL; mock not invoked.")
            elif not rec.execution_authorized:
                # Defensive — should not happen given mode=LIVE on a clean
                # current-id route, but kept explicit for invariant clarity.
                skipped_reason = "NOT_AUTHORIZED"
                notes.append(f"Task {tc.value} not execution_authorized despite LIVE mode.")
            else:
                response = self._mock_client.invoke(
                    tc,
                    rec,
                    payload={"workspace": str(ws), "adapter": selection.primary.name},
                )
                mock_kind = str(response.get("kind") or response.get("status") or "MOCKED")
                invoked = True
            steps.append(
                MockedTraceStep(
                    task_class=tc.value,
                    route_decision=rec.decision,
                    selected_model_id=rec.selected_model_id,
                    execution_authorized=rec.execution_authorized,
                    invoked_mock=invoked,
                    mock_response_kind=mock_kind,
                    skipped_reason=skipped_reason,
                )
            )

        # Hard invariant: the loop must never have written to the workspace.
        tree_after = _hash_workspace_tree(ws)
        patch_not_applied = tree_after == tree_before
        if not patch_not_applied:
            raise _SourceMutationError(
                "MockedIntakeRepairLoop wrote to fixture workspace — invariant violated."
            )

        def _step(tc: TaskClass) -> MockedTraceStep | None:
            for s in steps:
                if s.task_class == tc.value:
                    return s
            return None

        diag_step = _step(TaskClass.BUILD_DIAGNOSIS)
        plan_step = _step(TaskClass.PATCH_PLANNING)
        verifier_step = _step(TaskClass.VERIFIER_SUMMARY)

        diagnose_mock_route_selected = bool(diag_step and diag_step.invoked_mock)
        patch_plan_mock_generated = bool(plan_step and plan_step.invoked_mock)
        verifier_result_captured = verifier_step is not None

        terminus = "MOCK_LOOP_COMPLETE"
        if not diagnose_mock_route_selected and not patch_plan_mock_generated:
            terminus = "ROUTER_BLOCKED"

        return MockedIntakeRepairTrace(
            workspace=str(ws),
            build_system_id=selection.primary.build_system_id,
            adapter_name=selection.primary.name,
            selection_multi_match=selection.multi_match,
            selection_note=selection.note or "",
            steps=tuple(steps),
            diagnose_mock_route_selected=diagnose_mock_route_selected,
            patch_plan_mock_generated=patch_plan_mock_generated,
            patch_not_applied_to_source=patch_not_applied,
            verifier_result_captured=verifier_result_captured,
            training_eligible=False,
            evidence_written=False,
            terminus=terminus,
            notes=tuple(notes),
        )


def default_mock_canned() -> dict[TaskClass, dict]:
    """A canonical canned-response mapping for the four pipeline classes.

    Tests may pass their own mapping. This one is structured so a trace
    written for any adapter looks identical in shape.
    """
    return {
        TaskClass.BUILD_DIAGNOSIS: {
            "kind": "MOCK_BUILD_DIAGNOSIS",
            "summary": "fixture deliberately fails to compile/typecheck",
            "primary_finding": "TYPE_MISMATCH or MISSING_IDENTIFIER",
        },
        TaskClass.PATCH_PLANNING: {
            "kind": "MOCK_PATCH_PLAN",
            "steps": ["read failing file", "replace bad line", "re-run verifier"],
        },
        TaskClass.PATCH_GENERATION: {
            "kind": "MOCK_PATCH_DIFF",
            "diff": "--- a/example\n+++ b/example\n@@ -1 +1 @@\n-bad\n+good\n",
            "applied_to_source": False,
        },
        TaskClass.VERIFIER_SUMMARY: {
            "kind": "MOCK_VERIFIER_SUMMARY",
            "status": "MOCK_PASS",
            "applied_to_temp_only": True,
        },
    }


__all__ = [
    "MockedIntakeRepairLoop",
    "MockedIntakeRepairTrace",
    "MockedTraceStep",
    "MOCKED_LOOP_STATUS_TOKENS",
    "TASK_CLASS_PIPELINE",
    "default_mock_canned",
]

"""Executable, non-production M5 topology fake for isolated contract tests.

This module intentionally does not compile a LangGraph, call a repository, or
write a checkpoint.  It exercises the frozen M5 topology with sanitized
contract projections so E6 can prove its safe routing decisions before the E5
handoff checkpoint authorizes production wiring.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import TerminalState
from app.experience_asset.domain.models import ContractModel

from .contracts import M5ContextProjectionV1, PrivacyReviewStatusV1
from .service import M5IsolatedService
from .workflow_contract import (
    M5_TOPOLOGY_HASH,
    M5_WORKFLOW_VERSION,
    M5GraphStateV1,
)


def _model_hash(model: ContractModel) -> str:
    """Hash a contract model without retaining its contents in graph state."""

    payload = model.model_dump(mode="json")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class M5IsolatedWorkflowOutcome:
    """Sanitized result of one in-memory topology traversal.

    ``persisted`` is always false: durable checkpoints, terminal records, and
    retries remain E5-to-E6 integration work.
    """

    terminal: TerminalState
    state: M5GraphStateV1
    trace: tuple[str, ...]
    persisted: bool = False


class M5IsolatedWorkflowFake:
    """Run only the allowed M5 policy slice against a contract projection."""

    def __init__(self, service: M5IsolatedService | None = None) -> None:
        self._service = service or M5IsolatedService()

    def run(
        self,
        context: M5ContextProjectionV1,
        *,
        command_id: UUID,
        privacy_failure_code: str | None = None,
    ) -> M5IsolatedWorkflowOutcome:
        """Traverse the non-mutating branch of the proposed M5 topology.

        The optional failure code is an injected test double for the bounded
        privacy-review worker. It never represents an unvalidated model error
        or a persisted retry record.
        """

        state = self._initial_state(context, command_id=command_id)
        trace = ["START"]
        stale_reason = context.stale_reason()
        if stale_reason is not None:
            trace.extend(("load_m5_context:not_ready_or_stale", "terminalize_m5_run:END"))
            return self._terminal(
                state,
                terminal=TerminalState.NEEDS_USER_INPUT,
                trace=trace,
                finding_codes=[stale_reason],
                message=(
                    "M5 input is not ready or is stale. Refresh the current version before "
                    "evaluation."
                ),
                retryable=False,
            )

        matrix = self._service.evaluate_routes(context)
        state = state.model_copy(
            update={
                "last_node": "evaluate_m5_routes",
                "selected_edge": "evaluate_m5_routes:evaluated",
                "route_matrix_hash": _model_hash(matrix),
            }
        )
        trace.extend(("load_m5_context:ready", "evaluate_m5_routes:evaluated"))

        if privacy_failure_code is not None:
            review = self._service.fail_privacy_review(
                context,
                failure_code=privacy_failure_code,
            )
            terminal = self._failure_terminal(privacy_failure_code)
            trace.extend(("review_m5_privacy:safe_failure", "terminalize_m5_run:END"))
            return self._terminal(
                state.model_copy(
                    update={
                        "privacy_proposal_attempts": 1,
                        "privacy_review_hash": review.review_hash,
                    }
                ),
                terminal=terminal,
                trace=trace,
                finding_codes=[review.failure_code or terminal.value],
                message="Privacy review did not complete. No external approval was granted.",
                retryable=terminal
                in {
                    TerminalState.MODEL_UNAVAILABLE,
                    TerminalState.MODEL_OOM,
                    TerminalState.TIMED_OUT,
                    TerminalState.STORAGE_ERROR,
                },
            )

        review = self._service.review_tagged_privacy(
            context,
            run_id=context.model_run_id or uuid4(),
        )
        state = state.model_copy(
            update={
                "last_node": "review_m5_privacy",
                "privacy_proposal_attempts": 1,
                "privacy_review_hash": review.review_hash,
            }
        )
        if review.status is not PrivacyReviewStatusV1.COMPLETE:
            raise AssertionError(
                "tagged privacy review must be complete without an injected failure"
            )
        open_findings = [
            str(finding.category)
            for finding in review.findings
            if not self._service.finding_is_resolved(finding.resolution)
        ]
        if open_findings:
            trace.extend(
                (
                    "review_m5_privacy:open_findings",
                    "wait_m5_privacy_resolution:pause",
                    "terminalize_m5_run:END",
                )
            )
            return self._terminal(
                state,
                terminal=TerminalState.NEEDS_USER_INPUT,
                trace=trace,
                finding_codes=sorted(set(open_findings)),
                message=("Privacy decisions are required before external routes can be approved."),
                retryable=False,
            )

        trace.extend(
            (
                "review_m5_privacy:resolved_or_empty",
                "wait_m5_approval:no_final_draft",
                "verify_m5_state:verified",
                "terminalize_m5_run:END",
            )
        )
        return self._terminal(
            state,
            terminal=TerminalState.SUCCEEDED,
            trace=trace,
            finding_codes=[],
            message="Route readiness and privacy review were verified.",
            retryable=False,
        )

    @staticmethod
    def _initial_state(
        context: M5ContextProjectionV1,
        *,
        command_id: UUID,
    ) -> M5GraphStateV1:
        return M5GraphStateV1(
            run_id=str(context.model_run_id or uuid4()),
            asset_id=str(context.asset_id),
            base_version_id=str(context.version_id),
            command_id=str(command_id),
            content_hash=context.content_hash,
            relation_projection_hash=context.relation.projection_hash,
            workflow_version=M5_WORKFLOW_VERSION,
            topology_hash=M5_TOPOLOGY_HASH,
            canonical_version_id=str(context.version_id),
        )

    @staticmethod
    def _failure_terminal(failure_code: str) -> TerminalState:
        try:
            candidate = TerminalState(failure_code)
        except ValueError:
            return TerminalState.INTERNAL_ERROR
        if candidate in {
            TerminalState.MODEL_UNAVAILABLE,
            TerminalState.MODEL_OOM,
            TerminalState.TIMED_OUT,
            TerminalState.INVALID_MODEL_OUTPUT,
            TerminalState.STORAGE_ERROR,
        }:
            return candidate
        return TerminalState.INTERNAL_ERROR

    @staticmethod
    def _terminal(
        state: M5GraphStateV1,
        *,
        terminal: TerminalState,
        trace: list[str],
        finding_codes: list[str],
        message: str,
        retryable: bool,
    ) -> M5IsolatedWorkflowOutcome:
        terminal_state = state.model_copy(
            update={
                "last_node": "terminalize_m5_run",
                "selected_edge": "terminalize_m5_run:END",
                "terminal_candidate": terminal.value,
                "finding_codes": finding_codes,
                "safe_message": message,
                "retryable": retryable,
            }
        )
        return M5IsolatedWorkflowOutcome(
            terminal=terminal,
            state=terminal_state,
            trace=tuple(trace),
        )


__all__ = ["M5IsolatedWorkflowFake", "M5IsolatedWorkflowOutcome"]

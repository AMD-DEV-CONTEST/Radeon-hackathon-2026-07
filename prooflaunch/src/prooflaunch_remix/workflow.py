from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Callable

from .adapters import AdapterBundle
from .contracts import (
    CampaignRequest,
    CampaignState,
    ReleaseApproval,
    ReleaseDecision,
    Stage,
)
from .files import atomic_write_text
from .ledger import EvidenceLedger


class WorkflowBlocked(RuntimeError):
    pass


class Supervisor:
    """Single owner of state, retries, evidence, and fail-closed release."""

    transitions = {
        Stage.EVIDENCE: Stage.PLAN,
        Stage.PLAN: Stage.CREATE,
        Stage.CREATE: Stage.AUDIT,
        Stage.AUDIT: Stage.REPAIR,
        Stage.REPAIR: Stage.AUDIT,
        Stage.AWAITING_RELEASE: Stage.DELIVER,
        Stage.DELIVER: Stage.DELIVER,
        Stage.BLOCKED: Stage.BLOCKED,
    }

    def __init__(
        self,
        adapters: AdapterBundle,
        *,
        event_sink: Callable[[str, CampaignState, dict[str, Any]], None] | None = None,
    ) -> None:
        self.adapters = adapters
        self.event_sink = event_sink

    @staticmethod
    def _request_digest(request: CampaignRequest) -> str:
        payload = json.dumps(
            request.__dict__,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def run(
        self,
        request: CampaignRequest,
        output_dir: str,
        run_id: str | None = None,
    ) -> CampaignState:
        """Run the legacy synchronous workflow through deterministic delivery.

        Production callers use ``prepare`` and ``release`` so a real reviewer
        owns the consequential decision.  This compatibility entry point keeps
        the original local-fixture contract used by the deterministic pipeline
        while recording an explicit, content-bound approval in the same ledger.
        """

        prepared = self.prepare(request, output_dir, run_id=run_id)
        if prepared.stage is not Stage.AWAITING_RELEASE:
            return prepared
        approval = ReleaseApproval.create(
            run_id=prepared.run_id,
            preview_digest=prepared.prepared_preview_digest or "",
            decision=ReleaseDecision.APPROVE,
            approver="legacy-synchronous-run",
            reason="Compatibility approval for the deterministic local run API.",
            issued_at="2026-01-01T00:00:00+00:00",
        )
        return self.release(output_dir, approval)

    def prepare(
        self,
        request: CampaignRequest,
        output_dir: str,
        run_id: str | None = None,
    ) -> CampaignState:
        """Build and audit a campaign, then pause for an explicit decision."""

        resolved_run_id = run_id or f"pl-{self._request_digest(request)}-{uuid.uuid4().hex[:8]}"
        state = CampaignState(
            run_id=resolved_run_id,
            request=request,
            output_dir=output_dir,
        )
        state.output_path.mkdir(parents=True, exist_ok=True)
        ledger_path = state.output_path / "evidence-ledger.jsonl"
        if ledger_path.exists():
            manifest_path = state.output_path / "campaign-state.json"
            if manifest_path.is_file():
                existing = self._load_state(manifest_path)
                if (
                    existing.run_id == state.run_id
                    and existing.request == request
                    and existing.output_path.resolve() == state.output_path.resolve()
                    and EvidenceLedger.verify(ledger_path)
                ):
                    return existing
            else:
                raise FileExistsError(
                    "incomplete prior prepare attempt detected; fail closed and use "
                    f"a new output directory: {ledger_path}"
                )
            raise FileExistsError(
                f"output directory already contains an evidence ledger: {ledger_path}"
            )
        ledger = EvidenceLedger(ledger_path, state.run_id)
        ledger.append(
            state.stage.value,
            "run_started",
            {"request_digest": self._request_digest(request)},
        )

        try:
            state.claims = self.adapters.evidence.extract(request)
            approved = [claim for claim in state.claims if claim.approved]
            if not approved:
                raise WorkflowBlocked("no source-bound approved claims")
            self._event(ledger, state, "claims_extracted", {"count": len(state.claims)})

            state.stage = Stage.PLAN
            state.briefs = self.adapters.director.plan(state)
            approved_ids = {claim.id for claim in approved}
            for brief in state.briefs:
                if not brief.claim_ids or not set(brief.claim_ids).issubset(approved_ids):
                    raise WorkflowBlocked(f"brief {brief.id} contains unapproved claims")
                pulse = self.adapters.audience.review(brief)
                state.audience_pulses.append(pulse)
            self._event(
                ledger,
                state,
                "briefs_planned",
                {
                    "count": len(state.briefs),
                    "emotion_matches": sum(p.matched for p in state.audience_pulses),
                },
            )

            state.stage = Stage.CREATE
            state.assets = self.adapters.studio.create(state)
            if not state.assets:
                raise WorkflowBlocked("studio returned no assets")
            self._event(ledger, state, "assets_created", {"count": len(state.assets)})

            while True:
                state.stage = Stage.AUDIT
                state.findings = self.adapters.auditor.audit(state)
                blockers = state.release_blockers
                self._event(
                    ledger,
                    state,
                    "release_audited",
                    {
                        "finding_count": len(state.findings),
                        "blocker_count": len(blockers),
                    },
                )
                if not blockers:
                    break
                if state.repair_count >= state.max_repairs:
                    raise WorkflowBlocked(
                        f"release audit still has {len(blockers)} blocker(s) after "
                        f"{state.repair_count} repair rounds"
                    )
                state.stage = Stage.REPAIR
                state.repair_count += 1
                state.assets = self.adapters.repairer.repair(state)
                self._event(
                    ledger,
                    state,
                    "assets_repaired",
                    {"round": state.repair_count, "asset_count": len(state.assets)},
                )

            state.stage = Stage.AWAITING_RELEASE
            state.prepared_preview_digest = state.preview_digest()
            self._event(
                ledger,
                state,
                "release_awaiting_approval",
                {
                    "preview_digest": state.prepared_preview_digest,
                    "claim_count": len(state.claims),
                    "brief_count": len(state.briefs),
                    "asset_count": len(state.assets),
                    "finding_count": len(state.findings),
                },
            )
        except WorkflowBlocked as exc:
            state.stage = Stage.BLOCKED
            state.blocked_reason = str(exc)
            self._event(ledger, state, "release_blocked", {"reason": str(exc)})
        except Exception as exc:
            state.stage = Stage.BLOCKED
            state.blocked_reason = f"adapter failure: {type(exc).__name__}: {exc}"
            self._event(
                ledger,
                state,
                "adapter_failure",
                {
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                },
            )

        self._persist_state(state)
        return state

    def release(
        self,
        output_dir: str | Path,
        approval: ReleaseApproval,
    ) -> CampaignState:
        """Apply one decision to a persisted, audited preview.

        The state is always reloaded from disk; callers cannot release a stale
        in-memory object. Validation failures raise ``WorkflowBlocked`` without
        changing the prepared state.
        """

        root = Path(output_dir).resolve()
        state = self._load_state(root / "campaign-state.json")
        if state.output_path.resolve() != root:
            raise WorkflowBlocked("campaign output directory does not match state")
        if state.stage is not Stage.AWAITING_RELEASE:
            raise WorkflowBlocked("release decision is only valid from awaiting_release")
        if state.blocked_reason is not None:
            raise WorkflowBlocked("awaiting campaign contains a blocked reason")
        if state.max_repairs > 2 or state.repair_count > state.max_repairs:
            raise WorkflowBlocked("repair bound integrity check failed")
        if state.release_blockers:
            raise WorkflowBlocked("release preview contains audit blockers")
        if not isinstance(approval, ReleaseApproval) or not approval.integrity_valid:
            raise WorkflowBlocked("release approval integrity check failed")

        ledger_path = root / "evidence-ledger.jsonl"
        events = self._verified_ledger_events(ledger_path, state.run_id)
        prepared_events = [
            event
            for event in events
            if event.get("kind") == "release_awaiting_approval"
            and event.get("stage") == Stage.AWAITING_RELEASE.value
        ]
        if len(prepared_events) != 1:
            raise WorkflowBlocked("ledger release-gate checkpoint is missing or ambiguous")
        prepared_event = prepared_events[0]
        ledger_digest = str(prepared_event.get("payload", {}).get("preview_digest", ""))
        current_digest = state.preview_digest()
        if not state.prepared_preview_digest:
            raise WorkflowBlocked("prepared preview digest is missing")
        if not (
            ledger_digest
            == state.prepared_preview_digest
            == current_digest
            == approval.preview_digest
        ):
            raise WorkflowBlocked("release preview changed after audit")
        if approval.run_id != state.run_id:
            raise WorkflowBlocked("release approval belongs to another run")

        ledger = self._resume_ledger(ledger_path, state.run_id, events)
        last_event = events[-1]
        last_kind = last_event.get("kind")
        recorded_approval = last_event.get("payload", {}).get("approval")
        approval_payload = approval.serializable()
        if last_kind == "campaign_delivered":
            approval_id = last_event.get("payload", {}).get("approval_id")
            prior = events[-2] if len(events) > 1 else {}
            if (
                approval_id != approval.approval_id
                or prior.get("kind") != "release_approved"
                or prior.get("payload", {}).get("approval") != approval_payload
            ):
                raise WorkflowBlocked("delivered ledger does not match this approval")
            exports = last_event.get("payload", {}).get("exports")
            if not isinstance(exports, list) or not exports or not all(
                isinstance(path, str) and Path(path).is_file() for path in exports
            ):
                raise WorkflowBlocked("delivered ledger references missing exports")
            state.release_approval = approval
            state.approvals = [approval_payload]
            state.exports = list(exports)
            state.stage = Stage.DELIVER
            self._persist_state(state)
            return state
        if last_kind == "release_approved":
            if recorded_approval != approval_payload:
                raise WorkflowBlocked("pending export belongs to another approval")
            if state.release_approval not in (None, approval):
                raise WorkflowBlocked("persisted approval conflicts with the ledger")
            if state.approvals not in ([], [approval_payload]) or state.exports:
                raise WorkflowBlocked("persisted release state conflicts with the ledger")
            state.release_approval = approval
            state.approvals = [approval_payload]
        elif last_kind == "release_awaiting_approval":
            if state.release_approval is not None or state.approvals or state.exports:
                raise WorkflowBlocked("campaign contains a decision absent from the ledger")
            state.release_approval = approval
            state.approvals.append(approval_payload)
        else:
            raise WorkflowBlocked("ledger is not paused at a releasable checkpoint")

        if approval.decision is ReleaseDecision.REJECT:
            if last_kind != "release_awaiting_approval":
                raise WorkflowBlocked("rejection cannot resume an approved release")
            state.stage = Stage.BLOCKED
            state.blocked_reason = f"release rejected by {approval.approver}: {approval.reason}"
            self._event(
                ledger,
                state,
                "release_rejected",
                {"approval": approval.serializable()},
            )
            self._persist_state(state)
            return state
        if approval.decision is not ReleaseDecision.APPROVE:
            raise WorkflowBlocked("unsupported release decision")

        if last_kind == "release_awaiting_approval":
            self._event(
                ledger,
                state,
                "release_approved",
                {"approval": approval_payload},
            )
            self._persist_state(state)
        try:
            state.exports = self.adapters.exporter.export(state)
            if not state.exports:
                raise WorkflowBlocked("exporter returned no deliverables")
            state.stage = Stage.DELIVER
            self._event(
                ledger,
                state,
                "campaign_delivered",
                {
                    "exports": state.exports,
                    "approval_id": approval.approval_id,
                    "preview_digest": approval.preview_digest,
                },
            )
        except Exception as exc:
            state.stage = Stage.BLOCKED
            state.blocked_reason = f"release failed closed: {type(exc).__name__}: {exc}"
            self._event(
                ledger,
                state,
                "release_failed",
                {
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                    "approval_id": approval.approval_id,
                },
            )
        self._persist_state(state)
        return state

    @staticmethod
    def _load_state(path: Path) -> CampaignState:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return CampaignState.from_serializable(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise WorkflowBlocked(f"campaign state reload failed: {exc}") from exc

    @staticmethod
    def _verified_ledger_events(path: Path, run_id: str) -> list[dict[str, Any]]:
        if not EvidenceLedger.verify(path):
            raise WorkflowBlocked("evidence ledger verification failed")
        try:
            events = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WorkflowBlocked("evidence ledger reload failed") from exc
        if not events or any(event.get("run_id") != run_id for event in events):
            raise WorkflowBlocked("evidence ledger run identity mismatch")
        return events

    @staticmethod
    def _resume_ledger(
        path: Path,
        run_id: str,
        events: list[dict[str, Any]],
    ) -> EvidenceLedger:
        ledger = EvidenceLedger(path, run_id)
        ledger.sequence = int(events[-1]["sequence"])
        ledger.previous_hash = str(events[-1]["event_hash"])
        return ledger

    @staticmethod
    def _persist_state(state: CampaignState) -> None:
        atomic_write_text(
            state.output_path / "campaign-state.json",
            json.dumps(state.serializable(), ensure_ascii=False, indent=2),
        )

    def _event(
        self,
        ledger: EvidenceLedger,
        state: CampaignState,
        kind: str,
        payload: dict[str, Any],
    ) -> None:
        ledger.append(state.stage.value, kind, payload)
        checkpoint = state.output_path / "campaign-checkpoint.json"
        atomic_write_text(
            checkpoint,
            json.dumps(state.serializable(), ensure_ascii=False, indent=2),
        )
        if self.event_sink is not None:
            self.event_sink(kind, state, dict(payload))

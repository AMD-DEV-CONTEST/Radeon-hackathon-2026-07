"""One explicit search: reserve, compare once, validate, settle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.experience_asset.application.readiness import ReadinessService
from app.experience_asset.discovery_fingerprint import compute_discovery_fingerprint
from app.experience_asset.domain.enums import DiscoveryFailureClass, DiscoveryOutcome
from app.experience_asset.domain.relation import (
    RELATION_CONTRACT_VERSION,
    DiscoveryAttemptV1,
    DiscoveryFingerprintV1,
    RoleGraphProjectionV1,
)
from app.experience_asset.inference import InvalidModelOutput, ModelClient, ModelRequest
from app.experience_asset.inference.budget import (
    describe_budget,
    prompt_budget_tokens,
    resolve_counter,
)
from app.experience_asset.inference.models import (
    ModelTimedOut,
    ModelUnavailable,
    RelationDiscoveryProposal,
)
from app.experience_asset.observability.retrieval_phase import (
    candidate_search_event,
    no_match_event,
)
from app.experience_asset.persistence import SQLiteAssetRepository
from app.experience_asset.persistence.relation_ledger import (
    LedgerConflictError,
    ReservationHeldError,
)

from .validation import ProposalRejected, validate_relation_proposal

DISCOVERY_PROMPT_VERSION = "e5-discovery-prompt/v1"
DISCOVERY_INTENT_VERSION = "e5-discovery-intent/v1"
PREFILTER_CONFIG_VERSION = "e5-prefilter/v1"
ROLE_CONTRACT_VERSION = "e5-role/v1"
DISCOVERY_MAX_OUTPUT_TOKENS = 1024
DISCOVERY_TIMEOUT_SECONDS = 120
DISCOVERY_MAX_ELIGIBLE = 8
"""A ceiling, not a target. The binding constraint is the token budget."""
DISCOVERY_SUMMARY_CHARS = 240

SYSTEM_POLICY = (
    "Compare the current role graph against every supplied historical graph in one "
    "pass and return at most one relation. Answer with identifiers only: the "
    "historical projection id, one of the six relation types, node mappings by id, "
    "and current-side boundary node ids. Never invent a node id, never return a "
    "label outside the six, and never propose a tool. If no comparison yields a "
    "complete package — a fixed relation type, a bilateral mapping, and a "
    "source-grounded current-side boundary — answer NO_MATCH. Abstaining is the "
    "correct answer far more often than a weak relation: a false relation spends "
    "the user's attention and redirects their later reasoning, while a missed one "
    "leaves their asset exactly as it was."
)


class DiscoveryUnavailable(RuntimeError):
    """Discovery cannot start; carries the outcome the caller should report."""

    def __init__(self, outcome: DiscoveryOutcome, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome


@dataclass(frozen=True)
class DiscoveryResult:
    outcome: DiscoveryOutcome
    attempt: DiscoveryAttemptV1
    candidate_id: UUID | None = None
    failure_class: DiscoveryFailureClass | None = None
    defect: str | None = None


class DiscoveryService:
    def __init__(
        self,
        repository: SQLiteAssetRepository,
        model_client: ModelClient,
    ) -> None:
        self.repository = repository
        self.model_client = model_client
        self.readiness = ReadinessService(repository)

    # ------------------------------------------------------------------

    def build_fingerprint(
        self,
        *,
        current: RoleGraphProjectionV1,
        eligible: list[RoleGraphProjectionV1],
        card_hash: str,
    ) -> DiscoveryFingerprintV1:
        model_id = str(getattr(self.model_client, "model_id", "deterministic-contract-fake"))
        return DiscoveryFingerprintV1(
            current_asset_id=current.asset_id,
            current_version_id=current.version_id,
            current_knowledge_card_hash=card_hash,
            current_projection_hash=current.projection_hash,
            eligible_projection_hashes=sorted(
                {item.projection_hash for item in eligible}
            ),
            model_identity=model_id,
            model_revision=str(getattr(self.model_client, "model_revision", "unpinned")),
            prompt_version=DISCOVERY_PROMPT_VERSION,
            role_contract_version=ROLE_CONTRACT_VERSION,
            validation_contract_version=RELATION_CONTRACT_VERSION,
            discovery_intent_version=DISCOVERY_INTENT_VERSION,
            inference_parameters_hash=hashlib.sha256(
                json.dumps(
                    {
                        "max_output_tokens": DISCOVERY_MAX_OUTPUT_TOKENS,
                        "timeout_seconds": DISCOVERY_TIMEOUT_SECONDS,
                        "temperature": 0,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            prefilter_config_version=PREFILTER_CONFIG_VERSION,
        )

    @staticmethod
    def compact_graph(projection: RoleGraphProjectionV1) -> dict:
        """Summary-role material only — never detailed evidence.

        The discovery decision does not need the details, and sending them would
        put historical content into a prompt before the user has agreed to look
        at that history at all.
        """
        return {
            "projection_id": str(projection.projection_id),
            "asset_id": str(projection.asset_id),
            "nodes": [
                {
                    "node_id": node.node_id,
                    "is_root": node.is_root,
                    "role": node.role.value if node.role else None,
                    "summary": node.summary_text[:DISCOVERY_SUMMARY_CHARS],
                }
                for node in projection.nodes
            ],
            "edges": [
                {
                    "root_node_id": edge.root_node_id,
                    "member_node_id": edge.member_node_id,
                    "edge_type": edge.edge_type.value,
                }
                for edge in projection.edges
            ],
        }

    # ------------------------------------------------------------------

    async def discover(self, asset_id: UUID) -> DiscoveryResult:
        """Run one explicit search for an already-gated ready card."""
        readiness = self.readiness.read(asset_id)
        if readiness is None:
            raise DiscoveryUnavailable(
                DiscoveryOutcome.NOT_READY, "this card is not ready"
            )
        current = self._current_projection(asset_id, readiness.knowledge_card_hash)
        eligible = self.repository.list_eligible_projections(current_asset_id=asset_id)
        eligible = self._fit_eligible(current, eligible[:DISCOVERY_MAX_ELIGIBLE])

        fingerprint = self.build_fingerprint(
            current=current,
            eligible=eligible or [current],
            card_hash=readiness.knowledge_card_hash,
        )
        digest = compute_discovery_fingerprint(fingerprint)

        cached = self.repository.read_settled_result(digest)
        if cached is not None:
            return DiscoveryResult(
                outcome=cached.outcome,
                attempt=cached,
                candidate_id=cached.candidate_id,
            )

        eligible_hash = hashlib.sha256(
            json.dumps(
                sorted(str(item.projection_id) for item in eligible), sort_keys=True
            ).encode()
        ).hexdigest()
        reservation = DiscoveryAttemptV1(
            attempt_id=uuid4(),
            run_id=uuid4(),
            asset_id=asset_id,
            discovery_fingerprint=digest,
            current_projection_id=current.projection_id,
            eligible_set_hash=eligible_hash,
            attempt_number=1,
            outcome=DiscoveryOutcome.RUNNING,
            lease_expires_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        try:
            attempt = self.repository.reserve_attempt(
                reservation, fingerprint=fingerprint
            )
        except ReservationHeldError as exc:
            raise DiscoveryUnavailable(
                DiscoveryOutcome.RUNNING, "a search for this exact question is running"
            ) from exc
        except LedgerConflictError as exc:
            raise DiscoveryUnavailable(DiscoveryOutcome.STALE, str(exc)) from exc

        if not eligible:
            # Nothing to compare against is a finished search, not a fault.
            return self._settle_no_match(attempt)
        return await self._compare(attempt, current, eligible, digest)

    # ------------------------------------------------------------------

    def _fit_eligible(
        self,
        current: RoleGraphProjectionV1,
        eligible: list[RoleGraphProjectionV1],
    ) -> list[RoleGraphProjectionV1]:
        """Take graphs in eligibility order until the budget is spent.

        Counting rather than taking a fixed number, because one projection in
        the frozen fixtures is nearly twice the size of another and the contract
        caps only the per-node text. A fixed count safe for the largest possible
        graph would waste most of the window on ordinary ones; a count sized for
        ordinary ones overflows on the large.

        Order is eligibility order, which is already deterministic. Dropping the
        tail rather than sampling keeps the same corpus producing the same
        prompt, which the discovery fingerprint depends on.
        """
        counter = resolve_counter()
        budget = prompt_budget_tokens(DISCOVERY_MAX_OUTPUT_TOKENS)
        spent = counter.count(SYSTEM_POLICY) + counter.count(
            json.dumps(self.compact_graph(current), ensure_ascii=False)
        )
        kept: list[RoleGraphProjectionV1] = []
        for projection in eligible:
            cost = counter.count(
                json.dumps(self.compact_graph(projection), ensure_ascii=False)
            )
            if spent + cost > budget:
                break
            spent += cost
            kept.append(projection)
        return kept

    async def _compare(
        self,
        attempt: DiscoveryAttemptV1,
        current: RoleGraphProjectionV1,
        eligible: list[RoleGraphProjectionV1],
        digest: str,
    ) -> DiscoveryResult:
        request = ModelRequest(
            run_id=attempt.run_id,
            stage="E5-relation-discovery",
            system_policy=SYSTEM_POLICY,
            canonical_context={
                "current_graph": self.compact_graph(current),
                "eligible_graphs": [self.compact_graph(item) for item in eligible],
                "relation_types": [
                    "SAME_THEME",
                    "METHOD_REUSE",
                    "COUNTEREXAMPLE",
                    "SUPPLEMENT",
                    "PREREQUISITE",
                    "FOLLOW_UP",
                ],
                "discovery_intent_version": DISCOVERY_INTENT_VERSION,
                "context_bound": {
                    **describe_budget(resolve_counter(), DISCOVERY_MAX_OUTPUT_TOKENS),
                    "eligible_supplied": len(eligible),
                    "eligible_ceiling": DISCOVERY_MAX_ELIGIBLE,
                },
            },
            source_excerpts=[],
            output_schema=RelationDiscoveryProposal.model_json_schema(),
            max_output_tokens=DISCOVERY_MAX_OUTPUT_TOKENS,
            timeout_seconds=DISCOVERY_TIMEOUT_SECONDS,
        )
        try:
            result = await self.model_client.generate_relation_discovery(request)
        except ModelUnavailable as exc:
            return self._settle_failure(
                attempt, DiscoveryFailureClass.MODEL_UNAVAILABLE, str(exc)
            )
        except ModelTimedOut as exc:
            return self._settle_failure(
                attempt, DiscoveryFailureClass.MODEL_TIMED_OUT, str(exc)
            )
        except InvalidModelOutput as exc:
            return self._settle_failure(
                attempt, DiscoveryFailureClass.MALFORMED_MODEL_OUTPUT, str(exc)
            )

        proposal = result.proposal
        if proposal.outcome == "NO_MATCH":
            return self._settle_no_match(attempt)

        try:
            candidate = validate_relation_proposal(
                proposal,
                current_projection=current,
                eligible={item.projection_id: item for item in eligible},
                discovery_fingerprint=digest,
            )
        except ProposalRejected as exc:
            # Never NO_MATCH. A rejected proposal supports no semantic claim,
            # and caching it as one would file a transport accident as a proven
            # absence.
            return self._settle_failure(
                attempt,
                DiscoveryFailureClass.RUNTIME_VALIDATION_REJECTED,
                str(exc),
                defect=exc.defect,
            )

        settled = attempt.model_copy(
            update={
                "outcome": DiscoveryOutcome.CANDIDATE,
                "candidate_id": candidate.candidate_id,
                "lease_expires_at": None,
                "finished_at": datetime.now(UTC),
            }
        )
        self.repository.record_retrieval_event(
            current.asset_id,
            candidate_search_event(
                related_asset_id=candidate.related_asset_id,
                eligible_count=len(eligible),
                discovery_fingerprint=digest,
            ),
        )
        try:
            # Bindings are rechecked inside this write. A projection invalidated
            # mid-validation must not yield a candidate that was valid only when
            # the comparison started.
            self.repository.settle_attempt(settled, candidate=candidate)
        except LedgerConflictError as exc:
            return self._settle_failure(
                attempt, DiscoveryFailureClass.STORAGE_CONFLICT, str(exc)
            )
        return DiscoveryResult(
            outcome=DiscoveryOutcome.CANDIDATE,
            attempt=settled,
            candidate_id=candidate.candidate_id,
        )

    def _settle_no_match(self, attempt: DiscoveryAttemptV1) -> DiscoveryResult:
        # A finished search that found nothing is still a search, and the trace
        # has to show it ran — otherwise an abstention is indistinguishable
        # from never having looked.
        self.repository.record_retrieval_event(
            attempt.asset_id,
            no_match_event(discovery_fingerprint=attempt.discovery_fingerprint),
        )
        settled = attempt.model_copy(
            update={
                "outcome": DiscoveryOutcome.NO_MATCH,
                "lease_expires_at": None,
                "finished_at": datetime.now(UTC),
            }
        )
        self.repository.settle_attempt(settled)
        return DiscoveryResult(outcome=DiscoveryOutcome.NO_MATCH, attempt=settled)

    def _settle_failure(
        self,
        attempt: DiscoveryAttemptV1,
        failure_class: DiscoveryFailureClass,
        message: str,
        *,
        defect: str | None = None,
    ) -> DiscoveryResult:
        settled = attempt.model_copy(
            update={
                "outcome": DiscoveryOutcome.TECHNICAL_FAILURE,
                "failure_class": failure_class,
                "lease_expires_at": None,
                "finished_at": datetime.now(UTC),
            }
        )
        self.repository.settle_attempt(settled)
        return DiscoveryResult(
            outcome=DiscoveryOutcome.TECHNICAL_FAILURE,
            attempt=settled,
            failure_class=failure_class,
            defect=defect,
        )

    def _current_projection(
        self, asset_id: UUID, card_hash: str
    ) -> RoleGraphProjectionV1:
        for projection in self.repository.list_eligible_projections(
            current_asset_id=uuid4()
        ):
            if (
                projection.asset_id == asset_id
                and projection.knowledge_card_hash == card_hash
            ):
                return projection
        raise DiscoveryUnavailable(
            DiscoveryOutcome.NOT_READY,
            "this card has no active projection to compare from",
        )

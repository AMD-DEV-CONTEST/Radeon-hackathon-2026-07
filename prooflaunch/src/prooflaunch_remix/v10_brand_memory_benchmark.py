from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Mapping, Sequence

from .v10_brand_memory import (
    BrandGenomeMemory,
    EntityKind,
    MemoryAtom,
    MemoryKind,
    MemorySource,
    PolicyVerdict,
)
from .v10_brand_memory_retrieval import (
    BrandMemoryRetriever,
    DenseEmbeddingIndex,
    HybridFusionConfig,
    MemoryRetrievalRequest,
    RetrievalMode,
)
from .v10_contracts import V10ContractError, stable_digest


NOW = "2026-07-31T12:00:00+00:00"
FUTURE = "2027-07-31T12:00:00+00:00"
PAST = "2026-07-30T12:00:00+00:00"
EARLIER = "2026-07-29T12:00:00+00:00"
TOPICS = ("claim", "logo", "audience")
TOPIC_VECTORS: Mapping[str, tuple[float, ...]] = {
    "claim": (1.0, 0.0, 0.0),
    "logo": (0.0, 1.0, 0.0),
    "audience": (0.0, 0.0, 1.0),
}


@dataclass(frozen=True)
class MemoryBenchmarkCase:
    case_id: str
    request: MemoryRetrievalRequest
    relevant_atom_ids: frozenset[str]
    stale_atom_ids: frozenset[str]
    transferable_atom_id: str
    schema: str = "ProofLaunchMemoryBenchmarkCaseV1"


@dataclass(frozen=True)
class MemoryModeMetrics:
    mode: RetrievalMode
    case_count: int
    retrieved_count: int
    relevant_retrieved_count: int
    retrieval_precision: float
    complete_case_rate: float
    stale_recall: float
    mean_context_saving_rate: float
    cross_campaign_transfer_rate: float
    brand_contamination_rate: float
    neural_inference_observed: bool
    schema: str = "ProofLaunchMemoryModeMetricsV1"


@dataclass(frozen=True)
class MemoryBenchmarkReport:
    benchmark_id: str
    memory_only: bool
    raw_input_available_to_answerer: bool
    case_count: int
    mode_metrics: tuple[MemoryModeMetrics, ...]
    case_result_digests: tuple[str, ...]
    fixture_rights_profile: str
    trained_model_metrics: None
    schema: str = "ProofLaunchMemoryBenchmarkReportV1"

    @property
    def content_sha256(self) -> str:
        return stable_digest(asdict(self))


@dataclass(frozen=True)
class StreamingMemoryReport:
    step_count: int
    source_revisions: tuple[str, ...]
    old_revision_excluded_after_update: bool
    expired_fact_excluded: bool
    conflict_winner_retrieved: bool
    conflict_loser_quarantined: bool
    rollback_restored_prior_revision: bool
    event_chain_valid: bool
    neural_inference_observed: bool
    schema: str = "ProofLaunchStreamingMemoryReportV1"

    @property
    def content_sha256(self) -> str:
        return stable_digest(asdict(self))


def _source(name: str, revision: str = "fixture-v1") -> MemorySource:
    return MemorySource(
        locator=f"project://memory-benchmark/{name}",
        revision=revision,
        sha256=stable_digest({"name": name, "revision": revision}),
        rights_profile="project_owned_synthetic",
        storage_allowed=True,
        training_allowed=True,
    )


def _atom(
    atom_id: str,
    *,
    brand_id: str,
    campaign_id: str,
    topic: str,
    kind: MemoryKind = MemoryKind.SEMANTIC,
    entity_kind: EntityKind | None = None,
    scope: str = "campaign",
    valid_until: str | None = FUTURE,
    created_at: str = NOW,
    version: int = 1,
    source_revision: str = "fixture-v1",
    utility: float = 0.9,
) -> MemoryAtom:
    return MemoryAtom(
        atom_id=atom_id,
        kind=kind,
        entity_kind=entity_kind,
        subject_id=f"{topic}:{brand_id}:{campaign_id}",
        payload={
            "brand_id": brand_id,
            "campaign_id": campaign_id,
            "scope": scope,
            "topic": topic,
            "visible_fact": f"{brand_id} {campaign_id} {topic} verified memory",
        },
        source=_source(atom_id, source_revision),
        created_at=created_at,
        valid_until=valid_until,
        confidence=0.96,
        utility=utility,
        approved=True,
        version=version,
        permanent=kind == MemoryKind.SYMBOLIC_RULE,
        token_cost=8 if kind != MemoryKind.SYMBOLIC_RULE else 5,
    )


def build_memory_benchmark_fixture(
) -> tuple[
    BrandGenomeMemory,
    DenseEmbeddingIndex,
    tuple[MemoryBenchmarkCase, ...],
]:
    graph = BrandGenomeMemory()
    vectors: dict[str, tuple[float, ...]] = {}
    cases: list[MemoryBenchmarkCase] = []
    for brand in ("alpha", "beta"):
        for topic in TOPICS:
            rule_id = f"{brand}:global:{topic}:rule"
            rule = _atom(
                rule_id,
                brand_id=brand,
                campaign_id="global",
                topic=topic,
                kind=MemoryKind.SYMBOLIC_RULE,
                scope="brand_global",
                valid_until=None,
            )
            if graph.store(rule).verdict != PolicyVerdict.ACCEPT:
                raise V10ContractError("benchmark rule admission failed")
            vectors[rule_id] = TOPIC_VECTORS[topic]

            stale_id = f"{brand}:stale:{topic}"
            stale = _atom(
                stale_id,
                brand_id=brand,
                campaign_id="old-campaign",
                topic=topic,
                valid_until=PAST,
                created_at=EARLIER,
            )
            if graph.store(stale).verdict != PolicyVerdict.ACCEPT:
                raise V10ContractError("benchmark stale admission failed")
            vectors[stale_id] = TOPIC_VECTORS[topic]

        for campaign in ("c1", "c2"):
            for topic in TOPICS:
                fact_id = f"{brand}:{campaign}:{topic}"
                fact = _atom(
                    fact_id,
                    brand_id=brand,
                    campaign_id=campaign,
                    topic=topic,
                )
                if graph.store(fact).verdict != PolicyVerdict.ACCEPT:
                    raise V10ContractError("benchmark fact admission failed")
                vectors[fact_id] = TOPIC_VECTORS[topic]
                request = MemoryRetrievalRequest(
                    request_id=f"query:{brand}:{campaign}:{topic}",
                    query_text=f"retrieve verified {topic} rule and campaign fact",
                    query_vector=TOPIC_VECTORS[topic],
                    now=NOW,
                    brand_id=brand,
                    campaign_id=campaign,
                    subject_ids=(fact.subject_id,),
                    max_context_tokens=16,
                    top_k=2,
                    minimum_confidence=0.9,
                )
                cases.append(
                    MemoryBenchmarkCase(
                        case_id=request.request_id,
                        request=request,
                        relevant_atom_ids=frozenset({fact_id, f"{brand}:global:{topic}:rule"}),
                        stale_atom_ids=frozenset({f"{brand}:stale:{topic}"}),
                        transferable_atom_id=f"{brand}:global:{topic}:rule",
                    )
                )
    index = DenseEmbeddingIndex(
        model_id="controlled-fixture-vector-provider",
        model_revision="project-owned-v1",
        vectors=vectors,
        observed_neural_inference=False,
    )
    return graph, index, tuple(cases)


def run_memory_only_benchmark() -> MemoryBenchmarkReport:
    graph, index, cases = build_memory_benchmark_fixture()
    retriever = BrandMemoryRetriever(graph, index, HybridFusionConfig())
    modes = (
        RetrievalMode.ENTITY_CENTRIC,
        RetrievalMode.SYMBOLIC,
        RetrievalMode.NEURAL,
        RetrievalMode.HYBRID,
        RetrievalMode.VECTOR_ONLY,
        RetrievalMode.NO_MEMORY,
    )
    atom_by_id = {atom.atom_id: atom for atom in graph.atoms}
    metrics: list[MemoryModeMetrics] = []
    result_digests: list[str] = []
    for mode in modes:
        retrieved_count = 0
        relevant_count = 0
        complete = 0
        stale_hits = 0
        stale_total = 0
        transfer_hits = 0
        contamination = 0
        saving = 0.0
        neural_observed = False
        for case in cases:
            result = retriever.retrieve(case.request, mode)
            result_digests.append(result.content_sha256)
            returned = set(result.atom_ids)
            retrieved_count += len(returned)
            relevant_count += len(returned & case.relevant_atom_ids)
            complete += case.relevant_atom_ids <= returned
            stale_hits += len(returned & case.stale_atom_ids)
            stale_total += len(case.stale_atom_ids)
            transfer_hits += case.transferable_atom_id in returned
            contamination += sum(
                str(atom_by_id[atom_id].payload.get("brand_id"))
                != case.request.brand_id
                for atom_id in returned
            )
            saving += result.context_saving_rate
            neural_observed = neural_observed or result.neural_inference_observed
        metrics.append(
            MemoryModeMetrics(
                mode=mode,
                case_count=len(cases),
                retrieved_count=retrieved_count,
                relevant_retrieved_count=relevant_count,
                retrieval_precision=(
                    relevant_count / retrieved_count if retrieved_count else 0.0
                ),
                complete_case_rate=complete / len(cases),
                stale_recall=stale_hits / stale_total,
                mean_context_saving_rate=saving / len(cases),
                cross_campaign_transfer_rate=transfer_hits / len(cases),
                brand_contamination_rate=(
                    contamination / retrieved_count if retrieved_count else 0.0
                ),
                neural_inference_observed=neural_observed,
            )
        )
    return MemoryBenchmarkReport(
        benchmark_id="brand-genome-memory-only-v1",
        memory_only=True,
        raw_input_available_to_answerer=False,
        case_count=len(cases),
        mode_metrics=tuple(metrics),
        case_result_digests=tuple(result_digests),
        fixture_rights_profile="project_owned_synthetic",
        trained_model_metrics=None,
    )


def run_streaming_benchmark() -> StreamingMemoryReport:
    graph = BrandGenomeMemory()
    old = _atom(
        "stream:alpha:c1:claim:v1",
        brand_id="alpha",
        campaign_id="c1",
        topic="claim",
        source_revision="stream-r1",
        utility=0.4,
    )
    graph.store(old)
    old_event = graph.events[-1].event_hash
    new = replace(
        old,
        atom_id="stream:alpha:c1:claim:v2",
        source=_source("stream-alpha-c1-claim-v2", "stream-r2"),
        payload={**old.payload, "visible_fact": "revised claim evidence"},
        version=2,
        utility=0.95,
    )
    if graph.update(old.atom_id, new).verdict != PolicyVerdict.ACCEPT:
        raise V10ContractError("streaming update failed")
    after_update = {atom.atom_id for atom in graph.retrieve(now=NOW)}

    expired = _atom(
        "stream:expired",
        brand_id="alpha",
        campaign_id="c1",
        topic="logo",
        valid_until=PAST,
        created_at=EARLIER,
    )
    graph.store(expired)
    after_expiry = {atom.atom_id for atom in graph.retrieve(now=NOW)}

    conflict_a = _atom(
        "stream:conflict:a",
        brand_id="alpha",
        campaign_id="c1",
        topic="audience",
    )
    conflict_b = replace(
        conflict_a,
        atom_id="stream:conflict:b",
        source=_source("stream-conflict-b", "stream-r2"),
        payload={**conflict_a.payload, "visible_fact": "conflicting audience"},
    )
    graph.store(conflict_a)
    graph.store(conflict_b)
    from .v10_brand_memory import EdgeKind, MemoryEdge

    graph.add_edge(
        MemoryEdge(
            edge_id="stream:conflict-edge",
            kind=EdgeKind.CONFLICT,
            source_atom_id=conflict_a.atom_id,
            target_atom_id=conflict_b.atom_id,
            source_locator="project://memory-benchmark/conflict",
            approved=True,
            created_at=NOW,
        )
    )
    graph.resolve_conflict(
        "stream:conflict-edge",
        winner_atom_id=conflict_b.atom_id,
        approval_id="approval:stream-conflict",
        occurred_at=NOW,
    )
    after_resolution = {atom.atom_id for atom in graph.retrieve(now=NOW)}
    chain_valid = graph.verify_event_chain()
    graph.rollback_to_event(old_event)
    after_rollback = {atom.atom_id for atom in graph.retrieve(now=NOW)}
    return StreamingMemoryReport(
        step_count=8,
        source_revisions=(old.source.revision, new.source.revision),
        old_revision_excluded_after_update=(
            old.atom_id not in after_update and new.atom_id in after_update
        ),
        expired_fact_excluded=expired.atom_id not in after_expiry,
        conflict_winner_retrieved=conflict_b.atom_id in after_resolution,
        conflict_loser_quarantined=conflict_a.atom_id not in after_resolution,
        rollback_restored_prior_revision=(
            old.atom_id in after_rollback and new.atom_id not in after_rollback
        ),
        event_chain_valid=chain_valid and graph.verify_event_chain(),
        neural_inference_observed=False,
    )


def build_memory_card(
    benchmark: MemoryBenchmarkReport,
    streaming: StreamingMemoryReport,
) -> dict[str, object]:
    by_mode = {item.mode: item for item in benchmark.mode_metrics}
    hybrid = by_mode[RetrievalMode.HYBRID]
    vector_only = by_mode[RetrievalMode.VECTOR_ONLY]
    no_memory = by_mode[RetrievalMode.NO_MEMORY]
    mechanical_gates = {
        "retrieval_precision_at_least_0_97": hybrid.retrieval_precision >= 0.97,
        "stale_recall_is_zero": hybrid.stale_recall == 0.0,
        "context_saving_is_positive": hybrid.mean_context_saving_rate > 0.0,
        "cross_campaign_transfer_is_complete": (
            hybrid.cross_campaign_transfer_rate == 1.0
        ),
        "brand_contamination_is_zero": hybrid.brand_contamination_rate == 0.0,
        "hybrid_complete_rate_beats_vector_only": (
            hybrid.complete_case_rate > vector_only.complete_case_rate
        ),
        "hybrid_complete_rate_beats_no_memory": (
            hybrid.complete_case_rate > no_memory.complete_case_rate
        ),
        "streaming_revision_expiry_conflict_and_rollback_pass": all(
            (
                streaming.old_revision_excluded_after_update,
                streaming.expired_fact_excluded,
                streaming.conflict_winner_retrieved,
                streaming.conflict_loser_quarantined,
                streaming.rollback_restored_prior_revision,
                streaming.event_chain_valid,
            )
        ),
    }
    card: dict[str, object] = {
        "schema": "ProofLaunchBrandGenomeMemoryCardV1",
        "frozen": True,
        "reuse_or_justify": {
            "sage_graph_memory": {
                "source": "https://arxiv.org/abs/2605.12061v1",
                "adopted": "typed evolving graph and writer/reader feedback boundary",
                "not_claimed": "no Graph Foundation Model was reproduced",
            },
            "taskmem": {
                "source": "https://arxiv.org/abs/2605.31075v1",
                "adopted": "memory-only and streaming evaluation isolation",
                "not_claimed": "no TaskMem RL adapter or reported benchmark gain was reproduced",
            },
            "hybrid_fusion_analysis": {
                "source": "https://arxiv.org/abs/2210.11934v2",
                "adopted": "frozen fusion parameters plus explicit vector-only ablation",
                "not_claimed": "controlled fixtures do not establish production-optimal weights",
            },
        },
        "benchmark_sha256": benchmark.content_sha256,
        "streaming_sha256": streaming.content_sha256,
        "mechanical_gates": mechanical_gates,
        "mechanical_v1_passed": all(mechanical_gates.values()),
        "trained_model_metrics": None,
        "observed_neural_embedding_inference": False,
        "human_4a_evaluation": None,
        "radeon_execution_receipt": None,
        "promotion_eligible": False,
        "promotion_blockers": [
            "dense vectors are controlled fixtures rather than observed neural embeddings",
            "no trained memorization policy or learned retriever checkpoint exists",
            "no external long-memory benchmark or human 4A evaluation has run",
            "no Radeon runtime receipt is bound to this memory card",
        ],
        "truth_boundary": (
            "Mechanical V1 gates apply only to the project-owned synthetic memory-only "
            "and streaming fixtures. They are not learned retrieval, TaskMem/SAGE "
            "reproduction, production reliability, human 4A, or Radeon evidence."
        ),
        "content_sha256": None,
    }
    card["content_sha256"] = stable_digest(
        {key: value for key, value in card.items() if key != "content_sha256"}
    )
    return card

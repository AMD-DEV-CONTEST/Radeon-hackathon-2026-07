"""Construction standards search tool registration."""

from buildguard.rag.advanced.corrective_retriever import AdvancedRagPipeline
from buildguard.rag.schemas import RagSearchInput, RagSearchOutput
from buildguard.rag.service import RagService
from buildguard.tools.base import ToolDefinition
from buildguard.tools.registry import ToolRegistry


def register_rag_tool(
    registry: ToolRegistry,
    service: RagService,
    *,
    advanced: AdvancedRagPipeline | None = None,
    timeout_seconds: float = 30,
) -> None:
    def search(raw: object) -> RagSearchOutput:
        request = RagSearchInput.model_validate(raw)
        if advanced is None:
            return service.search(request)
        result = advanced.retrieve(request)
        return RagSearchOutput(
            chunks=result.chunks,
            retrieved_chunk_ids=[item.chunk_id for item in result.chunks],
            reranked_chunk_ids=[item.chunk_id for item in result.chunks],
            scores=result.scores,
            citations=result.citations,
            evidence_status=(
                "sufficient" if result.evidence_status == "sufficient" else "insufficient_evidence"
            ),
            retrieval_latency_ms=result.retrieval_latency_ms,
            stage_latency_ms={
                "advanced_rag": result.retrieval_latency_ms,
                "retrieval_attempts": float(result.retrieval_attempts),
                "correction_count": float(result.correction_count),
            },
        )

    registry.register(
        ToolDefinition(
            name="search_construction_standards",
            description="Search indexed local construction standards with hybrid retrieval.",
            input_schema=RagSearchInput,
            output_schema=RagSearchOutput,
            permission="auto",
            read_only=True,
            timeout_seconds=timeout_seconds,
            category="rag",
            max_items=50,
        ),
        search,
    )

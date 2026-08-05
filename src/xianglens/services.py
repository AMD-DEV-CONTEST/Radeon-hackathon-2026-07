"""Application service container and dependency construction."""

from __future__ import annotations

from dataclasses import dataclass

from xianglens.agent.graph import GraphServices, build_graph
from xianglens.config import Settings
from xianglens.inference.llama_client import LlamaCppClient, ModelClient
from xianglens.storage.knowledge_store import (
    KnowledgeStore,
    MilvusKnowledgeStore,
    create_embedder,
)
from xianglens.storage.sqlite_store import SQLiteStore
from xianglens.tools.image_tools import ImageInspector
from xianglens.tools.private_lens import PrivateLensTool


@dataclass(slots=True)
class AppServices:
    settings: Settings
    model: ModelClient
    database: SQLiteStore
    knowledge: KnowledgeStore
    image_inspector: ImageInspector
    private_lens: PrivateLensTool | None
    graph: object


def create_services(settings: Settings) -> AppServices:
    settings.ensure_runtime_directories()
    database = SQLiteStore(settings.sqlite_path)
    database.initialize()
    embedder = create_embedder(
        settings.embedding_provider,
        settings.embedding_model,
        settings.embedding_dimension,
    )
    knowledge = MilvusKnowledgeStore(settings.milvus_uri, embedder)
    image_inspector = ImageInspector(settings.max_upload_bytes, settings.max_image_pixels)
    private_lens = None
    if settings.private_lens_enabled:
        if settings.private_lens_path is None:
            raise RuntimeError(
                "XIANG_PRIVATE_LENS_PATH is required when XIANG_PRIVATE_LENS_ENABLED=true"
            )
        private_lens = PrivateLensTool(
            name=settings.private_lens_name,
            source_path=settings.private_lens_path,
        )
    model = LlamaCppClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        enable_thinking=settings.llm_enable_thinking,
        reasoning_budget=settings.llm_reasoning_budget,
    )
    graph = build_graph(
        GraphServices(
            model=model,
            knowledge=knowledge,
            database=database,
            image_inspector=image_inspector,
            private_lens=private_lens,
            rag_top_k=settings.rag_top_k,
        )
    )
    return AppServices(
        settings=settings,
        model=model,
        database=database,
        knowledge=knowledge,
        image_inspector=image_inspector,
        private_lens=private_lens,
        graph=graph,
    )

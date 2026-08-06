from __future__ import annotations

import importlib

from agent_factory.knowledge_system.schema import KnowledgeRuntimeConfig
from agent_factory.models import get_embedding_model, get_embedding_model_settings


def build_knowledge_store_index(config: KnowledgeRuntimeConfig):
    embeddings = get_embedding_model()
    settings = get_embedding_model_settings()
    if embeddings is None or settings.dims is None:
        return None
    index_config_cls = importlib.import_module("langgraph.store.base").IndexConfig
    return index_config_cls(
        embed=embeddings,
        dims=settings.dims,
        fields=list(config.rag_store.index_fields or ["content"]),
    )

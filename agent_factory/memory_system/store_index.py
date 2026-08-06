from __future__ import annotations

import importlib

from agent_factory.memory_system.config import MemorySystemConfig
from agent_factory.models import get_embedding_model, get_embedding_model_settings


def build_memory_store_index(config: MemorySystemConfig):
    if not config.semantic_index.enabled:
        return None
    embeddings = get_embedding_model()
    settings = get_embedding_model_settings()
    if embeddings is None or settings.dims is None:
        return None
    index_config_cls = importlib.import_module("langgraph.store.base").IndexConfig
    return index_config_cls(
        embed=embeddings,
        dims=settings.dims,
        fields=list(config.semantic_index.fields or ["$"]),
    )

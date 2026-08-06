from __future__ import annotations

from dataclasses import dataclass

from app.agents.memory import MemoryAgent
from app.agents.orchestrator import AgentOrchestrator
from app.agents.planner import PlannerAgent
from app.agents.research import ResearchAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.tool import ToolAgent
from app.config import config
from app.services.embeddings import LocalEmbeddingEngine
from app.services.ollama_client import OllamaClient
from app.services.rag import ChromaRAGService
from app.services.storage import SQLiteStorage


@dataclass(slots=True)
class AppServices:
    storage: SQLiteStorage
    embeddings: LocalEmbeddingEngine
    rag: ChromaRAGService
    ollama: OllamaClient
    orchestrator: AgentOrchestrator


_services: AppServices | None = None


def get_services() -> AppServices:
    global _services
    if _services is None:
        config.ensure_directories()
        storage = SQLiteStorage(config.db_path)
        embeddings = LocalEmbeddingEngine(dimensions=config.embedding_dimensions)
        rag = ChromaRAGService(config, storage, embeddings)
        ollama = OllamaClient(config)
        orchestrator = AgentOrchestrator(
            storage=storage,
            ollama=ollama,
            planner=PlannerAgent(ollama),
            research=ResearchAgent(rag),
            memory=MemoryAgent(storage),
            tools=ToolAgent(storage),
            reviewer=ReviewerAgent(ollama),
        )
        _services = AppServices(
            storage=storage,
            embeddings=embeddings,
            rag=rag,
            ollama=ollama,
            orchestrator=orchestrator,
        )
    return _services

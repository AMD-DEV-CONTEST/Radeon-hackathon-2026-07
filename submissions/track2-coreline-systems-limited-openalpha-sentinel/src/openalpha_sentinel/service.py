from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent import StrategyAgent
from .config import Settings
from .database import Database
from .embeddings import HashEmbedding
from .llm import LocalModelRouter
from .permissions import PermissionGate
from .pipeline import IngestionPipeline
from .retrieval import HybridRetriever
from .schemas import ChatAnswer, DashboardStats, PipelineResult
from .sources import GitHubSource, RSSSource, SnapshotSource


class OpenAlphaService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.settings.ensure_directories()
        self.database = Database(self.settings)
        self.database.initialize()
        self.embedding = HashEmbedding()
        self.retriever = HybridRetriever(self.database, self.embedding)
        self.models = LocalModelRouter(self.settings)
        self.agent = StrategyAgent(self.database, self.retriever, self.models)
        self.pipeline = IngestionPipeline(self.settings, self.database, embedding=self.embedding)
        self.permissions = PermissionGate(self.settings, self.database)

    def dashboard(self) -> DashboardStats:
        return DashboardStats(
            **self.database.dashboard(),
            offline=self.permissions.is_offline(),
            llm_backend=self.models.name,
        )

    def seed_demo(self, fixture_dir: Path | None = None) -> PipelineResult:
        path = fixture_dir or Path(__file__).resolve().parents[2] / "fixtures" / "strategies"
        artifacts = SnapshotSource().load_directory(path)
        return self.pipeline.process(artifacts, kind="demo_seed")

    def discover_github(self, query: str, limit: int = 5) -> PipelineResult:
        self.permissions.check_url("https://api.github.com/search/repositories")
        source = GitHubSource(
            token=self.settings.github_token,
            user_agent=self.settings.user_agent,
            url_validator=self.permissions.check_url,
        )
        try:
            artifacts = source.search(query, limit=limit)
        finally:
            source.close()
        return self.pipeline.process(artifacts, kind="github_discovery")

    def ingest_rss(self, url: str) -> PipelineResult:
        self.permissions.check_url(url, allow_explicit_feed=True)
        source = RSSSource(
            user_agent=self.settings.user_agent,
            url_validator=self.permissions.check_url,
        )
        try:
            artifacts = source.fetch(url)
        finally:
            source.close()
        return self.pipeline.process(artifacts, kind="rss_ingestion")

    def ask(self, question: str, session_id: str | None = None) -> ChatAnswer:
        return self.agent.ask(question, session_id)

    def create_watch_rule(
        self, name: str, kind: str, config: dict[str, Any], interval_minutes: int
    ) -> dict[str, Any]:
        if kind not in {"github", "rss"}:
            raise ValueError("watch rule kind must be github or rss")
        if interval_minutes < 5:
            raise ValueError("interval_minutes must be at least 5")
        return self.database.create_watch_rule(name, kind, config, interval_minutes)

    def run_watch_rule(self, rule: dict[str, Any]) -> PipelineResult:
        if rule["kind"] == "github":
            result = self.discover_github(
                str(rule["config"].get("query", "algorithmic trading strategy")),
                int(rule["config"].get("limit", 5)),
            )
        elif rule["kind"] == "rss":
            result = self.ingest_rss(str(rule["config"]["url"]))
        else:
            raise ValueError(f"Unsupported watch rule: {rule['kind']}")
        self.database.mark_watch_run(rule["id"], int(rule["interval_minutes"]))
        return result

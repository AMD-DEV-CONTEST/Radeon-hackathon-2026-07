from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from openalpha_sentinel.chunking import chunk_document
from openalpha_sentinel.config import Settings
from openalpha_sentinel.database import Database
from openalpha_sentinel.extractor import RuleBasedExtractor
from openalpha_sentinel.permissions import PermissionGate
from openalpha_sentinel.pipeline import IngestionPipeline
from openalpha_sentinel.retrieval import HybridRetriever
from openalpha_sentinel.schemas import FetchedArtifact, PipelineResult, SourceDocument
from openalpha_sentinel.service import OpenAlphaService
from openalpha_sentinel.sources import SnapshotSource
from openalpha_sentinel.utils import new_id
from openalpha_sentinel.worker import CollectorWorker


MEAN_REVERSION_TEXT = """# Daily Equity Mean Reversion

This mean reversion strategy trades US equities on a daily timeframe. It buys
oversold stocks when the RSI is below 30 and the z-score is below -2, then exits
when the z-score returns to zero.

The backtest period is 2018 through 2025. Results include a 0.10% commission,
transaction costs, and slippage. The research code is released under the MIT
License. These figures are source-author claims and require independent review.
"""

MOMENTUM_TEXT = """# Crypto Trend Momentum

This momentum and trend-following strategy trades Bitcoin and Ethereum on a
weekly timeframe. It enters when the moving average confirms a breakout and
volume is rising.

The backtest covers 2019 through 2025 and includes commission and slippage.
The code is released under the Apache-2.0 License.
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "runtime"
    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "openalpha.db",
        offline=False,
        allowed_domains=("github.com",),
        llm_backend="heuristic",
    )


@pytest.fixture
def database(settings: Settings) -> Database:
    database = Database(settings)
    database.initialize()
    return database


def _artifact(
    *,
    name: str = "daily-equity-mean-reversion",
    title: str = "Daily Equity Mean Reversion",
    text: str = MEAN_REVERSION_TEXT,
    revision: str = "a" * 40,
    license_spdx: str = "MIT",
) -> FetchedArtifact:
    canonical_url = f"https://github.com/openalpha/{name}"
    immutable_url = (
        f"https://github.com/openalpha/{name}/blob/{revision}/README.md"
    )
    return FetchedArtifact(
        kind="github_repository",
        canonical_url=canonical_url,
        external_id=f"github:{name}",
        title=title,
        author="openalpha",
        revision_key=revision,
        immutable_url=immutable_url,
        license_spdx=license_spdx,
        documents=[
            SourceDocument(
                path="README.md",
                title=title,
                text=text,
                source_url=immutable_url,
            )
        ],
        metadata={"fixture": True},
    )


def _momentum_artifact() -> FetchedArtifact:
    return _artifact(
        name="crypto-trend-momentum",
        title="Crypto Trend Momentum",
        text=MOMENTUM_TEXT,
        revision="b" * 40,
        license_spdx="Apache-2.0",
    )


def _pipeline(settings: Settings, database: Database) -> IngestionPipeline:
    return IngestionPipeline(settings, database)


def _extract_card(text: str, *, title: str = "Extractor Regression"):
    artifact = _artifact(name="extractor-regression", title=title, text=text)
    chunks = chunk_document(text, "doc-extractor", "rev-extractor")
    return RuleBasedExtractor().extract(
        artifact,
        "source-extractor",
        "rev-extractor",
        chunks,
    )


def test_unseeded_ids_are_unique_under_burst_creation():
    values = {new_id("job") for _ in range(200)}

    assert len(values) == 200


def test_database_initialization_is_repeatable_and_creates_fts5(
    database: Database,
):
    database.initialize()

    with database.connect() as connection:
        table_names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]

    assert {
        "sources",
        "revisions",
        "documents",
        "chunks",
        "chunk_fts",
        "strategy_cards",
        "evidence",
        "embeddings",
        "watch_rules",
    }.issubset(table_names)
    assert foreign_keys == 1


def test_chunk_document_applies_source_line_offset():
    chunks = chunk_document(
        "first source line\nsecond source line",
        "doc-offset",
        "rev-offset",
        line_offset=7,
    )

    assert [(chunk.start_line, chunk.end_line) for chunk in chunks] == [(8, 9)]


def test_same_artifact_is_idempotent_across_pipeline_runs(
    settings: Settings, database: Database
):
    pipeline = _pipeline(settings, database)
    artifact = _artifact()

    first = pipeline.process([artifact], kind="test_first")
    second = pipeline.process([artifact], kind="test_second")

    assert first.state == "COMPLETED"
    assert first.processed == 1
    assert first.created_cards == 1
    assert first.skipped_revisions == 0
    assert second.state == "COMPLETED"
    assert second.processed == 1
    assert second.created_cards == 0
    assert second.skipped_revisions == 1

    dashboard = database.dashboard()
    assert dashboard["sources"] == 1
    assert dashboard["revisions"] == 1
    assert dashboard["strategies"] == 1
    assert dashboard["notifications"] == 1
    assert len(database.list_jobs()) == 2
    assert len(database.search_fts('"mean"')) == 1

    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM chunks").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM chunk_fts").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 1


def test_idempotency_survives_service_restart(settings: Settings):
    first_service = OpenAlphaService(settings)
    first = first_service.pipeline.process([_artifact()], kind="before_restart")

    restarted_service = OpenAlphaService(settings)
    second = restarted_service.pipeline.process([_artifact()], kind="after_restart")

    assert first.created_cards == 1
    assert second.created_cards == 0
    assert second.skipped_revisions == 1
    assert restarted_service.database.dashboard()["strategies"] == 1


def test_new_revision_preserves_prior_card(settings: Settings, database: Database):
    pipeline = _pipeline(settings, database)
    first = _artifact()
    updated = _artifact(
        text=MEAN_REVERSION_TEXT + "\nThe revision adds a weekly review note.\n",
        revision="c" * 40,
    )

    result = pipeline.process([first, updated], kind="revision_history")

    assert result.created_cards == 2
    assert database.dashboard()["sources"] == 1
    assert database.dashboard()["revisions"] == 2
    assert database.dashboard()["strategies"] == 2
    assert {card["revision_key"] for card in database.list_cards()} == {"a" * 40, "c" * 40}


def test_partial_source_failure_preserves_successful_results(settings: Settings, database: Database):
    invalid = _artifact(name="empty-source").model_copy(update={"documents": []})

    result = _pipeline(settings, database).process([_artifact(), invalid], kind="partial_failure")

    assert result.state == "PARTIAL_SUCCESS"
    assert result.created_cards == 1
    assert len(result.errors) == 1
    assert database.dashboard()["strategies"] == 1


def test_extractor_keeps_missing_cost_information_unknown():
    card = _extract_card(
        """# Daily Research Note

This daily mean reversion strategy trades equities using an RSI entry signal.
The source-author backtest covers 2020 through 2025.
"""
    )

    assert card.cost_disclosure == "unknown"
    assert "transaction_cost_not_disclosed" not in card.risk_flags
    assert all(item.field != "cost_disclosure" for item in card.evidence)


def test_extractor_preserves_explicit_cost_omission():
    card = _extract_card(
        """# Daily Research Note

This daily strategy trades equities. The note does not disclose transaction
costs for its 2020 through 2025 backtest.
"""
    )

    assert card.cost_disclosure == "not_disclosed"
    assert "transaction_cost_not_disclosed" in card.risk_flags
    assert any(item.field == "cost_disclosure" for item in card.evidence)


@pytest.mark.parametrize("text", ["", " \n\t ", "#\n---\n> *"])
def test_extractor_rejects_sources_without_usable_text(text: str):
    with pytest.raises(ValueError, match="usable text"):
        _extract_card(text)


def test_extractor_does_not_match_keywords_inside_other_terms():
    card = _extract_card(
        """# Terminology Boundary Notes

Reversion research from Stockholm discusses optionality in a future-proof
software design without naming an investable market or trading signal.
"""
    )

    assert card.strategy_type == "unknown"
    assert card.markets == []
    assert card.signals == []


def test_late_pipeline_failure_removes_partial_revision_and_can_retry(
    settings: Settings, database: Database, monkeypatch: pytest.MonkeyPatch
):
    pipeline = _pipeline(settings, database)

    def fail_embedding(_: list[str]) -> list[list[float]]:
        raise RuntimeError("simulated embedding failure")

    monkeypatch.setattr(pipeline.embedding, "embed_many", fail_embedding)
    failed = pipeline.process([_artifact()], kind="late_failure")

    assert failed.state == "FAILED"
    assert failed.created_cards == 0
    assert "simulated embedding failure" in failed.errors[0]
    with database.connect() as connection:
        for table in (
            "revisions",
            "documents",
            "chunks",
            "chunk_fts",
            "strategy_cards",
            "evidence",
            "embeddings",
            "notifications",
        ):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0

    retried = _pipeline(settings, database).process([_artifact()], kind="late_failure_retry")

    assert retried.state == "COMPLETED"
    assert retried.created_cards == 1
    assert retried.skipped_revisions == 0
    assert database.dashboard()["revisions"] == 1
    assert database.dashboard()["strategies"] == 1
    assert len(database.search_fts('"mean"')) == 1


def test_strategy_card_fields_and_field_level_evidence(
    settings: Settings, database: Database
):
    result = _pipeline(settings, database).process([_artifact()], kind="card_test")
    assert result.state == "COMPLETED"

    listed = database.list_cards()
    assert len(listed) == 1
    card = listed[0]
    assert card["title"] == "Daily Equity Mean Reversion"
    assert card["strategy_type"] == "mean reversion"
    assert card["markets"] == ["equities"]
    assert card["timeframes"] == ["daily"]
    assert {"RSI", "z-score"}.issubset(card["signals"])
    assert card["license_spdx"] == "MIT"
    assert card["cost_disclosure"] == "disclosed"
    assert "transaction_cost_not_disclosed" not in card["risk_flags"]
    assert "backtest_period_not_disclosed" not in card["risk_flags"]
    assert card["source_url"] == _artifact().canonical_url
    assert card["immutable_url"] == _artifact().immutable_url
    assert card["revision_key"] == "a" * 40

    stored = database.get_card(card["id"])
    assert stored is not None
    evidence = stored["evidence"]
    fields = {item["field_name"] for item in evidence}
    assert {
        "summary",
        "strategy_type",
        "markets",
        "signals",
        "cost_disclosure",
        "license_spdx",
    }.issubset(fields)
    assert all(item["chunk_id"] for item in evidence)
    assert all(item["quote"] for item in evidence)
    assert all("/blob/" in item["source_url"] for item in evidence)
    assert all("#L1-L" in item["source_url"] for item in evidence)

    with database.connect() as connection:
        chunk_ids = {
            row["id"] for row in connection.execute("SELECT id FROM chunks")
        }
    assert {item["chunk_id"] for item in evidence}.issubset(chunk_ids)


def test_github_evidence_uses_document_blob_not_repository_tree(settings: Settings, database: Database):
    artifact = _artifact()
    document_url = artifact.documents[0].source_url
    artifact = artifact.model_copy(
        update={
            "immutable_url": f"https://github.com/openalpha/daily-equity-mean-reversion/tree/{'a' * 40}"
        }
    )

    _pipeline(settings, database).process([artifact], kind="blob_evidence")
    card = database.list_cards()[0]
    stored = database.get_card(card["id"])
    assert stored is not None
    assert card["immutable_url"].endswith(f"/tree/{'a' * 40}")
    assert all(item["source_url"].startswith(document_url) for item in stored["evidence"])
    assert all("#L" in item["source_url"] for item in stored["evidence"])

    hit = HybridRetriever(database).search("mean reversion RSI", limit=1)[0]
    assert hit.immutable_url == document_url


def test_snapshot_evidence_anchors_to_original_fixture_lines(
    settings: Settings, database: Database
):
    fixture = (
        Path(__file__).parents[1]
        / "fixtures"
        / "strategies"
        / "daily-equity-mean-reversion.md"
    )
    artifact = SnapshotSource().load_file(fixture)
    document = artifact.documents[0]
    commit = "3aba9fc095ab77157ef225a6c5f77dfa5562ffa9"
    pinned_url = (
        "https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/"
        f"blob/{commit}/fixtures/strategies/daily-equity-mean-reversion.md"
    )

    assert document.line_offset == 7
    assert document.text.splitlines()[14].startswith("The test deducts")
    assert fixture.read_text(encoding="utf-8").splitlines()[21].startswith(
        "The test deducts"
    )
    assert artifact.immutable_url == pinned_url

    result = _pipeline(settings, database).process(
        [artifact], kind="snapshot_line_anchors"
    )
    assert result.state == "COMPLETED"

    card = database.list_cards()[0]
    stored = database.get_card(card["id"])
    assert stored is not None
    cost_evidence = next(
        item
        for item in stored["evidence"]
        if item["field_name"] == "cost_disclosure"
    )
    assert cost_evidence["line_start"] <= 22 <= cost_evidence["line_end"]
    assert cost_evidence["source_url"] == (
        f"{pinned_url}#L{cost_evidence['line_start']}-L{cost_evidence['line_end']}"
    )


def test_hybrid_retrieval_combines_lexical_and_vector_scores(
    settings: Settings, database: Database
):
    result = _pipeline(settings, database).process(
        [_artifact(), _momentum_artifact()], kind="retrieval_test"
    )
    assert result.state == "COMPLETED"
    assert result.created_cards == 2

    hits = HybridRetriever(database).search(
        "equity mean reversion RSI z-score", limit=5
    )

    assert hits
    assert hits[0].card_title == "Daily Equity Mean Reversion"
    assert "mean reversion" in hits[0].text.lower()
    assert hits[0].lexical_score == pytest.approx(1.0)
    assert hits[0].vector_score > 0
    assert hits[0].score == pytest.approx(
        hits[0].lexical_score * 0.6 + hits[0].vector_score * 0.4
    )
    assert hits[0].source_url == _artifact().canonical_url
    assert hits[0].immutable_url == _artifact().immutable_url


@pytest.mark.parametrize(
    "question",
    [
        "What is EBITDA?",
        "Explain photosynthesis in algae.",
    ],
)
def test_hash_retrieval_rejects_unrelated_vector_collisions(
    settings: Settings,
    question: str,
):
    service = OpenAlphaService(settings)
    assert service.seed_demo().state == "COMPLETED"

    assert service.retriever.search(question) == []
    answer = service.ask(question, session_id="unrelated-question")

    assert "does not contain enough evidence" in answer.answer
    assert answer.citations == []


def test_agent_lists_cards_with_local_citations(settings: Settings):
    service = OpenAlphaService(settings)
    ingested = service.pipeline.process([_artifact(), _momentum_artifact()], kind="agent_list_test")
    assert ingested.state == "COMPLETED"

    answer = service.ask("有哪些策略？", session_id="list-session")

    assert answer.backend == "deterministic-tool"
    assert "Daily Equity Mean Reversion" in answer.answer
    assert "[S1]" in answer.answer
    assert len(answer.citations) == 2
    assert answer.citations[0].label == "S1"
    assert _artifact().immutable_url in {citation.url for citation in answer.citations}
    assert all(step.status == "completed" for step in answer.steps)
    assert any(
        event["detail"].get("tool") == "list_strategy_cards"
        for event in service.database.list_audit_events()
    )

    follow_up = service.ask("只保留 MIT 许可证策略", session_id="list-session")
    assert "Daily Equity Mean Reversion" in follow_up.answer
    assert "Crypto Trend Momentum" not in follow_up.answer
    assert len(follow_up.citations) == 1


def test_agent_reports_insufficient_material_and_persists_memory(
    settings: Settings,
):
    service = OpenAlphaService(settings)

    missing = service.ask("这个策略的夏普比率是多少？", session_id="empty-session")
    assert "资料不足" in missing.answer
    assert missing.citations == []
    assert missing.backend == "heuristic-local"

    remembered = service.ask(
        "记住以后只看 MIT 许可证策略", session_id="memory-session"
    )
    assert "保存在本地" in remembered.answer
    assert remembered.citations == []
    assert service.database.preferences()["research_filter"] == {
        "instruction": "记住以后只看 MIT 许可证策略",
        "license": "MIT",
    }

    follow_up = service.ask("这些策略的来源是什么？", session_id="memory-session")
    assert "资料不足" in follow_up.answer
    messages = service.database.recent_messages("memory-session", limit=10)
    assert len(messages) == 4
    assert {message["role"] for message in messages} == {"user", "assistant"}
    assert any("MIT" in message["content"] for message in messages)
    assert any("来源" in message["content"] for message in messages)


def test_permission_gate_enforces_offline_mode_and_domain_grants(
    settings: Settings,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "openalpha_sentinel.permissions.socket.getaddrinfo",
        lambda host, port, **_: [
            (2, 1, 6, "", ("93.184.216.34", port)),
        ],
    )
    gate = PermissionGate(settings, database)

    gate.check_url("https://api.github.com/search/repositories")
    with pytest.raises(PermissionError, match="Domain is not approved: example.com"):
        gate.check_url("https://example.com/feed.xml")

    gate.grant_domain(".Example.COM")
    gate.check_url("https://news.example.com/feed.xml")
    gate.check_url(
        "https://feeds.research.test/strategies.xml", allow_explicit_feed=True
    )
    assert gate.allowed_domains() == [
        "example.com",
        "feeds.research.test",
        "github.com",
    ]

    gate.set_offline(True)
    assert gate.is_offline() is True
    with pytest.raises(PermissionError, match="offline mode"):
        gate.check_url("https://github.com/openalpha/strategy")
    gate.set_offline(False)
    assert gate.is_offline() is False

    event_types = {
        event["event_type"] for event in database.list_audit_events()
    }
    assert {"domain_granted", "offline_mode_changed"}.issubset(event_types)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("file:///etc/passwd", "absolute"),
        ("https://user:secret@example.com/feed", "Credentials"),
        ("https://example.com:99999/feed", "invalid port"),
        ("http://127.0.0.1/feed", "non-public"),
        ("http://169.254.169.254/latest/meta-data", "non-public"),
        ("http://[::1]/feed", "non-public"),
    ],
    ids=[
        "file-scheme",
        "embedded-credentials",
        "invalid-port",
        "loopback",
        "cloud-metadata",
        "ipv6-loopback",
    ],
)
def test_permission_gate_rejects_unsafe_source_urls(
    settings: Settings,
    database: Database,
    url: str,
    message: str,
):
    gate = PermissionGate(settings, database)

    with pytest.raises(PermissionError, match=message):
        gate.check_url(url, allow_explicit_feed=True)


def test_permission_gate_rejects_domains_resolving_to_private_addresses(
    settings: Settings,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "openalpha_sentinel.permissions.socket.getaddrinfo",
        lambda host, port, **_: [
            (2, 1, 6, "", ("10.0.0.7", port)),
        ],
    )
    gate = PermissionGate(settings, database)

    with pytest.raises(PermissionError, match="non-public"):
        gate.check_url("https://feeds.example.com/research.xml", allow_explicit_feed=True)
    assert "feeds.example.com" not in gate.allowed_domains()


def test_settings_offline_default_is_honored_until_locally_overridden(
    settings: Settings, database: Database
):
    offline_gate = PermissionGate(replace(settings, offline=True), database)

    assert offline_gate.is_offline() is True
    offline_gate.set_offline(False)
    assert offline_gate.is_offline() is False


def test_watch_rules_become_due_and_update_schedule_and_cursor(
    database: Database,
):
    enabled = database.create_watch_rule(
        "GitHub mean reversion",
        "github",
        {"query": "mean reversion", "limit": 5},
        interval_minutes=15,
    )
    disabled = database.create_watch_rule(
        "Disabled RSS",
        "rss",
        {"url": "https://example.com/feed.xml"},
        interval_minutes=30,
        enabled=False,
    )
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(
        timespec="seconds"
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE watch_rules SET next_run_at=? WHERE id IN (?, ?)",
            (past, enabled["id"], disabled["id"]),
        )

    due = database.due_watch_rules()
    assert [rule["id"] for rule in due] == [enabled["id"]]
    assert due[0]["config"] == {"limit": 5, "query": "mean reversion"}

    database.mark_watch_run(
        enabled["id"], interval_minutes=15, cursor={"last_sha": "abc123"}
    )
    updated = database.get_watch_rule(enabled["id"])
    assert updated is not None
    assert updated["last_run_at"] is not None
    assert updated["cursor"] == {"last_sha": "abc123"}
    last_run = datetime.fromisoformat(updated["last_run_at"])
    next_run = datetime.fromisoformat(updated["next_run_at"])
    assert next_run - last_run == timedelta(minutes=15)
    assert database.due_watch_rules() == []

    disabled_after = database.get_watch_rule(disabled["id"])
    assert disabled_after is not None
    assert disabled_after["enabled"] is False
    assert disabled_after["last_run_at"] is None


def test_worker_run_once_executes_a_due_rule(settings: Settings):
    service = OpenAlphaService(settings)
    rule = service.create_watch_rule(
        "Due fixture rule", "github", {"query": "mean reversion", "limit": 1}, 15
    )
    with service.database.connect() as connection:
        connection.execute(
            "UPDATE watch_rules SET next_run_at=? WHERE id=?",
            (
                (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds"),
                rule["id"],
            ),
        )

    def run_locally(due_rule: dict) -> PipelineResult:
        service.database.mark_watch_run(due_rule["id"], due_rule["interval_minutes"])
        return PipelineResult(job_id="job_fixture", state="COMPLETED")

    service.run_watch_rule = run_locally  # type: ignore[method-assign]
    outcomes = CollectorWorker(service).run_once()

    assert outcomes == [{"rule_id": rule["id"], "state": "COMPLETED"}]
    assert service.database.due_watch_rules() == []

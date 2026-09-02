from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from creative_hub.db.models import (
    BookDiscoveryCandidateRecord,
    BookDiscoverySelectionRecord,
    BookRecord,
    InputResolutionRecord,
    ProjectRecord,
)
from creative_hub.models import OrchestrationBase
from creative_hub.shidu.book_identity import normalize_book_identity
from creative_hub.shidu.repository import IdempotencyConflict, ShiduRepository
from creative_hub.shidu.schemas import (
    CreateBook,
    CreateBookDiscoveryResolution,
    DiscoveredBookIdentity,
    SelectBookDiscoveryCandidate,
)


PROJECT_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")
SEARCH_SCHEMA = "a" * 64
READER_SCHEMA = "b" * 64


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def attach(connection, _record) -> None:
        connection.execute("ATTACH DATABASE ':memory:' AS orchestration")
        connection.execute("PRAGMA foreign_keys = ON")

    OrchestrationBase.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as value:
        value.add_all(
            [
                ProjectRecord(
                    id=project_id,
                    project_key=f"discovery-{project_id}",
                    title=f"Discovery {project_id}",
                    config={},
                    config_digest="0" * 64,
                )
                for project_id in (PROJECT_ID, OTHER_PROJECT_ID)
            ]
        )
        value.commit()
        yield value
    engine.dispose()


def _identity(
    *,
    title: str = "活着",
    author: str = "余华",
    edition: str = "2012 版",
    canonical_url: str = "https://example.com/books/to-live",
    content_digest: str = "c" * 64,
) -> DiscoveredBookIdentity:
    return DiscoveredBookIdentity(
        title=title,
        author=author,
        language="zh-CN",
        edition=edition,
        translator="",
        canonical_url=canonical_url,
        reader_content_digest=content_digest,
    )


def _command(
    *,
    project_id: UUID = PROJECT_ID,
    command_key: str = "discover:1",
    raw_input: str = "活着",
    candidates: tuple[DiscoveredBookIdentity, ...] | None = None,
) -> CreateBookDiscoveryResolution:
    return CreateBookDiscoveryResolution(
        project_id=project_id,
        raw_input=raw_input,
        candidates=candidates if candidates is not None else (_identity(),),
        search_provider="coding_plan.search",
        search_schema_digest=SEARCH_SCHEMA,
        reader_provider="coding_plan.read_page",
        reader_schema_digest=READER_SCHEMA,
        command_key=command_key,
    )


def test_discovery_candidate_identity_is_persisted_and_selection_ignores_client_identity_fields(
    session: Session,
) -> None:
    repository = ShiduRepository(session)
    resolution = repository.create_book_discovery_resolution(_command()).value

    candidate = resolution.candidates[0]
    expected = normalize_book_identity(
        "活着", "余华", "zh-CN", "2012 版", ""
    )
    assert candidate.id == session.scalar(select(BookDiscoveryCandidateRecord.id))
    assert candidate.input_resolution_id == resolution.id
    assert candidate.ordinal == 1
    assert candidate.identity_digest == expected.digest
    assert candidate.title == expected.title
    assert candidate.author == expected.author
    assert candidate.language == expected.language
    assert candidate.edition == expected.edition
    assert candidate.translator == expected.translator
    assert candidate.reader_content_digest == "c" * 64
    assert candidate.search_provider == "coding_plan.search"
    assert candidate.search_schema_digest == SEARCH_SCHEMA
    assert candidate.reader_provider == "coding_plan.read_page"
    assert candidate.reader_schema_digest == READER_SCHEMA

    # The persistence boundary keys selection solely by server-side IDs.  Any
    # identity-like attributes carried by an upstream client are ignored.
    spoofed = SimpleNamespace(
        project_id=PROJECT_ID,
        input_resolution_id=resolution.id,
        candidate_id=candidate.id,
        command_key="select:1",
        title="伪造书名",
        author="伪造作者",
        language="xx",
        edition="伪造版本",
        translator="伪造译者",
    )
    selected = repository.select_book_discovery_candidate(spoofed)

    assert selected.value.identity_digest == candidate.identity_digest
    assert selected.value.title == candidate.title
    assert selected.value.author == candidate.author
    assert session.scalar(select(BookRecord.title)) == expected.title


def test_candidate_selection_is_project_and_resolution_scoped(
    session: Session,
) -> None:
    repository = ShiduRepository(session)
    first = repository.create_book_discovery_resolution(_command()).value
    second = repository.create_book_discovery_resolution(
        _command(
            command_key="discover:2",
            raw_input="许三观卖血记",
            candidates=(
                _identity(
                    title="许三观卖血记",
                    edition="1995 版",
                    canonical_url="https://example.com/books/chronicle-of-a-blood-merchant",
                    content_digest="d" * 64,
                ),
            ),
        )
    ).value
    other_project = repository.create_book_discovery_resolution(
        _command(
            project_id=OTHER_PROJECT_ID,
            command_key="discover:other",
        )
    ).value

    with pytest.raises(ValueError, match="project.*resolution|candidate"):
        repository.select_book_discovery_candidate(
            SelectBookDiscoveryCandidate(
                project_id=OTHER_PROJECT_ID,
                input_resolution_id=first.id,
                candidate_id=first.candidates[0].id,
                command_key="select:wrong-project",
            )
        )
    with pytest.raises(ValueError, match="project.*resolution|candidate"):
        repository.select_book_discovery_candidate(
            SelectBookDiscoveryCandidate(
                project_id=PROJECT_ID,
                input_resolution_id=second.id,
                candidate_id=first.candidates[0].id,
                command_key="select:wrong-resolution",
            )
        )
    with pytest.raises(ValueError, match="project.*resolution|candidate"):
        repository.select_book_discovery_candidate(
            SelectBookDiscoveryCandidate(
                project_id=PROJECT_ID,
                input_resolution_id=other_project.id,
                candidate_id=other_project.candidates[0].id,
                command_key="select:cross-project-resolution",
            )
        )


def test_discovery_candidate_identity_is_unique_within_resolution(
    session: Session,
) -> None:
    repository = ShiduRepository(session)
    resolution = repository.create_book_discovery_resolution(_command()).value
    persisted = session.get(BookDiscoveryCandidateRecord, resolution.candidates[0].id)
    duplicate = BookDiscoveryCandidateRecord(
        id=uuid4(),
        project_id=persisted.project_id,
        input_resolution_id=persisted.input_resolution_id,
        ordinal=2,
        title=persisted.title,
        author=persisted.author,
        language=persisted.language,
        edition=persisted.edition,
        translator=persisted.translator,
        identity_digest=persisted.identity_digest,
        canonical_url="https://example.com/books/to-live-duplicate",
        reader_content_digest="e" * 64,
        search_provider=persisted.search_provider,
        search_schema_digest=persisted.search_schema_digest,
        reader_provider=persisted.reader_provider,
        reader_schema_digest=persisted.reader_schema_digest,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()


def test_orch_0032_migration_upgrade_down_and_constraints(monkeypatch) -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "orchestration_migrations"
        / "versions"
        / "orch_0032_shidu_book_discovery_candidates.py"
    )
    spec = importlib.util.spec_from_file_location("orch_0032_test", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    calls: list[tuple[str, object]] = []

    class Recorder:
        def create_table(self, name, *items, **kwargs):
            calls.append(("create_table", (name, items, kwargs)))

        def create_index(self, name, *args, **kwargs):
            calls.append(("create_index", (name, args, kwargs)))

        def execute(self, statement):
            calls.append(("execute", str(statement)))

        def drop_index(self, name, *args, **kwargs):
            calls.append(("drop_index", (name, args, kwargs)))

        def drop_table(self, name, *args, **kwargs):
            calls.append(("drop_table", (name, args, kwargs)))

    monkeypatch.setattr(migration, "op", Recorder())
    migration.upgrade()

    created_tables = {
        payload[0]: payload
        for name, payload in calls
        if name == "create_table"
    }
    table_name, items, kwargs = created_tables["book_discovery_candidates"]
    constraint_names = {getattr(item, "name", None) for item in items}
    assert migration.revision == "orch_0032"
    assert migration.down_revision == "orch_0031"
    assert table_name == "book_discovery_candidates"
    assert kwargs["schema"] == "orchestration"
    assert "uq_orch_book_discovery_candidates_identity" in constraint_names
    assert "uq_orch_book_discovery_candidates_ordinal" in constraint_names
    selection_name, selection_items, selection_kwargs = created_tables[
        "book_discovery_selections"
    ]
    selection_constraints = {
        getattr(item, "name", None) for item in selection_items
    }
    assert selection_name == "book_discovery_selections"
    assert selection_kwargs["schema"] == "orchestration"
    assert "uq_orch_book_discovery_selections_fact" in selection_constraints
    assert "uq_orch_book_discovery_selections_command" in selection_constraints
    assert any(
        name == "execute"
        and "trg_book_discovery_selections_immutable" in str(payload)
        for name, payload in calls
    )
    assert not any(name.startswith("drop_") for name, _payload in calls)

    calls.clear()
    migration.downgrade()
    assert (
        "drop_table",
        ("book_discovery_selections", (), {"schema": "orchestration"}),
    ) in calls
    assert ("drop_table", ("book_discovery_candidates", (), {"schema": "orchestration"})) in calls


def test_unresolved_discovery_persists_no_candidate_rows(session: Session) -> None:
    repository = ShiduRepository(session)
    result = repository.create_book_discovery_resolution(
        _command(command_key="discover:none", candidates=())
    ).value

    assert result.status == "UNRESOLVED"
    assert result.candidates == ()
    assert session.scalar(select(InputResolutionRecord.id)) == result.id
    assert session.scalars(select(BookDiscoveryCandidateRecord)).all() == []


def test_discovery_replay_lookup_is_durable_and_title_scoped(
    session: Session,
) -> None:
    repository = ShiduRepository(session)
    stored = repository.create_book_discovery_resolution(_command()).value

    replay = repository.get_book_discovery_replay(
        PROJECT_ID,
        "discover:1",
        " 《活着》 ",
    )

    assert replay is not None
    assert replay.id == stored.id
    assert (
        repository.get_book_discovery_replay(
            PROJECT_ID,
            "discover:missing",
            "活着",
        )
        is None
    )
    with pytest.raises(IdempotencyConflict, match="different.*title"):
        repository.get_book_discovery_replay(
            PROJECT_ID,
            "discover:1",
            "兄弟",
        )


def test_selection_fact_is_durable_projects_resolution_and_conflicts_before_book_reuse(
    session: Session,
) -> None:
    repository = ShiduRepository(session)
    existing_a = repository.create_or_reuse_book(
        CreateBook(
            project_id=PROJECT_ID,
            title="活着",
            author="余华",
            language="zh-CN",
            edition="2012 版",
            translator="",
            command_key="book:existing-a",
        )
    ).value
    existing_b = repository.create_or_reuse_book(
        CreateBook(
            project_id=PROJECT_ID,
            title="兄弟",
            author="余华",
            language="zh-CN",
            edition="2005 版",
            translator="",
            command_key="book:existing-b",
        )
    ).value
    resolution = repository.create_book_discovery_resolution(
        _command(
            raw_input="余华作品",
            candidates=(
                _identity(),
                _identity(
                    title="兄弟",
                    edition="2005 版",
                    canonical_url="https://example.com/books/brothers",
                    content_digest="d" * 64,
                ),
            ),
        )
    ).value
    candidate_a, candidate_b = resolution.candidates
    command = SelectBookDiscoveryCandidate(
        project_id=PROJECT_ID,
        input_resolution_id=resolution.id,
        candidate_id=candidate_a.id,
        command_key="selection:existing-a-or-b",
    )

    selected = repository.select_book_discovery_candidate(command)
    replay = repository.select_book_discovery_candidate(command)

    assert selected.value.id == existing_a.id
    assert replay.value.id == existing_a.id
    facts = session.scalars(select(BookDiscoverySelectionRecord)).all()
    assert len(facts) == 1
    assert facts[0].project_id == PROJECT_ID
    assert facts[0].input_resolution_id == resolution.id
    assert facts[0].candidate_id == candidate_a.id
    assert facts[0].book_id == existing_a.id
    assert facts[0].command_idempotency_key == "selection:existing-a-or-b"
    projection = repository.get_book_discovery_resolution(
        PROJECT_ID, resolution.id
    )
    assert projection.status == "RESOLVED"
    assert projection.selected_book_id == existing_a.id

    with pytest.raises(IdempotencyConflict, match="different.*candidate"):
        repository.select_book_discovery_candidate(
            SelectBookDiscoveryCandidate(
                project_id=PROJECT_ID,
                input_resolution_id=resolution.id,
                candidate_id=candidate_b.id,
                command_key="selection:existing-a-or-b",
            )
        )
    assert session.get(BookRecord, existing_b.id).id == existing_b.id
    assert len(session.scalars(select(BookDiscoverySelectionRecord)).all()) == 1

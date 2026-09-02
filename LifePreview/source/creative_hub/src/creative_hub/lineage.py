"""Append-only, project-scoped artifact lineage.

``ArtifactLineageGraph`` is the sole writable lineage authority.  Artifact
records carry no embedded parent list, avoiding divergent lineage sources.
Edges point from an output artifact to one ordered input role.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db.models import ArtifactLineageEdgeRecord, ArtifactRecordRow


_ROLE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,199}$")


class ArtifactLineageError(RuntimeError):
    pass


class ArtifactLineageUnavailable(ArtifactLineageError):
    """Artifact or lineage is absent/outside the requested project."""


class ArtifactLineageConflict(ArtifactLineageError):
    pass


class ArtifactLineageCycle(ArtifactLineageConflict):
    pass


@dataclass(frozen=True, slots=True)
class LineageInput:
    artifact_id: UUID
    role: str
    ordinal: int

    def __post_init__(self) -> None:
        if not _ROLE.fullmatch(self.role):
            raise ValueError("invalid lineage role")
        if self.ordinal < 0:
            raise ValueError("lineage ordinal must be non-negative")


@dataclass(frozen=True, slots=True)
class ArtifactLineageEdge:
    edge_id: UUID
    project_id: UUID
    output_artifact_id: UUID
    input_artifact_id: UUID
    role: str
    ordinal: int
    created_at: datetime


ArtifactScopeCheck = Callable[[UUID, UUID], bool]


class ArtifactLineageGraph:
    """Thread-safe append-only DAG with deterministic role ordering."""

    def __init__(
        self,
        *,
        artifact_in_project: ArtifactScopeCheck | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._artifact_in_project = artifact_in_project
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._edges: dict[UUID, list[ArtifactLineageEdge]] = defaultdict(list)
        self._role_positions: set[tuple[UUID, UUID, str, int]] = set()
        self._version: dict[UUID, int] = defaultdict(int)

    def append(
        self,
        *,
        project_id: UUID,
        output_artifact_id: UUID,
        inputs: Sequence[LineageInput],
    ) -> tuple[ArtifactLineageEdge, ...]:
        if not inputs:
            return ()
        with self._lock:
            self._assert_scoped(project_id, output_artifact_id)
            for value in inputs:
                self._assert_scoped(project_id, value.artifact_id)
                if value.artifact_id == output_artifact_id:
                    raise ArtifactLineageCycle(
                        "artifact lineage cannot contain a self-cycle"
                    )

            positions = [
                (
                    project_id,
                    output_artifact_id,
                    value.role,
                    value.ordinal,
                )
                for value in inputs
            ]
            if len(positions) != len(set(positions)):
                raise ArtifactLineageConflict(
                    "lineage role ordinal is duplicated in the batch"
                )
            existing_by_position = {
                (
                    edge.project_id,
                    edge.output_artifact_id,
                    edge.role,
                    edge.ordinal,
                ): edge
                for edge in self._edges.get(project_id, ())
                if edge.output_artifact_id == output_artifact_id
            }
            if all(position in existing_by_position for position in positions):
                replay = tuple(
                    existing_by_position[position] for position in positions
                )
                if all(
                    edge.input_artifact_id == value.artifact_id
                    for edge, value in zip(replay, inputs, strict=True)
                ):
                    return replay
                raise ArtifactLineageConflict(
                    "lineage role ordinal has different input"
                )
            if any(position in existing_by_position for position in positions):
                raise ArtifactLineageConflict(
                    "partial lineage batch retry is not allowed"
                )
            self._validate_contiguous_role_order(
                project_id=project_id,
                output_artifact_id=output_artifact_id,
                inputs=inputs,
            )

            adjacency = self._adjacency(project_id)
            prospective = list(adjacency.get(output_artifact_id, ()))
            prospective.extend(value.artifact_id for value in inputs)
            adjacency[output_artifact_id] = prospective
            if self._contains_cycle(adjacency):
                raise ArtifactLineageCycle("artifact lineage must remain acyclic")

            now = self._clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("lineage clock must be timezone-aware")
            edges = tuple(
                ArtifactLineageEdge(
                    edge_id=uuid4(),
                    project_id=project_id,
                    output_artifact_id=output_artifact_id,
                    input_artifact_id=value.artifact_id,
                    role=value.role,
                    ordinal=value.ordinal,
                    created_at=now,
                )
                for value in inputs
            )
            self._edges[project_id].extend(edges)
            self._role_positions.update(positions)
            self._version[project_id] += 1
            return edges

    def ordered_inputs(
        self,
        *,
        project_id: UUID,
        output_artifact_id: UUID,
        role: str | None = None,
    ) -> tuple[ArtifactLineageEdge, ...]:
        if role is not None and not _ROLE.fullmatch(role):
            raise ValueError("invalid lineage role")
        with self._lock:
            return tuple(
                sorted(
                    (
                        edge
                        for edge in self._edges.get(project_id, ())
                        if edge.output_artifact_id == output_artifact_id
                        and (role is None or edge.role == role)
                    ),
                    key=lambda edge: (edge.role, edge.ordinal, str(edge.edge_id)),
                )
            )

    def ancestors(
        self,
        *,
        project_id: UUID,
        artifact_ids: Iterable[UUID],
    ) -> frozenset[UUID]:
        """Return roots and every transitive input in the same project."""

        with self._lock:
            adjacency = self._adjacency(project_id)
            marked = set(artifact_ids)
            queue = deque(marked)
            while queue:
                output = queue.popleft()
                for input_id in adjacency.get(output, ()):
                    if input_id not in marked:
                        marked.add(input_id)
                        queue.append(input_id)
            return frozenset(marked)

    def version(self, *, project_id: UUID) -> int:
        with self._lock:
            return self._version[project_id]

    def edges(self, *, project_id: UUID) -> tuple[ArtifactLineageEdge, ...]:
        with self._lock:
            return tuple(self._edges.get(project_id, ()))

    def _assert_scoped(self, project_id: UUID, artifact_id: UUID) -> None:
        if (
            self._artifact_in_project is not None
            and not self._artifact_in_project(project_id, artifact_id)
        ):
            # Same response for missing and cross-project artifacts.
            raise ArtifactLineageUnavailable("artifact lineage is unavailable")

    def _adjacency(self, project_id: UUID) -> dict[UUID, list[UUID]]:
        result: dict[UUID, list[UUID]] = defaultdict(list)
        for edge in self._edges.get(project_id, ()):
            result[edge.output_artifact_id].append(edge.input_artifact_id)
        return result

    def _validate_contiguous_role_order(
        self,
        *,
        project_id: UUID,
        output_artifact_id: UUID,
        inputs: Sequence[LineageInput],
    ) -> None:
        by_role: dict[str, list[int]] = defaultdict(list)
        for edge in self._edges.get(project_id, ()):
            if edge.output_artifact_id == output_artifact_id:
                by_role[edge.role].append(edge.ordinal)
        for value in inputs:
            by_role[value.role].append(value.ordinal)
        for ordinals in by_role.values():
            ordered = sorted(ordinals)
            if ordered != list(range(len(ordered))):
                raise ArtifactLineageConflict(
                    "lineage ordinals must be contiguous from zero per role"
                )

    @staticmethod
    def _contains_cycle(adjacency: dict[UUID, list[UUID]]) -> bool:
        visiting: set[UUID] = set()
        visited: set[UUID] = set()

        def visit(node: UUID) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for child in adjacency.get(node, ()):
                if visit(child):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        nodes = set(adjacency)
        nodes.update(child for children in adjacency.values() for child in children)
        return any(visit(node) for node in nodes if node not in visited)


class PostgresArtifactLineageGraph:
    """Append-only lineage authority persisted in PostgreSQL."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _lock_project(session: Session, project_id: UUID) -> None:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:project_id, 0))"
                ),
                {"project_id": str(project_id)},
            )

    @staticmethod
    def _edge(row: ArtifactLineageEdgeRecord) -> ArtifactLineageEdge:
        created_at = row.created_at
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            created_at = created_at.replace(tzinfo=UTC)
        return ArtifactLineageEdge(
            edge_id=row.id,
            project_id=row.project_id,
            output_artifact_id=row.output_artifact_id,
            input_artifact_id=row.input_artifact_id,
            role=row.role,
            ordinal=row.ordinal,
            created_at=created_at,
        )

    @staticmethod
    def _assert_scoped(
        session: Session,
        *,
        project_id: UUID,
        artifact_ids: Iterable[UUID],
    ) -> None:
        expected = set(artifact_ids)
        if not expected:
            return
        observed = set(
            session.scalars(
                select(ArtifactRecordRow.id).where(
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.id.in_(expected),
                    ArtifactRecordRow.status == "COMMITTED",
                )
            )
        )
        if observed != expected:
            # Missing, non-visible and cross-project artifacts deliberately
            # share one non-enumerating response.
            raise ArtifactLineageUnavailable(
                "artifact lineage is unavailable"
            )

    def append(
        self,
        *,
        project_id: UUID,
        output_artifact_id: UUID,
        inputs: Sequence[LineageInput],
    ) -> tuple[ArtifactLineageEdge, ...]:
        if not inputs:
            return ()
        positions = [
            (value.role, value.ordinal, value.artifact_id) for value in inputs
        ]
        if len({(role, ordinal) for role, ordinal, _ in positions}) != len(
            positions
        ):
            raise ArtifactLineageConflict(
                "lineage role ordinal is duplicated in the batch"
            )
        if any(value.artifact_id == output_artifact_id for value in inputs):
            raise ArtifactLineageCycle(
                "artifact lineage cannot contain a self-cycle"
            )
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("lineage clock must be timezone-aware")
        try:
            with self._session_factory() as session, session.begin():
                self._lock_project(session, project_id)
                self._assert_scoped(
                    session,
                    project_id=project_id,
                    artifact_ids=[
                        output_artifact_id,
                        *(value.artifact_id for value in inputs),
                    ],
                )
                # The project advisory lock serializes the append/replay
                # decision. Lineage edges are immutable facts, so a row lock
                # would incorrectly require UPDATE permission from the
                # append-only execution role.
                existing_rows = session.scalars(
                    select(ArtifactLineageEdgeRecord)
                    .where(
                        ArtifactLineageEdgeRecord.project_id == project_id,
                        ArtifactLineageEdgeRecord.output_artifact_id
                        == output_artifact_id,
                    )
                ).all()
                existing = {
                    (row.role, row.ordinal): row for row in existing_rows
                }
                if all(
                    (value.role, value.ordinal) in existing for value in inputs
                ):
                    replay = tuple(
                        existing[(value.role, value.ordinal)]
                        for value in inputs
                    )
                    if all(
                        row.input_artifact_id == value.artifact_id
                        for row, value in zip(replay, inputs, strict=True)
                    ):
                        return tuple(self._edge(row) for row in replay)
                    raise ArtifactLineageConflict(
                        "lineage role ordinal has different input"
                    )
                if any(
                    (value.role, value.ordinal) in existing for value in inputs
                ):
                    raise ArtifactLineageConflict(
                        "partial lineage batch retry is not allowed"
                    )
                by_role: dict[str, list[int]] = defaultdict(list)
                for row in existing_rows:
                    by_role[row.role].append(row.ordinal)
                for value in inputs:
                    by_role[value.role].append(value.ordinal)
                if any(
                    sorted(ordinals) != list(range(len(ordinals)))
                    for ordinals in by_role.values()
                ):
                    raise ArtifactLineageConflict(
                        "lineage ordinals must be contiguous from zero per role"
                    )
                created: list[ArtifactLineageEdgeRecord] = []
                # Flush in deterministic role/ordinal order because the
                # database trigger checks contiguity after each row.
                indexed = list(enumerate(inputs))
                for _, value in sorted(
                    indexed,
                    key=lambda item: (item[1].role, item[1].ordinal),
                ):
                    row = ArtifactLineageEdgeRecord(
                        id=uuid4(),
                        project_id=project_id,
                        output_artifact_id=output_artifact_id,
                        input_artifact_id=value.artifact_id,
                        role=value.role,
                        ordinal=value.ordinal,
                        created_at=now,
                    )
                    session.add(row)
                    session.flush()
                    created.append(row)
                by_position = {
                    (row.role, row.ordinal): row for row in created
                }
                return tuple(
                    self._edge(by_position[(value.role, value.ordinal)])
                    for value in inputs
                )
        except IntegrityError as exc:
            message = str(exc.orig).lower()
            if "cycle" in message:
                raise ArtifactLineageCycle(
                    "artifact lineage must remain acyclic"
                ) from exc
            raise ArtifactLineageConflict(
                "artifact lineage changed concurrently"
            ) from exc

    def ordered_inputs(
        self,
        *,
        project_id: UUID,
        output_artifact_id: UUID,
        role: str | None = None,
    ) -> tuple[ArtifactLineageEdge, ...]:
        if role is not None and not _ROLE.fullmatch(role):
            raise ValueError("invalid lineage role")
        statement = select(ArtifactLineageEdgeRecord).where(
            ArtifactLineageEdgeRecord.project_id == project_id,
            ArtifactLineageEdgeRecord.output_artifact_id
            == output_artifact_id,
        )
        if role is not None:
            statement = statement.where(
                ArtifactLineageEdgeRecord.role == role
            )
        with self._session_factory() as session:
            rows = session.scalars(
                statement.order_by(
                    ArtifactLineageEdgeRecord.role,
                    ArtifactLineageEdgeRecord.ordinal,
                    ArtifactLineageEdgeRecord.id,
                )
            ).all()
            return tuple(self._edge(row) for row in rows)

    def ancestors(
        self,
        *,
        project_id: UUID,
        artifact_ids: Iterable[UUID],
    ) -> frozenset[UUID]:
        marked = set(artifact_ids)
        frontier = set(marked)
        with self._session_factory() as session:
            while frontier:
                inputs = set(
                    session.scalars(
                        select(
                            ArtifactLineageEdgeRecord.input_artifact_id
                        ).where(
                            ArtifactLineageEdgeRecord.project_id == project_id,
                            ArtifactLineageEdgeRecord.output_artifact_id.in_(
                                frontier
                            ),
                        )
                    )
                )
                frontier = inputs - marked
                marked.update(frontier)
        return frozenset(marked)

    def version(self, *, project_id: UUID) -> int:
        with self._session_factory() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(ArtifactLineageEdgeRecord)
                    .where(
                        ArtifactLineageEdgeRecord.project_id == project_id
                    )
                )
                or 0
            )

    def edges(
        self,
        *,
        project_id: UUID,
    ) -> tuple[ArtifactLineageEdge, ...]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ArtifactLineageEdgeRecord)
                .where(
                    ArtifactLineageEdgeRecord.project_id == project_id
                )
                .order_by(
                    ArtifactLineageEdgeRecord.created_at,
                    ArtifactLineageEdgeRecord.id,
                )
            ).all()
            return tuple(self._edge(row) for row in rows)

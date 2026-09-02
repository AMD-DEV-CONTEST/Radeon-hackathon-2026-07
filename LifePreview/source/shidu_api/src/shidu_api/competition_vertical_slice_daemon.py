"""CPU-idle production daemon for the clicked AMD vertical slice.

The HTTP POST made by the user creates a durable
``h3_deferred_vertical_slice`` row.  This daemon is the sole automatic bridge
from that row to the seven restart-safe coordinator stages.  Merely importing,
constructing, or polling this module never constructs a FLUX/H3 runtime.  The
production stage factory is loaded lazily only after a valid clicked job and
its first persistent checkpoint exist.

The injected factory must bind the seven named functions as follows:

* ``source_prepared`` -> ``HistoricalVisualIdentityPreparer.prepare_source``;
* ``flux_generated`` -> the staged runner's ``run_flux_stage``;
* ``references_published`` -> CAS publication of the three FLUX images;
* ``authority_finalized`` -> ``finalize_with_flux_references``;
* ``workflow_materialized`` ->
  ``SqlAlchemyShiduService.materialize_deferred_video_job``;
* ``h3_generated`` -> the staged runner's ``run_h3_stage``;
* ``delivered`` -> ``publish_competition_vertical_slice`` using the persisted
  succeeded runner checkpoint and its canonical result digest.

Keeping complex ROCm construction behind a factory gives deployment one
explicit integration boundary without leaving an unpolled clicked-job gap.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import re
import signal
import sys
from threading import Event
import time
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from creative_hub.db.models import VideoJobProjectionRecord
from creative_hub.runtime_bootstrap import database_url

from .competition_vertical_slice_worker import (
    CheckpointPort,
    ClickedDeferredVideoJob,
    CompetitionVerticalSliceCoordinator,
    CoordinatorContractError,
    DeferredJobPort,
    StageReceipt,
    WorkerCheckpoint,
    WorkerStage,
)


SessionFactory = Callable[[], Session]
StageResult = Mapping[str, Any]
StageFunction = Callable[["StageInvocation"], StageResult]
StageFactory = Callable[["CompetitionDaemonContext"], "ProductionStageFunctions"]

_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_ERROR_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{1,99}\Z")
_WORKER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_STAGE_ORDER: tuple[WorkerStage, ...] = (
    "source_prepared",
    "flux_generated",
    "references_published",
    "authority_finalized",
    "workflow_materialized",
    "h3_generated",
    "delivered",
)
_WORKER_STATE_KEYS = {
    "schemaVersion",
    "ownerDigest",
    "status",
    "attemptOrdinal",
    "jobAuthorityDigest",
    "errorCode",
}
_MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CompetitionDaemonContext:
    """Non-secret, CPU-only construction context passed to the stage factory."""

    project_id: UUID
    persistent_root: Path
    session_factory: SessionFactory

    def __post_init__(self) -> None:
        if not isinstance(self.project_id, UUID):
            raise ValueError("competition project_id is required")
        root = Path(self.persistent_root)
        if not root.is_absolute():
            raise ValueError("competition persistent_root must be absolute")
        if not callable(self.session_factory):
            raise ValueError("competition session_factory is invalid")
        object.__setattr__(self, "persistent_root", root)


@dataclass(frozen=True, slots=True)
class StageInvocation:
    """The complete restart/idempotency authority passed to one stage."""

    stage: WorkerStage
    job: ClickedDeferredVideoJob
    prior_receipts: tuple[StageReceipt, ...]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ProductionStageFunctions:
    """Exact production function bundle for the seven coordinator stages."""

    source_prepared: StageFunction
    flux_generated: StageFunction
    references_published: StageFunction
    authority_finalized: StageFunction
    workflow_materialized: StageFunction
    h3_generated: StageFunction
    delivered: StageFunction

    def __post_init__(self) -> None:
        if any(
            not callable(getattr(self, stage))
            for stage in _STAGE_ORDER
        ):
            raise ValueError("competition production stage bundle is incomplete")

    def for_stage(self, stage: WorkerStage) -> StageFunction:
        if stage not in _STAGE_ORDER:
            raise ValueError("competition stage is invalid")
        return getattr(self, stage)


def _required_digest(value: object, field: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise CoordinatorContractError(f"{field} must be a lowercase SHA-256")
    return value


def _worker_state(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != _WORKER_STATE_KEYS:
        raise CoordinatorContractError("competition worker state is invalid")
    if value.get("schemaVersion") != "amd.vertical-slice-worker-state.v1":
        raise CoordinatorContractError("competition worker state version is invalid")
    _required_digest(value.get("ownerDigest"), "worker owner digest")
    _required_digest(value.get("jobAuthorityDigest"), "worker job authority")
    if value.get("status") not in {
        "active",
        "retryable_failed",
        "terminal_failed",
        "delivered",
    }:
        raise CoordinatorContractError("competition worker status is invalid")
    ordinal = value.get("attemptOrdinal")
    if type(ordinal) is not int or ordinal < 1:
        raise CoordinatorContractError("competition worker attempt is invalid")
    error = value.get("errorCode")
    if error is not None and (
        type(error) is not str or _ERROR_CODE_RE.fullmatch(error) is None
    ):
        raise CoordinatorContractError("competition worker error code is invalid")
    if (value["status"] in {"active", "delivered"}) != (error is None):
        raise CoordinatorContractError("competition worker error state is invalid")
    return dict(value)


def _detached_projection(record: object) -> SimpleNamespace:
    """Detach only the fields required by ClickedDeferredVideoJob."""

    return SimpleNamespace(
        project_id=getattr(record, "project_id"),
        book_id=getattr(record, "book_id"),
        trial_script_revision_id=getattr(record, "trial_script_revision_id"),
        external_job_id=getattr(record, "external_job_id"),
        status=getattr(record, "status"),
        payload=dict(getattr(record, "payload")),
        command_idempotency_key=getattr(record, "command_idempotency_key"),
    )


class PostgresDeferredJobPort(DeferredJobPort):
    """Claim/report adapter for clicked 3-second deferred/materialized jobs.

    A stable deployment worker identity is persisted only as a SHA-256 digest.
    The digest acts as a restart lease: the same supervisor identity can resume,
    while another concurrently configured daemon cannot steal active GPU work.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        project_id: UUID,
        worker_identity: str,
        scan_limit: int = 64,
    ) -> None:
        if not callable(session_factory) or not isinstance(project_id, UUID):
            raise ValueError("competition deferred-job adapter is invalid")
        if (
            type(worker_identity) is not str
            or _WORKER_ID_RE.fullmatch(worker_identity) is None
        ):
            raise ValueError("competition worker identity is invalid")
        if type(scan_limit) is not int or not 1 <= scan_limit <= 256:
            raise ValueError("competition scan_limit is invalid")
        self._sessions = session_factory
        self._project_id = project_id
        self._scan_limit = scan_limit
        self.owner_digest = sha256(worker_identity.encode("utf-8")).hexdigest()

    def claim_next_clicked_deferred(self) -> object | None:
        statement = (
            select(VideoJobProjectionRecord)
            .where(
                VideoJobProjectionRecord.project_id == self._project_id,
                VideoJobProjectionRecord.status.in_(("queued", "processing")),
            )
            .order_by(
                VideoJobProjectionRecord.created_at,
                VideoJobProjectionRecord.id,
            )
            .with_for_update(skip_locked=True)
            .limit(self._scan_limit)
        )
        with self._sessions() as session, session.begin():
            records = list(session.scalars(statement))
            for record in records:
                if getattr(record, "project_id", None) != self._project_id:
                    continue
                try:
                    clicked = ClickedDeferredVideoJob.from_projection_record(record)
                except CoordinatorContractError:
                    # This port owns only the frozen competition projection.  Other
                    # queued jobs and malformed rows are not silently claimed.
                    continue
                payload = dict(record.payload)
                state = _worker_state(payload.get("competitionWorker"))
                if state is not None:
                    if state["jobAuthorityDigest"] != clicked.authority_digest:
                        raise CoordinatorContractError(
                            "competition worker state belongs to another click"
                        )
                    if state["status"] in {"terminal_failed", "delivered"}:
                        continue
                    if (
                        state["status"] == "active"
                        and state["ownerDigest"] != self.owner_digest
                    ):
                        continue
                    attempt_ordinal = state["attemptOrdinal"] + 1
                else:
                    attempt_ordinal = 1
                payload["competitionWorker"] = {
                    "schemaVersion": "amd.vertical-slice-worker-state.v1",
                    "ownerDigest": self.owner_digest,
                    "status": "active",
                    "attemptOrdinal": attempt_ordinal,
                    "jobAuthorityDigest": clicked.authority_digest,
                    "errorCode": None,
                }
                record.payload = payload
                record.status = "processing"
                session.flush()
                return _detached_projection(record)
        return None

    def report(
        self,
        job: ClickedDeferredVideoJob,
        status: Literal["retryable_failed", "terminal_failed", "delivered"],
        code: str | None,
    ) -> None:
        if not isinstance(job, ClickedDeferredVideoJob):
            raise CoordinatorContractError("competition report job is invalid")
        if job.project_id != self._project_id:
            raise CoordinatorContractError("competition report project is invalid")
        if status not in {"retryable_failed", "terminal_failed", "delivered"}:
            raise CoordinatorContractError("competition report status is invalid")
        if status == "delivered":
            if code is not None:
                raise CoordinatorContractError("delivered report contains an error")
        elif type(code) is not str or _ERROR_CODE_RE.fullmatch(code) is None:
            raise CoordinatorContractError("competition report error code is invalid")
        statement = (
            select(VideoJobProjectionRecord)
            .where(
                VideoJobProjectionRecord.project_id == job.project_id,
                VideoJobProjectionRecord.external_job_id == job.external_job_id,
            )
            .with_for_update()
        )
        with self._sessions() as session, session.begin():
            record = session.scalar(statement)
            if record is None:
                raise CoordinatorContractError("competition report job disappeared")
            # The delivery publisher may already have changed the public row to
            # succeeded.  Re-attest immutable click fields using a runnable view.
            runnable = _detached_projection(record)
            runnable.status = "processing"
            current = ClickedDeferredVideoJob.from_projection_record(runnable)
            if current.authority_digest != job.authority_digest:
                raise CoordinatorContractError("competition report click changed")
            payload = dict(record.payload)
            state = _worker_state(payload.get("competitionWorker"))
            if (
                state is None
                or state["ownerDigest"] != self.owner_digest
                or state["jobAuthorityDigest"] != job.authority_digest
            ):
                raise CoordinatorContractError("competition report lease is invalid")
            payload["competitionWorker"] = {
                **state,
                "status": status,
                "errorCode": code,
            }
            record.payload = payload
            record.status = {
                "retryable_failed": "processing",
                "terminal_failed": "failed",
                "delivered": "succeeded",
            }[status]
            session.flush()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CoordinatorContractError("checkpoint JSON has duplicate keys")
        result[key] = value
    return result


class AtomicPersistentCheckpointPort(CheckpointPort):
    """Atomic standard-JSON checkpoints with a revision compare-and-swap."""

    def __init__(self, *, root: Path, persistent_root: Path = Path("/persistent")) -> None:
        anchor = Path(persistent_root)
        location = Path(root)
        if not anchor.is_absolute() or not location.is_absolute():
            raise ValueError("checkpoint path must be absolute persistent storage")
        anchor.mkdir(parents=True, exist_ok=True)
        if anchor.is_symlink():
            raise ValueError("persistent root symlinks are forbidden")
        resolved_anchor = anchor.resolve(strict=True)
        try:
            relative = location.absolute().relative_to(anchor.absolute())
        except ValueError as exc:
            raise ValueError("checkpoint root must stay inside persistent storage") from exc
        # Validate the lexical route before resolving it so an existing
        # in-tree symlink cannot be hidden by Path.resolve().
        current = anchor.absolute()
        for part in relative.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError("checkpoint directory symlinks are forbidden")
        resolved_location = location.resolve(strict=False)
        try:
            resolved_location.relative_to(resolved_anchor)
        except ValueError as exc:
            raise ValueError("checkpoint root must stay inside persistent storage") from exc
        self._anchor = resolved_anchor
        self._root = resolved_location
        self._mkdir_safe(self._root)

    def _mkdir_safe(self, location: Path) -> None:
        relative = location.relative_to(self._anchor)
        current = self._anchor
        for part in relative.parts:
            current = current / part
            if current.exists():
                if current.is_symlink() or not current.is_dir():
                    raise ValueError("checkpoint directory is unsafe")
            else:
                current.mkdir(mode=0o700)

    def path_for(self, job: ClickedDeferredVideoJob) -> Path:
        if not isinstance(job, ClickedDeferredVideoJob):
            raise CoordinatorContractError("checkpoint job is invalid")
        project = self._root / str(job.project_id)
        self._mkdir_safe(project)
        target = project / f"{job.authority_digest}.json"
        if target.is_symlink():
            raise CoordinatorContractError("checkpoint symlinks are forbidden")
        return target

    @staticmethod
    def _read(path: Path) -> WorkerCheckpoint | None:
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise CoordinatorContractError("checkpoint path is unsafe")
        try:
            size = path.stat().st_size
            if not 1 <= size <= _MAX_CHECKPOINT_BYTES:
                raise OSError
            raw = path.read_text(encoding="utf-8")
            value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CoordinatorContractError("checkpoint JSON is unavailable") from exc
        return WorkerCheckpoint.from_json_object(value)

    def load(self, job: ClickedDeferredVideoJob) -> WorkerCheckpoint | None:
        checkpoint = self._read(self.path_for(job))
        if checkpoint is not None and (
            checkpoint.job_authority_digest != job.authority_digest
        ):
            raise CoordinatorContractError("checkpoint belongs to another click")
        return checkpoint

    @contextmanager
    def _locked(self, target: Path):
        lock_path = target.with_suffix(".lock")
        if lock_path.is_symlink():
            raise CoordinatorContractError("checkpoint lock symlinks are forbidden")
        handle = lock_path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def save(
        self,
        job: ClickedDeferredVideoJob,
        checkpoint: WorkerCheckpoint,
        *,
        expected_revision: int | None,
    ) -> WorkerCheckpoint:
        if not isinstance(checkpoint, WorkerCheckpoint):
            raise CoordinatorContractError("checkpoint value is invalid")
        if checkpoint.job_authority_digest != job.authority_digest:
            raise CoordinatorContractError("checkpoint belongs to another click")
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise CoordinatorContractError("checkpoint expected revision is invalid")
        target = self.path_for(job)
        with self._locked(target):
            current = self._read(target)
            current_revision = None if current is None else current.revision
            if current_revision != expected_revision:
                raise CoordinatorContractError("checkpoint revision compare-and-swap failed")
            base_revision = 0 if expected_revision is None else expected_revision
            if checkpoint.revision != base_revision:
                raise CoordinatorContractError("checkpoint input revision is stale")
            persisted = checkpoint.with_revision(base_revision + 1)
            body = json.dumps(
                persisted.to_json_object(),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            # Keep the transient basename short enough for legacy Windows
            # MAX_PATH test environments; the directory and final authority
            # name still carry the full project/job digest.
            temporary = target.with_name(f".cp-{uuid4().hex[:12]}.partial")
            try:
                with temporary.open("xb") as handle:
                    try:
                        os.chmod(temporary, 0o600)
                    except OSError:
                        pass
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
                if os.name != "nt":
                    directory_fd = os.open(target.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            return persisted


class _LazyStageBundle:
    def __init__(self, *, factory: StageFactory, context: CompetitionDaemonContext) -> None:
        if not callable(factory):
            raise ValueError("competition stage factory is invalid")
        self._factory = factory
        self._context = context
        self._value: ProductionStageFunctions | None = None

    def get(self) -> ProductionStageFunctions:
        if self._value is None:
            value = self._factory(self._context)
            if not isinstance(value, ProductionStageFunctions):
                raise CoordinatorContractError(
                    "competition stage factory returned the wrong type"
                )
            self._value = value
        return self._value


class _LazyFunctionStagePort:
    def __init__(self, *, stage: WorkerStage, bundle: _LazyStageBundle) -> None:
        self._stage = stage
        self._bundle = bundle

    def execute(
        self,
        *,
        job: ClickedDeferredVideoJob,
        prior_receipts: tuple[StageReceipt, ...],
        idempotency_key: str,
    ) -> StageReceipt:
        invocation = StageInvocation(
            stage=self._stage,
            job=job,
            prior_receipts=prior_receipts,
            idempotency_key=idempotency_key,
        )
        payload = self._bundle.get().for_stage(self._stage)(invocation)
        if not isinstance(payload, Mapping):
            raise CoordinatorContractError(
                f"{self._stage} returned an invalid production receipt"
            )
        normalized = dict(payload)
        _required_digest(normalized.get("outputDigest"), "stage outputDigest")
        return StageReceipt.build(
            stage=self._stage,
            job_authority_digest=job.authority_digest,
            payload=normalized,
        )


class CompetitionVerticalSliceDaemon:
    """Small CPU-idle poll loop around the restart-safe coordinator."""

    def __init__(
        self,
        *,
        coordinator: CompetitionVerticalSliceCoordinator,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(coordinator, CompetitionVerticalSliceCoordinator):
            raise ValueError("competition coordinator is invalid")
        if not callable(sleep):
            raise ValueError("competition sleep function is invalid")
        self.coordinator = coordinator
        self._sleep = sleep

    def run_once(self) -> WorkerCheckpoint | None:
        return self.coordinator.process_one()

    def serve(
        self,
        *,
        poll_seconds: float,
        should_stop: Callable[[], bool],
    ) -> None:
        if (
            type(poll_seconds) not in {int, float}
            or isinstance(poll_seconds, bool)
            or not 0.05 <= float(poll_seconds) <= 60.0
        ):
            raise ValueError("competition poll interval is invalid")
        if not callable(should_stop):
            raise ValueError("competition stop predicate is invalid")
        while not should_stop():
            self.run_once()
            if should_stop():
                break
            self._sleep(float(poll_seconds))


def build_competition_vertical_slice_daemon(
    *,
    jobs: DeferredJobPort,
    checkpoints: CheckpointPort,
    context: CompetitionDaemonContext,
    stage_factory: StageFactory,
) -> CompetitionVerticalSliceDaemon:
    """Build the daemon without invoking the GPU-capable stage factory."""

    lazy = _LazyStageBundle(factory=stage_factory, context=context)
    ports = {
        stage: _LazyFunctionStagePort(stage=stage, bundle=lazy)
        for stage in _STAGE_ORDER
    }
    coordinator = CompetitionVerticalSliceCoordinator(
        jobs=jobs,
        checkpoints=checkpoints,
        source_preparer=ports["source_prepared"],
        flux_runner=ports["flux_generated"],
        reference_publisher=ports["references_published"],
        authority_finalizer=ports["authority_finalized"],
        workflow_materializer=ports["workflow_materialized"],
        h3_runner=ports["h3_generated"],
        delivery_publisher=ports["delivered"],
    )
    return CompetitionVerticalSliceDaemon(coordinator=coordinator)


def _stage_factory_from_spec(specification: str) -> StageFactory:
    if type(specification) is not str or specification.count(":") != 1:
        raise RuntimeError("competition stage factory must use module:function")
    module_name, attribute = specification.split(":", 1)
    if not module_name or not attribute:
        raise RuntimeError("competition stage factory must use module:function")

    # Import/call is intentionally inside this returned closure.  No clicked
    # job means the daemon can poll forever without constructing GPU adapters.
    def factory(context: CompetitionDaemonContext) -> ProductionStageFunctions:
        try:
            function = getattr(importlib.import_module(module_name), attribute)
        except (ImportError, AttributeError) as exc:
            raise RuntimeError("competition stage factory is unavailable") from exc
        if not callable(function):
            raise RuntimeError("competition stage factory is unavailable")
        result = function(context)
        if not isinstance(result, ProductionStageFunctions):
            raise RuntimeError("competition stage factory returned the wrong type")
        return result

    return factory


def configured_daemon() -> CompetitionVerticalSliceDaemon:
    """Fail-closed production construction from stable supervisor settings."""

    try:
        project_id = UUID(os.environ["SHIDU_PROJECT_ID"])
        worker_identity = os.environ["AMD_COMPETITION_WORKER_ID"]
        stage_spec = os.environ["AMD_COMPETITION_STAGE_FACTORY"]
    except (KeyError, ValueError):
        raise RuntimeError("competition vertical-slice daemon is not configured") from None
    persistent_root = Path(
        os.environ.get("AMD_PERSISTENT_ROOT", "/persistent/douyin-amd")
    )
    try:
        persistent_root.resolve(strict=True).relative_to(
            Path("/persistent").resolve(strict=True)
        )
    except (OSError, ValueError):
        raise RuntimeError("competition persistent root is invalid") from None
    try:
        engine = create_engine(
            database_url("CREATIVE_ORCHESTRATION"), pool_pre_ping=True
        )
    except (RuntimeError, ValueError):
        raise RuntimeError("competition database is not configured") from None
    sessions: SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    context = CompetitionDaemonContext(
        project_id=project_id,
        persistent_root=persistent_root,
        session_factory=sessions,
    )
    jobs = PostgresDeferredJobPort(
        session_factory=sessions,
        project_id=project_id,
        worker_identity=worker_identity,
    )
    checkpoints = AtomicPersistentCheckpointPort(
        root=persistent_root / "vertical-slice" / "coordinator-checkpoints",
        persistent_root=Path("/persistent"),
    )
    return build_competition_vertical_slice_daemon(
        jobs=jobs,
        checkpoints=checkpoints,
        context=context,
        stage_factory=_stage_factory_from_spec(stage_spec),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the CPU-idle AMD competition vertical-slice daemon."
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    arguments = parser.parse_args(argv)
    daemon = configured_daemon()
    if arguments.once:
        daemon.run_once()
        return 0
    stop = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
    daemon.serve(
        poll_seconds=arguments.poll_seconds,
        should_stop=stop.is_set,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AtomicPersistentCheckpointPort",
    "CompetitionDaemonContext",
    "CompetitionVerticalSliceDaemon",
    "PostgresDeferredJobPort",
    "ProductionStageFunctions",
    "StageInvocation",
    "build_competition_vertical_slice_daemon",
    "configured_daemon",
    "main",
]

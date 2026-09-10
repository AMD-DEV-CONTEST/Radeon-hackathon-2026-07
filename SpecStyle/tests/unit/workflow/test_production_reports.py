"""APP-COMPOSE-001C private durable verification-report storage contracts."""

from __future__ import annotations

import importlib
import inspect
import json
import os
import stat
import gc
from dataclasses import replace

import pytest

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import (
    RuleLevel,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import ArtifactId, AttemptId, JobId, RuleId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.hashing import hash_bytes
from specstyle.reliability.fixtures import sample_production_request
from specstyle.verification.rule_models import (
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)


def _module():
    try:
        return importlib.import_module("specstyle.workflow.production_reports")
    except ModuleNotFoundError:
        pytest.fail("production report store module is missing")


def _request(attempt_id: str = "attempt") -> GenerationRequest:
    return replace(sample_production_request(), attempt_id=AttemptId(attempt_id))


def _report(artifact_id: str = "artifact-1") -> VerificationReport:
    artifact = ArtifactRef(ArtifactId(artifact_id), hash_bytes(b"artifact content"))
    first = RuleDefinition(
        RuleId("rule-b"),
        RuleLevel.L2,
        RuleScope.ITEM,
        False,
        StaticApplicability.APPLICABLE,
        GatePolicy("reject", "manual_review", "continue"),
    )
    second = RuleDefinition(
        RuleId("rule-a"),
        RuleLevel.L1,
        RuleScope.ITEM,
        True,
        StaticApplicability.APPLICABLE,
        GatePolicy("reject", "reject", "reject"),
    )
    return VerificationReport(
        (artifact,),
        (first, second),
        (
            RuleResult(second.rule_id, RuleStatus.PASS, (artifact.artifact_id,), 0.5),
            RuleResult(
                first.rule_id, RuleStatus.WARNING, (artifact.artifact_id,), None
            ),
        ),
    )


def _open_store(root):
    module = _module()
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return module._open_production_report_store(root_fd)
    finally:
        os.close(root_fd)


def _report_directory(root, attempt_id: str = "attempt"):
    return root / "jobs" / "job" / "reports" / attempt_id


class _IoTrace:
    def __init__(self) -> None:
        self.real_open, self.real_fsync = os.open, os.fsync
        self.real_link, self.real_unlink = os.link, os.unlink
        self.real_write = os.write
        self.names: dict[int, str] = {}
        self.events: list[str] = []

    def open(self, path, flags, mode=0o777, *, dir_fd=None):
        fd = self.real_open(path, flags, mode, dir_fd=dir_fd)
        self.names[fd] = os.fspath(path)
        self.events.append(f"open:{path}")
        return fd

    def fsync(self, fd: int) -> None:
        self.events.append(f"fsync:{self.names.get(fd, 'root')}")
        self.real_fsync(fd)

    def link(self, src, dst, **kwargs):
        self.events.append(f"link:{dst}")
        return self.real_link(src, dst, **kwargs)

    def unlink(self, path, *, dir_fd=None):
        self.events.append(f"unlink:{path}")
        return self.real_unlink(path, dir_fd=dir_fd)


def test_private_surface_signatures_and_for_attempt_performs_no_io(tmp_path) -> None:
    module = _module()
    assert module.__all__ == ()
    assert str(inspect.signature(module._open_production_report_store)) == (
        "(root_fd: 'int', /) -> '_ProductionReportStore'"
    )
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        assert list(tmp_path.iterdir()) == []
        assert str(inspect.signature(repository.put)) == (
            "(request: 'GenerationRequest', report: 'VerificationReport', /) -> 'None'"
        )
        assert str(inspect.signature(repository.__call__)) == (
            "() -> 'VerificationReport | None'"
        )
        assert str(inspect.signature(type(repository).__call__)) == (
            "(self, /) -> 'VerificationReport | None'"
        )
    finally:
        repository.close()
        store.close()


def test_put_is_canonical_durable_and_exactly_readable(tmp_path) -> None:
    request, report = _request(), _report()
    store = _open_store(tmp_path)
    repository = store.for_attempt(request.job_id, request.attempt_id)
    try:
        repository.put(request, report)

        assert repository() == report
        directory = tmp_path / "jobs" / "job" / "reports" / "attempt"
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat.S_IMODE((directory / "report.json").stat().st_mode) == 0o600
        assert stat.S_IMODE((directory / "metadata.json").stat().st_mode) == 0o600
        expected_report = {
            "artifacts": [
                {
                    "artifact_id": "artifact-1",
                    "sha256": report.artifacts[0].sha256.value,
                }
            ],
            "results": [
                {
                    "affected_artifact_ids": ["artifact-1"],
                    "rule_id": "rule-a",
                    "score": float.hex(0.5),
                    "status": "PASS",
                },
                {
                    "affected_artifact_ids": ["artifact-1"],
                    "rule_id": "rule-b",
                    "score": None,
                    "status": "WARNING",
                },
            ],
            "rules": [
                {
                    "applicability": "APPLICABLE",
                    "gate_policy": {
                        "on_fail": "reject",
                        "on_unverifiable": "manual_review",
                        "on_warning": "continue",
                    },
                    "level": "L2",
                    "required": False,
                    "rule_id": "rule-b",
                    "scope": "ITEM",
                },
                {
                    "applicability": "APPLICABLE",
                    "gate_policy": {
                        "on_fail": "reject",
                        "on_unverifiable": "reject",
                        "on_warning": "reject",
                    },
                    "level": "L1",
                    "required": True,
                    "rule_id": "rule-a",
                    "scope": "ITEM",
                },
            ],
            "schema": "specstyle.production_report.v1",
        }
        report_bytes = (directory / "report.json").read_bytes()
        assert report_bytes == json.dumps(
            expected_report, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        assert json.loads((directory / "metadata.json").read_bytes()) == {
            "artifact_id": "artifact-1",
            "artifact_sha256": report.artifacts[0].sha256.value,
            "compiled_spec_hash": request.compiled_spec.compiled_spec_hash.value,
            "generation_fingerprint": request.generation_fingerprint.value,
            "job_id": "job",
            "attempt_id": "attempt",
            "media_type": "application/json",
            "output_profile": "xhs_grid",
            "report_sha256": hash_bytes(report_bytes).value,
            "request_hash": request.request_hash.value,
            "schema": "specstyle.production_report.v1",
            "size_bytes": len(report_bytes),
        }
    finally:
        repository.close()
        store.close()


def test_reports_for_distinct_attempts_coexist(tmp_path) -> None:
    first_request, second_request = _request("attempt-1"), _request("attempt-2")
    first_report, second_report = _report("artifact-1"), _report("artifact-2")
    store = _open_store(tmp_path)
    first = store.for_attempt(first_request.job_id, first_request.attempt_id)
    second = store.for_attempt(second_request.job_id, second_request.attempt_id)
    try:
        assert first() is None
        assert second() is None
        first.put(first_request, first_report)
        second.put(second_request, second_report)
        assert first() == first_report
        assert second() == second_report
    finally:
        first.close()
        second.close()
        store.close()


def test_duplicate_put_is_idempotent_and_collision_never_overwrites(tmp_path) -> None:
    request, report = _request(), _report()
    changed = VerificationReport(
        report.artifacts,
        report.rules,
        (replace(report.results[0], score=0.25), report.results[1]),
    )
    store = _open_store(tmp_path)
    repository = store.for_attempt(request.job_id, request.attempt_id)
    try:
        repository.put(request, report)
        directory = _report_directory(tmp_path)
        before = (
            (directory / "report.json").read_bytes(),
            (directory / "metadata.json").read_bytes(),
        )
        inode = (directory / "metadata.json").stat().st_ino

        repository.put(request, report)
        assert (directory / "metadata.json").stat().st_ino == inode
        with pytest.raises(
            InfrastructureError, match="^production report store corrupted$"
        ):
            repository.put(request, changed)

        assert (
            (directory / "report.json").read_bytes(),
            (directory / "metadata.json").read_bytes(),
        ) == before
        assert repository() == report
    finally:
        repository.close()
        store.close()


def test_request_binding_and_report_shape_fail_before_io(tmp_path) -> None:
    request, report = _request(), _report()
    two_artifacts = VerificationReport(
        (
            report.artifacts[0],
            ArtifactRef(ArtifactId("artifact-2"), hash_bytes(b"second")),
        ),
        (),
        (),
    )
    store = _open_store(tmp_path)
    repository = store.for_attempt(request.job_id, request.attempt_id)
    try:
        for invalid_request, invalid_report in (
            (replace(request, attempt_id=AttemptId("other")), report),
            (replace(request, job_id=JobId("other")), report),
            (request, two_artifacts),
        ):
            with pytest.raises(DomainError, match="^invalid production report$"):
                repository.put(invalid_request, invalid_report)
        assert list(tmp_path.iterdir()) == []
    finally:
        repository.close()
        store.close()


def test_report_and_store_close_are_idempotent(tmp_path) -> None:
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    live = store.for_attempt(JobId("job"), AttemptId("live"))
    repository.close()
    repository.close()
    with pytest.raises(
        InfrastructureError, match="^production report repository closed$"
    ):
        repository()
    store.close()
    store.close()
    with pytest.raises(InfrastructureError, match="^production report store closed$"):
        store.for_attempt(JobId("job"), AttemptId("new"))
    with pytest.raises(InfrastructureError, match="^production report store closed$"):
        live.put(_request("live"), _report())
    live.close()


@pytest.mark.parametrize("explicit_close", (True, False))
def test_attempt_lock_registry_releases_repositories(
    tmp_path, explicit_close: bool
) -> None:
    store = _open_store(tmp_path)
    try:
        for index in range(2_000):
            repository = store.for_attempt(JobId("job"), AttemptId(f"attempt-{index}"))
            if explicit_close:
                repository.close()
        del repository
        gc.collect()
        assert len(store._locks) == 0
    finally:
        store.close()


def test_live_repositories_share_only_the_same_attempt_holder(tmp_path) -> None:
    store = _open_store(tmp_path)
    first = store.for_attempt(JobId("job"), AttemptId("attempt"))
    second = store.for_attempt(JobId("job"), AttemptId("attempt"))
    other = store.for_attempt(JobId("job"), AttemptId("other"))
    try:
        assert first._holder is second._holder
        assert first._holder is not other._holder
    finally:
        first.close()
        second.close()
        other.close()
        store.close()


@pytest.mark.parametrize(
    "link_level", ("jobs", "job", "reports", "attempt", "report", "metadata")
)
def test_symlinks_are_rejected_without_touching_targets(
    tmp_path, link_level: str
) -> None:
    outside = tmp_path.parent / f"outside-report-{link_level}"
    outside.mkdir()
    target = outside / "target"
    target.write_bytes(b"do not touch")
    jobs = tmp_path / "jobs"
    if link_level == "jobs":
        jobs.symlink_to(outside, target_is_directory=True)
    else:
        jobs.mkdir(mode=0o700)
        job = jobs / "job"
        if link_level == "job":
            job.symlink_to(outside, target_is_directory=True)
        else:
            job.mkdir(mode=0o700)
            reports = job / "reports"
            if link_level == "reports":
                reports.symlink_to(outside, target_is_directory=True)
            else:
                reports.mkdir(mode=0o700)
                attempt = reports / "attempt"
                if link_level == "attempt":
                    attempt.symlink_to(outside, target_is_directory=True)
                else:
                    attempt.mkdir(mode=0o700)
                    name = "report.json" if link_level == "report" else "metadata.json"
                    (attempt / name).symlink_to(target)
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        with pytest.raises(
            InfrastructureError, match="^production report store corrupted$"
        ):
            repository.put(_request(), _report())
        assert target.read_bytes() == b"do not touch"
    finally:
        repository.close()
        store.close()


@pytest.mark.parametrize("name", ("report.json", "metadata.json"))
def test_hardlinked_committed_files_are_rejected_without_mutation(
    tmp_path, name: str
) -> None:
    request, report = _request(), _report()
    store = _open_store(tmp_path)
    repository = store.for_attempt(request.job_id, request.attempt_id)
    repository.put(request, report)
    path = _report_directory(tmp_path) / name
    outside = tmp_path.parent / f"report-hardlink-{name}"
    os.link(path, outside)
    before = outside.read_bytes()
    try:
        with pytest.raises(
            InfrastructureError, match="^production report store corrupted$"
        ):
            repository()
        assert outside.read_bytes() == before
        assert path.exists()
    finally:
        repository.close()
        store.close()


def test_content_is_fsynced_before_metadata_commit_marker(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    trace = _IoTrace()
    for operation in ("open", "fsync", "link", "unlink"):
        monkeypatch.setattr(module.os, operation, getattr(trace, operation))
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        repository.put(_request(), _report())
    finally:
        repository.close()
        store.close()
    report_temp = next(
        event[5:]
        for event in trace.events
        if event.startswith("open:.specstyle-report.")
    )
    metadata_temp = next(
        event[5:]
        for event in trace.events
        if event.startswith("open:.specstyle-metadata.")
    )
    report_order = [
        trace.events.index(f"fsync:{report_temp}"),
        trace.events.index("link:report.json"),
        trace.events.index(f"unlink:{report_temp}"),
    ]
    metadata_order = [
        trace.events.index(f"fsync:{metadata_temp}"),
        trace.events.index("link:metadata.json"),
        trace.events.index(f"unlink:{metadata_temp}"),
    ]
    assert report_order == sorted(report_order)
    assert metadata_order == sorted(metadata_order)
    assert "fsync:attempt" in trace.events[report_order[-1] + 1 : metadata_order[0]]


def test_failed_metadata_commit_leaves_recoverable_content_only_partial(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    real_link, fail_once = os.link, True

    def flaky_link(src, dst, **kwargs):
        nonlocal fail_once
        if dst == "metadata.json" and fail_once:
            fail_once = False
            raise OSError("sensitive link detail")
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(module.os, "link", flaky_link)
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        with pytest.raises(
            InfrastructureError, match="^production report store unavailable$"
        ) as error:
            repository.put(_request(), _report())
        assert "sensitive" not in str(error.value)
        directory = _report_directory(tmp_path)
        assert (directory / "report.json").is_file()
        assert not (directory / "metadata.json").exists()
        assert repository() is None
        repository.put(_request(), _report())
        assert repository() == _report()
    finally:
        repository.close()
        store.close()


def test_short_writes_are_retried_until_report_and_metadata_are_exact(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    real_write = os.write
    sizes: list[int] = []

    def short_write(fd: int, content: bytes) -> int:
        size = real_write(fd, content[:7])
        sizes.append(size)
        return size

    monkeypatch.setattr(module.os, "write", short_write)
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        repository.put(_request(), _report())
        assert repository() == _report()
        assert len(sizes) > 2
        assert max(sizes) <= 7
    finally:
        repository.close()
        store.close()


@pytest.mark.parametrize("prefix", (".specstyle-report.", ".specstyle-metadata."))
def test_retry_recovers_only_linked_reserved_temp_alias(
    tmp_path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    module = _module()
    real_unlink, fail_once = os.unlink, True

    def flaky_unlink(path, *, dir_fd=None):
        nonlocal fail_once
        if os.fspath(path).startswith(prefix) and fail_once:
            fail_once = False
            raise OSError("sensitive unlink detail")
        return real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "unlink", flaky_unlink)
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        with pytest.raises(
            InfrastructureError, match="^production report store unavailable$"
        ):
            repository.put(_request(), _report())
        directory = _report_directory(tmp_path)
        aliases = list(directory.glob(f"{prefix}*.tmp"))
        assert len(aliases) == 1
        final = directory / (
            "report.json" if prefix == ".specstyle-report." else "metadata.json"
        )
        assert final.stat().st_ino == aliases[0].stat().st_ino
        monkeypatch.setattr(module.os, "unlink", real_unlink)
        repository.put(_request(), _report())
        assert repository() == _report()
        assert not list(directory.glob(".specstyle-*.tmp"))
    finally:
        repository.close()
        store.close()


@pytest.mark.parametrize("kind", ("orphan", "malformed", "extra_link"))
def test_temp_namespace_anomalies_fail_closed_without_deletion(
    tmp_path, kind: str
) -> None:
    module = _module()
    directory = _report_directory(tmp_path)
    directory.mkdir(parents=True, mode=0o700)
    first = directory / ".specstyle-report.00000000000000000000000000000000.tmp"
    if kind == "malformed":
        first = directory / ".specstyle-report.not-hex.tmp"
        first.write_bytes(b"orphan")
    elif kind == "orphan":
        first.write_bytes(b"orphan")
    else:
        final = directory / "report.json"
        final.write_bytes(module._canonical(module._report_primitive(_report())))
        os.link(final, first)
        os.link(
            final,
            directory / ".specstyle-report.11111111111111111111111111111111.tmp",
        )
    first.chmod(0o600)
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        with pytest.raises(
            InfrastructureError, match="^production report store corrupted$"
        ):
            repository.put(_request(), _report())
        assert first.exists()
    finally:
        repository.close()
        store.close()


def test_cleanup_failure_preserves_primary_and_orphan_fails_closed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    trace = _IoTrace()

    def failed_write(fd: int, content: bytes) -> int:
        if trace.names.get(fd, "").startswith(".specstyle-report."):
            raise OSError("sensitive write detail")
        return trace.real_write(fd, content)

    def failed_cleanup(path, *, dir_fd=None):
        if os.fspath(path).startswith(".specstyle-report."):
            raise OSError("sensitive cleanup detail")
        return trace.real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "open", trace.open)
    monkeypatch.setattr(module.os, "write", failed_write)
    monkeypatch.setattr(module.os, "unlink", failed_cleanup)
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        with pytest.raises(
            InfrastructureError, match="^production report store unavailable$"
        ) as error:
            repository.put(_request(), _report())
        assert "sensitive" not in str(error.value)
        monkeypatch.setattr(module.os, "write", trace.real_write)
        monkeypatch.setattr(module.os, "unlink", trace.real_unlink)
        with pytest.raises(
            InfrastructureError, match="^production report store corrupted$"
        ):
            repository.put(_request(), _report())
        assert list(_report_directory(tmp_path).glob(".specstyle-report.*.tmp"))
    finally:
        repository.close()
        store.close()


def _oversized_report() -> VerificationReport:
    artifact = _report().artifacts
    policy = GatePolicy("reject", "reject", "continue")
    rules = tuple(
        RuleDefinition(
            RuleId(f"r{index:05d}{'x' * 120}"),
            RuleLevel.L1,
            RuleScope.ITEM,
            False,
            StaticApplicability.NOT_APPLICABLE,
            policy,
        )
        for index in range(5_500)
    )
    return VerificationReport(artifact, rules, ())


def test_bounded_constants_and_oversized_report_fail_before_io(tmp_path) -> None:
    module = _module()
    report = _oversized_report()
    assert module._MAX_REPORT == 1024 * 1024
    assert module._MAX_METADATA == 4096
    assert len(module._canonical(module._report_primitive(report))) > module._MAX_REPORT
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        with pytest.raises(DomainError, match="^invalid production report$"):
            repository.put(_request(), report)
        assert list(tmp_path.iterdir()) == []
    finally:
        repository.close()
        store.close()


def test_oversized_metadata_fails_before_directory_creation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_encode_metadata",
        lambda _request, _report, _encoded: b"x" * (module._MAX_METADATA + 1),
    )
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        with pytest.raises(DomainError, match="^invalid production report$"):
            repository.put(_request(), _report())
        assert list(tmp_path.iterdir()) == []
    finally:
        repository.close()
        store.close()


def test_oversized_sparse_report_is_rejected_before_content_read(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    request, report = _request(), _report()
    store = _open_store(tmp_path)
    repository = store.for_attempt(request.job_id, request.attempt_id)
    repository.put(request, report)
    directory = _report_directory(tmp_path)
    metadata = json.loads((directory / "metadata.json").read_bytes())
    metadata["size_bytes"] = module._MAX_REPORT + 1
    (directory / "metadata.json").write_bytes(module._canonical(metadata))
    (directory / "metadata.json").chmod(0o600)
    with (directory / "report.json").open("r+b") as output:
        output.truncate(module._MAX_REPORT + 1)
    trace, real_read = _IoTrace(), os.read

    def guarded_read(fd: int, amount: int) -> bytes:
        assert trace.names.get(fd) != "report.json"
        return real_read(fd, amount)

    monkeypatch.setattr(module.os, "open", trace.open)
    monkeypatch.setattr(module.os, "read", guarded_read)
    try:
        with pytest.raises(
            InfrastructureError, match="^production report store corrupted$"
        ):
            repository()
    finally:
        repository.close()
        store.close()


@pytest.mark.parametrize("failed_parent", ("root", "jobs", "job", "reports"))
def test_retry_resyncs_each_parent_after_directory_creation_fsync_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch, failed_parent: str
) -> None:
    module = _module()
    trace, inject = _IoTrace(), True

    def flaky_fsync(fd: int) -> None:
        nonlocal inject
        name = trace.names.get(fd, "root")
        trace.events.append(f"fsync:{name}")
        if name == failed_parent and inject:
            inject = False
            raise OSError("sensitive parent sync detail")
        trace.real_fsync(fd)

    monkeypatch.setattr(module.os, "open", trace.open)
    monkeypatch.setattr(module.os, "fsync", flaky_fsync)
    store = _open_store(tmp_path)
    repository = store.for_attempt(JobId("job"), AttemptId("attempt"))
    try:
        with pytest.raises(
            InfrastructureError, match="^production report store unavailable$"
        ):
            repository.put(_request(), _report())
        trace.events.clear()
        repository.put(_request(), _report())
        assert f"fsync:{failed_parent}" in trace.events
        assert repository() == _report()
    finally:
        repository.close()
        store.close()

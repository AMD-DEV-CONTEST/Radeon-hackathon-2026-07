from __future__ import annotations

import gc
import inspect
import json
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.identifiers import ArtifactId, JobId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.observability.hashing import hash_bytes
from specstyle.workflow import production_artifacts


def _artifact(
    content: bytes = b"production artifact",
    artifact_id: str = "artifact-1",
) -> GeneratedArtifact:
    return GeneratedArtifact(
        ArtifactRef(ArtifactId(artifact_id), hash_bytes(content)),
        content,
        Sha256("1" * 64),
        Sha256("2" * 64),
    )


def _open_store(root: os.PathLike[str]):
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return production_artifacts._open_production_artifact_store(root_fd)
    finally:
        os.close(root_fd)


def _open_repository(root: os.PathLike[str]):
    store = _open_store(root)
    return store, store.for_job(JobId("job-1"))


def _artifact_directory(root, artifact_id: str = "artifact-1"):
    return root / "jobs" / "job-1" / "artifacts" / artifact_id


class _IoTrace:
    def __init__(self) -> None:
        self.real_open, self.real_fsync = os.open, os.fsync
        self.real_link, self.real_unlink = os.link, os.unlink
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


def test_private_surface_signature_and_for_job_performs_no_io(tmp_path) -> None:
    assert production_artifacts.__all__ == ()
    assert (
        str(inspect.signature(production_artifacts._open_production_artifact_store))
        == "(root_fd: 'int', /) -> '_ProductionArtifactStore'"
    )

    store, repository = _open_repository(tmp_path)
    try:
        assert list(tmp_path.iterdir()) == []
        assert str(inspect.signature(repository.put)) == (
            "(artifact: 'GeneratedArtifact', /) -> 'None'"
        )
        assert str(inspect.signature(repository.__call__)) == (
            "(artifact_ref: 'ArtifactRef', /) -> 'GeneratedArtifact | None'"
        )
        assert str(inspect.signature(repository.get_by_id)) == (
            "(artifact_id: 'ArtifactId', /) -> 'GeneratedArtifact | None'"
        )
    finally:
        store.close()


def test_put_is_durable_commit_and_readback_is_exact(tmp_path) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    try:
        repository.put(artifact)

        assert repository(artifact.ref) == artifact
        job_dir = tmp_path / "jobs" / "job-1"
        artifact_dir = _artifact_directory(tmp_path)
        assert stat.S_IMODE((tmp_path / "jobs").stat().st_mode) == 0o700
        assert stat.S_IMODE(job_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE((job_dir / "artifacts").stat().st_mode) == 0o700
        assert stat.S_IMODE(artifact_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE((artifact_dir / "artifact.png").stat().st_mode) == 0o600
        assert stat.S_IMODE((artifact_dir / "metadata.json").stat().st_mode) == 0o600
        assert (artifact_dir / "artifact.png").read_bytes() == artifact.content

        expected = {
            "schema": "specstyle.production_artifact.v1",
            "job_id": "job-1",
            "artifact_id": "artifact-1",
            "content_sha256": artifact.ref.sha256.value,
            "size_bytes": len(artifact.content),
            "media_type": "image/png",
            "request_hash": artifact.request_hash.value,
            "generation_fingerprint": artifact.generation_fingerprint.value,
        }
        metadata = (artifact_dir / "metadata.json").read_bytes()
        assert json.loads(metadata) == expected
        assert metadata == json.dumps(
            expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    finally:
        store.close()


def test_get_by_id_reads_committed_artifact_without_a_known_hash(tmp_path) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    try:
        assert repository.get_by_id(ArtifactId("missing")) is None

        repository.put(artifact)

        assert repository.get_by_id(ArtifactId("artifact-1")) == artifact
    finally:
        store.close()


@pytest.mark.parametrize("mutation", ["job_id", "artifact_id", "content_hash"])
def test_get_by_id_fails_closed_on_bound_identity_or_hash_mismatch(
    tmp_path, mutation: str
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    try:
        repository.put(artifact)
        directory = _artifact_directory(tmp_path)
        if mutation == "content_hash":
            (directory / "artifact.png").write_bytes(b"x" * len(artifact.content))
        else:
            path = directory / "metadata.json"
            metadata = json.loads(path.read_bytes())
            metadata[mutation] = "other"
            path.write_bytes(
                json.dumps(
                    metadata,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
            )

        with pytest.raises(
            InfrastructureError, match="^production artifact store corrupted$"
        ):
            repository.get_by_id(ArtifactId("artifact-1"))
    finally:
        store.close()


def test_get_by_id_rejects_a_forged_artifact_identifier(tmp_path) -> None:
    store, repository = _open_repository(tmp_path)
    hostile = ArtifactId("artifact-1")
    object.__setattr__(hostile, "value", "../artifact-1")
    try:
        with pytest.raises(DomainError, match="^invalid production artifact id$"):
            repository.get_by_id(hostile)
        assert list(tmp_path.iterdir()) == []
    finally:
        store.close()


def test_job_repository_persists_and_reads_multiple_artifacts(tmp_path) -> None:
    first = _artifact(b"first artifact", "artifact-1")
    second = _artifact(b"second artifact", "artifact-2")
    store, repository = _open_repository(tmp_path)
    try:
        repository.put(first)
        repository.put(second)

        assert repository(first.ref) == first
        assert repository(second.ref) == second
        artifacts = tmp_path / "jobs" / "job-1" / "artifacts"
        assert (artifacts / "artifact-1" / "artifact.png").read_bytes() == first.content
        assert (
            artifacts / "artifact-2" / "artifact.png"
        ).read_bytes() == second.content
        assert (artifacts / "artifact-1" / "metadata.json").is_file()
        assert (artifacts / "artifact-2" / "metadata.json").is_file()
    finally:
        store.close()


def test_duplicate_put_is_idempotent_and_clean_absence_is_none(tmp_path) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    try:
        assert repository(artifact.ref) is None

        repository.put(artifact)
        metadata_before = (_artifact_directory(tmp_path) / "metadata.json").stat()
        repository.put(artifact)
        metadata_after = (_artifact_directory(tmp_path) / "metadata.json").stat()

        assert repository(artifact.ref) == artifact
        assert metadata_after.st_ino == metadata_before.st_ino
    finally:
        store.close()


def test_content_only_partial_write_can_be_completed(tmp_path) -> None:
    artifact = _artifact()
    artifact_dir = _artifact_directory(tmp_path)
    artifact_dir.mkdir(parents=True, mode=0o700)
    content_path = artifact_dir / "artifact.png"
    content_path.write_bytes(artifact.content)
    content_path.chmod(0o600)

    store, repository = _open_repository(tmp_path)
    try:
        assert repository(artifact.ref) is None
        repository.put(artifact)
        assert repository(artifact.ref) == artifact
    finally:
        store.close()


def test_repository_and_store_close_are_idempotent(tmp_path) -> None:
    store, repository = _open_repository(tmp_path)
    live_repository = store.for_job(JobId("job-live"))

    repository.close()
    repository.close()
    with pytest.raises(
        InfrastructureError, match="production artifact repository closed"
    ):
        repository(_artifact().ref)

    store.close()
    store.close()
    with pytest.raises(InfrastructureError, match="production artifact store closed"):
        store.for_job(JobId("job-2"))
    with pytest.raises(InfrastructureError, match="production artifact store closed"):
        live_repository.put(_artifact())
    live_repository.close()


@pytest.mark.parametrize("explicit_close", (True, False))
def test_job_lock_registry_releases_closed_or_collected_repositories(
    tmp_path, explicit_close: bool
) -> None:
    store = _open_store(tmp_path)
    try:
        for index in range(10_000):
            repository = store.for_job(JobId(f"job-{index}"))
            if explicit_close:
                repository.close()
        del repository
        gc.collect()
        assert len(store._locks) == 0
    finally:
        store.close()


def test_live_repositories_share_holder_without_cross_job_aliasing(tmp_path) -> None:
    artifact = _artifact()
    store = _open_store(tmp_path)
    first = store.for_job(JobId("job-1"))
    second = store.for_job(JobId("job-1"))
    third = store.for_job(JobId("job-1"))
    other = store.for_job(JobId("job-2"))
    try:
        assert first._holder is second._holder is third._holder
        assert other._holder is not first._holder
        holder = second._holder
        first.close()
        assert second._holder is holder
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (
                pool.submit(second.put, artifact),
                pool.submit(third.put, artifact),
            )
        assert all(future.exception() is None for future in futures)
        content_path = _artifact_directory(tmp_path) / "artifact.png"
        inode = content_path.stat().st_ino
        second.put(artifact)
        assert content_path.stat().st_ino == inode
    finally:
        second.close()
        third.close()
        other.close()
        store.close()


def test_repository_close_race_never_dereferences_a_released_holder(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    entered, release = threading.Event(), threading.Event()
    real_validate = production_artifacts._validate_artifact

    def blocked_validate(value):
        entered.set()
        assert release.wait(timeout=5)
        return real_validate(value)

    monkeypatch.setattr(production_artifacts, "_validate_artifact", blocked_validate)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(repository.put, artifact)
            assert entered.wait(timeout=5)
            repository.close()
            release.set()
        assert future.result() is None
    finally:
        release.set()
        store.close()


@pytest.mark.parametrize(
    "link_level", ["jobs", "job", "artifacts", "artifact_id", "artifact", "metadata"]
)
def test_symlinks_are_rejected_without_touching_the_target(
    tmp_path, link_level: str
) -> None:
    artifact = _artifact()
    outside = tmp_path.parent / f"outside-{link_level}"
    outside.mkdir()
    target = outside / "target"
    target.write_bytes(b"do not touch")
    jobs = tmp_path / "jobs"

    if link_level == "jobs":
        jobs.symlink_to(outside, target_is_directory=True)
    else:
        jobs.mkdir(mode=0o700)
        job_dir = jobs / "job-1"
        if link_level == "job":
            job_dir.symlink_to(outside, target_is_directory=True)
        else:
            job_dir.mkdir(mode=0o700)
            artifacts_dir = job_dir / "artifacts"
            if link_level == "artifacts":
                artifacts_dir.symlink_to(outside, target_is_directory=True)
            else:
                artifacts_dir.mkdir(mode=0o700)
                artifact_dir = artifacts_dir / "artifact-1"
                if link_level == "artifact_id":
                    artifact_dir.symlink_to(outside, target_is_directory=True)
                else:
                    artifact_dir.mkdir(mode=0o700)
                    name = (
                        "artifact.png" if link_level == "artifact" else "metadata.json"
                    )
                    (artifact_dir / name).symlink_to(target)

    store, repository = _open_repository(tmp_path)
    try:
        with pytest.raises(
            InfrastructureError, match="production artifact store corrupted"
        ):
            repository.put(artifact)
        assert target.read_bytes() == b"do not touch"
    finally:
        store.close()


def test_hardlinked_content_is_rejected_without_mutation(tmp_path) -> None:
    artifact = _artifact()
    outside = tmp_path.parent / "outside-hardlink"
    outside.write_bytes(artifact.content)
    outside.chmod(0o644)
    artifact_dir = _artifact_directory(tmp_path)
    artifact_dir.mkdir(parents=True, mode=0o700)
    os.link(outside, artifact_dir / "artifact.png")
    before = outside.stat()

    store = _open_store(tmp_path)
    try:
        with pytest.raises(
            InfrastructureError, match="production artifact store corrupted"
        ):
            store.for_job(JobId("job-1")).put(artifact)
        after = outside.stat()
        assert outside.read_bytes() == artifact.content
        assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode) == 0o644
        assert not (artifact_dir / "metadata.json").exists()
    finally:
        store.close()


def _mutated_metadata(valid: bytes, mutation: str) -> bytes:
    parsed = json.loads(valid)
    if mutation == "extra":
        parsed["extra"] = "forbidden"
    elif mutation == "missing":
        parsed.pop("media_type")
    elif mutation == "wrong_schema":
        parsed["schema"] = "specstyle.production_artifact.v2"
    elif mutation == "boolean_size":
        parsed["size_bytes"] = True
    elif mutation == "zero_size":
        parsed["size_bytes"] = 0
    elif mutation == "noncanonical":
        return json.dumps(parsed, indent=2).encode("ascii")
    elif mutation == "duplicate":
        return valid.replace(
            b'{"artifact_id":',
            b'{"artifact_id":"artifact-1","artifact_id":',
            1,
        )
    elif mutation == "nan":
        parsed["size_bytes"] = float("nan")
    return json.dumps(
        parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing",
        "wrong_schema",
        "boolean_size",
        "zero_size",
        "noncanonical",
        "duplicate",
        "nan",
    ],
)
def test_metadata_parser_rejects_non_exact_json(tmp_path, mutation: str) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    repository.put(artifact)
    metadata_path = _artifact_directory(tmp_path) / "metadata.json"
    metadata_path.write_bytes(_mutated_metadata(metadata_path.read_bytes(), mutation))
    metadata_path.chmod(0o600)

    try:
        with pytest.raises(
            InfrastructureError, match="production artifact store corrupted"
        ):
            repository(artifact.ref)
    finally:
        store.close()


def test_committed_collision_never_overwrites_the_original(tmp_path) -> None:
    original = _artifact()
    collision = _artifact(b"different production artifact")
    store, repository = _open_repository(tmp_path)
    try:
        repository.put(original)
        content_path = _artifact_directory(tmp_path) / "artifact.png"
        metadata_path = _artifact_directory(tmp_path) / "metadata.json"
        before = (content_path.read_bytes(), metadata_path.read_bytes())

        with pytest.raises(
            InfrastructureError, match="production artifact store corrupted"
        ):
            repository.put(collision)

        assert (content_path.read_bytes(), metadata_path.read_bytes()) == before
        assert repository(original.ref) == original
    finally:
        store.close()


def test_short_writes_are_retried_until_both_files_are_complete(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact(b"a sufficiently long production artifact")
    store, repository = _open_repository(tmp_path)
    real_write = os.write
    write_sizes: list[int] = []

    def short_write(fd: int, content: bytes) -> int:
        size = real_write(fd, content[:3])
        write_sizes.append(size)
        return size

    monkeypatch.setattr(production_artifacts.os, "write", short_write)
    try:
        repository.put(artifact)
        assert repository(artifact.ref) == artifact
        assert len(write_sizes) > 2
        assert max(write_sizes) <= 3
    finally:
        store.close()


def test_content_is_fsynced_before_metadata_commit_marker(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    trace = _IoTrace()
    for operation in ("open", "fsync", "link", "unlink"):
        monkeypatch.setattr(
            production_artifacts.os, operation, getattr(trace, operation)
        )
    try:
        repository.put(artifact)
    finally:
        store.close()

    artifact_temp = next(
        event[5:]
        for event in trace.events
        if event.startswith("open:.specstyle-artifact.")
    )
    metadata_temp = next(
        event[5:]
        for event in trace.events
        if event.startswith("open:.specstyle-metadata.")
    )
    artifact_order = [
        trace.events.index(f"fsync:{artifact_temp}"),
        trace.events.index("link:artifact.png"),
        trace.events.index(f"unlink:{artifact_temp}"),
    ]
    metadata_order = [
        trace.events.index(f"fsync:{metadata_temp}"),
        trace.events.index("link:metadata.json"),
        trace.events.index(f"unlink:{metadata_temp}"),
    ]
    assert artifact_order == sorted(artifact_order)
    assert metadata_order == sorted(metadata_order)
    assert (
        "fsync:artifact-1" in trace.events[artifact_order[-1] + 1 : metadata_order[0]]
    )


def test_unsupported_commit_link_leaves_recoverable_content_only_partial(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    real_link = os.link
    fail_marker = True

    def flaky_link(src, dst, **kwargs):
        nonlocal fail_marker
        if dst == "metadata.json" and fail_marker:
            fail_marker = False
            raise OSError("sensitive unsupported-link detail")
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(production_artifacts.os, "link", flaky_link)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store unavailable$"
        ) as error:
            repository.put(artifact)
        assert "sensitive" not in str(error.value)
        artifact_dir = _artifact_directory(tmp_path)
        assert (artifact_dir / "artifact.png").read_bytes() == artifact.content
        assert not (artifact_dir / "metadata.json").exists()
        assert repository(artifact.ref) is None

        repository.put(artifact)
        assert repository(artifact.ref) == artifact
    finally:
        store.close()


def test_noncanonical_artifact_reference_is_rejected(tmp_path) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    repository.put(artifact)
    hostile = ArtifactRef(ArtifactId("artifact-1"), artifact.ref.sha256)
    object.__setattr__(hostile, "artifact_id", "artifact-1")

    try:
        with pytest.raises(
            DomainError, match="^invalid production artifact reference$"
        ):
            repository(hostile)
    finally:
        store.close()


def test_read_flags_are_nonblocking_to_reject_special_files_without_hanging() -> None:
    assert production_artifacts._READ_FLAGS & os.O_NONBLOCK


def test_content_fsync_failure_never_creates_commit_marker(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    trace = _IoTrace()

    def failed_content_fsync(fd: int) -> None:
        if trace.names.get(fd, "").startswith(".specstyle-artifact."):
            raise OSError("sensitive fsync detail")
        trace.real_fsync(fd)

    monkeypatch.setattr(production_artifacts.os, "open", trace.open)
    monkeypatch.setattr(production_artifacts.os, "fsync", failed_content_fsync)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store unavailable$"
        ) as error:
            repository.put(artifact)
        assert "sensitive" not in str(error.value)
        artifact_dir = _artifact_directory(tmp_path)
        assert not (artifact_dir / "artifact.png").exists()
        assert not (artifact_dir / "metadata.json").exists()
    finally:
        store.close()


def test_recovered_content_is_fsynced_again_before_metadata_commit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact()
    artifact_dir = _artifact_directory(tmp_path)
    artifact_dir.mkdir(parents=True, mode=0o700)
    (artifact_dir / "artifact.png").write_bytes(artifact.content)
    (artifact_dir / "artifact.png").chmod(0o600)
    store, repository = _open_repository(tmp_path)
    trace = _IoTrace()
    monkeypatch.setattr(production_artifacts.os, "open", trace.open)
    monkeypatch.setattr(production_artifacts.os, "fsync", trace.fsync)
    try:
        repository.put(artifact)
    finally:
        store.close()

    metadata_open = next(
        index
        for index, event in enumerate(trace.events)
        if event.startswith("open:.specstyle-metadata.")
    )
    assert "fsync:artifact.png" in trace.events[:metadata_open]
    assert "fsync:artifact-1" in trace.events[:metadata_open]


def test_retry_after_commit_directory_fsync_failure_reestablishes_durability(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    trace = _IoTrace()
    metadata_synced = False
    fail_commit_directory = True

    def flaky_fsync(fd: int) -> None:
        nonlocal metadata_synced, fail_commit_directory
        name = trace.names.get(fd, "root")
        trace.events.append(f"fsync:{name}")
        if name.startswith(".specstyle-metadata."):
            metadata_synced = True
        if name == "artifact-1" and metadata_synced and fail_commit_directory:
            fail_commit_directory = False
            raise OSError("sensitive directory sync detail")
        trace.real_fsync(fd)

    monkeypatch.setattr(production_artifacts.os, "open", trace.open)
    monkeypatch.setattr(production_artifacts.os, "fsync", flaky_fsync)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store unavailable$"
        ):
            repository.put(artifact)
        artifact_dir = _artifact_directory(tmp_path)
        assert (artifact_dir / "artifact.png").exists()
        assert (artifact_dir / "metadata.json").exists()

        trace.events.clear()
        repository.put(artifact)
        assert "fsync:artifact.png" in trace.events
        assert "fsync:metadata.json" in trace.events
        assert "fsync:artifact-1" in trace.events
        assert repository(artifact.ref) == artifact
    finally:
        store.close()


@pytest.mark.parametrize("failed_parent", ("root", "jobs", "job-1", "artifacts"))
def test_retry_after_directory_creation_fsync_failure_resyncs_parent_entry(
    tmp_path, monkeypatch: pytest.MonkeyPatch, failed_parent: str
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    trace = _IoTrace()
    inject_failure = True

    def flaky_fsync(fd: int) -> None:
        nonlocal inject_failure
        name = trace.names.get(fd, "root")
        trace.events.append(f"fsync:{name}")
        if name == failed_parent and inject_failure:
            inject_failure = False
            raise OSError("sensitive parent sync detail")
        trace.real_fsync(fd)

    monkeypatch.setattr(production_artifacts.os, "open", trace.open)
    monkeypatch.setattr(production_artifacts.os, "fsync", flaky_fsync)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store unavailable$"
        ):
            repository.put(artifact)
        trace.events.clear()

        repository.put(artifact)
        assert f"fsync:{failed_parent}" in trace.events
        assert repository(artifact.ref) == artifact
    finally:
        store.close()


def test_bounded_io_constants_and_invalid_content_sizes_are_frozen(tmp_path) -> None:
    assert production_artifacts._MAX_PNG == 32 * 1024 * 1024
    assert production_artifacts._MAX_METADATA == 4096
    assert production_artifacts._CHUNK == 64 * 1024
    store, repository = _open_repository(tmp_path)
    try:
        for content in (b"", b"x" * (production_artifacts._MAX_PNG + 1)):
            with pytest.raises(DomainError, match="^invalid production artifact$"):
                repository.put(_artifact(content))
        assert list(tmp_path.iterdir()) == []
    finally:
        store.close()


@pytest.mark.parametrize(
    ("target_prefix", "final_name"),
    (
        (".specstyle-artifact.", "artifact.png"),
        (".specstyle-metadata.", "metadata.json"),
    ),
)
def test_partial_temp_write_never_creates_truncated_final_and_retry_succeeds(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    target_prefix: str,
    final_name: str,
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    trace, real_write = _IoTrace(), os.write
    partial_written = False

    def partial_then_fail(fd: int, content: bytes) -> int:
        nonlocal partial_written
        if trace.names.get(fd, "").startswith(target_prefix):
            if partial_written:
                raise OSError("sensitive partial write detail")
            partial_written = True
            return real_write(fd, content[:1])
        return real_write(fd, content)

    monkeypatch.setattr(production_artifacts.os, "open", trace.open)
    monkeypatch.setattr(production_artifacts.os, "write", partial_then_fail)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store unavailable$"
        ):
            repository.put(artifact)
        artifact_dir = _artifact_directory(tmp_path)
        assert not (artifact_dir / final_name).exists()

        monkeypatch.setattr(production_artifacts.os, "write", real_write)
        repository.put(artifact)
        assert repository(artifact.ref) == artifact
    finally:
        store.close()


@pytest.mark.parametrize(("content", "expected"), ((b"ab", 3), (b"abcd", 3)))
def test_bounded_reader_rejects_short_or_extra_content(
    tmp_path, content: bytes, expected: int
) -> None:
    path = tmp_path / "bounded"
    path.write_bytes(content)
    fd = os.open(path, os.O_RDONLY)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store corrupted$"
        ):
            production_artifacts._read_exact_bounded(fd, expected, 8)
    finally:
        os.close(fd)


def test_reserved_temp_token_collision_is_corruption_without_deletion(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "a" * 32
    collision = tmp_path / f".specstyle-artifact.{token}.tmp"
    collision.write_bytes(b"existing")
    collision.chmod(0o600)
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    root_stat = os.fstat(directory_fd)
    monkeypatch.setattr(production_artifacts.secrets, "token_hex", lambda size: token)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store corrupted$"
        ):
            production_artifacts._open_temp(
                directory_fd, "artifact", (root_stat.st_dev, root_stat.st_uid)
            )
        assert collision.read_bytes() == b"existing"
    finally:
        os.close(directory_fd)


def test_cleanup_failure_preserves_primary_error_and_orphan_fails_closed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    trace, real_write, real_unlink = _IoTrace(), os.write, os.unlink

    def failed_write(fd: int, content: bytes) -> int:
        if trace.names.get(fd, "").startswith(".specstyle-artifact."):
            raise OSError("sensitive primary write detail")
        return real_write(fd, content)

    def failed_cleanup(path, *, dir_fd=None):
        if os.fspath(path).startswith(".specstyle-artifact."):
            raise OSError("sensitive cleanup detail")
        return real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(production_artifacts.os, "open", trace.open)
    monkeypatch.setattr(production_artifacts.os, "write", failed_write)
    monkeypatch.setattr(production_artifacts.os, "unlink", failed_cleanup)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store unavailable$"
        ) as error:
            repository.put(artifact)
        assert "sensitive" not in str(error.value)
        monkeypatch.setattr(production_artifacts.os, "write", real_write)
        monkeypatch.setattr(production_artifacts.os, "unlink", real_unlink)
        with pytest.raises(
            InfrastructureError, match="^production artifact store corrupted$"
        ):
            repository.put(artifact)
        assert list(_artifact_directory(tmp_path).glob(".specstyle-artifact.*.tmp"))
    finally:
        store.close()


def test_read_detects_inode_link_mutation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"x" * (production_artifacts._CHUNK + 1)
    path = tmp_path / "artifact.png"
    path.write_bytes(content)
    path.chmod(0o600)
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    root_stat, real_read, mutated = os.fstat(directory_fd), os.read, False

    def mutating_read(fd: int, amount: int) -> bytes:
        nonlocal mutated
        chunk = real_read(fd, amount)
        if chunk and not mutated:
            mutated = True
            os.link(path, tmp_path / "mutation-alias")
        return chunk

    monkeypatch.setattr(production_artifacts.os, "read", mutating_read)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store corrupted$"
        ):
            production_artifacts._read_file(
                directory_fd,
                "artifact.png",
                (root_stat.st_dev, root_stat.st_uid),
                missing_ok=False,
                expected=len(content),
                maximum=production_artifacts._MAX_PNG,
            )
    finally:
        os.close(directory_fd)


@pytest.mark.parametrize("prefix", (".specstyle-artifact.", ".specstyle-metadata."))
def test_retry_recovers_only_linked_reserved_temp_alias(
    tmp_path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    real_unlink, fail_once = os.unlink, True

    def flaky_unlink(path, *, dir_fd=None):
        nonlocal fail_once
        if os.fspath(path).startswith(prefix) and fail_once:
            fail_once = False
            raise OSError("sensitive unlink detail")
        return real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(production_artifacts.os, "unlink", flaky_unlink)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store unavailable$"
        ):
            repository.put(artifact)
        artifact_dir = _artifact_directory(tmp_path)
        aliases = list(artifact_dir.glob(f"{prefix}*.tmp"))
        assert len(aliases) == 1
        final = artifact_dir / (
            "artifact.png" if "artifact" in prefix else "metadata.json"
        )
        assert final.stat().st_ino == aliases[0].stat().st_ino
        monkeypatch.setattr(production_artifacts.os, "unlink", real_unlink)
        repository.put(artifact)
        assert repository(artifact.ref) == artifact
        assert not list(artifact_dir.glob(".specstyle-*.tmp"))
    finally:
        store.close()


@pytest.mark.parametrize("kind", ("orphan", "malformed", "extra_link"))
def test_temp_namespace_anomalies_fail_closed_without_deletion(
    tmp_path, kind: str
) -> None:
    artifact = _artifact()
    artifact_dir = _artifact_directory(tmp_path)
    artifact_dir.mkdir(parents=True, mode=0o700)
    first = artifact_dir / ".specstyle-artifact.00000000000000000000000000000000.tmp"
    if kind == "malformed":
        first = artifact_dir / ".specstyle-artifact.not-hex.tmp"
        first.write_bytes(b"orphan")
    elif kind == "orphan":
        first.write_bytes(b"orphan")
    else:
        final = artifact_dir / "artifact.png"
        final.write_bytes(artifact.content)
        os.link(final, first)
        os.link(
            final,
            artifact_dir / ".specstyle-artifact.11111111111111111111111111111111.tmp",
        )
    first.chmod(0o600)
    store = _open_store(tmp_path)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store corrupted$"
        ):
            store.for_job(JobId("job-1")).put(artifact)
        assert first.exists()
    finally:
        store.close()


@pytest.mark.parametrize("identical", (True, False))
def test_concurrent_puts_are_idempotent_or_never_overwrite(
    tmp_path, identical: bool
) -> None:
    artifacts = (_artifact(), _artifact() if identical else _artifact(b"conflict"))
    store, repository = _open_repository(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(repository.put, artifact) for artifact in artifacts]
        errors = [future.exception() for future in futures]
        assert sum(error is None for error in errors) == (2 if identical else 1)
        assert all(
            error is None or type(error) is InfrastructureError for error in errors
        )
        assert (_artifact_directory(tmp_path) / "artifact.png").read_bytes() in {
            artifact.content for artifact in artifacts
        }
    finally:
        store.close()


def test_link_eexist_with_identical_competing_claim_is_idempotent(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    real_link, competed = os.link, False

    def competing_link(src, dst, **kwargs):
        nonlocal competed
        if dst == "artifact.png" and not competed:
            competed = True
            competitor = tmp_path / "competing-temp"
            competitor.write_bytes(artifact.content)
            competitor.chmod(0o600)
            real_link(competitor, _artifact_directory(tmp_path) / dst)
            competitor.unlink()
            raise FileExistsError
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(production_artifacts.os, "link", competing_link)
    try:
        repository.put(artifact)
        assert repository(artifact.ref) == artifact
    finally:
        store.close()


def test_oversized_sparse_content_is_rejected_before_content_read(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact()
    store, repository = _open_repository(tmp_path)
    repository.put(artifact)
    artifact_dir = _artifact_directory(tmp_path)
    metadata = json.loads((artifact_dir / "metadata.json").read_bytes())
    metadata["size_bytes"] = production_artifacts._MAX_PNG + 1
    (artifact_dir / "metadata.json").write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("ascii")
    )
    (artifact_dir / "metadata.json").chmod(0o600)
    with (artifact_dir / "artifact.png").open("r+b") as output:
        output.truncate(production_artifacts._MAX_PNG + 1)
    trace, real_read = _IoTrace(), os.read

    def guarded_read(fd: int, amount: int) -> bytes:
        assert trace.names.get(fd) != "artifact.png"
        return real_read(fd, amount)

    monkeypatch.setattr(production_artifacts.os, "open", trace.open)
    monkeypatch.setattr(production_artifacts.os, "read", guarded_read)
    try:
        with pytest.raises(
            InfrastructureError, match="^production artifact store corrupted$"
        ):
            repository(artifact.ref)
    finally:
        store.close()


def test_bounded_reader_requests_at_most_expected_plus_eof_probe(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = production_artifacts._CHUNK + 3
    path = tmp_path / "bounded"
    path.write_bytes(b"x" * expected)
    fd, real_read, returned = os.open(path, os.O_RDONLY), os.read, []

    def tracked_read(target: int, amount: int) -> bytes:
        chunk = real_read(target, amount)
        returned.append((amount, len(chunk)))
        return chunk

    monkeypatch.setattr(production_artifacts.os, "read", tracked_read)
    try:
        assert (
            production_artifacts._read_exact_bounded(fd, expected, expected)
            == b"x" * expected
        )
        assert max(amount for amount, _ in returned) <= production_artifacts._CHUNK
        assert sum(size for _, size in returned) <= expected + 1
        assert returned[-1][0] == 1
    finally:
        os.close(fd)

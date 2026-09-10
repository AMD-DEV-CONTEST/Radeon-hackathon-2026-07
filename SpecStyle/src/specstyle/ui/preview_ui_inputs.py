"""Private staging and descriptor boundary for isolated Preview UI runs."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import uuid

from specstyle.errors import DomainError, InfrastructureError
from specstyle.spec.loader import load_style_spec_text
from specstyle.workflow.preview_run_one import PreviewRunOneFds

_PROMPT_TEMPLATE_ID = "ui-preview-prompt-template"
_PROMPT_TEMPLATE_REVISION = "v1"
_PROMPT_TEMPLATE_SHA256 = (
    "c9fdcd842a7b644b7071312ed69e1c49a5168b8357401b898986277824534265"
)
_MAX_UPLOAD_BYTES = 32 * 1024 * 1024
_PATH_FIELDS = (
    "production_config_root",
    "production_context_evidence_root",
    "preview_config_root",
    "model_root",
    "evidence_root",
    "display_root",
    "style_asset_root",
    "staging_root",
)
_ROOT_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW
_STAGING_SEAL = object()
if hasattr(os, "O_CLOEXEC"):
    _ROOT_FLAGS |= os.O_CLOEXEC
    _FILE_FLAGS |= os.O_CLOEXEC


@dataclass(frozen=True, slots=True)
class PreviewUiRuntimePaths:
    production_config_root: Path
    production_context_evidence_root: Path
    preview_config_root: Path
    model_root: Path
    evidence_root: Path
    display_root: Path
    style_asset_root: Path
    staging_root: Path
    _identities: tuple[tuple[int, int], ...] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        values = tuple(Path(getattr(self, name)) for name in _PATH_FIELDS)
        identities: list[tuple[int, int]] = []
        for name, value in zip(_PATH_FIELDS, values, strict=True):
            try:
                info = value.lstat()
            except OSError:
                raise DomainError(f"{name} unavailable")
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid not in (0, os.geteuid())
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                raise DomainError(f"{name} unavailable")
            object.__setattr__(self, name, value)
            identities.append((info.st_dev, info.st_ino))
        if len(set(identities)) != len(values):
            raise DomainError("preview runtime roots must be distinct")
        object.__setattr__(self, "_identities", tuple(identities))


class PreviewUiInputError(DomainError):
    pass


class PreviewUiCleanupError(InfrastructureError):
    pass


@dataclass(frozen=True, slots=True)
class _Upload:
    path: Path
    identity: tuple[int, int]


class StagedPreviewInputs:
    __slots__ = (
        "_closed",
        "_directory_fd",
        "_directory_identity",
        "_lock",
        "_name",
        "_root_fd",
        "_root_identity",
        "_root_path",
        "_seal",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("staged preview inputs are issued only by staging")

    @property
    def directory(self) -> Path:
        return self._root_path / self._name

    @property
    def source(self) -> Path:
        return self.directory / "source.bin"

    @property
    def style(self) -> Path:
        return self.directory / "style.bin"

    @property
    def spec(self) -> Path:
        return self.directory / "spec.json"

    @property
    def metadata(self) -> Path:
        return self.directory / "metadata.json"

    def __copy__(self) -> StagedPreviewInputs:
        raise TypeError("staged preview inputs cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> StagedPreviewInputs:
        raise TypeError("staged preview inputs cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("staged preview inputs cannot be serialized")


def _upload_path(value: object, label: str) -> _Upload:
    raw = os.fspath(value) if isinstance(value, os.PathLike) else value
    if not isinstance(raw, str):
        raw = getattr(raw, "name", None)
    if not isinstance(raw, str) or not raw:
        raise PreviewUiInputError(f"{label} upload required")
    path = Path(raw)
    try:
        info = path.lstat()
    except OSError:
        raise PreviewUiInputError(f"{label} upload required") from None
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_UPLOAD_BYTES:
        raise PreviewUiInputError(f"{label} upload required")
    return _Upload(path, (info.st_dev, info.st_ino))


def _copy_upload(source: _Upload, directory_fd: int, target: str) -> str:
    try:
        source_fd = os.open(source.path, _FILE_FLAGS)
    except OSError:
        raise PreviewUiInputError("upload unavailable") from None
    output_fd = -1
    try:
        info = os.fstat(source_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or (info.st_dev, info.st_ino) != source.identity
            or not 0 < info.st_size <= _MAX_UPLOAD_BYTES
        ):
            raise PreviewUiInputError("upload unavailable")
        output_fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        digest = hashlib.sha256()
        with os.fdopen(source_fd, "rb", closefd=False) as input_file:
            with os.fdopen(output_fd, "wb") as output_file:
                output_fd = -1
                copied = 0
                while block := input_file.read(1024 * 1024):
                    copied += len(block)
                    if copied > _MAX_UPLOAD_BYTES:
                        raise PreviewUiInputError("upload unavailable")
                    digest.update(block)
                    output_file.write(block)
                output_file.flush()
                os.fsync(output_file.fileno())
        return digest.hexdigest()
    except OSError:
        raise PreviewUiInputError("upload unavailable") from None
    finally:
        os.close(source_fd)
        if output_fd >= 0:
            os.close(output_fd)


def _read_staged(directory_fd: int, name: str) -> bytes:
    descriptor = os.open(name, _FILE_FLAGS, dir_fd=directory_fd)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_UPLOAD_BYTES:
            raise PreviewUiInputError("preview spec invalid")
        parts: list[bytes] = []
        remaining = info.st_size
        while remaining:
            block = os.read(descriptor, min(remaining, 64 * 1024))
            if not block:
                raise PreviewUiInputError("preview spec invalid")
            parts.append(block)
            remaining -= len(block)
        if os.read(descriptor, 1):
            raise PreviewUiInputError("preview spec invalid")
        return b"".join(parts)
    finally:
        os.close(descriptor)


def _metadata(
    source_digest: str,
    style_digest: str,
    spec: bytes,
    positive: object,
    negative: object,
) -> bytes:
    if type(positive) is not str or type(negative) is not str:
        raise PreviewUiInputError("preview prompt invalid")
    try:
        parsed = load_style_spec_text(spec)
    except DomainError:
        raise PreviewUiInputError("preview spec invalid") from None
    payload = {
        "schema_version": "specstyle.preview.job_input.v1",
        "source": {"asset_id": f"source-{source_digest[:16]}"},
        "style": {"asset_id": f"style-{style_digest[:16]}"},
        "prompt": {
            "template_pin": {
                "id": _PROMPT_TEMPLATE_ID,
                "revision": _PROMPT_TEMPLATE_REVISION,
                "sha256": _PROMPT_TEMPLATE_SHA256,
            },
            "preset_id": parsed.style.preset_id,
            "positive": positive,
            "negative": negative,
        },
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()


def _write_private(directory_fd: int, name: str, content: bytes) -> None:
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        with os.fdopen(fd, "wb") as output:
            fd = -1
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.fsync(directory_fd)


def _open_bound_root(path: Path, identity: tuple[int, int]) -> int:
    descriptor = os.open(path, _ROOT_FLAGS)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in (0, os.geteuid())
            or stat.S_IMODE(info.st_mode) & 0o022
            or (info.st_dev, info.st_ino) != identity
        ):
            raise InfrastructureError("preview runtime root identity changed")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _issue_staged(paths: PreviewUiRuntimePaths) -> StagedPreviewInputs:
    root_fd = _open_bound_root(paths.staging_root, paths._identities[7])
    name = f"ui-preview-{uuid.uuid4().hex}"
    directory_fd = -1
    created = False
    try:
        os.mkdir(name, 0o700, dir_fd=root_fd)
        created = True
        directory_fd = os.open(name, _ROOT_FLAGS, dir_fd=root_fd)
        info = os.fstat(directory_fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise InfrastructureError("preview staging unavailable")
        os.fsync(root_fd)
        issued = object.__new__(StagedPreviewInputs)
        issued._closed = False
        issued._directory_fd = directory_fd
        issued._directory_identity = (info.st_dev, info.st_ino)
        issued._lock = threading.Lock()
        issued._name = name
        issued._root_fd = root_fd
        issued._root_identity = paths._identities[7]
        issued._root_path = paths.staging_root
        issued._seal = _STAGING_SEAL
        return issued
    except BaseException:
        if directory_fd >= 0:
            os.close(directory_fd)
        if created:
            try:
                os.rmdir(name, dir_fd=root_fd)
            except OSError:
                pass
        os.close(root_fd)
        raise


def stage_preview_inputs(
    paths: PreviewUiRuntimePaths,
    source: object,
    style: object,
    spec: object,
    positive: str,
    negative: str,
) -> StagedPreviewInputs:
    if type(paths) is not PreviewUiRuntimePaths:
        raise PreviewUiInputError("preview runtime unavailable")
    source_path = _upload_path(source, "source")
    style_path = _upload_path(style, "style")
    spec_path = _upload_path(spec, "spec")
    staged = _issue_staged(paths)
    try:
        source_digest = _copy_upload(source_path, staged._directory_fd, "source.bin")
        style_digest = _copy_upload(style_path, staged._directory_fd, "style.bin")
        _copy_upload(spec_path, staged._directory_fd, "spec.json")
        _write_private(
            staged._directory_fd,
            "metadata.json",
            _metadata(
                source_digest,
                style_digest,
                _read_staged(staged._directory_fd, "spec.json"),
                positive,
                negative,
            ),
        )
        return staged
    except BaseException as error:
        try:
            cleanup_preview_staging(staged)
        except InfrastructureError:
            raise PreviewUiCleanupError("preview staging cleanup failed") from error
        raise


def _validate_staged(staged: object, *, require_open: bool) -> None:
    if (
        type(staged) is not StagedPreviewInputs
        or getattr(staged, "_seal", None) is not _STAGING_SEAL
        or type(getattr(staged, "_closed", None)) is not bool
        or type(getattr(staged, "_root_fd", None)) is not int
        or type(getattr(staged, "_directory_fd", None)) is not int
    ):
        raise DomainError("invalid staged preview inputs")
    if require_open and staged._closed:
        raise InfrastructureError("staged preview inputs are closed")
    if require_open:
        try:
            root = os.fstat(staged._root_fd)
            directory = os.fstat(staged._directory_fd)
        except OSError:
            raise InfrastructureError("staged preview inputs unavailable") from None
        if (
            not stat.S_ISDIR(root.st_mode)
            or (root.st_dev, root.st_ino) != staged._root_identity
            or not stat.S_ISDIR(directory.st_mode)
            or (directory.st_dev, directory.st_ino) != staged._directory_identity
            or directory.st_uid != os.geteuid()
            or stat.S_IMODE(directory.st_mode) != 0o700
        ):
            raise InfrastructureError("staged preview input identity changed")


def cleanup_preview_staging(staged: StagedPreviewInputs) -> None:
    _validate_staged(staged, require_open=False)
    with staged._lock:
        if staged._closed:
            return
        _validate_staged(staged, require_open=True)
        staged._closed = True
    failure = False
    try:
        for name in os.listdir(staged._directory_fd):
            child = os.stat(name, dir_fd=staged._directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(child.st_mode):
                raise OSError
            os.unlink(name, dir_fd=staged._directory_fd)
        os.fsync(staged._directory_fd)
        os.close(staged._directory_fd)
        staged._directory_fd = -1
        os.rmdir(staged._name, dir_fd=staged._root_fd)
        os.fsync(staged._root_fd)
    except OSError:
        failure = True
    finally:
        for field in ("_directory_fd", "_root_fd"):
            descriptor = getattr(staged, field)
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    failure = True
                setattr(staged, field, -1)
    if failure:
        raise PreviewUiCleanupError("preview staging cleanup failed")


class OpenPreviewUiFds:
    def __init__(
        self, paths: PreviewUiRuntimePaths, staged: StagedPreviewInputs
    ) -> None:
        self._paths = paths
        self._staged = staged
        self._fds: list[int] = []

    def __enter__(self) -> PreviewRunOneFds:
        try:
            for path, identity in zip(
                _root_paths(self._paths), self._paths._identities[:7], strict=True
            ):
                descriptor = os.open(path, _ROOT_FLAGS)
                self._fds.append(descriptor)
                info = os.fstat(descriptor)
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or info.st_uid not in (0, os.geteuid())
                    or stat.S_IMODE(info.st_mode) & 0o022
                    or (info.st_dev, info.st_ino) != identity
                ):
                    raise InfrastructureError("preview runtime root identity changed")
            _validate_staged(self._staged, require_open=True)
            for name in ("source.bin", "style.bin", "spec.json", "metadata.json"):
                descriptor = os.open(
                    name, _FILE_FLAGS, dir_fd=self._staged._directory_fd
                )
                self._fds.append(descriptor)
                info = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) & 0o022
                    or not 0 < info.st_size <= _MAX_UPLOAD_BYTES
                ):
                    raise InfrastructureError("preview staged file invalid")
            return PreviewRunOneFds(*self._fds)
        except BaseException as error:
            self._close(error)
            raise

    def _close(self, primary: BaseException | None = None) -> None:
        failure = False
        while self._fds:
            try:
                os.close(self._fds.pop())
            except OSError:
                failure = True
        if failure and primary is not None:
            primary.add_note("preview UI descriptor cleanup failed")
        elif failure:
            raise InfrastructureError("preview UI descriptor cleanup failed")

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _traceback: object | None,
    ) -> None:
        self._close(exc)


def _root_paths(paths: PreviewUiRuntimePaths) -> tuple[Path, ...]:
    return (
        paths.production_config_root,
        paths.production_context_evidence_root,
        paths.preview_config_root,
        paths.model_root,
        paths.evidence_root,
        paths.display_root,
        paths.style_asset_root,
    )

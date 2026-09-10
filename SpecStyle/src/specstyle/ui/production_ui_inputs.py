"""Private staging and descriptor boundary for Production UI uploads."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.spec.loader import load_style_spec_text
from specstyle.workflow.production_job_input import validate_production_job_spec_text
from specstyle.workflow.run_one import ProductionRunOneFds

_METADATA_VERSION = "specstyle.production.job_input.v1"
_PROMPT_TEMPLATE_ID = "ui-prompt-template"
_PROMPT_TEMPLATE_REVISION = "v1"
_PROMPT_TEMPLATE_SHA256 = (
    "52e3054077274103b29878dc23626312ed3c4b27d4596579635d1af7bb90f84e"
)


@dataclass(frozen=True, slots=True)
class ProductionUiRuntimePaths:
    config_root: Path
    evidence_root: Path
    model_root: Path
    state_root: Path
    artifact_root: Path
    style_asset_root: Path
    export_root: Path
    staging_root: Path

    def __post_init__(self) -> None:
        values = tuple(Path(getattr(self, field)) for field in self.__slots__)
        for field, value in zip(self.__slots__, values, strict=True):
            if not value.is_dir():
                raise DomainError(f"{field} unavailable")
            object.__setattr__(self, field, value)
        identities = tuple(
            (value.stat().st_dev, value.stat().st_ino) for value in values
        )
        if len(set(identities)) != len(values):
            raise DomainError("production runtime roots must be distinct")


class UiRunInputError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class StagedInputs:
    directory: Path
    source: Path
    style: Path
    spec: Path
    metadata: Path
    max_rounds: int
    form_fingerprint: Sha256


def stage_inputs(
    paths: ProductionUiRuntimePaths,
    source: object,
    style: object,
    spec: object,
    positive: str,
    negative: str,
    source_url: str | None,
    license_: str | None,
    attribution: str | None,
    consent: str,
) -> StagedInputs:
    source_path = _upload_path(source, "source")
    style_path = _upload_path(style, "style")
    spec_path = _upload_path(spec, "spec")
    staged = Path(tempfile.mkdtemp(prefix="ui-run-", dir=paths.staging_root))
    try:
        staged.chmod(0o700)
        source_dst = _copy_upload(source_path, staged / "source.bin")
        style_dst = _copy_upload(style_path, staged / "style.bin")
        spec_dst = _copy_upload(spec_path, staged / "spec.json")
        metadata, max_rounds = _metadata(
            source_dst,
            style_dst,
            spec_dst,
            positive,
            negative,
            source_url,
            license_,
            attribution,
            consent,
        )
        metadata_dst = _write_private(staged / "metadata.json", metadata)
        fingerprint = _form_fingerprint(
            source_dst,
            style_dst,
            spec_dst,
            positive,
            negative,
            source_url,
            license_,
            attribution,
            consent,
        )
        return StagedInputs(
            staged,
            source_dst,
            style_dst,
            spec_dst,
            metadata_dst,
            max_rounds,
            fingerprint,
        )
    except BaseException:
        cleanup_staging(staged)
        raise


def _upload_path(value: object, label: str) -> Path:
    raw = value
    if raw is None:
        raise UiRunInputError(f"{label} upload required")
    if not isinstance(raw, str):
        raw = getattr(raw, "name", None)
    if not isinstance(raw, str) or not raw:
        raise UiRunInputError(f"{label} upload required")
    path = Path(str(raw))
    if not path.is_file():
        raise UiRunInputError(f"{label} upload required")
    return path


def cleanup_staging(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _copy_upload(source: Path, target: Path) -> Path:
    with source.open("rb") as input_file:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                fd = -1
                shutil.copyfileobj(input_file, output, length=1024 * 1024)
        except BaseException:
            if fd >= 0:
                os.close(fd)
            raise
    target.chmod(0o600)
    return target


def _metadata(
    source: Path,
    style: Path,
    spec: Path,
    positive: str,
    negative: str,
    source_url: str | None,
    license_: str | None,
    attribution: str | None,
    consent: str,
) -> tuple[bytes, int]:
    summary = validate_production_job_spec_text(spec.read_text(encoding="utf-8"))
    data = {
        "schema_version": _METADATA_VERSION,
        "source": {
            "asset_id": _asset_id("source", source),
            "credit": {
                "source_url": source_url or None,
                "license": license_ or None,
                "attribution": attribution or None,
                "consent": consent,
            },
        },
        "style": {"asset_id": _asset_id("style", style)},
        "prompt": {
            "template_pin": {
                "id": _PROMPT_TEMPLATE_ID,
                "revision": _PROMPT_TEMPLATE_REVISION,
                "sha256": _PROMPT_TEMPLATE_SHA256,
            },
            "preset_id": summary.preset_id,
            "positive": positive,
            "negative": negative,
        },
    }
    encoded = json.dumps(data, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return encoded, summary.max_rounds


def _form_fingerprint(
    source: Path,
    style: Path,
    spec: Path,
    positive: str,
    negative: str,
    source_url: str | None,
    license_: str | None,
    attribution: str | None,
    consent: str,
) -> Sha256:
    source_spec = load_style_spec_text(spec.read_text(encoding="utf-8"))
    payload = {
        "schema": "specstyle.production.ui-replay-form.v1",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "style_sha256": hashlib.sha256(style.read_bytes()).hexdigest(),
        "source_spec": source_spec.model_dump(mode="json", round_trip=True),
        "positive": positive,
        "negative": negative,
        "source_url": source_url or None,
        "license": license_ or None,
        "attribution": attribution or None,
        "consent": consent,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return Sha256(hashlib.sha256(encoded).hexdigest())


def _asset_id(prefix: str, path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{prefix}-{digest[:16]}"


def _write_private(path: Path, content: bytes) -> Path:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            fd = -1
            output.write(content)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        raise
    path.chmod(0o600)
    return path


class OpenProductionUiFds:
    def __init__(self, paths: ProductionUiRuntimePaths, staged: StagedInputs) -> None:
        self._paths = paths
        self._staged = staged
        self._fds: list[int] = []

    def __enter__(self) -> ProductionRunOneFds:
        try:
            for path in _root_paths(self._paths):
                self._fds.append(os.open(path, os.O_RDONLY | os.O_DIRECTORY))
            for path in (
                self._staged.source,
                self._staged.style,
                self._staged.spec,
                self._staged.metadata,
            ):
                self._assert_private_file(path)
                self._fds.append(os.open(path, os.O_RDONLY))
            return ProductionRunOneFds(*self._fds)
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_args: object) -> None:
        while self._fds:
            os.close(self._fds.pop())

    @staticmethod
    def _assert_private_file(path: Path) -> None:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise DomainError("invalid staged production input")


def _root_paths(paths: ProductionUiRuntimePaths) -> tuple[Path, ...]:
    return (
        paths.config_root,
        paths.evidence_root,
        paths.model_root,
        paths.state_root,
        paths.artifact_root,
        paths.style_asset_root,
        paths.export_root,
    )

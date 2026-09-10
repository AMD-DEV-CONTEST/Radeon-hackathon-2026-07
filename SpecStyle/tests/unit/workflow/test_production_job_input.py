"""Strict loader contracts for production job material."""

from __future__ import annotations

import copy
from dataclasses import fields
import importlib
import inspect
import json
import os
from pathlib import Path
import pickle
import tempfile
import threading
from types import SimpleNamespace

import pytest

from specstyle.domain.identifiers import AssetId, JobId
from specstyle.domain.artifacts import AssetRef
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.requests import RenderedPrompt
from specstyle.generation.preprocess import PreprocessPlan, preprocess_image
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import OutputProfileCapability, ResourcePin
from tests.unit.spec.test_compiler import raw_spec


class _HostileInt(int):
    pass


class _StyleResolver:
    def __init__(self, content: dict[str, bytes]) -> None:
        self._content = content
        self._closed = False
        self._lock = threading.Lock()

    def __call__(self, reference: AssetRef) -> bytes:
        with self._lock:
            if self._closed:
                raise InfrastructureError("style asset resolver is closed")
            return self._content[reference.sha256.value]

    def close(self) -> None:
        with self._lock:
            self._closed = True


@pytest.fixture(autouse=True)
def _cas_backend_seam(monkeypatch):
    module = importlib.import_module("specstyle.workflow.production_job_input")
    content: dict[str, bytes] = {}

    def store(_root: int, digest: str, value: bytes, _target: tuple[int, int]) -> None:
        content[digest] = value

    def resolver(_root: int, _refs: tuple[AssetRef, ...], _target: tuple[int, int]):
        return _StyleResolver(content)

    monkeypatch.setattr(module, "_store_style", store)
    monkeypatch.setattr(module, "open_content_addressed_style_resolver", resolver)


def _metadata() -> bytes:
    return json.dumps(
        {
            "schema_version": "specstyle.production.job_input.v1",
            "source": {
                "asset_id": "source-1",
                "credit": {
                    "source_url": "https://example.test/source",
                    "license": "CC0-1.0",
                    "attribution": "Example",
                    "consent": "obtained",
                },
            },
            "style": {"asset_id": "style-1"},
            "prompt": {
                "template_pin": {
                    "id": "prompt-template",
                    "revision": "r1",
                    "sha256": "a" * 64,
                },
                "preset_id": "preset",
                "positive": "soft product lighting",
                "negative": "watermark",
            },
        },
        separators=(",", ":"),
    ).encode()


def _load(data: bytes):
    handle = tempfile.NamedTemporaryFile(delete=False)
    try:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(data)
        handle.flush()
        handle.seek(0)
        return importlib.import_module(
            "specstyle.workflow.production_job_input"
        ).load_production_job_input_metadata(handle.fileno())
    finally:
        handle.close()
        os.unlink(handle.name)


def test_metadata_loader_issues_frozen_exact_public_values() -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")

    assert module.__all__ == (
        "ProductionAssetProvenance",
        "ProductionJobInputMetadata",
        "ProductionJobSpecSummary",
        "load_production_job_input_metadata",
        "open_production_job_input",
        "validate_production_job_spec_text",
    )
    assert all(
        parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        for parameter in inspect.signature(
            module.load_production_job_input_metadata
        ).parameters.values()
    )
    metadata = _load(_metadata())
    assert [field.name for field in fields(module.ProductionAssetProvenance)] == [
        "source_url",
        "license",
        "attribution",
        "consent",
    ]
    assert [field.name for field in fields(module.ProductionJobInputMetadata)] == [
        "source_asset_id",
        "style_asset_id",
        "prompt",
        "source_provenance",
    ]
    assert metadata.source_asset_id == AssetId("source-1")
    assert metadata.style_asset_id == AssetId("style-1")
    assert type(metadata.prompt) is RenderedPrompt
    assert metadata.source_provenance.consent == "obtained"


def test_metadata_loader_does_not_leak_duplicated_fds_on_success_or_failure() -> None:
    before = len(os.listdir("/dev/fd"))
    for _ in range(100):
        _load(_metadata())
        with pytest.raises(DomainError):
            _load(b"{}")
    assert len(os.listdir("/dev/fd")) == before


def test_borrowed_read_never_moves_the_callers_shared_offset(
    monkeypatch, tmp_path: Path
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    fd = _write(tmp_path / "input", b"metadata")
    os.lseek(fd, 3, os.SEEK_SET)
    real_pread = module.os.pread
    observed: list[int] = []

    def pread(duplicate: int, size: int, offset: int) -> bytes:
        observed.append(os.lseek(fd, 0, os.SEEK_CUR))
        return real_pread(duplicate, size, offset)

    monkeypatch.setattr(module.os, "pread", pread)
    try:
        assert module._read_borrowed(fd, 64) == b"metadata"
        assert observed and set(observed) == {3}
        assert os.lseek(fd, 0, os.SEEK_CUR) == 3
    finally:
        os.close(fd)


@pytest.mark.parametrize("returned", (b"", b"x" * 65))
def test_borrowed_read_rejects_pread_short_or_overlong_results(
    monkeypatch, returned: bytes, tmp_path: Path
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    fd = _write(tmp_path / "input", b"metadata")
    monkeypatch.setattr(module.os, "pread", lambda *_args: returned)
    try:
        with pytest.raises(InfrastructureError):
            module._read_borrowed(fd, 64)
        os.fstat(fd)
    finally:
        os.close(fd)


def _png(color: str) -> bytes:
    return _image("PNG", color)


def _image(format_: str, color: str) -> bytes:
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (64, 64), color).save(output, format_)
    return output.getvalue()


def _unsupported_image(
    format_: str, *, animated: bool = False, icc: bool = False
) -> bytes:
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    image = Image.new("RGB", (64, 64), "red")
    options = {"icc_profile": b"untrusted"} if icc else {}
    if animated:
        image.save(
            output, format_, save_all=True, append_images=[image.copy()], **options
        )
    else:
        image.save(output, format_, **options)
    return output.getvalue()


def _write(path: Path, content: bytes) -> int:
    path.write_bytes(content)
    path.chmod(0o600)
    return os.open(path, os.O_RDONLY)


def _context(profile: str = "xhs_grid"):
    module = importlib.import_module("specstyle.production.context_config")
    config = object.__new__(module.ProductionContextConfig)
    pin = ResourcePin("processor", "r1", hash_bytes(b"processor"))
    object.__setattr__(
        config,
        "source_preprocess",
        SimpleNamespace(
            processor_pin=pin, resize_mode="contain_pad", background=(255, 255, 255)
        ),
    )
    object.__setattr__(
        config,
        "output_profiles",
        (
            OutputProfileCapability(
                ResourcePin(f"{profile}-output", "r1", hash_bytes(profile.encode())),
                profile,
                ("product_instance",),
                ("preview", "production"),
            ),
        ),
    )
    object.__setattr__(config, "_seal", module._CONFIG_SEAL)
    return config


def _spec(style_hash: str) -> bytes:
    data = raw_spec().model_dump(mode="python", round_trip=True)
    data["profiles"]["preview"]["resolution"] = (64, 64)
    data["profiles"]["production"]["resolution"] = (64, 64)
    data["assets"]["style_references"][0]["asset_sha256"] = style_hash
    data["repair"]["policy_version"] = "1.0"
    return json.dumps(data, separators=(",", ":")).encode()


def _open_with_spec(module: object, tmp_path: Path, spec: bytes):
    source, style = _png("red"), _png("blue")
    root = tmp_path / "cas"
    root.mkdir(mode=0o700)
    fds = (
        _write(tmp_path / "source", source),
        _write(tmp_path / "style", style),
        _write(tmp_path / "spec", spec),
        os.open(root, os.O_RDONLY | os.O_DIRECTORY),
    )
    args = (
        *fds,
        _load(_metadata()),
        _context(),
        __import__("specstyle.domain.identifiers", fromlist=["JobId"]).JobId("job-1"),
        "bundle-1",
    )
    return root, fds, args


def _normalized_blue() -> bytes:
    style = _png("blue")
    return _normalized_style(style)


def _normalized_style(style: bytes) -> bytes:
    plan = PreprocessPlan(
        (64, 64),
        "contain_pad",
        (255, 255, 255),
        ResourcePin("processor", "r1", hash_bytes(b"processor")),
    )
    reference = AssetRef(AssetId("style-1"), hash_bytes(style))
    return preprocess_image(style, reference, plan).content


def test_production_spec_preflight_returns_the_validated_batch_contract() -> None:
    from specstyle.workflow.production_job_input import (
        ProductionJobSpecSummary,
        validate_production_job_spec_text,
    )

    data = raw_spec().model_dump(mode="json")
    data["repair"]["policy_version"] = "1.0"
    summary = validate_production_job_spec_text(json.dumps(data))

    assert summary == ProductionJobSpecSummary("preset", 1)


def test_production_spec_preflight_accepts_one_nonlegacy_output_profile() -> None:
    from specstyle.workflow.production_job_input import (
        ProductionJobSpecSummary,
        validate_production_job_spec_text,
    )

    data = raw_spec().model_dump(mode="json")
    data["repair"]["policy_version"] = "1.0"
    data["outputs"]["profiles"] = ["talking_head_cover"]

    summary = validate_production_job_spec_text(json.dumps(data))

    assert summary == ProductionJobSpecSummary("preset", 1)


def test_production_spec_preflight_rejects_noncontract_repair_budget() -> None:
    from specstyle.workflow.production_job_input import (
        validate_production_job_spec_text,
    )

    raw = raw_spec().model_copy(
        update={
            "repair": raw_spec().repair.model_copy(
                update={"policy_version": "1.0", "max_rounds": 2}
            )
        }
    )

    with pytest.raises(DomainError, match="^invalid production job input$"):
        validate_production_job_spec_text(json.dumps(raw.model_dump(mode="json")))


def _open_job(module: object, fds: tuple[int, ...], metadata=None):
    return module.open_production_job_input(
        *fds, metadata or _load(_metadata()), _context(), JobId("job-1"), "bundle-1"
    )


def test_open_normalizes_writes_and_resolves_style_without_consuming_caller_fds(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    source, style = _png("red"), _png("blue")
    normalized = _normalized_style(style)
    root = tmp_path / "cas"
    root.mkdir(mode=0o700)
    source_fd = _write(tmp_path / "source.png", source)
    style_fd = _write(tmp_path / "style.png", style)
    spec_fd = _write(tmp_path / "style.json", _spec(hash_bytes(normalized).value))
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    metadata = _load(_metadata())
    try:
        offsets = tuple(
            os.lseek(fd, 1, os.SEEK_SET) for fd in (source_fd, style_fd, spec_fd)
        )
        fds = (source_fd, style_fd, spec_fd, root_fd)
        issued = _open_job(module, fds, metadata)
        assert issued.request.spec_text == json.dumps(
            json.loads(_spec(hash_bytes(normalized).value)),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        assert issued.style_assets(issued.request.style_references[0]) == normalized
        assert len(issued.asset_credits) == 2
        for fd in fds:
            os.fstat(fd)
        assert (
            tuple(os.lseek(fd, 0, os.SEEK_CUR) for fd in (source_fd, style_fd, spec_fd))
            == offsets
        )
        issued.close()
        issued.close()
        reused = _open_job(module, fds, metadata)
        reused.close()
    finally:
        os.close(root_fd)
        os.close(spec_fd)
        os.close(style_fd)
        os.close(source_fd)


@pytest.mark.parametrize("source_format", ("PNG", "JPEG", "WEBP"))
@pytest.mark.parametrize("style_format", ("PNG", "JPEG", "WEBP"))
def test_open_normalizes_every_supported_input_pair_deterministically(
    tmp_path: Path, source_format: str, style_format: str
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    source = _image(source_format, "red")
    style = _image(style_format, "blue")
    normalized = _normalized_style(style)
    root = tmp_path / "cas"
    root.mkdir(mode=0o700)
    fds = (
        _write(tmp_path / "source", source),
        _write(tmp_path / "style", style),
        _write(tmp_path / "spec", _spec(hash_bytes(normalized).value)),
        os.open(root, os.O_RDONLY | os.O_DIRECTORY),
    )
    try:
        first = _open_job(module, fds)
        second = _open_job(module, fds)
        assert first.request == second.request
        assert first.asset_credits == second.asset_credits
        reference = first.request.style_references[0]
        assert normalized == first.style_assets(reference)
        first.close()
        second.close()
    finally:
        for fd in reversed(fds):
            os.close(fd)


def test_open_refuses_a_normalized_style_hash_mismatch_before_cas_write(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    root, fds, args = _open_with_spec(module, tmp_path, _spec("0" * 64))
    try:
        with pytest.raises(DomainError, match="^invalid production job input$"):
            module.open_production_job_input(*args)
        assert list(root.iterdir()) == []
    finally:
        for fd in reversed(fds):
            os.close(fd)


@pytest.mark.parametrize("variation_index", (True, _HostileInt(0), -1, 2**31))
def test_open_rejects_variation_before_material_load_or_cas_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    variation_index: object,
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    root, fds, args = _open_with_spec(module, tmp_path, _spec("0" * 64))
    called: list[str] = []
    monkeypatch.setattr(module, "_load_materials", lambda *_args: called.append("load"))
    monkeypatch.setattr(module, "_store_style", lambda *_args: called.append("store"))
    try:
        with pytest.raises(DomainError, match="^invalid production job input$"):
            module.open_production_job_input(
                *args,
                variation_index=variation_index,  # type: ignore[arg-type]
            )
        assert called == []
        assert list(root.iterdir()) == []
    finally:
        for fd in reversed(fds):
            os.close(fd)


def test_open_carries_a_nonzero_variation_into_the_request(tmp_path: Path) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    style = _png("blue")
    normalized = _normalized_style(style)
    _root, fds, args = _open_with_spec(
        module, tmp_path, _spec(hash_bytes(normalized).value)
    )
    try:
        issued = module.open_production_job_input(*args, variation_index=7)
        assert issued.request.variation_index == 7
        assert issued.style_assets(issued.request.style_references[0]) == normalized
        issued.close()
    finally:
        for fd in reversed(fds):
            os.close(fd)


def test_open_derives_the_single_output_profile_from_the_spec(tmp_path: Path) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    style = _png("blue")
    normalized = _normalized_style(style)
    data = json.loads(_spec(hash_bytes(normalized).value))
    data["outputs"]["profiles"] = ["talking_head_cover"]
    root = tmp_path / "cas"
    root.mkdir(mode=0o700)
    fds = (
        _write(tmp_path / "source", _png("red")),
        _write(tmp_path / "style", style),
        _write(tmp_path / "spec", json.dumps(data, separators=(",", ":")).encode()),
        os.open(root, os.O_RDONLY | os.O_DIRECTORY),
    )
    try:
        issued = module.open_production_job_input(
            *fds,
            _load(_metadata()),
            _context("talking_head_cover"),
            JobId("job-talking"),
            "bundle-talking",
        )
        assert issued.request.output_profile == "talking_head_cover"
        issued.close()
    finally:
        for fd in reversed(fds):
            os.close(fd)


@pytest.mark.parametrize(
    "bad,expected",
    (
        (b"not an image", DomainError),
        (_unsupported_image("GIF"), DomainError),
        (_unsupported_image("GIF", animated=True), DomainError),
        (_unsupported_image("TIFF"), DomainError),
        (_unsupported_image("JPEG", icc=True), DomainError),
        (_png("red")[:-8], InfrastructureError),
    ),
)
@pytest.mark.parametrize("slot", ("source", "style"))
def test_open_refuses_noncanonical_images_before_cas_write(
    tmp_path: Path, bad: bytes, expected: type[Exception], slot: str
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    source = bad if slot == "source" else _png("red")
    style = bad if slot == "style" else _png("blue")
    style_hash = hash_bytes(_normalized_blue()).value if slot == "source" else "0" * 64
    root = tmp_path / "cas"
    root.mkdir(mode=0o700)
    fds = (
        _write(tmp_path / "source", source),
        _write(tmp_path / "style", style),
        _write(tmp_path / "spec", _spec(style_hash)),
        os.open(root, os.O_RDONLY | os.O_DIRECTORY),
    )
    try:
        args = (
            *fds,
            _load(_metadata()),
            _context(),
            __import__("specstyle.domain.identifiers", fromlist=["JobId"]).JobId(
                "job-1"
            ),
            "bundle-1",
        )
        with pytest.raises(
            expected,
            match="^invalid production job input$|^production job input unavailable$",
        ):
            module.open_production_job_input(*args)
        assert list(root.iterdir()) == []
    finally:
        for fd in reversed(fds):
            os.close(fd)


def test_open_refuses_pixel_limit_before_cas_write(tmp_path: Path) -> None:
    from io import BytesIO

    from PIL import Image

    module = importlib.import_module("specstyle.workflow.production_job_input")
    output = BytesIO()
    Image.new("RGB", (5001, 5001), "red").save(output, "PNG")
    root = tmp_path / "cas"
    root.mkdir(mode=0o700)
    fds = (
        _write(tmp_path / "source", output.getvalue()),
        _write(tmp_path / "style", _png("blue")),
        _write(tmp_path / "spec", _spec(hash_bytes(_normalized_blue()).value)),
        os.open(root, os.O_RDONLY | os.O_DIRECTORY),
    )
    try:
        with pytest.raises(DomainError, match="^invalid production job input$"):
            module.open_production_job_input(
                *fds,
                _load(_metadata()),
                _context(),
                __import__("specstyle.domain.identifiers", fromlist=["JobId"]).JobId(
                    "job-1"
                ),
                "bundle-1",
            )
        assert list(root.iterdir()) == []
    finally:
        for fd in reversed(fds):
            os.close(fd)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda data: data["outputs"].update(
            {"profiles": ["xhs_grid", "talking_head_cover"]}
        ),
        lambda data: data["assets"].update(
            {"style_references": data["assets"]["style_references"] * 2}
        ),
        lambda data: data["repair"].update(
            {"max_rounds": 2, "stop_after_no_improvement": 2}
        ),
        lambda data: data["verification"].update(
            {
                "l3": {
                    "plugin_id": "l3",
                    "plugin_revision": "r1",
                    "threshold_profile": "t1",
                }
            }
        ),
        lambda data: data["domain"].update(
            {"profile": "face_identity", "verifier_version": "v1"}
        ),
        lambda data: data["generation"].update({"batch_execution": "parallel"}),
        lambda data: data["profiles"]["production"].update({"resolution": [66, 64]}),
    ),
)
def test_open_refuses_out_of_scope_specs_before_cas_write(
    tmp_path: Path, mutate
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    data = json.loads(_spec(hash_bytes(_normalized_blue()).value))
    mutate(data)
    root, fds, args = _open_with_spec(
        module, tmp_path, json.dumps(data, separators=(",", ":")).encode()
    )
    try:
        with pytest.raises(DomainError, match="^invalid production job input$"):
            module.open_production_job_input(*args)
        assert list(root.iterdir()) == []
    finally:
        for fd in reversed(fds):
            os.close(fd)


def test_issued_input_cannot_be_copied_or_serialized(tmp_path: Path) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    source, style = _png("red"), _png("blue")
    plan = PreprocessPlan(
        (64, 64),
        "contain_pad",
        (255, 255, 255),
        ResourcePin("processor", "r1", hash_bytes(b"processor")),
    )
    normalized = preprocess_image(
        style, AssetRef(AssetId("style-1"), hash_bytes(style)), plan
    )
    root = tmp_path / "cas"
    root.mkdir(mode=0o700)
    fds = (
        _write(tmp_path / "source.png", source),
        _write(tmp_path / "style.png", style),
        _write(tmp_path / "style.json", _spec(hash_bytes(normalized.content).value)),
        os.open(root, os.O_RDONLY | os.O_DIRECTORY),
    )
    try:
        issued = module.open_production_job_input(
            *fds,
            _load(_metadata()),
            _context(),
            __import__("specstyle.domain.identifiers", fromlist=["JobId"]).JobId(
                "job-1"
            ),
            "bundle-1",
        )
        with pytest.raises(TypeError):
            copy.copy(issued)
        with pytest.raises(TypeError):
            pickle.dumps(issued)
        with issued as entered:
            assert entered is issued
        with pytest.raises(InfrastructureError):
            issued.__enter__()
    finally:
        for fd in reversed(fds):
            os.close(fd)


def test_issued_input_close_is_idempotent_and_thread_safe(tmp_path: Path) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    root, fds, args = _open_with_spec(
        module, tmp_path, _spec(hash_bytes(_normalized_blue()).value)
    )
    del root
    try:
        issued = module.open_production_job_input(*args)
        workers = [threading.Thread(target=issued.close) for _ in range(12)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        with pytest.raises(
            InfrastructureError, match="^production job input unavailable$"
        ):
            issued.__enter__()
    finally:
        for fd in reversed(fds):
            os.close(fd)


def test_issued_input_preserves_primary_error_when_resolver_close_fails(
    monkeypatch, tmp_path: Path
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    root, fds, args = _open_with_spec(
        module, tmp_path, _spec(hash_bytes(_normalized_blue()).value)
    )
    del root
    issued = module.open_production_job_input(*args)
    resolver, original = issued.style_assets, type(issued.style_assets).close

    def fail_close(_self) -> None:
        raise OSError("secret close detail")

    monkeypatch.setattr(type(resolver), "close", fail_close)
    try:
        with pytest.raises(RuntimeError, match="^primary") as raised:
            with issued:
                raise RuntimeError("primary")
        assert getattr(raised.value, "__notes__", []) == [
            "production job input cleanup failed"
        ]
    finally:
        original(resolver)
        for fd in reversed(fds):
            os.close(fd)

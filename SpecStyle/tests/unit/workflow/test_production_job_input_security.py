"""Security-boundary contracts for production job material."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace

import pytest

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AssetId, JobId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.preprocess import PreprocessPlan, preprocess_image
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import OutputProfileCapability, ResourcePin
from tests.unit.spec.test_compiler import raw_spec


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


def _replace_path(data: dict, path: tuple[str, ...], value: str) -> None:
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _load(data: bytes):
    handle = tempfile.NamedTemporaryFile(delete=False)
    try:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(data)
        handle.flush()
        handle.seek(0)
        module = importlib.import_module("specstyle.workflow.production_job_input")
        return module.load_production_job_input_metadata(handle.fileno())
    finally:
        handle.close()
        os.unlink(handle.name)


def _png(color: str) -> bytes:
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (64, 64), color).save(output, "PNG")
    return output.getvalue()


def _write(path: Path, content: bytes) -> int:
    path.write_bytes(content)
    path.chmod(0o600)
    return os.open(path, os.O_RDONLY)


def _context():
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
                ResourcePin("xhs-output", "r1", hash_bytes(b"xhs-output")),
                "xhs_grid",
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
    root = tmp_path / "cas"
    root.mkdir(mode=0o700)
    fds = (
        _write(tmp_path / "source", _png("red")),
        _write(tmp_path / "style", _png("blue")),
        _write(tmp_path / "spec", spec),
        os.open(root, os.O_RDONLY | os.O_DIRECTORY),
    )
    args = (*fds, _load(_metadata()), _context(), JobId("job-1"), "bundle-1")
    return root, fds, args


def _normalized_blue() -> bytes:
    style = _png("blue")
    plan = PreprocessPlan(
        (64, 64),
        "contain_pad",
        (255, 255, 255),
        ResourcePin("processor", "r1", hash_bytes(b"processor")),
    )
    return preprocess_image(
        style, AssetRef(AssetId("style-1"), hash_bytes(style)), plan
    ).content


@pytest.mark.parametrize(
    "path,poisoned",
    (
        (
            ("prompt", "positive"),
            "Authorization: AWS4-HMAC-SHA256 "
            "Credential=AKIAIOSFODNN7/20260802/cn-north-1/s3/aws4_request",
        ),
        (("prompt", "positive"), "authorization: opaque-value"),
        (("prompt", "positive"), "credential = opaque-value"),
        (("prompt", "positive"), "Cookie: sessionid=opaque-value"),
        (("prompt", "positive"), "session=opaque-value"),
        (("prompt", "positive"), "passwd: opaque-value"),
        (("prompt", "positive"), "source:/private"),
        (("prompt", "positive"), "asset:/home/alice/private"),
        (("prompt", "positive"), r"debug:C:\Users\alice\private"),
        (("prompt", "positive"), r"trace:\\server\share\private"),
        (("prompt", "template_pin", "id"), "path:/home/alice/template"),
        (("prompt", "template_pin", "revision"), "r1\u00a0/home/alice/template"),
        (("prompt", "negative"), "avoid\u2003/home/alice/private"),
        (("source", "credit", "source_url"), "https://example.test/a\u00a0b"),
    ),
)
def test_persisted_metadata_strings_fail_before_cas(
    monkeypatch, tmp_path: Path, path: tuple[str, ...], poisoned: str
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    calls: list[str] = []
    monkeypatch.setattr(module, "_store_style", lambda *_args: calls.append("store"))
    root = tmp_path / "cas"
    root.mkdir(mode=0o700)
    data = json.loads(_metadata())
    _replace_path(data, path, poisoned)
    with pytest.raises(DomainError, match="^invalid production job input$") as raised:
        _load(json.dumps(data).encode())
    assert poisoned not in str(raised.value)
    assert calls == []
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    "plain",
    (
        "basic product lighting",
        "bearer product photography",
        "studio session lighting",
        "cookie decoration photography",
        "reference https://example.test/look",
    ),
)
def test_public_loader_accepts_ambiguous_plain_photography_text(plain: str) -> None:
    data = _metadata().replace(b"soft product lighting", plain.encode())
    assert _load(data).prompt.positive == plain


@pytest.mark.parametrize(
    "path,poisoned",
    (
        (("metadata", "name"), "Spec path:/home/alice/private"),
        (("runtime", "rocm_version"), "6.2\u00a0/opt/rocm/private"),
        (
            ("profiles", "production", "scheduler"),
            "euler\u2003C:\\Users\\alice\\private",
        ),
        (
            ("assets", "style_references", "0", "source_url"),
            "https://example.test/a\u00a0b",
        ),
    ),
)
def test_persisted_spec_primitives_fail_before_cas(
    monkeypatch, tmp_path: Path, path: tuple[str, ...], poisoned: str
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    data = json.loads(_spec(hash_bytes(_normalized_blue()).value))
    target = data
    for key in path[:-1]:
        target = target[int(key)] if key.isdigit() else target[key]
    target[path[-1]] = poisoned
    root, fds, args = _open_with_spec(
        module, tmp_path, json.dumps(data, separators=(",", ":")).encode()
    )
    calls: list[str] = []
    monkeypatch.setattr(module, "_store_style", lambda *_args: calls.append("store"))
    try:
        with pytest.raises(
            DomainError, match="^invalid production job input$"
        ) as raised:
            module.open_production_job_input(*args)
        assert poisoned not in str(raised.value)
        assert calls == []
        assert list(root.iterdir()) == []
    finally:
        for fd in reversed(fds):
            os.close(fd)


def test_open_revalidates_mutated_pin_before_cas(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    root, fds, args = _open_with_spec(
        module, tmp_path, _spec(hash_bytes(_normalized_blue()).value)
    )
    poisoned = "path:/home/alice/template"
    object.__setattr__(args[4].prompt.template_pin, "revision", poisoned)
    calls: list[str] = []
    monkeypatch.setattr(module, "_store_style", lambda *_args: calls.append("store"))
    try:
        with pytest.raises(
            DomainError, match="^invalid production job input$"
        ) as raised:
            module.open_production_job_input(*args)
        assert poisoned not in str(raised.value)
        assert calls == []
        assert list(root.iterdir()) == []
    finally:
        for fd in reversed(fds):
            os.close(fd)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda data: (
            b'{"schema_version":"specstyle.production.job_input.v1",' + data[1:]
        ),
        lambda data: data.replace(b'"style":{"asset_id":"style-1"}', b'"style":{}'),
        lambda data: data.replace(
            b'"style":{"asset_id":"style-1"}', b'"style":{"asset_id":"source-1"}'
        ),
        lambda data: data.replace(b'"source-1"', b'"/private/source"'),
    ),
)
def test_metadata_loader_rejects_duplicate_missing_or_unsafe_values(mutate) -> None:
    with pytest.raises(DomainError) as raised:
        _load(mutate(_metadata()))
    assert "soft product lighting" not in str(raised.value)
    assert "/private/source" not in str(raised.value)


@pytest.mark.parametrize(
    "content,mode,links",
    ((b"", 0o600, 1), (_metadata(), 0o644, 1), (_metadata(), 0o600, 2)),
)
def test_metadata_loader_refuses_untrusted_or_empty_borrowed_files(
    tmp_path: Path, content: bytes, mode: int, links: int
) -> None:
    path = tmp_path / "metadata"
    path.write_bytes(content)
    path.chmod(mode)
    if links == 2:
        os.link(path, tmp_path / "metadata-link")
    fd = os.open(path, os.O_RDONLY)
    try:
        with pytest.raises(DomainError, match="^invalid production job input$"):
            module = importlib.import_module("specstyle.workflow.production_job_input")
            module.load_production_job_input_metadata(fd)
        os.fstat(fd)
    finally:
        os.close(fd)


def test_metadata_loader_rejects_boolean_and_closed_descriptors() -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    with pytest.raises(DomainError, match="^invalid production job input$"):
        module.load_production_job_input_metadata(True)
    fd = os.open("/dev/null", os.O_RDONLY)
    os.close(fd)
    with pytest.raises(InfrastructureError, match="^production job input unavailable$"):
        module.load_production_job_input_metadata(fd)


@pytest.mark.parametrize("field,value", (("license", 123), ("attribution", object())))
def test_public_provenance_invalid_types_are_fixed_domain_errors(
    field: str, value: object
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    values = {"source_url": None, "license": None, "attribution": None, "consent": None}
    values[field] = value
    with pytest.raises(DomainError, match="^invalid production job input$"):
        module.ProductionAssetProvenance(**values)


def test_public_metadata_invalid_direct_construction_is_a_fixed_domain_error() -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    with pytest.raises(DomainError, match="^invalid production job input$"):
        module.ProductionJobInputMetadata(
            AssetId("source-1"), AssetId("style-1"), object(), object()
        )


@pytest.mark.parametrize(
    "secret",
    (
        "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature",
        "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
    ),
)
def test_metadata_loader_rejects_prompt_secret_before_opening_job(secret: str) -> None:
    poisoned = _metadata().replace(b"soft product lighting", secret.encode())
    with pytest.raises(DomainError, match="^invalid production job input$"):
        _load(poisoned)


@pytest.mark.parametrize(
    "poisoned",
    (
        "Authorization: Basic abc123",
        "api key abc123",
        "client_secret:abc123",
        "access-token = abc123",
        "access key: abc123",
        "client key = abc123",
        "private key: abc123",
        "look at ../../etc/passwd",
        "look at asset/../secret",
        "look at /home/alice/secret.txt",
        r"look at C:\Users\alice\secret.txt",
        r"look at \\server\share\secret.txt",
        "look at ~/secret.txt",
    ),
)
def test_metadata_plain_text_rejects_embedded_secrets_and_paths(poisoned: str) -> None:
    data = _metadata().replace(b"soft product lighting", poisoned.encode())
    with pytest.raises(DomainError, match="^invalid production job input$") as raised:
        _load(data)
    assert poisoned not in str(raised.value)


@pytest.mark.parametrize(
    "field,original", (("license", "CC0-1.0"), ("attribution", "Example"))
)
def test_provenance_plain_text_rejects_embedded_paths(
    field: str, original: str
) -> None:
    poisoned = f"credit from /home/alice/{field}"
    data = _metadata().replace(original.encode(), poisoned.encode())
    with pytest.raises(DomainError, match="^invalid production job input$") as raised:
        _load(data)
    assert poisoned not in str(raised.value)


@pytest.mark.parametrize(
    "url",
    (
        "https://example.test:bad/source",
        "https://[invalid/source",
        "https://user@example.test/source",
        "https://example.test/source?token=x",
    ),
)
def test_provenance_url_parse_failures_are_fixed_errors(url: str) -> None:
    data = _metadata().replace(b"https://example.test/source", url.encode())
    with pytest.raises(DomainError, match="^invalid production job input$") as raised:
        _load(data)
    assert url not in str(raised.value)


@pytest.mark.parametrize(
    "poisoned",
    (
        b"soft product\x7flighting",
        b"token=topsecret",
        b"C:\\\\private\\\\source",
        b"https://user:pass@example.test/source",
        b"https://example.test/source?token=topsecret",
    ),
)
def test_metadata_loader_redacts_every_persisted_string(poisoned: bytes) -> None:
    data = _metadata().replace(b"soft product lighting", poisoned)
    with pytest.raises(DomainError, match="^invalid production job input$") as raised:
        _load(data)
    assert poisoned.decode("utf-8", "replace") not in str(raised.value)


def test_main_loader_delegates_to_anonymous_cas_module() -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "_production_input_cas import store_style as _store_style" in source
    assert "O_TMPFILE" not in source
    assert "os.link" not in source
    assert "os.unlink" not in source
    assert "secrets." not in source


@pytest.mark.parametrize(
    "poisoned",
    (
        "bundle /home/alice/private",
        "bundle ../../private",
        r"bundle C:\Users\alice\private",
        r"bundle \\server\share\private",
    ),
)
def test_bundle_rejects_embedded_paths_before_fd_or_cas_access(
    tmp_path: Path, poisoned: str
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    root, fds, args = _open_with_spec(
        module, tmp_path, _spec(hash_bytes(_normalized_blue()).value)
    )
    del root
    try:
        with pytest.raises(DomainError, match="^invalid production job input$"):
            module.open_production_job_input(*args[:-1], poisoned)
    finally:
        for fd in reversed(fds):
            os.close(fd)


def test_style_spec_allows_model_repository_ids_but_rejects_plain_asset_paths() -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    loader = importlib.import_module("specstyle.spec.loader")
    data = json.loads(_spec(hash_bytes(_normalized_blue()).value))
    data["models"]["base"]["id"] = "org/model"
    raw = loader.load_style_spec_text(json.dumps(data).encode())
    module._validate_spec(raw)
    data["assets"]["style_references"][0]["license"] = "license /home/alice/file"
    raw = loader.load_style_spec_text(json.dumps(data).encode())
    with pytest.raises(DomainError, match="^invalid production job input$"):
        module._validate_spec(raw)


def test_prompt_preset_mismatch_rejects_before_cas_mutation(
    monkeypatch, tmp_path: Path
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    root, fds, args = _open_with_spec(
        module, tmp_path, _spec(hash_bytes(_normalized_blue()).value)
    )
    calls: list[str] = []
    monkeypatch.setattr(module, "_store_style", lambda *_args: calls.append("store"))
    mismatch = _load(_metadata().replace(b'"preset"', b'"other"'))
    try:
        with pytest.raises(DomainError, match="^invalid production job input$"):
            module.open_production_job_input(*fds, mismatch, *args[5:])
        assert calls == []
        assert list(root.iterdir()) == []
    finally:
        for fd in reversed(fds):
            os.close(fd)


def test_successful_loader_builds_an_executable_generation_request(
    tmp_path: Path,
) -> None:
    from specstyle.generation.requests import GenerationRequest, PreparedControlInput
    from specstyle.observability.environment import (
        DeviceInventory,
        EnvironmentSnapshot,
        TextObservation,
    )
    from specstyle.spec.compiler import compile_style_spec
    from specstyle.spec.loader import load_style_spec_text
    from specstyle.workflow.production_service import _initial_generation_request
    from tests.unit.spec.test_compiler import context

    class Builder:
        def build(self, source, _graph):
            return PreparedControlInput("canny", source)

    module = importlib.import_module("specstyle.workflow.production_job_input")
    root, fds, args = _open_with_spec(
        module, tmp_path, _spec(hash_bytes(_normalized_blue()).value)
    )
    del root
    try:
        issued = module.open_production_job_input(*args)
        compiled = compile_style_spec(
            load_style_spec_text(issued.request.spec_text), context()
        )
        graph = compiled.production_graphs[0]
        na = TextObservation("UNAVAILABLE", None, "NOT_REPORTED")
        inventory = DeviceInventory("UNAVAILABLE", "NOT_INSTALLED", ())
        environment = EnvironmentSnapshot(
            "1.0", na, na, na, na, na, na, na, na, na, na, inventory
        )
        request = _initial_generation_request(
            issued.request, compiled, graph, Builder(), environment
        )
        assert type(request) is GenerationRequest
        assert (
            request.prompt.preset_id.value == request.graph.preset_id.value == "preset"
        )
        issued.close()
    finally:
        for fd in reversed(fds):
            os.close(fd)


@pytest.mark.parametrize(
    "failure,expected",
    (
        (DomainError("bad input"), DomainError),
        (InfrastructureError("decoder unavailable"), InfrastructureError),
    ),
)
def test_preprocess_failure_classification_is_preserved(
    monkeypatch, tmp_path: Path, failure: Exception, expected: type[Exception]
) -> None:
    module = importlib.import_module("specstyle.workflow.production_job_input")
    root, fds, args = _open_with_spec(
        module, tmp_path, _spec(hash_bytes(_normalized_blue()).value)
    )
    del root

    def fail(*_args: object) -> None:
        raise failure

    monkeypatch.setattr(module, "preprocess_image", fail)
    try:
        with pytest.raises(
            expected,
            match="^invalid production job input$|^production job input unavailable$",
        ):
            module.open_production_job_input(*args)
    finally:
        for fd in reversed(fds):
            os.close(fd)

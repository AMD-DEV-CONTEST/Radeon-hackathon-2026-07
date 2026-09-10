from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import pickle
import threading
from types import SimpleNamespace

import pytest

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AssetId
from specstyle.errors import DomainError
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
                raise RuntimeError("closed")
            return self._content[reference.sha256.value]

    def close(self) -> None:
        with self._lock:
            self._closed = True


@pytest.fixture(autouse=True)
def _cas_backend_seam(monkeypatch: pytest.MonkeyPatch):
    import specstyle.workflow.preview_job_input as module

    content: dict[str, bytes] = {}

    def store(_root: int, digest: str, value: bytes, _target: tuple[int, int]) -> None:
        content[digest] = value

    def resolver(_root: int, _refs: tuple[AssetRef, ...], _target: tuple[int, int]):
        return _StyleResolver(content)

    monkeypatch.setattr(module, "_store_style", store)
    monkeypatch.setattr(module, "open_content_addressed_style_resolver", resolver)


def _png(color: str) -> bytes:
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (64, 64), color).save(output, "PNG")
    return output.getvalue()


def _context():
    from specstyle.production.context_config import (
        ProductionContextConfig,
        _CONFIG_SEAL,
    )

    config = object.__new__(ProductionContextConfig)
    processor = ResourcePin("processor", "r1", hash_bytes(b"processor"))
    object.__setattr__(
        config,
        "source_preprocess",
        SimpleNamespace(
            processor_pin=processor,
            resize_mode="contain_pad",
            background=(255, 255, 255),
        ),
    )
    object.__setattr__(
        config,
        "output_profiles",
        (
            OutputProfileCapability(
                ResourcePin("output", "r1", hash_bytes(b"output")),
                "xhs_grid",
                ("product_instance",),
                ("preview", "production"),
            ),
        ),
    )
    object.__setattr__(config, "_seal", _CONFIG_SEAL)
    return config


def _metadata(schema: str = "specstyle.preview.job_input.v1") -> bytes:
    return json.dumps(
        {
            "schema_version": schema,
            "source": {"asset_id": "source-1"},
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


def _spec(style: bytes, **preview_changes: object) -> bytes:
    processor = _context().source_preprocess.processor_pin
    style_ref = AssetRef(AssetId("style-1"), hash_bytes(style))
    prepared = preprocess_image(
        style,
        style_ref,
        PreprocessPlan((64, 64), "contain_pad", (255, 255, 255), processor),
    )
    data = raw_spec().model_dump(mode="python", round_trip=True)
    data["profiles"]["preview"].update(
        pipeline="lcm", resolution=(64, 64), steps=4, guidance_scale=0.0
    )
    data["profiles"]["preview"].update(preview_changes)
    data["profiles"]["production"]["resolution"] = (64, 64)
    data["repair"]["policy_version"] = "1.0"
    data["assets"]["style_references"][0]["asset_sha256"] = hash_bytes(
        prepared.content
    ).value
    return json.dumps(data, separators=(",", ":")).encode()


def _private_file(path: Path, content: bytes) -> int:
    path.write_bytes(content)
    path.chmod(0o600)
    return os.open(path, os.O_RDONLY)


def test_preview_metadata_is_independent_and_strict(tmp_path: Path) -> None:
    from specstyle.workflow.preview_job_input import load_preview_job_input_metadata

    fd = _private_file(tmp_path / "metadata.json", _metadata())
    try:
        metadata = load_preview_job_input_metadata(fd)
    finally:
        os.close(fd)
    assert metadata.source_asset_id == AssetId("source-1")
    assert metadata.style_asset_id == AssetId("style-1")
    assert metadata.prompt.positive == "soft product lighting"

    fd = _private_file(
        tmp_path / "production.json", _metadata("specstyle.production.job_input.v1")
    )
    try:
        with pytest.raises(DomainError, match="preview job input"):
            load_preview_job_input_metadata(fd)
    finally:
        os.close(fd)


def test_preview_input_prepares_only_preview_materials(tmp_path: Path) -> None:
    import specstyle.workflow.preview_job_input as module

    source, style = _png("white"), _png("blue")
    files = (
        _private_file(tmp_path / "source", source),
        _private_file(tmp_path / "style", style),
        _private_file(tmp_path / "spec", _spec(style)),
        _private_file(tmp_path / "metadata", _metadata()),
    )
    style_root = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        metadata = module.load_preview_job_input_metadata(files[3])
        with module.open_preview_job_input(
            files[0], files[1], files[2], style_root, metadata, _context(), 3
        ) as opened:
            assert opened.output_profile == "xhs_grid"
            assert opened.variation_index == 3
            assert (opened.source.width, opened.source.height) == (64, 64)
            assert opened.style_references[0].asset_id == AssetId("style-1")
            assert opened.style_assets(opened.style_references[0]).startswith(
                b"\x89PNG"
            )
            assert not hasattr(opened, "asset_credits")
            assert not hasattr(opened, "verification_plan")
            for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                with pytest.raises(TypeError, match="preview job inputs"):
                    operation(opened)
    finally:
        os.close(style_root)
        for fd in files:
            os.close(fd)


@pytest.mark.parametrize(
    "changes",
    (
        {"pipeline": "sdxl_turbo"},
        {"steps": 3},
        {"steps": 9},
        {"guidance_scale": -0.0},
        {"guidance_scale": 1.0},
    ),
)
def test_preview_input_rejects_non_lcm_profile(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    import specstyle.workflow.preview_job_input as module

    source, style = _png("white"), _png("blue")
    files = (
        _private_file(tmp_path / "source", source),
        _private_file(tmp_path / "style", style),
        _private_file(tmp_path / "spec", _spec(style, **changes)),
        _private_file(tmp_path / "metadata", _metadata()),
    )
    style_root = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        metadata = module.load_preview_job_input_metadata(files[3])
        with pytest.raises(DomainError, match="preview job input"):
            module.open_preview_job_input(
                files[0], files[1], files[2], style_root, metadata, _context(), 0
            )
    finally:
        os.close(style_root)
        for fd in files:
            os.close(fd)

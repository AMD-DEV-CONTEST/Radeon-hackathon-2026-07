"""GEN-003..006 + ROCM probe + SEC registry — shipped entry points."""

from __future__ import annotations

from dataclasses import replace
import importlib
from pathlib import Path

import pytest

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.generation.diffusers_backend import (
    DiffusersBackend,
)
from specstyle.generation.model_registry import ModelDescriptor, ModelRegistry
from specstyle.generation.output_profiles import PROFILES, render_output_profile
from specstyle.generation.pipeline_factory import PipelineFactory
from specstyle.generation.preview import StrengthMapping, map_user_strength
from specstyle.generation.rocm_probe import probe_rocm, require_rocm


def _sha(c: str = "a") -> Sha256:
    return Sha256(c * 64)


_REVISION = "a" * 40


def _registry() -> ModelRegistry:
    fam = "sdxl"
    return ModelRegistry(
        (
            ModelDescriptor(
                "base1", "base", _REVISION, _sha("1"), "Apache-2.0", "APPROVED", fam
            ),
            ModelDescriptor(
                "ip1", "ip_adapter", _REVISION, _sha("2"), "Apache-2.0", "APPROVED", fam
            ),
            ModelDescriptor(
                "cn1", "controlnet", _REVISION, _sha("3"), "Apache-2.0", "APPROVED", fam
            ),
            ModelDescriptor(
                "prev1",
                "preview_adapter",
                _REVISION,
                _sha("4"),
                "Apache-2.0",
                "APPROVED",
                fam,
            ),
            ModelDescriptor(
                "bad", "base", _REVISION, _sha("5"), "Unknown", "UNKNOWN", fam
            ),
        )
    )


def test_registry_blocks_unknown_and_floating() -> None:
    reg = _registry()
    with pytest.raises(DomainError, match="UNKNOWN"):
        reg.require_production("bad")
    with pytest.raises(DomainError):
        ModelDescriptor("x", "base", "main", _sha("a"), "MIT", "APPROVED", "sdxl")


def test_pipeline_factory_family_gate(tmp_path: Path) -> None:
    factory = PipelineFactory(_registry(), tmp_path / "cache")
    graph = factory.build_production("base1", "ip1", "cn1")
    assert graph.profile == "production"
    assert graph.cache_root == "cache"
    preview = factory.build_preview("base1", "ip1", "cn1", "prev1")
    assert preview.preview_adapter is not None


def test_rocm_probe_honest_without_gpu() -> None:
    result = probe_rocm(None)
    # On this Mac, likely unavailable — never forge True without hip.
    if not result.available:
        with pytest.raises(DomainError, match="rocm not available"):
            require_rocm(result)
    assert result.snapshot_hash


def test_strength_mapping_monotone() -> None:
    m = StrengthMapping("map-v1", 4, 30, 0.0, 5.0)
    low = map_user_strength(0.2, m, "production")
    high = map_user_strength(0.8, m, "production")
    assert low["ip_adapter_scale"] < high["ip_adapter_scale"]  # type: ignore[operator]
    assert low["steps"] == 30


def test_output_profiles_sizes_and_deterministic() -> None:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, format="PNG")
    src = buf.getvalue()
    for name, layout in PROFILES.items():
        kwargs = {}
        if name == "background_sequence":
            kwargs["sequence_index"] = 0
        a = render_output_profile(src, name, text="hello", **kwargs)
        b = render_output_profile(src, name, text="hello", **kwargs)
        assert a == b
        img = Image.open(BytesIO(a))
        assert img.size == layout.size


def test_pinned_xhs_renderer_contains_without_stretch_or_overlay() -> None:
    from io import BytesIO

    from PIL import Image

    module = importlib.import_module("specstyle.generation.output_profiles")
    assert hasattr(module, "render_production_output")
    contracts = importlib.import_module("specstyle.generation.output_profile_contracts")
    capability = contracts.production_output_profile_capabilities()[0]
    source = BytesIO()
    Image.new("RGB", (80, 40), (200, 10, 20)).save(source, format="PNG")

    first = module.render_production_output(source.getvalue(), capability)
    second = module.render_production_output(source.getvalue(), capability)

    assert first == second
    rendered = Image.open(BytesIO(first))
    assert rendered.mode == "RGB"
    assert rendered.size == (1080, 1080)
    assert rendered.info == {}
    assert rendered.getpixel((540, 540)) == (200, 10, 20)
    assert rendered.getpixel((0, 0)) == (255, 255, 255)


def test_pinned_talking_cover_renderer_centers_without_crop_or_stretch() -> None:
    from io import BytesIO

    from PIL import Image

    module = importlib.import_module("specstyle.generation.output_profiles")
    contracts = importlib.import_module("specstyle.generation.output_profile_contracts")
    capabilities = contracts.production_output_profile_capabilities()
    assert tuple(item.profile for item in capabilities) == (
        "xhs_grid",
        "talking_head_cover",
        "background_sequence",
    )
    capability = capabilities[1]
    assert capability.pin.id == "specstyle-output-renderer-talking-head-cover"
    assert capability.pin.revision == "v1"
    assert capability.pin.sha256.value == (
        "8325042d826cdcbfd3fa376f570109be331349c7a193bdd3fe33d7b305d08648"
    )
    assert capability.render_contract.native_resolution == (768, 768)
    assert capability.render_contract.final_resolution == (1080, 1440)
    assert capability.render_contract.fit == "contain_pad_center"
    source = BytesIO()
    Image.new("RGB", (768, 768), (20, 140, 60)).save(source, format="PNG")

    first = module.render_production_output(source.getvalue(), capability)
    second = module.render_production_output(source.getvalue(), capability)

    assert first == second
    with Image.open(BytesIO(first)) as rendered:
        assert rendered.mode == "RGB"
        assert rendered.size == (1080, 1440)
        assert rendered.info == {}
        assert rendered.getpixel((0, 179)) == (255, 255, 255)
        assert rendered.getpixel((0, 180)) == (20, 140, 60)
        assert rendered.getpixel((1079, 1259)) == (20, 140, 60)
        assert rendered.getpixel((1079, 1260)) == (255, 255, 255)

    wrong_size = BytesIO()
    Image.new("RGB", (1024, 1024), (20, 140, 60)).save(wrong_size, format="PNG")
    with pytest.raises(DomainError, match="^invalid native output resolution$"):
        module.render_production_output(wrong_size.getvalue(), capability)
    with pytest.raises(TypeError):
        module.render_production_output(source.getvalue(), capability, "title")


def test_pinned_background_sequence_renderer_is_single_index_zero_frame() -> None:
    from io import BytesIO

    from PIL import Image

    module = importlib.import_module("specstyle.generation.output_profiles")
    contracts = importlib.import_module("specstyle.generation.output_profile_contracts")
    capability = next(
        item
        for item in contracts.production_output_profile_capabilities()
        if item.profile == "background_sequence"
    )
    assert capability.pin.id == "specstyle-output-renderer-background-sequence"
    assert capability.pin.revision == "v1"
    assert capability.pin.sha256.value == (
        "ac043a1b1070143cb50ae4837aa4d01178e2b7b0a9028c997fb7abde68952a2b"
    )
    contract = capability.render_contract
    assert contract.native_resolution == (768, 768)
    assert contract.final_resolution == (1920, 1080)
    assert contract.fit == "contain_pad_center"
    assert contract.sequence_semantics == "single_item_sequence_index_zero"
    source = BytesIO()
    Image.new("RGB", (768, 768), (15, 90, 170)).save(source, format="PNG")

    first = module.render_production_output(source.getvalue(), capability)
    second = module.render_production_output(source.getvalue(), capability)

    assert first == second
    with Image.open(BytesIO(first)) as rendered:
        assert rendered.mode == "RGB"
        assert rendered.size == (1920, 1080)
        assert rendered.info == {}
        assert rendered.getpixel((419, 0)) == (255, 255, 255)
        assert rendered.getpixel((420, 0)) == (15, 90, 170)
        assert rendered.getpixel((1499, 1079)) == (15, 90, 170)
        assert rendered.getpixel((1500, 1079)) == (255, 255, 255)

    with pytest.raises(TypeError):
        module.render_production_output(source.getvalue(), capability, 0)


def test_production_renderer_rejects_a_forged_capability_pin() -> None:
    from io import BytesIO

    from PIL import Image

    module = importlib.import_module("specstyle.generation.output_profiles")
    contracts = importlib.import_module("specstyle.generation.output_profile_contracts")
    capability = contracts.production_output_profile_capabilities()[0]
    forged = replace(capability, pin=replace(capability.pin, sha256=_sha("0")))
    source = BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(source, format="PNG")

    with pytest.raises(DomainError, match="^invalid output renderer contract$"):
        module.render_production_output(source.getvalue(), forged)


def test_diffusers_backend_rejects_unsealed_pipeline_injection() -> None:
    with pytest.raises(DomainError, match="loaded production pipeline"):
        DiffusersBackend(object(), lambda _ref: b"")


def test_family_mismatch_blocked() -> None:
    reg = ModelRegistry(
        (
            ModelDescriptor(
                "base1", "base", _REVISION, _sha("1"), "Apache-2.0", "APPROVED", "sdxl"
            ),
            ModelDescriptor(
                "ip1",
                "ip_adapter",
                _REVISION,
                _sha("2"),
                "Apache-2.0",
                "APPROVED",
                "other",
            ),
            ModelDescriptor(
                "cn1",
                "controlnet",
                _REVISION,
                _sha("3"),
                "Apache-2.0",
                "APPROVED",
                "sdxl",
            ),
        )
    )
    factory = PipelineFactory(reg, Path("cache"))
    with pytest.raises(DomainError, match="family"):
        factory.build_production("base1", "ip1", "cn1")


def test_blocked_license_not_production() -> None:
    reg = ModelRegistry(
        (
            ModelDescriptor(
                "base1", "base", _REVISION, _sha("1"), "Proprietary", "BLOCKED", "sdxl"
            ),
        )
    )
    with pytest.raises(DomainError, match="BLOCKED"):
        reg.require_production("base1")


def test_preview_backend_rejects_production_profile() -> None:
    from specstyle.generation.pipeline_factory import PipelineGraph
    from specstyle.generation.preview import PreviewBackend, StrengthMapping
    from tests.unit.exporting.test_manifest import _production_request

    reg = _registry()
    factory = PipelineFactory(reg, Path("cache"))
    g = factory.build_preview("base1", "ip1", "cn1", "prev1")
    pgraph = PipelineGraph(
        "preview", g.base, g.ip_adapter, g.controlnet, g.preview_adapter, g.cache_root
    )

    class Stub:
        def generate(self, request):  # pragma: no cover
            raise AssertionError("should not be called")

    prev = PreviewBackend(pgraph, Stub(), StrengthMapping("map-v1", 4, 30, 0.0, 5.0))
    req = _production_request()
    with pytest.raises(DomainError, match="preview"):
        prev.generate(req)

"""Real OpenCV Canny control-input builder contract tests."""

from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
import importlib
from importlib import metadata
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import zlib

import cv2
import numpy as np
import pytest
from PIL import Image, features

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AssetId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.canny import (
    CannyControlInputBuilder,
    CannyProcessorConfig,
    _processor_material,
)
from specstyle.generation.preprocess import (
    PreparedImage,
    PreprocessPlan,
    preprocess_image,
)
from specstyle.generation.requests import PreparedControlInput
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import CompiledExecutionGraph, ResourcePin
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.models import StyleSpecV1
from tests.unit.spec.test_compiler import context, raw_spec


def _assert_unique_canny_contract_definitions(project_root: Path) -> None:
    source_root = project_root / "src"
    definitions = {
        "CannyProcessorConfig": [],
        "_rebuild_canny_processor_config": [],
    }
    private_canny_classes: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name == "CannyProcessorConfig":
                    definitions[node.name].append(relative)
                elif node.name == "_Canny":
                    private_canny_classes.append(relative)
            elif (
                isinstance(node, ast.FunctionDef)
                and node.name == "_rebuild_canny_processor_config"
            ):
                definitions[node.name].append(relative)

    canonical = ["specstyle/generation/canny_contracts.py"]
    assert definitions["CannyProcessorConfig"] == canonical
    assert definitions["_rebuild_canny_processor_config"] == canonical
    assert not private_canny_classes


def test_canny_config_uses_one_canonical_contract() -> None:
    contracts = importlib.import_module("specstyle.generation.canny_contracts")
    canny = importlib.import_module("specstyle.generation.canny")

    assert canny.CannyProcessorConfig is contracts.CannyProcessorConfig
    assert canny.CannyProcessorConfig.__module__ == (
        "specstyle.generation.canny_contracts"
    )
    assert not hasattr(canny, "_rebuild_config")


def test_canny_contract_definitions_are_unique_across_source_tree() -> None:
    project_root = Path(__file__).parents[3]

    _assert_unique_canny_contract_definitions(project_root)


@pytest.mark.parametrize(
    "definition",
    (
        "class CannyProcessorConfig:\n    pass\n",
        "def _rebuild_canny_processor_config():\n    pass\n",
        "class _Canny:\n    pass\n",
    ),
)
def test_unique_canny_contract_scan_detects_forbidden_source_definition(
    tmp_path: Path, definition: str
) -> None:
    contract = tmp_path / "src/specstyle/generation/canny_contracts.py"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        "class CannyProcessorConfig:\n    pass\n"
        "def _rebuild_canny_processor_config():\n    pass\n",
        encoding="utf-8",
    )
    outside_source = tmp_path / "tests/unit/test_duplicate.py"
    outside_source.parent.mkdir(parents=True)
    outside_source.write_text(
        "class CannyProcessorConfig:\n    pass\n",
        encoding="utf-8",
    )

    _assert_unique_canny_contract_definitions(tmp_path)

    duplicate = tmp_path / "src/specstyle/production/duplicate.py"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text(definition, encoding="utf-8")
    with pytest.raises(AssertionError):
        _assert_unique_canny_contract_definitions(tmp_path)


def test_context_canny_parser_has_no_parameter_semantics() -> None:
    project_root = Path(__file__).parents[3]
    path = project_root / "src/specstyle/production/context_config.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_canny"
    ]

    assert len(functions) == 1
    function = functions[0]
    assert len(function.body) == 2
    assert isinstance(function.body[0], ast.Assign)
    assert isinstance(function.body[1], ast.Return)
    assert not any(
        isinstance(node, (ast.Compare, ast.BoolOp)) for node in ast.walk(function)
    )
    calls = [
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert calls == ["_exact", "CannyProcessorConfig"]


def test_importing_canny_contract_does_not_load_runtime_dependencies() -> None:
    src_root = Path(__file__).parents[3] / "src"
    script = """
import sys

sys.path.insert(0, sys.argv[1])
from specstyle.generation.canny_contracts import CannyProcessorConfig

assert CannyProcessorConfig(100, 200, 3, False).low_threshold == 100
forbidden = (
    "cv2",
    "numpy",
    "PIL",
    "Pillow",
    "diffusers",
    "torch",
    "gradio",
    "specstyle.workflow.production_service",
)
assert not [name for name in forbidden if name in sys.modules]
"""

    completed = subprocess.run(
        (sys.executable, "-B", "-c", script, str(src_root)),
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def _encoded_square() -> bytes:
    image = Image.new("RGB", (64, 64), "black")
    try:
        for x in range(16, 48):
            for y in range(16, 48):
                image.putpixel((x, y), (255, 255, 255))
        output = BytesIO()
        image.save(output, "PNG", optimize=False, compress_level=9)
        return output.getvalue()
    finally:
        image.close()


def _source() -> PreparedImage:
    encoded = _encoded_square()
    return preprocess_image(
        encoded,
        AssetRef(AssetId("source"), hash_bytes(encoded)),
        PreprocessPlan(
            (64, 64),
            "contain_pad",
            (1, 2, 3),
            ResourcePin(
                "source-preprocessor", "v1", hash_bytes(b"source-preprocessor")
            ),
        ),
    )


@pytest.fixture(scope="module")
def production_graph() -> CompiledExecutionGraph:
    compiled = compile_style_spec(StyleSpecV1.model_validate(raw_spec()), context())
    return replace(compiled.production_graphs[0], resolution=(64, 64))


@pytest.mark.parametrize(
    "values",
    [
        (True, 200, 3, False),
        (100, 200.0, 3, False),
        (-1, 200, 3, False),
        (100, 100, 3, False),
        (100, 256, 3, False),
        (100, 200, True, False),
        (100, 200, 5, False),
        (100, 200, 3, 0),
        (100, 200, 3, True),
    ],
)
def test_config_requires_exact_supported_canny_parameters(
    values: tuple[object, ...],
) -> None:
    with pytest.raises(DomainError):
        CannyProcessorConfig(*values)  # type: ignore[arg-type]


def test_config_and_builder_are_frozen_strict_values() -> None:
    config = CannyProcessorConfig(100, 200, 3, False)
    assert config == CannyProcessorConfig(100, 200, 3, False)
    assert not hasattr(config, "__dict__")
    with pytest.raises((AttributeError, TypeError)):
        config.low_threshold = 1  # type: ignore[misc]

    class HostileConfig(CannyProcessorConfig):
        pass

    with pytest.raises(DomainError):
        CannyControlInputBuilder(HostileConfig(100, 200, 3, False))
    with pytest.raises(DomainError):
        CannyControlInputBuilder(object())  # type: ignore[arg-type]


def test_builder_emits_literal_golden_edge_pixels_as_clean_rgb_png(
    production_graph: CompiledExecutionGraph,
) -> None:
    source = _source()
    result = CannyControlInputBuilder(CannyProcessorConfig(100, 200, 3, False)).build(
        source, production_graph
    )

    assert type(result) is PreparedControlInput
    assert result.kind == "canny"
    assert result.source == source.source
    image = Image.open(BytesIO(result.image.content))
    try:
        image.load()
        pixels = np.asarray(image)
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.size == (64, 64)
        assert getattr(image, "n_frames", 1) == 1
        assert not image.info
        assert np.array_equal(pixels[:, :, 0], pixels[:, :, 1])
        assert np.array_equal(pixels[:, :, 1], pixels[:, :, 2])
        assert np.count_nonzero(pixels[:, :, 0]) == 124
        assert (
            hashlib.sha256(pixels[:, :, 0].tobytes()).hexdigest()
            == "b3d0f80acac26a06bcfbf0584d9534b2f9014607044579985733ab493ac7323e"
        )
    finally:
        image.close()


def test_builder_accepts_preview_canny_graph(
    production_graph: CompiledExecutionGraph,
) -> None:
    preview_graph = replace(
        production_graph,
        generation_profile="preview",
        pipeline="lcm",
        steps=4,
        guidance_scale=0.0,
        scheduler=None,
    )

    result = CannyControlInputBuilder(CannyProcessorConfig(100, 200, 3, False)).build(
        _source(), preview_graph
    )

    assert result.kind == "canny"
    assert (result.image.width, result.image.height) == preview_graph.resolution


def test_builder_calls_exact_opencv_pipeline_parameters(
    production_graph: CompiledExecutionGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, object]] = []
    real_imdecode = cv2.imdecode
    real_cvt_color = cv2.cvtColor
    real_canny = cv2.Canny

    def imdecode(array: np.ndarray, flag: int) -> np.ndarray:
        calls.append(("imdecode", flag))
        return real_imdecode(array, flag)

    def cvt_color(array: np.ndarray, conversion: int) -> np.ndarray:
        calls.append(("cvtColor", conversion))
        return real_cvt_color(array, conversion)

    def canny(
        array: np.ndarray,
        low: int,
        high: int,
        *,
        apertureSize: int,
        L2gradient: bool,
    ) -> np.ndarray:
        calls.append(("Canny", (low, high, apertureSize, L2gradient)))
        return real_canny(
            array,
            low,
            high,
            apertureSize=apertureSize,
            L2gradient=L2gradient,
        )

    monkeypatch.setattr(cv2, "imdecode", imdecode)
    monkeypatch.setattr(cv2, "cvtColor", cvt_color)
    monkeypatch.setattr(cv2, "Canny", canny)
    CannyControlInputBuilder(CannyProcessorConfig(100, 200, 3, False)).build(
        _source(), production_graph
    )
    assert calls == [
        ("imdecode", cv2.IMREAD_COLOR),
        ("cvtColor", cv2.COLOR_BGR2GRAY),
        ("Canny", (100, 200, 3, False)),
    ]


def test_builder_passes_every_pinned_png_encoder_parameter(
    production_graph: CompiledExecutionGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source()
    real_save = Image.Image.save
    calls: list[dict[str, object]] = []

    def tracked_save(
        image: Image.Image, output: object, *args: object, **kwargs: object
    ) -> None:
        calls.append(dict(kwargs))
        real_save(image, output, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Image.Image, "save", tracked_save)
    CannyControlInputBuilder(CannyProcessorConfig(100, 200, 3, False)).build(
        source, production_graph
    )
    assert calls == [
        {
            "format": "PNG",
            "optimize": False,
            "compress_level": 9,
            "compress_type": 0,
        }
    ]


def test_processor_material_contains_actual_versions_and_all_algorithm_choices() -> (
    None
):
    material = json.loads(_processor_material(CannyProcessorConfig(100, 200, 3, False)))
    assert material == {
        "algorithm": "opencv.Canny",
        "algorithm_version": "1",
        "aperture_size": 3,
        "color_conversions": [
            "cv2.imdecode:IMREAD_COLOR",
            "cv2.cvtColor:COLOR_BGR2GRAY",
            "numpy.repeat:GRAY_TO_RGB",
        ],
        "dependencies": {
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "opencv_build_information_sha256": hashlib.sha256(
                cv2.getBuildInformation().encode("utf-8")
            ).hexdigest(),
            "opencv_distribution": "opencv-python-headless",
            "opencv_distribution_version": metadata.version("opencv-python-headless"),
            "pillow": Image.__version__,
            "pillow_linked_zlib": features.version_codec("zlib"),
            "python_zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
        },
        "high_threshold": 200,
        "l2_gradient": False,
        "low_threshold": 100,
        "png": {
            "compress_level": 9,
            "compress_type": 0,
            "format": "PNG",
            "metadata": "none",
            "optimize": False,
        },
        "schema": "specstyle.canny_processor.v1",
    }


def test_processor_pin_is_stable_and_changes_with_parameters_or_versions(
    production_graph: CompiledExecutionGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source()

    def pin(config: CannyProcessorConfig):
        return (
            CannyControlInputBuilder(config)
            .build(source, production_graph)
            .processor_pin
        )

    baseline = pin(CannyProcessorConfig(100, 200, 3, False))
    assert baseline == pin(CannyProcessorConfig(100, 200, 3, False))
    assert baseline != pin(CannyProcessorConfig(99, 200, 3, False))
    assert baseline != pin(CannyProcessorConfig(100, 201, 3, False))
    mutations = (
        lambda patch: patch.setattr(cv2, "__version__", f"{cv2.__version__}-changed"),
        lambda patch: patch.setattr(
            features, "version_codec", lambda _name: "linked-zlib-changed"
        ),
        lambda patch: patch.setattr(
            zlib, "ZLIB_RUNTIME_VERSION", "python-zlib-changed"
        ),
        lambda patch: patch.setattr(
            metadata, "version", lambda _name: "distribution-changed"
        ),
        lambda patch: patch.setattr(
            cv2, "getBuildInformation", lambda: "build-information-changed"
        ),
        lambda patch: patch.setattr(
            "specstyle.generation.canny._PNG_COMPRESS_TYPE", 1, raising=False
        ),
    )
    for mutate in mutations:
        with monkeypatch.context() as patch:
            mutate(patch)
            assert baseline != pin(CannyProcessorConfig(100, 200, 3, False))


@pytest.mark.parametrize(
    "failure",
    ["linked_zlib", "python_zlib", "distribution", "build_information"],
)
def test_processor_material_fails_closed_when_provenance_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "linked_zlib":
        monkeypatch.setattr(features, "version_codec", lambda _name: None)
    elif failure == "python_zlib":
        monkeypatch.setattr(zlib, "ZLIB_RUNTIME_VERSION", "")
    elif failure == "distribution":
        monkeypatch.setattr(
            metadata,
            "version",
            lambda _name: (_ for _ in ()).throw(
                metadata.PackageNotFoundError("opencv-python-headless")
            ),
        )
    else:
        monkeypatch.setattr(cv2, "getBuildInformation", lambda: "  \n")
    with pytest.raises(InfrastructureError):
        _processor_material(CannyProcessorConfig(100, 200, 3, False))


def test_snapshot_preserves_source_audit_fields_and_replaces_only_processor_pin(
    production_graph: CompiledExecutionGraph,
) -> None:
    source = _source()
    result = CannyControlInputBuilder(CannyProcessorConfig(100, 200, 3, False)).build(
        source, production_graph
    )
    before = source.snapshot
    after = result.image.snapshot
    assert (
        after.input_format,
        after.input_mode,
        after.input_size,
        after.exif_orientation,
        after.pillow_version,
    ) == (
        before.input_format,
        before.input_mode,
        before.input_size,
        before.exif_orientation,
        before.pillow_version,
    )
    assert (
        after.plan.target_size,
        after.plan.resize_mode,
        after.plan.background,
    ) == (
        before.plan.target_size,
        before.plan.resize_mode,
        before.plan.background,
    )
    assert after.plan.processor_pin != before.plan.processor_pin
    assert PreparedImage(result.source, result.image.content, after) == result.image


def test_builder_rejects_wrong_source_graph_profile_controlnet_or_resolution(
    production_graph: CompiledExecutionGraph,
) -> None:
    builder = CannyControlInputBuilder(CannyProcessorConfig(100, 200, 3, False))
    source = _source()
    depth = replace(
        production_graph,
        controlnet=replace(production_graph.controlnet, controlnet_type="depth"),
    )
    wrong_size = replace(production_graph, resolution=(128, 64))
    for wrong_source, wrong_graph in (
        (object(), production_graph),
        (source, object()),
        (source, depth),
        (source, wrong_size),
    ):
        with pytest.raises(DomainError):
            builder.build(wrong_source, wrong_graph)  # type: ignore[arg-type]


@pytest.mark.parametrize("failure", ["decode_none", "decode_error", "encode"])
def test_builder_maps_decode_and_encode_failures_to_infrastructure_error(
    production_graph: CompiledExecutionGraph,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    source = _source()
    if failure == "decode_none":
        monkeypatch.setattr(cv2, "imdecode", lambda *_args: None)
    elif failure == "decode_error":
        monkeypatch.setattr(
            cv2,
            "imdecode",
            lambda *_args: (_ for _ in ()).throw(ValueError("decode failed")),
        )
    else:
        monkeypatch.setattr(
            Image.Image,
            "save",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("encode failed")),
        )
    with pytest.raises(InfrastructureError):
        CannyControlInputBuilder(CannyProcessorConfig(100, 200, 3, False)).build(
            source, production_graph
        )


def test_builder_maps_invalid_internal_encoding_to_infrastructure_error(
    production_graph: CompiledExecutionGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "specstyle.generation.canny._encode_clean_png", lambda _pixels: b"bad"
    )
    with pytest.raises(InfrastructureError):
        CannyControlInputBuilder(CannyProcessorConfig(100, 200, 3, False)).build(
            _source(), production_graph
        )


def test_builder_does_not_swallow_memory_error(
    production_graph: CompiledExecutionGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cv2,
        "Canny",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError("oom")),
    )
    with pytest.raises(MemoryError, match="oom"):
        CannyControlInputBuilder(CannyProcessorConfig(100, 200, 3, False)).build(
            _source(), production_graph
        )


def test_builder_closes_output_image_when_encoding_fails(
    production_graph: CompiledExecutionGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fromarray = Image.fromarray
    closed: list[bool] = []

    def tracked_fromarray(array: np.ndarray) -> Image.Image:
        image = real_fromarray(array)
        real_close = image.close

        def close() -> None:
            closed.append(True)
            real_close()

        image.close = close
        image.save = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("encode failed")
        )
        return image

    monkeypatch.setattr(Image, "fromarray", tracked_fromarray)
    with pytest.raises(InfrastructureError):
        CannyControlInputBuilder(CannyProcessorConfig(100, 200, 3, False)).build(
            _source(), production_graph
        )
    assert closed == [True]

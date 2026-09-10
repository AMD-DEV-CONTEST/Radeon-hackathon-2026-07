"""AST, import, signature, and size gates for private production modules."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

import specstyle.verification as verification_package


_MODULE_DIR = Path(__file__).parents[3] / "src" / "specstyle" / "verification"
_MODULES = ("production.py", "production_contracts.py", "production_metrics.py")
_BINDINGS = _MODULE_DIR / "l1" / "production_bindings.py"
_SRC_ROOT = Path(__file__).parents[3] / "src"


def _source(name: str) -> str:
    return (_MODULE_DIR / name).read_text(encoding="utf-8")


def _tree(name: str) -> ast.Module:
    return ast.parse(_source(name))


def _imports(name: str) -> tuple[str, ...]:
    values: list[str] = []
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            values.append(node.module)
    return tuple(values)


def _literal_homes(src_root: Path, literal: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(src_root).as_posix()
            for path in src_root.rglob("*.py")
            if literal in path.read_text(encoding="utf-8")
        )
    )


def _assert_literal_has_one_authoritative_home(src_root: Path, literal: str) -> None:
    assert _literal_homes(src_root, literal) == (
        "specstyle/verification/l1/production_bindings.py",
    )


def test_private_modules_export_nothing_and_package_does_not_reexport() -> None:
    for name in _MODULES:
        module = importlib.import_module(f"specstyle.verification.{name[:-3]}")
        assert module.__all__ == ()
    for name in (
        "ArtifactResolver",
        "_ProductionVerifierFactory",
        "_ProductionVerificationAllowlist",
    ):
        assert not hasattr(verification_package, name)


def test_production_ast_excludes_fake_and_legacy_verifier_dependencies() -> None:
    source = _source("production.py")
    forbidden = (
        "fake_backend",
        "reliability.fixtures",
        "FakeStyleEncoder",
        "l2.torch_encoder",
        "l2.threshold_profile",
        "verification.l3.mask",
        "verification.l3.product",
        "tests.",
    )
    assert all(value not in source for value in forbidden)


def test_contracts_and_metrics_keep_their_frozen_dependency_boundaries() -> None:
    contracts = _source("production_contracts.py")
    for forbidden in (
        "LoadedPipeline",
        "ArtifactResolver",
        "GeneratedArtifact",
        "StyleAssetResolver",
        "bytes",
        "BytesIO",
        "workflow",
        "production import",
    ):
        assert forbidden not in contracts
    metrics = _source("production_metrics.py")
    for forbidden in (
        "GenerationRequest",
        "GeneratedArtifact",
        "ArtifactResolver",
        "LoadedPipeline",
        "diffusers_loader",
        "StyleAssetResolver",
        "workflow",
    ):
        assert forbidden not in metrics


def test_private_module_import_graph_has_no_cycle() -> None:
    production_imports = _imports("production.py")
    contracts_imports = _imports("production_contracts.py")
    metrics_imports = _imports("production_metrics.py")
    assert "specstyle.verification.production_contracts" in production_imports
    assert "specstyle.verification.production_metrics" in production_imports
    assert "specstyle.verification.production" not in contracts_imports
    assert "specstyle.verification.production" not in metrics_imports


def test_factory_and_verifier_signatures_remain_positional_only() -> None:
    production = importlib.import_module("specstyle.verification.production")
    signatures = {
        production._create_production_verifier_factory: ("loaded", "allowlist"),
        production._ProductionVerifierFactory.create: (
            "self",
            "request",
            "plan",
            "artifact_resolver",
            "style_resolver",
        ),
        production._BoundProductionVerifier.verify: ("self", "artifacts", "rules"),
        production.ArtifactResolver.__call__: ("self", "reference"),
    }
    for callable_value, names in signatures.items():
        parameters = tuple(inspect.signature(callable_value).parameters.values())
        assert tuple(parameter.name for parameter in parameters) == names
        assert all(
            parameter.kind is inspect.Parameter.POSITIONAL_ONLY
            for parameter in parameters
        )


def test_private_modules_and_handwritten_functions_stay_within_size_limits() -> None:
    for name in _MODULES:
        source = _source(name)
        assert len(source.splitlines()) <= 800
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno is not None
                assert node.end_lineno - node.lineno + 1 < 50, (
                    name,
                    node.name,
                    node.end_lineno - node.lineno + 1,
                )


def test_l1_implementation_literals_have_one_authoritative_home() -> None:
    literals = (
        "decode_png_rgb_no_metadata_v1",
        "dimensions_exact_v1",
        "pixels_nonblank_v1",
        "technical_rgb_png_bundle_v1",
    )
    for literal in literals:
        _assert_literal_has_one_authoritative_home(_SRC_ROOT, literal)


def test_literal_home_scan_detects_a_second_source_copy(tmp_path: Path) -> None:
    literal = "decode_png_rgb_no_metadata_v1"
    src_root = tmp_path / "src"
    authority = src_root / "specstyle" / "verification" / "l1"
    duplicate = src_root / "specstyle" / "workflow"
    ignored_tests = tmp_path / "tests"
    authority.mkdir(parents=True)
    duplicate.mkdir(parents=True)
    ignored_tests.mkdir()
    (authority / "production_bindings.py").write_text(literal, encoding="utf-8")
    (duplicate / "production_service.py").write_text(literal, encoding="utf-8")
    (ignored_tests / "test_copy.py").write_text(literal, encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_literal_has_one_authoritative_home(src_root, literal)


def test_l1_binding_authority_has_only_low_level_dependencies() -> None:
    tree = ast.parse(_BINDINGS.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(node.module)

    assert set(imports) <= {
        "__future__",
        "dataclasses",
        "enum",
        "specstyle.domain.identifiers",
        "specstyle.errors",
    }
    assert all("workflow" not in name for name in imports)
    assert "specstyle.verification.production" not in imports

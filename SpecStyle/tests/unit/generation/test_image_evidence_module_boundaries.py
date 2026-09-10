"""Dependency and export boundaries for private image-evidence helpers."""

from __future__ import annotations

import ast
from pathlib import Path


_ROOT = Path(__file__).parents[3]
_MODULE = _ROOT / "src/specstyle/generation/image_evidence.py"
_PACKAGE = _ROOT / "src/specstyle/generation/__init__.py"


def test_image_evidence_module_is_private_and_does_not_import_loader() -> None:
    assert _MODULE.is_file()
    source = _MODULE.read_text()
    tree = ast.parse(source)
    assert "LoadedPipeline" not in source
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            assert node.name.startswith("_")
        if isinstance(node, ast.ImportFrom):
            assert node.module != "specstyle.generation.diffusers_loader"
            if node.module != "__future__":
                assert all(
                    alias.asname and alias.asname.startswith("_")
                    for alias in node.names
                )
        if isinstance(node, ast.Import):
            assert all(
                alias.name != "specstyle.generation.diffusers_loader"
                for alias in node.names
            )
            assert all(
                alias.asname and alias.asname.startswith("_") for alias in node.names
            )
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            names = (target.id for target in targets if isinstance(target, ast.Name))
            assert all(name.startswith("_") for name in names)


def test_generation_package_does_not_reexport_image_evidence_helpers() -> None:
    source = _PACKAGE.read_text()
    assert "image_evidence" not in source
    assert "_ProcessorProvenance" not in source
    assert "_VerifiedImageEvidence" not in source

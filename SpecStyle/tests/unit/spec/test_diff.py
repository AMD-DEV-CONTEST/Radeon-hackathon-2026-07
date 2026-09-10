"""SPEC-004 semantic_diff tests."""

from __future__ import annotations

from specstyle.spec.diff import semantic_diff
from specstyle.spec.migrations import migrate_style_spec
from specstyle.spec.models import StyleSpecV1
from tests.unit.spec.test_models import _valid_spec


def test_semantic_diff_identical_is_empty() -> None:
    a = StyleSpecV1(**_valid_spec())
    b = StyleSpecV1(**_valid_spec())
    diff = semantic_diff(a, b)
    assert diff.source_version == "1.0"
    assert diff.target_version == "1.0"
    assert diff.changes == ()


def test_semantic_diff_migration_sorted_paths() -> None:
    source = StyleSpecV1(**_valid_spec())
    target = migrate_style_spec(source, "1.1").target_spec
    diff = semantic_diff(source, target)
    paths = [c.path for c in diff.changes]
    assert paths == sorted(paths)
    assert all(c.kind in ("added", "changed") for c in diff.changes)

"""
tests/corpus/test_schema_registry.py — Schema version registry tests.

Verifies:
  - Current version is known and accepted
  - Missing / empty / unknown versions are rejected
  - migrate() returns a new dict without mutating original
  - require_migration() identifies old records correctly
  - version_history() returns the ordered list
  - Singleton get_registry() returns same instance
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.schema_registry import (
    CURRENT_VERSION,
    SchemaRegistry,
    SchemaVersionError,
    get_registry,
)

# ---------------------------------------------------------------------------
# validate_version
# ---------------------------------------------------------------------------


def test_current_version_is_accepted():
    SchemaRegistry().validate_version(CURRENT_VERSION)  # must not raise


def test_none_version_is_rejected():
    with pytest.raises(SchemaVersionError, match="missing"):
        SchemaRegistry().validate_version(None)


def test_empty_string_version_is_rejected():
    with pytest.raises(SchemaVersionError, match="missing"):
        SchemaRegistry().validate_version("")


def test_unknown_version_is_rejected():
    with pytest.raises(SchemaVersionError, match="Unknown"):
        SchemaRegistry().validate_version("determinex-agent-trace-v99")


def test_future_version_string_is_rejected():
    with pytest.raises(SchemaVersionError):
        SchemaRegistry().validate_version("determinex-agent-trace-v9999")


def test_arbitrary_string_is_rejected():
    with pytest.raises(SchemaVersionError, match="Unknown"):
        SchemaRegistry().validate_version("made-up-schema-2026")


# ---------------------------------------------------------------------------
# is_current
# ---------------------------------------------------------------------------


def test_is_current_true_for_current_version():
    assert SchemaRegistry().is_current(CURRENT_VERSION)


def test_is_current_false_for_unknown():
    assert not SchemaRegistry().is_current("determinex-agent-trace-v99")


def test_is_current_false_for_empty():
    assert not SchemaRegistry().is_current("")


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------


def test_migrate_current_version_returns_equivalent_dict():
    registry = SchemaRegistry()
    record = {"schema_version": CURRENT_VERSION, "task_id": "t1", "_sig": "abc"}
    migrated = registry.migrate(record)
    assert migrated["schema_version"] == CURRENT_VERSION
    assert migrated["task_id"] == "t1"
    assert migrated["_sig"] == "abc"


def test_migrate_does_not_mutate_original():
    registry = SchemaRegistry()
    original = {"schema_version": CURRENT_VERSION, "task_id": "t2", "extra": "data"}
    original_copy = dict(original)
    migrated = registry.migrate(original)
    assert original == original_copy  # original unchanged
    assert migrated is not original  # new dict returned


def test_migrate_unknown_version_raises():
    registry = SchemaRegistry()
    with pytest.raises(SchemaVersionError):
        registry.migrate({"schema_version": "determinex-agent-trace-v99"})


def test_migrate_missing_version_raises():
    registry = SchemaRegistry()
    with pytest.raises(SchemaVersionError, match="missing"):
        registry.migrate({"task_id": "no-version"})


# ---------------------------------------------------------------------------
# require_migration
# ---------------------------------------------------------------------------


def test_require_migration_false_for_current_version():
    assert not SchemaRegistry().require_migration({"schema_version": CURRENT_VERSION})


def test_require_migration_false_for_missing_version():
    assert not SchemaRegistry().require_migration({})


def test_require_migration_false_for_unknown_version():
    # Unknown versions are rejected, not queued for migration
    assert not SchemaRegistry().require_migration({"schema_version": "determinex-agent-trace-v99"})


# ---------------------------------------------------------------------------
# version_history
# ---------------------------------------------------------------------------


def test_version_history_is_a_list():
    history = SchemaRegistry.version_history()
    assert isinstance(history, list)
    assert len(history) >= 1


def test_current_version_in_history():
    assert CURRENT_VERSION in SchemaRegistry.version_history()


def test_version_history_is_ordered_oldest_first():
    history = SchemaRegistry.version_history()
    # Current version is always last (newest)
    assert history[-1] == CURRENT_VERSION


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_registry_returns_same_instance():
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2


def test_get_registry_has_correct_current_version():
    assert get_registry().current == CURRENT_VERSION

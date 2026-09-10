"""SPEC-004 migration registry tests for contracts section 14."""

from __future__ import annotations

import copy

import pytest

from specstyle.errors import DomainError
from specstyle.spec.migrations import migrate_style_spec
from specstyle.spec.models import (
    DEFAULT_ENVIRONMENT_POLICY_V11,
    LEGACY_STRENGTH_MAPPING_VERSION,
    SCHEMA_URI_V11,
    StyleSpecV1,
    StyleSpecV11,
)
from tests.unit.spec.test_models import _valid_spec


def _v1() -> StyleSpecV1:
    return StyleSpecV1(**_valid_spec())


def test_migrate_1_0_to_1_1_golden() -> None:
    source = _v1()
    source_dump = source.model_dump(mode="json")
    result = migrate_style_spec(source, "1.1")
    assert result.source_version == "1.0"
    assert result.target_version == "1.1"
    assert result.path == ("1.0", "1.1")
    target = result.target_spec
    assert type(target) is StyleSpecV11
    assert target.schema_version == "1.1"
    assert target.schema_uri == SCHEMA_URI_V11
    assert target.style.strength_mapping_version == LEGACY_STRENGTH_MAPPING_VERSION
    assert target.replay_contract.environment_policy == DEFAULT_ENVIRONMENT_POLICY_V11
    # The source remains unchanged.
    assert source.model_dump(mode="json") == source_dump
    assert source.schema_version == "1.0"
    # Other fields are deeply equal except for the migration path.
    td = target.model_dump(mode="json")
    sd = copy.deepcopy(source_dump)
    sd["schema_version"] = "1.1"
    sd["schema_uri"] = SCHEMA_URI_V11
    sd["style"]["strength_mapping_version"] = LEGACY_STRENGTH_MAPPING_VERSION
    sd["replay_contract"]["environment_policy"] = DEFAULT_ENVIRONMENT_POLICY_V11
    assert td == sd
    paths = {c.path for c in result.diff.changes}
    assert "schema_version" in paths
    assert "schema_uri" in paths
    assert "style.strength_mapping_version" in paths
    assert "replay_contract.environment_policy" in paths


def test_migrate_idempotent_for_same_source() -> None:
    source = _v1()
    a = migrate_style_spec(source, "1.1")
    b = migrate_style_spec(source, "1.1")
    assert a.target_spec.model_dump(mode="json") == b.target_spec.model_dump(
        mode="json"
    )
    assert [c.path for c in a.diff.changes] == [c.path for c in b.diff.changes]


def test_migrate_rejects_identity_and_downgrade() -> None:
    v1 = _v1()
    with pytest.raises(DomainError, match="unsupported style spec migration"):
        migrate_style_spec(v1, "1.0")
    v11 = migrate_style_spec(v1, "1.1").target_spec
    with pytest.raises(DomainError, match="unsupported style spec migration"):
        migrate_style_spec(v11, "1.1")
    with pytest.raises(DomainError, match="unsupported style spec migration"):
        migrate_style_spec(v11, "1.0")


def test_migrate_rejects_unknown_version() -> None:
    with pytest.raises(DomainError, match="unsupported style spec migration"):
        migrate_style_spec(_v1(), "2.0")
    with pytest.raises(DomainError, match="unsupported style spec migration"):
        migrate_style_spec(_v1(), "0.9")

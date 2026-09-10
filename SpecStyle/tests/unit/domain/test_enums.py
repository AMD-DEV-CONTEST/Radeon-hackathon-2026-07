"""Unit tests for specstyle.domain enums.

Cover the frozen BOOT-002A contract: all seven enums derive from
``enum.StrEnum`` with matching names and values; aliases, custom ``_missing_``,
and permissive conversion are absent; membership order and values are exact;
members behave as strings and round-trip through JSON; unknown, mis-cased, and
empty values raise ``ValueError``; ``NOT_APPLICABLE`` belongs only to
``StaticApplicability``; and ``specstyle.domain`` exports no enum or ``__all__``.
"""

import enum
import json

import pytest

from specstyle.domain.enums import (
    ArtifactStatus,
    DecisionReason,
    RepairStopReason,
    RuleLevel,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)

ALL_ENUMS = [
    RuleStatus,
    StaticApplicability,
    ArtifactStatus,
    DecisionReason,
    RepairStopReason,
    RuleLevel,
    RuleScope,
]


def _members(cls):
    """Return ordered ``(name, value)`` pairs, including aliases."""
    return [(name, member.value) for name, member in cls.__members__.items()]


# --- Exact member order and values ---


def test_rulestatus_members():
    assert _members(RuleStatus) == [
        ("PASS", "PASS"),
        ("FAIL", "FAIL"),
        ("WARNING", "WARNING"),
        ("UNVERIFIABLE", "UNVERIFIABLE"),
    ]


def test_staticapplicability_members():
    assert _members(StaticApplicability) == [
        ("APPLICABLE", "APPLICABLE"),
        ("NOT_APPLICABLE", "NOT_APPLICABLE"),
    ]


def test_artifactstatus_members():
    assert _members(ArtifactStatus) == [
        ("APPROVED", "APPROVED"),
        ("REJECTED", "REJECTED"),
        ("MANUAL_REVIEW", "MANUAL_REVIEW"),
    ]


def test_decisionreason_members():
    assert _members(DecisionReason) == [
        ("ALL_REQUIRED_PASS", "ALL_REQUIRED_PASS"),
        ("REQUIRED_GATE_FAILED", "REQUIRED_GATE_FAILED"),
        ("REQUIRED_GATE_UNVERIFIABLE", "REQUIRED_GATE_UNVERIFIABLE"),
        ("REPAIR_EXHAUSTED", "REPAIR_EXHAUSTED"),
        ("MANUAL_POLICY", "MANUAL_POLICY"),
    ]


def test_repairstopreason_members():
    assert _members(RepairStopReason) == [
        ("PASS_ALL_REQUIRED", "PASS_ALL_REQUIRED"),
        ("NO_ACTION", "NO_ACTION"),
        ("NO_IMPROVEMENT", "NO_IMPROVEMENT"),
        ("MAX_ROUNDS", "MAX_ROUNDS"),
        ("UNVERIFIABLE", "UNVERIFIABLE"),
        ("MANUAL_REQUEST", "MANUAL_REQUEST"),
    ]


def test_rulelevel_members():
    assert _members(RuleLevel) == [
        ("L1", "L1"),
        ("L2", "L2"),
        ("L3", "L3"),
    ]


def test_rulescope_members():
    assert _members(RuleScope) == [
        ("ITEM", "ITEM"),
        ("BATCH", "BATCH"),
    ]


# --- Invariants ---


@pytest.mark.parametrize("cls", ALL_ENUMS, ids=lambda c: c.__name__)
def test_name_equals_value(cls):
    for m in cls:
        assert m.name == m.value


@pytest.mark.parametrize("cls", ALL_ENUMS, ids=lambda c: c.__name__)
def test_members_are_str(cls):
    for m in cls:
        assert isinstance(m, str)


@pytest.mark.parametrize("cls", ALL_ENUMS, ids=lambda c: c.__name__)
def test_json_roundtrip(cls):
    for m in cls:
        dumped = json.dumps(m)
        assert dumped == json.dumps(m.value)  # Member serialization matches its value.
        loaded = json.loads(dumped)
        assert loaded == m.value
        assert cls(loaded) is m  # EnumClass(value) restores the member.


@pytest.mark.parametrize("cls", ALL_ENUMS, ids=lambda c: c.__name__)
def test_invalid_values_raise_valueerror(cls):
    first = next(iter(cls))
    bad_values = (
        "DEFINITELY_NOT_A_MEMBER_XYZ",  # Unknown value.
        first.value.lower(),  # Incorrect case.
        "",  # Empty string.
    )
    for bad in bad_values:
        with pytest.raises(ValueError):
            cls(bad)


@pytest.mark.parametrize("cls", ALL_ENUMS, ids=lambda c: c.__name__)
def test_no_custom_missing(cls):
    # Check only _missing_; test_enum_has_no_aliases covers aliases separately.
    assert "_missing_" not in cls.__dict__


@pytest.mark.parametrize("cls", ALL_ENUMS, ids=lambda c: c.__name__)
def test_enum_has_no_aliases(cls):
    # __members__ includes aliases; iteration includes only canonical members.
    assert len(cls.__members__) == len(cls)


@pytest.mark.parametrize("cls", ALL_ENUMS, ids=lambda c: c.__name__)
def test_enum_uses_strenum(cls):
    assert issubclass(cls, enum.StrEnum)
    for member in cls:
        assert str(member) == member.value


# --- RuleStatus / StaticApplicability separation ---


def test_rulestatus_excludes_not_applicable():
    names = {m.name for m in RuleStatus}
    values = {m.value for m in RuleStatus}
    assert "NOT_APPLICABLE" not in names
    assert "NOT_APPLICABLE" not in values
    assert not hasattr(RuleStatus, "NOT_APPLICABLE")


def test_not_applicable_only_in_staticapplicability():
    assert StaticApplicability.NOT_APPLICABLE.value == "NOT_APPLICABLE"
    for cls in ALL_ENUMS:
        if cls is StaticApplicability:
            assert hasattr(cls, "NOT_APPLICABLE")
        else:
            assert not hasattr(cls, "NOT_APPLICABLE"), (
                f"{cls.__name__} must not define NOT_APPLICABLE"
            )


# --- specstyle.domain does not re-export enums ---


def test_domain_package_does_not_reexport_enums():
    import specstyle.domain as dom

    for name in (
        "RuleStatus",
        "StaticApplicability",
        "ArtifactStatus",
        "DecisionReason",
        "RepairStopReason",
        "RuleLevel",
        "RuleScope",
    ):
        assert not hasattr(dom, name), f"specstyle.domain must not re-export {name}"


def test_domain_package_has_no_all():
    import specstyle.domain as dom

    assert not hasattr(dom, "__all__")

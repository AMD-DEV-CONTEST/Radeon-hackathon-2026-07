"""Unit tests for Identifier, six concrete IDs, and Sha256.

Cover the frozen Module 1 Domain Foundation contract: IDs accept only the
contracted ASCII regular expression, invalid values raise ``DomainError``
without stripping or case changes, ``Sha256`` requires and normalizes 64
hexadecimal characters, values are frozen/slotted/hashable with exact primitive
round trips, and every concrete identifier type remains isolated.

Key cases are ASCII control characters, trailing newlines, and length bounds.
"""

import dataclasses

import pytest

from specstyle.errors import DomainError
from specstyle.domain.identifiers import (
    Identifier,
    JobId,
    AssetId,
    AttemptId,
    ArtifactId,
    DecisionId,
    RuleId,
    Sha256,
)

ID_TYPES = [JobId, AssetId, AttemptId, ArtifactId, DecisionId, RuleId]

VALID_IDS = [
    pytest.param("a", id="min_1"),
    pytest.param("A1", id="alnum"),
    pytest.param("abc-def_ghi", id="hyphen_underscore"),
    pytest.param("a" * 128, id="max_128"),
    pytest.param("Z9_", id="mixed"),
]

INVALID_IDS = [
    pytest.param("", id="empty"),
    pytest.param("a" * 129, id="too_long_129"),
    pytest.param("-abc", id="leading_hyphen"),
    pytest.param("_abc", id="leading_underscore"),
    pytest.param("ab c", id="space"),
    pytest.param("abc\n", id="trailing_newline"),
    pytest.param("ab\tc", id="tab"),
    pytest.param("ab\x00c", id="nul"),
    pytest.param("ab\x1bc", id="esc"),
    pytest.param("café", id="non_ascii"),
    pytest.param("a.b", id="dot"),
]


# --- Valid and invalid IDs ---


@pytest.mark.parametrize("cls", ID_TYPES, ids=lambda c: c.__name__)
@pytest.mark.parametrize("value", VALID_IDS)
def test_valid_id_accepted(cls, value):
    obj = cls(value)
    assert obj.value == value
    assert str(obj) == value
    assert obj.to_primitive() == value
    assert cls.from_primitive(value) == obj


@pytest.mark.parametrize("cls", ID_TYPES, ids=lambda c: c.__name__)
@pytest.mark.parametrize("value", INVALID_IDS)
def test_invalid_id_raises_domain_error(cls, value):
    with pytest.raises(DomainError):
        cls(value)


@pytest.mark.parametrize("cls", ID_TYPES, ids=lambda c: c.__name__)
def test_non_string_id_raises_domain_error(cls):
    for bad in (None, 123, [], object()):
        with pytest.raises(DomainError):
            cls(bad)


def test_no_strip_leading_trailing_space():
    # Values are not stripped, so leading or trailing spaces are invalid.
    with pytest.raises(DomainError):
        JobId(" abc")
    with pytest.raises(DomainError):
        JobId("abc ")


def test_no_case_change():
    obj = JobId("AbC")
    assert obj.value == "AbC"
    assert str(obj) == "AbC"


# --- frozen / slots / hashable ---


@pytest.mark.parametrize("cls", ID_TYPES, ids=lambda c: c.__name__)
def test_frozen(cls):
    obj = cls("abc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        obj.value = "other"


@pytest.mark.parametrize("cls", ID_TYPES, ids=lambda c: c.__name__)
def test_no_dict(cls):
    obj = cls("abc")
    assert not hasattr(obj, "__dict__")


@pytest.mark.parametrize("cls", ID_TYPES, ids=lambda c: c.__name__)
def test_hashable(cls):
    a = cls("abc")
    b = cls("abc")
    assert hash(a) == hash(b)
    assert {a, b} == {a}
    assert {a: 1}[b] == 1


# --- Concrete type separation ---


def test_sibling_ids_not_equal():
    value = "same"
    instances = [t(value) for t in ID_TYPES]
    for i, a in enumerate(instances):
        for j, b in enumerate(instances):
            if i == j:
                assert a == b
            else:
                assert a != b, f"{type(a).__name__} == {type(b).__name__}"


@pytest.mark.parametrize("cls", ID_TYPES, ids=lambda c: c.__name__)
def test_subclass_isolation_from_base(cls):
    obj = cls("abc")
    assert isinstance(obj, Identifier)
    assert obj != Identifier("abc")
    assert Identifier("abc") != obj


@pytest.mark.parametrize("cls", ID_TYPES, ids=lambda c: c.__name__)
def test_from_primitive_returns_same_type(cls):
    obj = cls.from_primitive("abc")
    assert type(obj) is cls
    assert isinstance(obj, Identifier)


@pytest.mark.parametrize("cls", ID_TYPES, ids=lambda c: c.__name__)
def test_from_primitive_non_string_raises(cls):
    for bad in (None, 123, []):
        with pytest.raises(DomainError):
            cls.from_primitive(bad)


# --- Identifier base class ---


def test_identifier_base_construction():
    obj = Identifier("abc")
    assert obj.value == "abc"
    assert str(obj) == "abc"
    assert obj.to_primitive() == "abc"
    assert Identifier.from_primitive("abc") == obj


def test_identifier_base_frozen_no_dict():
    obj = Identifier("abc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        obj.value = "x"
    assert not hasattr(obj, "__dict__")


# --- Sha256 ---

VALID_SHA_LOWER = "a" * 64
VALID_SHA_UPPER = "A" * 64
VALID_SHA_MIXED = "0123456789abcdef" * 4  # 64 hex

INVALID_SHA = [
    pytest.param("", id="empty"),
    pytest.param("a" * 63, id="too_short_63"),
    pytest.param("a" * 65, id="too_long_65"),
    pytest.param("g" * 64, id="non_hex_g"),
    pytest.param("a" * 63 + "g", id="short_nonhex"),
    pytest.param("z" * 64, id="non_hex_z"),
]


@pytest.mark.parametrize("value", [VALID_SHA_LOWER, VALID_SHA_UPPER, VALID_SHA_MIXED])
def test_sha256_valid_normalizes_lowercase(value):
    s = Sha256(value)
    assert s.value == value.lower()
    assert str(s) == value.lower()
    assert s.to_primitive() == value.lower()


@pytest.mark.parametrize("value", INVALID_SHA)
def test_sha256_invalid_raises(value):
    with pytest.raises(DomainError):
        Sha256(value)


def test_sha256_non_string_raises():
    for bad in (None, 123, []):
        with pytest.raises(DomainError):
            Sha256(bad)


def test_sha256_round_trip():
    s = Sha256(VALID_SHA_UPPER)
    assert Sha256.from_primitive(s.to_primitive()) == s
    assert type(Sha256.from_primitive(VALID_SHA_LOWER)) is Sha256


def test_sha256_frozen_no_dict_hashable():
    s = Sha256(VALID_SHA_LOWER)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.value = "b" * 64
    assert not hasattr(s, "__dict__")
    assert hash(s) == hash(Sha256(VALID_SHA_LOWER))


def test_sha256_no_strip():
    # A leading space makes the 65-character value non-hexadecimal and invalid.
    with pytest.raises(DomainError):
        Sha256(" " + "a" * 64)

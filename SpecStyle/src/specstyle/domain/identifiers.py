"""Value objects for specstyle domain identifiers and hashes.

They are frozen, slotted, hashable, have no ``__dict__``, preserve concrete
type separation, and support exact ``to_primitive``/``from_primitive`` round
trips.

- Identifier / JobId / AssetId / AttemptId / ArtifactId / DecisionId / RuleId:
  accept only ``re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value,
  re.ASCII)``. Invalid values raise ``DomainError`` without stripping or case
  conversion.
- Sha256: requires exactly 64 hexadecimal characters and normalizes them to
  lowercase. It validates and stores hashes but never calculates them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from specstyle.errors import DomainError

_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", re.ASCII)
_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")


def _validate_id(value: object) -> str:
    """Validate an ID as a matching string without stripping or changing case."""
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise DomainError(f"invalid identifier: {value!r}")
    return value


def _validate_sha256(value: object) -> str:
    """Validate 64 hexadecimal characters and lowercase them without hashing."""
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise DomainError(f"invalid sha256: {value!r}")
    return value.lower()


@dataclass(frozen=True, slots=True)
class Identifier:
    """Base class for controlled local asset IDs, not public source filenames."""

    value: str

    def __post_init__(self) -> None:
        _validate_id(self.value)

    def __str__(self) -> str:
        return self.value

    def to_primitive(self) -> str:
        return self.value

    @classmethod
    def from_primitive(cls, value: object) -> Identifier:
        if not isinstance(value, str):
            raise DomainError(f"identifier primitive must be str: {value!r}")
        return cls(value)


class JobId(Identifier):
    """Batch job ID."""

    __slots__ = ()


class AssetId(Identifier):
    """Input asset ID."""

    __slots__ = ()


class AttemptId(Identifier):
    """Generation attempt ID."""

    __slots__ = ()


class ArtifactId(Identifier):
    """Generated artifact ID."""

    __slots__ = ()


class DecisionId(Identifier):
    """Repair decision ID."""

    __slots__ = ()


class RuleId(Identifier):
    """Verification rule ID."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class Sha256:
    """A validated lowercase 64-hex content hash; this type never calculates it."""

    value: str

    def __post_init__(self) -> None:
        normalized = _validate_sha256(self.value)
        # Normalize the frozen instance through object.__setattr__.
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value

    def to_primitive(self) -> str:
        return self.value

    @classmethod
    def from_primitive(cls, value: object) -> Sha256:
        if not isinstance(value, str):
            raise DomainError(f"sha256 primitive must be str: {value!r}")
        return cls(value)

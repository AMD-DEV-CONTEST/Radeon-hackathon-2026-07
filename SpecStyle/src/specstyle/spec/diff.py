"""SPEC-004 typed semantic diff under contracts section 14.3.

Compares the JSON-normalized primitive trees of two StyleSpecs, reports only
leaf differences in lexicographic path order, and performs no mutation or I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from specstyle.errors import DomainError
from specstyle.spec.models import StyleSpec, StyleSpecV1, StyleSpecV11


@dataclass(frozen=True, slots=True)
class FieldChange:
    path: str
    kind: Literal["added", "removed", "changed"]
    before: object | None
    after: object | None


@dataclass(frozen=True, slots=True)
class SpecDiff:
    source_version: str
    target_version: str
    changes: tuple[FieldChange, ...]


def _version_of(spec: StyleSpec) -> str:
    if type(spec) is StyleSpecV1:
        return "1.0"
    if type(spec) is StyleSpecV11:
        return "1.1"
    raise DomainError("unsupported style spec version") from None


def _dump(spec: StyleSpec) -> dict[str, object]:
    if not isinstance(spec, BaseModel):
        raise DomainError("unsupported style spec version") from None
    data = spec.model_dump(mode="json")
    if type(data) is not dict:
        raise DomainError("unsupported style spec version") from None
    return data


def _walk(
    left: object,
    right: object,
    path: str,
    out: list[FieldChange],
) -> None:
    if type(left) is dict and type(right) is dict:
        keys = sorted(set(left) | set(right))
        for key in keys:
            child = f"{path}.{key}" if path else key
            if key not in left:
                out.append(FieldChange(child, "added", None, right[key]))
            elif key not in right:
                out.append(FieldChange(child, "removed", left[key], None))
            else:
                _walk(left[key], right[key], child, out)
        return
    if type(left) is list and type(right) is list:
        n = max(len(left), len(right))
        for i in range(n):
            child = f"{path}[{i}]"
            if i >= len(left):
                out.append(FieldChange(child, "added", None, right[i]))
            elif i >= len(right):
                out.append(FieldChange(child, "removed", left[i], None))
            else:
                _walk(left[i], right[i], child, out)
        return
    if left != right:
        out.append(FieldChange(path or "$", "changed", left, right))


def semantic_diff(left: StyleSpec, right: StyleSpec, /) -> SpecDiff:
    if type(left) not in (StyleSpecV1, StyleSpecV11) or type(right) not in (
        StyleSpecV1,
        StyleSpecV11,
    ):
        raise DomainError("unsupported style spec version") from None
    changes: list[FieldChange] = []
    _walk(_dump(left), _dump(right), "", changes)
    changes.sort(key=lambda c: c.path)
    return SpecDiff(_version_of(left), _version_of(right), tuple(changes))

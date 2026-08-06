from __future__ import annotations

from collections.abc import Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


class PythonRequirementError(ValueError):
    pass


def normalize_python_requirements(values: Iterable[str]) -> list[str]:
    """Return deterministic requirements with one declaration per distribution and marker context."""

    declarations: dict[tuple[str, str], str] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if text.startswith("-"):
            raise PythonRequirementError(
                f"Python dependency declarations must be package requirements, not package-manager options: {text}"
            )
        try:
            requirement = Requirement(text)
        except InvalidRequirement as exc:
            raise PythonRequirementError(f"invalid Python dependency requirement {text!r}: {exc}") from exc
        name = canonicalize_name(requirement.name)
        marker = str(requirement.marker or "")
        declarations[(name, marker)] = _render_requirement(requirement)
    return [declarations[key] for key in sorted(declarations)]


def merge_python_requirements(existing: Iterable[str], incoming: Iterable[str]) -> list[str]:
    """Merge declarations by distribution identity, with the incoming declaration authoritative."""

    return normalize_python_requirements([*existing, *incoming])


def _render_requirement(requirement: Requirement) -> str:
    value = canonicalize_name(requirement.name)
    if requirement.extras:
        value += "[" + ",".join(sorted(canonicalize_name(extra) for extra in requirement.extras)) + "]"
    if requirement.url:
        value += f" @ {requirement.url}"
    else:
        value += str(requirement.specifier)
    if requirement.marker:
        value += f"; {requirement.marker}"
    return value

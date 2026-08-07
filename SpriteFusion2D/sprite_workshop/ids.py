"""Frame identity, naming templates, and tag selectors.

This is the contract that closed the biggest hole in plan v1.0: tags and frame
IDs had three consumers and no producer.  Everything that names or selects a
frame goes through this module (BACKEND_CLI_PLAN.md 5.3).
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .errors import UsageError
from .model import Frame, FrameSet

ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
TAG_KEY_PATTERN = ID_PATTERN
TAG_VALUE_PATTERN = ID_PATTERN

DEFAULT_NAME_TEMPLATE = "{set}_{index:02d}"


def validate_id(value: str, *, what: str = "frame id") -> str:
    """Reject anything that would be unsafe in a filename or engine metadata."""

    if not isinstance(value, str) or not value:
        raise UsageError(f"{what} must be a non-empty string", value=value)
    if not ID_PATTERN.match(value):
        raise UsageError(
            f"{what} may only contain lowercase letters, digits and underscore",
            value=value,
        )
    return value


def normalize_tags(tags: Mapping[str, str] | None) -> dict[str, str]:
    """Validate a ``key: value`` tag mapping."""

    if not tags:
        return {}
    out: dict[str, str] = {}
    for key, value in tags.items():
        if not TAG_KEY_PATTERN.match(str(key)):
            raise UsageError("invalid tag key", key=key)
        if not TAG_VALUE_PATTERN.match(str(value)):
            raise UsageError("invalid tag value", key=key, value=value)
        out[str(key)] = str(value)
    return out


class _TagAccess:
    """Makes ``{tag:action}`` work through the stdlib format protocol."""

    __slots__ = ("_tags",)

    def __init__(self, tags: Mapping[str, str]) -> None:
        self._tags = tags

    def __format__(self, spec: str) -> str:
        if not spec:
            raise UsageError("{tag} requires a key, for example {tag:action}")
        if spec not in self._tags:
            raise UsageError(
                "template references a tag the frame does not have", key=spec
            )
        return self._tags[spec]

    def __str__(self) -> str:  # pragma: no cover - guarded by __format__
        raise UsageError("{tag} requires a key, for example {tag:action}")


def render_name(
    template: str,
    *,
    frame_set: str,
    index: int,
    row: int | None = None,
    col: int | None = None,
    name: str | None = None,
    tags: Mapping[str, str] | None = None,
) -> str:
    """Render one frame ID from a naming template (BACKEND_CLI_PLAN.md 5.3)."""

    fields: dict[str, Any] = {
        "set": frame_set,
        "index": index,
        "tag": _TagAccess(tags or {}),
    }
    for key, value in (("row", row), ("col", col), ("name", name)):
        if value is not None:
            fields[key] = value

    try:
        rendered = template.format(**fields)
    except UsageError:
        raise
    except KeyError as exc:
        raise UsageError(
            "name template uses a placeholder that is not available in this mode",
            placeholder=str(exc).strip("'"),
            template=template,
        ) from exc
    except (IndexError, ValueError) as exc:
        raise UsageError(
            "invalid name template", template=template, reason=str(exc)
        ) from exc

    return validate_id(rendered.lower())


def render_names(
    template: str,
    *,
    frame_set: str,
    count: int,
    rows: Sequence[int] | None = None,
    cols: Sequence[int] | None = None,
    names: Sequence[str] | None = None,
    tags: Sequence[Mapping[str, str]] | None = None,
) -> tuple[list[str], list[str]]:
    """Render every frame ID, de-duplicating collisions.

    Returns ``(ids, warnings)``.  Collisions get a ``_2``/``_3`` suffix and a
    warning rather than silently overwriting.
    """

    ids: list[str] = []
    warnings: list[str] = []
    seen: dict[str, int] = {}

    for index in range(count):
        candidate = render_name(
            template,
            frame_set=frame_set,
            index=index,
            row=rows[index] if rows is not None else None,
            col=cols[index] if cols is not None else None,
            name=names[index] if names is not None else None,
            tags=tags[index] if tags is not None else None,
        )
        if candidate in seen:
            seen[candidate] += 1
            deduped = f"{candidate}_{seen[candidate]}"
            warnings.append(f"frame id collision: {candidate} renamed to {deduped}")
            candidate = deduped
        else:
            seen[candidate] = 1
        ids.append(candidate)

    return ids, warnings


def select_frames(frame_set: FrameSet, selector: str | None) -> tuple[int, ...]:
    """Resolve a frame selector to frame indices.

    Supported forms:
      ``all``                      every frame
      ``id:walk_00`` / ``id:a,b``  explicit ids
      ``index:0`` / ``index:0-3``  positions and ranges
      ``tag:action=walk``          key/value tag match
      ``tag:walk``                 shorthand; ambiguous across keys is an error
    """

    if selector is None or selector == "all":
        return tuple(range(len(frame_set)))

    kind, _, rest = selector.partition(":")
    if not rest:
        kind, rest = "id", selector

    if kind == "id":
        wanted = [part.strip() for part in rest.split(",") if part.strip()]
        indices = [frame_set.index_of(frame_id) for frame_id in wanted]
        return tuple(sorted(set(indices)))

    if kind == "index":
        return _select_by_index(frame_set, rest)

    if kind == "tag":
        return _select_by_tag(frame_set, rest)

    if kind == "clip":
        raise UsageError(
            "clip selectors need project context; use the project-level API",
            selector=selector,
        )

    raise UsageError("unknown frame selector", selector=selector)


def _select_by_index(frame_set: FrameSet, rest: str) -> tuple[int, ...]:
    total = len(frame_set)
    picked: set[int] = set()
    for part in rest.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, _, end_text = part.partition("-")
            try:
                start, end = int(start_text), int(end_text)
            except ValueError as exc:
                raise UsageError("invalid index range", value=part) from exc
            if start > end:
                raise UsageError("index range start is after its end", value=part)
            candidates = range(start, end + 1)
        else:
            try:
                candidates = [int(part)]
            except ValueError as exc:
                raise UsageError("invalid index", value=part) from exc
        for value in candidates:
            if not 0 <= value < total:
                raise UsageError("index out of range", index=value, frames=total)
            picked.add(value)
    return tuple(sorted(picked))


def _select_by_tag(frame_set: FrameSet, rest: str) -> tuple[int, ...]:
    if "=" in rest:
        key, _, value = rest.partition("=")
        key, value = key.strip(), value.strip()
        matched = [
            index
            for index, frame in enumerate(frame_set)
            if frame.tags.get(key) == value
        ]
        return tuple(matched)

    # Shorthand: any key whose value equals the term.  Ambiguity is an error
    # rather than a guess (BACKEND_CLI_PLAN.md 5.3).
    term = rest.strip()
    keys = {
        key for frame in frame_set for key, value in frame.tags.items() if value == term
    }
    if len(keys) > 1:
        raise UsageError(
            "tag shorthand matches several keys; qualify it as tag:key=value",
            value=term,
            keys=sorted(keys),
        )
    matched = [
        index for index, frame in enumerate(frame_set) if term in frame.tags.values()
    ]
    return tuple(matched)


def tags_from_id(frame: Frame, pattern: str) -> dict[str, str]:
    """Derive tags by matching a frame id against ``walk_{direction}_{index}``."""

    regex_parts: list[str] = []
    names: list[str] = []
    for literal, field_name in _iter_template_parts(pattern):
        if literal:
            regex_parts.append(re.escape(literal))
        if field_name is not None:
            if field_name == "index":
                regex_parts.append(r"\d+")
            else:
                names.append(field_name)
                regex_parts.append(f"(?P<{field_name}>[a-z0-9]+)")

    match = re.match(f"^{''.join(regex_parts)}$", frame.id)
    if match is None:
        raise UsageError(
            "frame id does not match the pattern", frame=frame.id, pattern=pattern
        )
    return normalize_tags({name: match.group(name) for name in names})


def _iter_template_parts(pattern: str):
    from string import Formatter

    for literal, field_name, _spec, _conv in Formatter().parse(pattern):
        yield literal, field_name

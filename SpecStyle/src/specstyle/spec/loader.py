"""Secure YAML parsing and path/input safety for Style Specs.

``load_style_spec_text`` checks UTF-8 and size, composes safely while rejecting
aliases, merges, duplicates, excessive depth or nodes, and non-mapping roots,
loads with ``SafeLoader`` while rejecting custom or unsafe tags, converts lists
to tuples, and validates ``StyleSpecV1``. ``load_style_spec_file`` requires a
relative path without ``..``, rejects symlinks component by component, keeps
the resolved path under the root, accepts only regular files, checks size and
short reads before and after reading, and then calls the text loader.

Limits are ``MAX_SPEC_BYTES=1_048_576``, ``MAX_YAML_DEPTH=32``, and
``MAX_YAML_NODES=10_000``; P0 rejects every alias and merge. Missing paths,
policy violations, and invalid input raise ``DomainError``. Permission, device,
short-read, and other non-input OS failures raise ``InfrastructureError`` with
the exception chain preserved. Error messages exclude full private absolute
paths, original YAML text, and field values.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import yaml
from yaml.composer import ComposerError
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from pydantic import ValidationError

from specstyle.errors import DomainError, InfrastructureError
from specstyle.spec.models import StyleSpec, StyleSpecV1, StyleSpecV11

MAX_SPEC_BYTES = 1_048_576
MAX_YAML_DEPTH = 32
MAX_YAML_NODES = 10_000

_MERGE_KEY = "<<"


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects aliases, merge keys, and duplicate keys."""

    def compose_node(self, parent: Any, index: Any) -> yaml.Node:  # type: ignore[override]
        if self.check_event(AliasEvent):
            raise ComposerError(None, None, "YAML alias is forbidden", None)
        return super().compose_node(parent, index)

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> Any:  # type: ignore[override]
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if isinstance(key_node, yaml.ScalarNode):
                if key_node.value == _MERGE_KEY:
                    raise ConstructorError(
                        None, None, "YAML merge key is forbidden", key_node.start_mark
                    )
                if key_node.value in seen:
                    raise ConstructorError(
                        None, None, "duplicate YAML key", key_node.start_mark
                    )
                seen.add(key_node.value)
        return super().construct_mapping(node, deep=deep)


def _walk_depth_nodes(node: yaml.Node, depth: int, count: list[int]) -> None:
    count[0] += 1
    if count[0] > MAX_YAML_NODES:
        raise DomainError("YAML node count exceeds limit")
    if depth > MAX_YAML_DEPTH:
        raise DomainError("YAML nesting depth exceeds limit")
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            _walk_depth_nodes(key_node, depth + 1, count)
            _walk_depth_nodes(value_node, depth + 1, count)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _walk_depth_nodes(item, depth + 1, count)


def _list_to_tuple(obj: Any) -> Any:
    """Convert YAML sequence lists to tuples while keeping models strict."""
    if isinstance(obj, list):
        return tuple(_list_to_tuple(x) for x in obj)
    if isinstance(obj, dict):
        return {k: _list_to_tuple(v) for k, v in obj.items()}
    return obj


def _validate_style_spec(data: dict[str, Any]) -> StyleSpec:
    version = data.get("schema_version")
    try:
        if version == "1.0":
            return StyleSpecV1(**data)
        if version == "1.1":
            return StyleSpecV11(**data)
    except ValidationError:
        raise DomainError("spec failed schema validation") from None
    raise DomainError("spec failed schema validation") from None


def load_style_spec_text(
    text: str | bytes, *, max_bytes: int = MAX_SPEC_BYTES
) -> StyleSpec:
    if isinstance(text, str):
        raw = text.encode("utf-8")
    elif isinstance(text, (bytes, bytearray)):
        raw = bytes(text)
    else:
        raise DomainError("spec text must be str or bytes")

    if len(raw) > max_bytes:
        raise DomainError("spec text exceeds size limit")

    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise DomainError("spec text is not valid UTF-8") from None

    try:
        root = yaml.compose(decoded, Loader=_StrictLoader)
    except (yaml.YAMLError, RecursionError):
        raise DomainError("invalid YAML structure or depth") from None
    if root is None:
        raise DomainError("empty YAML spec")
    if not isinstance(root, yaml.MappingNode):
        raise DomainError("YAML root must be a mapping")
    _walk_depth_nodes(root, 0, [0])

    try:
        data = yaml.load(decoded, Loader=_StrictLoader)
    except (yaml.YAMLError, RecursionError):
        raise DomainError("invalid YAML content or depth") from None
    if not isinstance(data, dict):
        raise DomainError("YAML root must be a mapping")

    data = _list_to_tuple(data)
    return _validate_style_spec(data)


def load_style_spec_file(
    allowed_root: Path,
    relative_path: str | Path,
    *,
    max_bytes: int = MAX_SPEC_BYTES,
) -> StyleSpec:
    root = Path(allowed_root)
    try:
        root_resolved = root.resolve(strict=True)
    except FileNotFoundError:
        raise DomainError("allowed_root does not exist") from None
    except OSError as exc:
        raise InfrastructureError("cannot resolve allowed_root") from exc
    if not root_resolved.is_dir():
        raise DomainError("allowed_root must be a directory")

    rp = Path(relative_path)
    if rp.is_absolute():
        raise DomainError("relative_path must be relative")
    if ".." in rp.parts:
        raise DomainError("relative_path must not contain parent traversal")

    # Reject symlinks component by component; TOCTOU is an accepted residual risk.
    cur = root_resolved
    for part in rp.parts:
        cur = cur / part
        try:
            if cur.is_symlink():
                raise DomainError("symlink in spec path is forbidden")
        except OSError as exc:
            raise InfrastructureError("cannot inspect path component") from exc

    target = root_resolved / rp
    try:
        target_resolved = target.resolve(strict=True)
    except FileNotFoundError:
        raise DomainError("spec file not found") from None
    except OSError as exc:
        raise InfrastructureError("cannot resolve spec path") from exc

    try:
        target_resolved.relative_to(root_resolved)
    except ValueError:
        raise DomainError("spec path escapes allowed_root") from None

    try:
        st = target_resolved.stat()
    except FileNotFoundError:
        raise DomainError("spec file not found") from None
    except OSError as exc:
        raise InfrastructureError("cannot stat spec file") from exc
    if not stat.S_ISREG(st.st_mode):
        raise DomainError("spec path must be a regular file")
    if st.st_size > max_bytes:
        raise DomainError("spec file exceeds size limit")

    try:
        raw = target_resolved.read_bytes()
    except FileNotFoundError:
        raise DomainError("spec file not found") from None
    except (PermissionError, IsADirectoryError) as exc:
        raise InfrastructureError("cannot read spec file") from exc
    except OSError as exc:
        raise InfrastructureError("read error") from exc

    # Check for short reads and recheck size after reading.
    if len(raw) != st.st_size:
        raise InfrastructureError("short read detected")
    if len(raw) > max_bytes:
        raise DomainError("spec file exceeds size limit")

    return load_style_spec_text(raw, max_bytes=max_bytes)

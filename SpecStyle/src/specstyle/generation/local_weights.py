"""Local weight resolution — no network, no auto-download, fail closed."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.model_registry import ModelDescriptor
from specstyle.observability.hashing import hash_file


@dataclass(frozen=True, slots=True)
class ResolvedWeight:
    model_id: str
    path: Path
    content_sha256: Sha256
    kind: str  # legacy_single_file only; not a production authorization


def _validate_relpath(relpath: str) -> str:
    if type(relpath) is not str or not relpath or relpath.startswith("/"):
        raise DomainError("invalid weights relpath")
    parts = relpath.replace("\\", "/").split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise DomainError("weights path escape")
    return "/".join(parts)


def resolve_weight(
    cache_root: Path,
    descriptor: ModelDescriptor,
    relpath: str,
) -> ResolvedWeight:
    """Resolve a model under ``cache_root/relpath``.

    Legacy/test-only helper for a single regular file whose SHA matches
    ``expected_sha256``. Directory markers are explicitly refused and this
    result is not a production-loading capability.
    """
    if not isinstance(cache_root, Path) or type(descriptor) is not ModelDescriptor:
        raise DomainError("invalid weight resolve inputs")
    safe = _validate_relpath(relpath)
    root = cache_root
    if not root.is_dir():
        raise InfrastructureError("model cache root missing")
    target = root.joinpath(*safe.split("/"))
    try:
        st = os.lstat(target)
    except OSError as exc:
        raise InfrastructureError("model weights missing") from exc
    if stat_is_symlink(st):
        raise InfrastructureError("model weights symlink refused")
    if stat_is_file(st):
        digest = hash_file(root, safe)
        if digest != descriptor.expected_sha256:
            raise InfrastructureError("model weight hash mismatch")
        return ResolvedWeight(descriptor.model_id, target, digest, "legacy_single_file")
    if stat_is_dir(st):
        raise InfrastructureError("legacy directory marker production loading disabled")
    raise InfrastructureError("model weights unsupported type")


def resolve_graph_weights(
    cache_root: Path,
    descriptors: tuple[ModelDescriptor, ...],
    relpaths: dict[str, str],
) -> tuple[ResolvedWeight, ...]:
    if type(descriptors) is not tuple or type(relpaths) is not dict:
        raise DomainError("invalid graph weight inputs")
    out: list[ResolvedWeight] = []
    for desc in descriptors:
        if type(desc) is not ModelDescriptor:
            raise DomainError("invalid descriptor")
        if desc.model_id not in relpaths:
            raise DomainError("missing weights relpath")
        out.append(resolve_weight(cache_root, desc, relpaths[desc.model_id]))
    return tuple(out)


def stat_is_symlink(st: os.stat_result) -> bool:
    import stat as statmod

    return statmod.S_ISLNK(st.st_mode)


def stat_is_file(st: os.stat_result) -> bool:
    import stat as statmod

    return statmod.S_ISREG(st.st_mode)


def stat_is_dir(st: os.stat_result) -> bool:
    import stat as statmod

    return statmod.S_ISDIR(st.st_mode)

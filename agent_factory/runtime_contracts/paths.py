from __future__ import annotations

from pathlib import Path

from agent_factory.runtime_contracts.builder import RuntimeBuildContext


def resolve_package_runtime_path(context: RuntimeBuildContext, value: str, *, field_path: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field_path} must not be empty")
    runtime_relative = _runtime_relative_path(raw)
    if context.runtime_root is not None:
        runtime_root = context.runtime_root.resolve()
        if runtime_relative is not None:
            return _path_inside(runtime_root, runtime_relative, field_path=field_path, raw=raw)
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise ValueError(
                f"{field_path} must use .agent_runtime/... or /runtime/...; got {raw!r}"
            )
        resolved = candidate.resolve()
        try:
            resolved.relative_to(runtime_root)
        except ValueError as exc:
            raise ValueError(
                f"{field_path} must resolve inside the package runtime workspace; got {raw!r}"
            ) from exc
        return resolved
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = context.package_root / candidate
    resolved = candidate.resolve()
    package_root = context.package_root.resolve()
    try:
        resolved.relative_to(package_root)
    except ValueError as exc:
        raise ValueError(
            f"{field_path} must resolve inside the package workspace; got {raw!r}. "
            "Use a package-relative .agent_runtime/... path."
        ) from exc
    return resolved


def package_runtime_path_text(context: RuntimeBuildContext, value: str, *, field_path: str) -> str:
    return str(resolve_package_runtime_path(context, value, field_path=field_path))


def _runtime_relative_path(value: str) -> Path | None:
    for marker in (".agent_runtime", "/runtime"):
        if value == marker:
            return Path()
        prefix = marker + "/"
        if value.startswith(prefix):
            return Path(value.removeprefix(prefix))
    return None


def _path_inside(root: Path, relative: Path, *, field_path: str, raw: str) -> Path:
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"{field_path} must resolve inside the package runtime workspace; got {raw!r}"
        ) from exc
    return target

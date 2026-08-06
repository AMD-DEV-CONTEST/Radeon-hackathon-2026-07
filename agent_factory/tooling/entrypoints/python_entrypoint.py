from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Callable
import uuid

from agent_factory.tooling.entrypoints.base import EntrypointAdapterError, ToolEntrypointCallable, parse_protocol


class PythonEntrypointAdapter:
    protocol = "python"

    def __init__(self, *, package_root: str | Path | None = None, allowed_roots: list[str | Path] | None = None) -> None:
        self.package_root = Path(package_root).resolve() if package_root else None
        roots = list(allowed_roots or [])
        if self.package_root is not None:
            roots.append(self.package_root)
        self.allowed_roots = [Path(root).resolve() for root in roots]

    def can_load(self, entrypoint: str) -> bool:
        parsed = parse_protocol(entrypoint)
        return parsed.protocol in {"python", "python-import"}

    def load(self, entrypoint: str) -> ToolEntrypointCallable:
        parsed = parse_protocol(entrypoint)
        if parsed.protocol == "python":
            return self._load_package_relative_target(parsed.target)
        if parsed.protocol == "python-import":
            return self._load_import_target(parsed.target)
        raise EntrypointAdapterError(f"cannot load entrypoint: {entrypoint}")

    def _load_package_relative_target(self, target: str) -> Callable[..., Any]:
        path_text, function_name = _split_target(target)
        if self.package_root is None:
            path = Path(path_text).expanduser().resolve()
            _assert_allowed_path(path, self.allowed_roots)
        else:
            path_candidate = Path(path_text).expanduser()
            path = path_candidate.resolve() if path_candidate.is_absolute() else (self.package_root / path_candidate).resolve()
            _assert_allowed_path(path, self.allowed_roots)
        if not path.exists() or not path.is_file():
            raise EntrypointAdapterError(f"package entrypoint file does not exist: {path_text}")
        if path.suffix != ".py":
            raise EntrypointAdapterError(f"package entrypoint must be a Python file: {path_text}")
        module = _module_from_path(path)
        return _function_from_module(module, function_name)

    def _load_import_target(self, target: str) -> Callable[..., Any]:
        module_name, function_name = _split_target(target)
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise EntrypointAdapterError(f"cannot import module {module_name}: {exc}") from exc
        return _function_from_module(module, function_name)


def _split_target(target: str) -> tuple[str, str]:
    if ":" not in target:
        raise EntrypointAdapterError("entrypoint must use '<path_or_module>:<function>'")
    path_or_module, function_name = target.rsplit(":", 1)
    path_or_module = path_or_module.strip()
    function_name = function_name.strip()
    if not path_or_module or not function_name:
        raise EntrypointAdapterError("entrypoint target and function must be non-empty")
    return path_or_module, function_name


def _module_from_path(path: Path) -> ModuleType:
    module_name = f"agent_factory_dynamic_tool_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise EntrypointAdapterError(f"cannot create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise EntrypointAdapterError(f"cannot load package entrypoint {path}: {exc}") from exc
    return module


def _function_from_module(module: ModuleType, function_name: str) -> Callable[..., Any]:
    function = getattr(module, function_name, None)
    if not callable(function):
        raise EntrypointAdapterError(f"entrypoint function is not callable: {function_name}")
    return function


def _assert_allowed_path(path: Path, allowed_roots: list[Path]) -> None:
    if not allowed_roots:
        raise EntrypointAdapterError("package root or allowed roots are not configured")
    for root in allowed_roots:
        try:
            path.relative_to(root)
            return
        except ValueError:
            continue
    raise EntrypointAdapterError(f"entrypoint escapes configured roots: {path}")

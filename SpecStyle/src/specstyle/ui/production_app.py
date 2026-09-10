"""Authenticated production Gradio composition rooted in the AMD runtime."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import stat
from typing import Any

from specstyle.errors import DomainError, InfrastructureError
from specstyle.production.context_config import (
    load_production_context_config,
    require_validated_production_threshold,
)
from specstyle.ui.app import UiServices, build_default_services, launch_app
from specstyle.ui.preview_run import (
    bind_preview_run_one_services,
    bind_unavailable_preview_services,
    reconcile_preview_ui_display,
)
from specstyle.ui.preview_wall import (
    bind_preview_wall_services,
    bind_unavailable_preview_wall_services,
)
from specstyle.ui.preview_ui_inputs import PreviewUiRuntimePaths
from specstyle.ui.production_run import (
    ProductionUiRuntimePaths,
    bind_production_run_one_services,
    bind_unavailable_production_services,
)
from specstyle.workflow.production_bootstrap import (
    load_production_ui_compiler_context,
)

__all__ = (
    "bind_optional_preview_services",
    "build_production_ui_services",
    "launch_production_ui",
    "main",
    "preview_runtime_paths",
    "production_runtime_paths",
)

_DEFAULT_ROOT = Path("/workspace/persistence/lookfile-runtime")
_PUBLIC_HOST = "0.0.0.0"
_THRESHOLD_UNAVAILABLE = "PRODUCTION_THRESHOLD_NOT_VALIDATED"
_LOCAL_HOST = "127.0.0.1"


def _trusted_directory(path: Path, label: str) -> None:
    try:
        info = os.lstat(path)
    except OSError:
        raise DomainError(f"production {label} directory unavailable") from None
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid not in (0, os.geteuid())
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise DomainError(f"production {label} directory untrusted")


def _private_directory(path: Path) -> Path:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError:
        raise InfrastructureError("production UI directory unavailable") from None
    try:
        info = os.lstat(path)
    except OSError:
        raise InfrastructureError("production UI directory unavailable") from None
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise DomainError("production UI directory untrusted")
    return path


def _mutable_parent(path: Path) -> Path:
    if not path.exists():
        return _private_directory(path)
    _trusted_directory(path, "mutable root")
    return path


def production_runtime_paths(runtime_root: Path, /) -> ProductionUiRuntimePaths:
    root = Path(runtime_root)
    _trusted_directory(root, "runtime root")
    config, evidence, models = (
        root / name for name in ("config", "evidence", "models")
    )
    for path, label in (
        (config, "config"),
        (evidence, "evidence"),
        (models, "models"),
    ):
        _trusted_directory(path, label)
    jobs = _mutable_parent(root / "jobs")
    product = _private_directory(jobs / "ui-production")
    state, artifacts, styles, export = (
        _private_directory(product / name)
        for name in ("state", "artifacts", "styles", "export")
    )
    temporary = _mutable_parent(root / "tmp")
    staging = _private_directory(temporary / "ui-production")
    return ProductionUiRuntimePaths(
        config, evidence, models, state, artifacts, styles, export, staging
    )


def preview_runtime_paths(runtime_root: Path, /) -> PreviewUiRuntimePaths:
    root = Path(runtime_root)
    _trusted_directory(root, "runtime root")
    config = root / "config"
    context_evidence = root / "evidence"
    preview_config = root / "preview-config"
    models = root / "models"
    for path, label in (
        (config, "config"),
        (context_evidence, "evidence"),
        (preview_config, "preview config"),
        (models, "models"),
    ):
        _trusted_directory(path, label)
    jobs = _mutable_parent(root / "jobs")
    product = _private_directory(jobs / "ui-preview")
    evidence, display, styles = (
        _private_directory(product / name) for name in ("evidence", "display", "styles")
    )
    temporary = _mutable_parent(root / "tmp")
    staging = _private_directory(temporary / "ui-preview")
    return PreviewUiRuntimePaths(
        config,
        context_evidence,
        preview_config,
        models,
        evidence,
        display,
        styles,
        staging,
    )


def _optional_preview_runtime_paths(runtime_root: Path) -> PreviewUiRuntimePaths | None:
    try:
        return preview_runtime_paths(runtime_root)
    except (DomainError, InfrastructureError):
        return None


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        return os.open(path, flags)
    except OSError:
        raise InfrastructureError("production bootstrap unavailable") from None


def _close_descriptors(descriptors: list[int], primary: BaseException | None) -> None:
    failure: OSError | None = None
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError as error:
            failure = failure or error
    if failure is not None and primary is not None:
        primary.add_note("production bootstrap descriptor cleanup failed")
    elif failure is not None:
        raise InfrastructureError("production bootstrap cleanup failed") from None


def build_production_ui_services(paths: ProductionUiRuntimePaths, /) -> UiServices:
    if type(paths) is not ProductionUiRuntimePaths:
        raise DomainError("invalid production UI paths")
    descriptors: list[int] = []
    primary: BaseException | None = None
    try:
        for path in (paths.config_root, paths.evidence_root, paths.model_root):
            descriptors.append(_open_directory(path))
        context_config = load_production_context_config(*descriptors[:2])
        context = load_production_ui_compiler_context(*descriptors)
        base = build_default_services(context)
        try:
            require_validated_production_threshold(context_config)
        except DomainError as exc:
            if str(exc) != _THRESHOLD_UNAVAILABLE:
                raise
            return bind_unavailable_production_services(base, _THRESHOLD_UNAVAILABLE)
        return bind_production_run_one_services(base, paths)
    except BaseException as error:
        primary = error
        raise
    finally:
        _close_descriptors(descriptors, primary)


def bind_optional_preview_services(
    services: UiServices,
    preview_paths: PreviewUiRuntimePaths | None,
    /,
) -> tuple[UiServices, PreviewUiRuntimePaths | None]:
    if preview_paths is None:
        return services, None
    try:
        reconcile_preview_ui_display(preview_paths)
        preview = bind_preview_run_one_services(services, preview_paths)
        return bind_preview_wall_services(preview, preview_paths), preview_paths
    except Exception:
        return (
            bind_unavailable_preview_wall_services(
                bind_unavailable_preview_services(services, "PREVIEW_UNAVAILABLE"),
                "PREVIEW_UNAVAILABLE",
            ),
            None,
        )


def _credential(value: object, label: str, minimum: int) -> str:
    if (
        type(value) is not str
        or not minimum <= len(value) <= 256
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise DomainError(f"production UI {label} invalid")
    return value


def _authentication(host: str, environ: Mapping[str, str]) -> tuple[str, str] | None:
    username = environ.get("SPECSTYLE_UI_USERNAME")
    password = environ.get("SPECSTYLE_UI_PASSWORD")
    if username is None and password is None and host == _LOCAL_HOST:
        return None
    if username is None or password is None:
        raise DomainError("production UI authentication required")
    return _credential(username, "username", 3), _credential(password, "password", 16)


def _gradio_paths(
    paths: ProductionUiRuntimePaths,
    preview_paths: PreviewUiRuntimePaths | None,
    exposed_preview_paths: PreviewUiRuntimePaths | None,
) -> tuple[list[str], list[str]]:
    allowed = [str(paths.export_root)]
    blocked = [
        str(path)
        for path in (
            paths.config_root,
            paths.evidence_root,
            paths.model_root,
            paths.state_root,
            paths.artifact_root,
            paths.style_asset_root,
            paths.staging_root,
        )
    ]
    if exposed_preview_paths is not None:
        allowed.append(str(exposed_preview_paths.display_root))
    if preview_paths is not None:
        blocked.extend(
            str(path)
            for path in (
                preview_paths.preview_config_root,
                preview_paths.evidence_root,
                preview_paths.style_asset_root,
                preview_paths.staging_root,
            )
        )
        if exposed_preview_paths is None:
            blocked.append(str(preview_paths.display_root))
    return allowed, blocked


def launch_production_ui(
    runtime_root: Path,
    /,
    *,
    host: str = _LOCAL_HOST,
    port: int = 7860,
    environ: Mapping[str, str] | None = None,
) -> Any:
    if host not in {_LOCAL_HOST, _PUBLIC_HOST}:
        raise DomainError("invalid production UI host")
    if type(port) is not int or isinstance(port, bool) or not 1 <= port <= 65535:
        raise DomainError("invalid production UI port")
    auth = _authentication(host, os.environ if environ is None else environ)
    paths = production_runtime_paths(runtime_root)
    preview_paths = _optional_preview_runtime_paths(runtime_root)
    services, exposed_preview_paths = bind_optional_preview_services(
        build_production_ui_services(paths), preview_paths
    )
    allowed, blocked = _gradio_paths(paths, preview_paths, exposed_preview_paths)
    return launch_app(
        services,
        server_name=host,
        server_port=port,
        share=False,
        auth=auth,
        allowed_paths=allowed,
        blocked_paths=blocked,
        max_file_size="32mb",
        show_error=False,
        inbrowser=False,
        quiet=True,
        enable_monitoring=False,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the SpecStyle production UI")
    parser.add_argument("--runtime-root", type=Path, default=_DEFAULT_ROOT)
    parser.add_argument(
        "--host", choices=(_LOCAL_HOST, _PUBLIC_HOST), default=_LOCAL_HOST
    )
    parser.add_argument("--port", type=int, default=7860)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    launch_production_ui(
        arguments.runtime_root,
        host=arguments.host,
        port=arguments.port,
    )
    return 0

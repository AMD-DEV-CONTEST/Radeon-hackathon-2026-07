from __future__ import annotations

from datetime import UTC, datetime
import base64
import mimetypes
import os
from pathlib import Path
from typing import Any

from agent_factory.document_processing import EMAIL_EXTENSIONS, OFFICE_EXTENSIONS, parse_file
from agent_factory.runtime_contracts import LoadedAgentPackage
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager
from agent_factory.factory_graph.frontend_bridge.agent_package_paths import (
    extension_root_for_package,
    host_session_workdir,
    package_runtime_workspace,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_utils import humanize_identifier
from agent_factory.workspace_mounts import WorkspaceMountRecord
from agent_factory.workspace_system import WorkspaceStore


WORKSPACE_BINARY_PREVIEW_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".zip",
    ".gz",
    ".tar",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
}


class AgentPackageWorkspaceService:
    def roots(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        roots = workspace_roots(package_id, package, session_id=session_id)
        return workspace_roots_payload(context=_workspace_context(package_id, session_id), roots=roots)

    def list_entries(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        *,
        scope: str = "workdir",
        relative_path: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return list_workspace_entries_from_roots(
            context=_workspace_context(package_id, session_id),
            roots=workspace_roots(package_id, package, session_id=session_id),
            scope=scope,
            relative_path=relative_path,
        )

    def read_file(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        *,
        scope: str = "workdir",
        relative_path: str,
        max_chars: int = 20000,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return read_workspace_file_from_roots(
            context=_workspace_context(package_id, session_id),
            roots=workspace_roots(package_id, package, session_id=session_id),
            scope=scope,
            relative_path=relative_path,
            max_chars=max_chars,
        )

    def resolve_file(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        *,
        scope: str = "workdir",
        relative_path: str,
        session_id: str | None = None,
    ) -> Path:
        return resolve_workspace_file_from_roots(
            roots=workspace_roots(package_id, package, session_id=session_id),
            scope=scope,
            relative_path=relative_path,
        )


def workspace_roots(package_id: str, package: LoadedAgentPackage, *, session_id: str | None = None) -> dict[str, Path]:
    workspace = package_runtime_workspace(package_id)
    normalized_session_id = str(session_id or "").strip()
    return {
        "package": package.package_root,
        "runtime": workspace.root,
        "workdir": _session_workspace_workdir(package_id, package, normalized_session_id)
        if normalized_session_id
        else workspace.workdir,
        "artifacts": workspace.artifacts,
        "extensions": extension_root_for_package(package_id, package),
    }


def workspace_scope_root(package_id: str, package: LoadedAgentPackage, scope: str, *, session_id: str | None = None) -> Path:
    return workspace_scope_root_from_roots(workspace_roots(package_id, package, session_id=session_id), scope)


def _workspace_context(package_id: str, session_id: str | None) -> dict[str, str]:
    normalized_session_id = str(session_id or "").strip()
    workspace_id = _session_workspace_id(package_id, normalized_session_id) if normalized_session_id else ""
    return {
        "package_id": package_id,
        **({"package_session_id": normalized_session_id} if normalized_session_id else {}),
        **({"workspace_id": workspace_id} if workspace_id else {}),
    }


def _session_workspace_id(package_id: str, session_id: str) -> str:
    if not session_id:
        return ""
    manager = AgentSessionManager(
        AgentSessionConfig(root=package_runtime_workspace(package_id).root / "sessions")
    )
    return manager.load(session_id).workspace_id


def _session_workspace_workdir(
    package_id: str,
    package: LoadedAgentPackage,
    session_id: str,
) -> Path:
    workspace_id = _session_workspace_id(package_id, session_id)
    store = WorkspaceStore()
    record = store.load_optional(workspace_id)
    if record is None:
        legacy = host_session_workdir(package_id, session_id)
        session = AgentSessionManager(
            AgentSessionConfig(root=package_runtime_workspace(package_id).root / "sessions")
        ).load(session_id)
        record = store.create(
            workspace_id=workspace_id,
            title=session.display_title or session.first_user_input or "新工作区",
            mode="isolated",
            owner_package_id=package_id,
            workdir_root=legacy if legacy.exists() else None,
        )
    return store.workdir(record.workspace_id)


def workspace_roots_payload(*, context: dict[str, Any], roots: dict[str, Path]) -> dict[str, Any]:
    return {
        **context,
        "roots": [
            {"scope": scope, "name": workspace_scope_label(scope), "exists": path.exists()}
            for scope, path in roots.items()
        ],
    }


def list_workspace_entries_from_roots(
    *,
    context: dict[str, Any],
    roots: dict[str, Path],
    scope: str = "workdir",
    relative_path: str = "",
    mounts: dict[str, WorkspaceMountRecord] | None = None,
) -> dict[str, Any]:
    root = workspace_scope_root_from_roots(roots, scope)
    active_mounts = mounts if scope == "workdir" else {}
    target = safe_workspace_path(root, relative_path, mounts=active_mounts)
    if not target.exists():
        return {**context, "scope": scope, "path": relative_path, "entries": []}
    if target.is_file():
        entries = [
            workspace_entry(
                target,
                root=root,
                scope=scope,
                relative_path=_normalized_workspace_relative_path(relative_path),
            )
        ]
    else:
        children = {path.name: path for path in target.iterdir()}
        if not str(relative_path or "").strip():
            for mount_name in active_mounts:
                children.setdefault(mount_name, root / mount_name)
        entries = [
            workspace_entry(
                path,
                root=root,
                scope=scope,
                relative_path=_workspace_child_path(relative_path, path.name),
                mount=active_mounts.get(path.name) if not str(relative_path or "").strip() else None,
            )
            for path in sorted(children.values(), key=workspace_sort_key)
        ]
    return {**context, "scope": scope, "path": relative_path, "entries": entries}


def read_workspace_file_from_roots(
    *,
    context: dict[str, Any],
    roots: dict[str, Path],
    scope: str = "workdir",
    relative_path: str,
    max_chars: int = 20000,
    mounts: dict[str, WorkspaceMountRecord] | None = None,
) -> dict[str, Any]:
    root = workspace_scope_root_from_roots(roots, scope)
    target = safe_workspace_path(
        root,
        relative_path,
        mounts=mounts if scope == "workdir" else None,
    )
    if not target.is_file():
        raise FileNotFoundError(f"workspace file not found: {relative_path}")
    stat = target.stat()
    byte_limit = max(4096, max_chars * 4)
    with target.open("rb") as handle:
        data = handle.read(byte_limit + 1)
    mime_type, _ = mimetypes.guess_type(target.name)
    is_binary = workspace_file_is_binary(target=target, data=data, mime_type=mime_type)
    content = ""
    content_base64 = ""
    preview_mode = "binary"
    truncated = stat.st_size > byte_limit
    extracted_text = workspace_extracted_text_preview(
        target=target,
        root=_workspace_content_root(
            root,
            relative_path,
            mounts=mounts if scope == "workdir" else None,
        ),
        max_chars=max_chars,
    )
    if extracted_text is not None:
        content, extracted_truncated = extracted_text
        is_binary = False
        preview_mode = "extracted_text"
        truncated = extracted_truncated
    elif not is_binary:
        text = data.decode("utf-8", errors="replace")
        truncated = truncated or len(text) > max_chars
        content = text[:max_chars]
        preview_mode = "text"
    else:
        preview_bytes = data[:byte_limit]
        content_base64 = base64.b64encode(preview_bytes).decode("ascii")
    return {
        **context,
        "scope": scope,
        "path": _normalized_workspace_relative_path(relative_path),
        "name": target.name,
        "kind": "binary" if is_binary else "text",
        "mime_type": mime_type or "application/octet-stream",
        "encoding": "base64" if is_binary else "utf-8",
        "size_bytes": stat.st_size,
        "content": content,
        "content_base64": content_base64,
        "preview_mode": preview_mode,
        "truncated": truncated,
    }


def resolve_workspace_file_from_roots(
    *,
    roots: dict[str, Path],
    scope: str = "workdir",
    relative_path: str,
    mounts: dict[str, WorkspaceMountRecord] | None = None,
) -> Path:
    root = workspace_scope_root_from_roots(roots, scope)
    target = safe_workspace_path(
        root,
        relative_path,
        mounts=mounts if scope == "workdir" else None,
    )
    if not target.is_file():
        raise FileNotFoundError(f"workspace file not found: {relative_path}")
    return target


def resolve_workspace_entry_from_roots(
    *,
    roots: dict[str, Path],
    scope: str = "workdir",
    relative_path: str,
    mounts: dict[str, WorkspaceMountRecord] | None = None,
) -> Path:
    root = workspace_scope_root_from_roots(roots, scope)
    target = safe_workspace_path(
        root,
        relative_path,
        mounts=mounts if scope == "workdir" else None,
    )
    if not target.exists():
        raise FileNotFoundError(f"workspace entry not found: {relative_path}")
    return target


def delete_workspace_file_from_roots(
    *,
    context: dict[str, Any],
    roots: dict[str, Path],
    scope: str = "workdir",
    relative_path: str,
    mounts: dict[str, WorkspaceMountRecord] | None = None,
) -> dict[str, Any]:
    root = workspace_scope_root_from_roots(roots, scope)
    target = safe_workspace_path(
        root,
        relative_path,
        mounts=mounts if scope == "workdir" else None,
    )
    if not target.is_file():
        raise FileNotFoundError(f"workspace file not found: {relative_path}")
    deleted_path = _normalized_workspace_relative_path(relative_path)
    target.unlink()
    return {**context, "scope": scope, "path": deleted_path, "deleted": True}


def workspace_scope_root_from_roots(roots: dict[str, Path], scope: str) -> Path:
    normalized = str(scope or "workdir").strip()
    if normalized not in roots:
        raise ValueError(f"unsupported workspace scope: {scope}")
    return roots[normalized].resolve()


def workspace_scope_label(scope: str) -> str:
    labels = {
        "package": "Package",
        "runtime": "Runtime",
        "workdir": "Workdir",
        "artifacts": "Artifacts",
        "extensions": "Extensions",
    }
    return labels.get(scope, humanize_identifier(scope))


def workspace_file_is_binary(*, target: Path, data: bytes, mime_type: str | None) -> bool:
    suffix = target.suffix.lower()
    if suffix in WORKSPACE_BINARY_PREVIEW_EXTENSIONS:
        return True
    if suffix == ".svg":
        return False
    normalized_mime = str(mime_type or "").lower()
    if normalized_mime.startswith("image/"):
        return True
    if normalized_mime in {"application/pdf", "application/zip", "application/octet-stream"}:
        return True
    return b"\x00" in data[:4096]


def workspace_extracted_text_preview(*, target: Path, root: Path, max_chars: int) -> tuple[str, bool] | None:
    if target.suffix.lower() not in (OFFICE_EXTENSIONS | EMAIL_EXTENSIONS):
        return None
    try:
        result = parse_file(target, root=root)
    except Exception:
        return None
    content = "\n\n".join(document.content.strip() for document in result.documents if document.content.strip()).strip()
    if not content:
        return None
    return content[:max_chars], len(content) > max_chars


def safe_workspace_path(
    root: Path,
    relative_path: str | os.PathLike[str] | None,
    *,
    mounts: dict[str, WorkspaceMountRecord] | None = None,
) -> Path:
    resolved_root = root.resolve()
    raw_path = str(relative_path or "").strip()
    if not raw_path:
        return resolved_root
    path = Path(raw_path)
    if path.is_absolute():
        raise ValueError("workspace path must be relative to its selected scope")
    parts = path.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"workspace path contains an invalid segment: {raw_path}")
    active_mounts = mounts or {}
    mount = active_mounts.get(parts[0]) if parts else None
    if mount is not None:
        resolved_mount_root = Path(mount.source_path).expanduser().resolve(strict=False)
        target = resolved_mount_root.joinpath(*parts[1:]).resolve(strict=False)
        try:
            target.relative_to(resolved_mount_root)
        except ValueError as exc:
            raise ValueError(f"workspace path escapes mounted directory: {raw_path}") from exc
        return target
    target = (resolved_root / path).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"workspace path escapes selected scope: {raw_path}") from exc
    return target


def workspace_entry(
    path: Path,
    *,
    root: Path,
    scope: str,
    relative_path: str | None = None,
    mount: WorkspaceMountRecord | None = None,
) -> dict[str, Any]:
    mount_source = (
        Path(mount.source_path).expanduser().resolve(strict=False)
        if mount is not None
        else None
    )
    effective_path = mount_source if mount_source is not None else path
    try:
        file_stat = effective_path.stat()
        size_bytes = file_stat.st_size if effective_path.is_file() else None
        updated_at = datetime.fromtimestamp(file_stat.st_mtime, UTC).isoformat()
    except OSError:
        size_bytes = None
        updated_at = None
    resolved_relative_path = relative_path
    if resolved_relative_path is None:
        try:
            resolved_relative_path = path.relative_to(root).as_posix()
        except ValueError:
            resolved_relative_path = path.name
    return {
        "name": path.name,
        "scope": scope,
        "path": "" if resolved_relative_path == "." else resolved_relative_path,
        "kind": "directory" if mount is not None or path.is_dir() else "file",
        "size_bytes": size_bytes,
        "updated_at": updated_at,
        **(
            {
                "mount": True,
                "mount_source": str(mount_source),
                "connected": (
                    mount_source.is_dir()
                    and os.path.lexists(path)
                    and path.resolve(strict=False) == mount_source
                ),
                "mount_id": mount.mount_id,
            }
            if mount is not None and mount_source is not None
            else {}
        ),
    }


def workspace_sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, path.name.lower())


def _normalized_workspace_relative_path(value: str | os.PathLike[str] | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"invalid workspace relative path: {raw}")
    return path.as_posix()


def _workspace_child_path(parent: str, name: str) -> str:
    normalized_parent = _normalized_workspace_relative_path(parent)
    return (
        f"{normalized_parent}/{name}"
        if normalized_parent
        else name
    )


def _workspace_content_root(
    root: Path,
    relative_path: str,
    *,
    mounts: dict[str, WorkspaceMountRecord] | None,
) -> Path:
    normalized = _normalized_workspace_relative_path(relative_path)
    first_part = Path(normalized).parts[0] if normalized else ""
    mount = (mounts or {}).get(first_part)
    if mount is None:
        return root
    return Path(mount.source_path).expanduser().resolve(strict=False)

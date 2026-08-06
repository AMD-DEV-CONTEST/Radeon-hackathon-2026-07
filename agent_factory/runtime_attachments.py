from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import mimetypes
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any

from agent_factory.document_processing import parse_file, parse_url
from agent_factory.file_capabilities import accepted_attachment_extensions
from agent_factory.file_utils import file_sha256


ATTACHMENT_INPUT_DIR = "input_files"
WORKSPACE_AGENT_DIR = ".agent"
ATTACHMENT_MAX_FILES_ENV = "AGENTFACTORY_ATTACHMENT_MAX_FILES"
ATTACHMENT_MAX_FILE_BYTES_ENV = "AGENTFACTORY_ATTACHMENT_MAX_FILE_BYTES"
ATTACHMENT_MAX_TOTAL_BYTES_ENV = "AGENTFACTORY_ATTACHMENT_MAX_TOTAL_BYTES"
ATTACHMENT_MAX_MODEL_CHARS_ENV = "AGENTFACTORY_ATTACHMENT_MAX_MODEL_CHARS"
DEFAULT_ATTACHMENT_MAX_FILES = 9
DEFAULT_ATTACHMENT_MAX_MODEL_CHARS = 24000
CURRENT_USER_ATTACHMENT_MANIFEST_HEADER = "Attachments included with the current user message:"


class AttachmentImportError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        code: str = "external_attachment_import_failed",
    ) -> None:
        super().__init__(message)
        self.path = path
        self.code = code


@dataclass(frozen=True, slots=True)
class AttachmentImportPolicy:
    max_files: int | None = DEFAULT_ATTACHMENT_MAX_FILES
    max_file_bytes: int | None = None
    max_total_bytes: int | None = None
    max_model_chars: int = DEFAULT_ATTACHMENT_MAX_MODEL_CHARS

    @classmethod
    def from_env(cls) -> "AttachmentImportPolicy":
        return cls(
            max_files=_attachment_max_files_from_env(),
            max_file_bytes=_optional_positive_int_env(ATTACHMENT_MAX_FILE_BYTES_ENV),
            max_total_bytes=_optional_positive_int_env(ATTACHMENT_MAX_TOTAL_BYTES_ENV),
            max_model_chars=_optional_positive_int_env(ATTACHMENT_MAX_MODEL_CHARS_ENV) or DEFAULT_ATTACHMENT_MAX_MODEL_CHARS,
        )


@dataclass(frozen=True, slots=True)
class RuntimeAttachmentRef:
    attachment_id: str
    display_name: str
    source_kind: str
    runtime_path: str
    mime_type: str | None
    size_bytes: int
    sha256: str
    scope: str
    access: str
    imported_at: str
    extracted_text: str | None = None
    extracted_char_count: int = 0
    extracted_text_truncated: bool = False
    parser: str | None = None
    parse_warnings: tuple[str, ...] = ()
    source_url: str | None = None

    def model_payload(self) -> dict[str, Any]:
        payload = {
            "attachment_id": self.attachment_id,
            "display_name": self.display_name,
            "source_kind": self.source_kind,
            "path": self.runtime_path,
            "runtime_path": self.runtime_path,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "scope": self.scope,
            "access": self.access,
            "imported_at": self.imported_at,
        }
        if self.extracted_text:
            payload["extracted_text"] = self.extracted_text
            payload["extracted_char_count"] = self.extracted_char_count
            payload["extracted_text_truncated"] = self.extracted_text_truncated
        if self.parser:
            payload["parser"] = self.parser
        if self.parse_warnings:
            payload["parse_warnings"] = list(self.parse_warnings)
        if self.source_url:
            payload["source_url"] = self.source_url
        return payload


@dataclass(frozen=True, slots=True)
class _PreparedLocalAttachment:
    raw_path: str
    source: Path
    size_bytes: int


@dataclass(frozen=True, slots=True)
class _ImportedLocalAttachment:
    ref: RuntimeAttachmentRef
    target_dir: Path


@dataclass(frozen=True, slots=True)
class _AttachmentText:
    content: str
    original_chars: int
    truncated: bool
    parser: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AttachmentImportResult:
    message: str
    attachments: list[dict[str, Any]]


def import_runtime_attachments(
    message: str,
    attachments: Any,
    *,
    storage_root: Path,
    runtime_path_root: str,
    base_dir: Path | None = None,
    scope: str = "run",
    policy: AttachmentImportPolicy | None = None,
) -> AttachmentImportResult:
    resolved_policy = policy or AttachmentImportPolicy.from_env()
    payload_attachments = import_payload_attachments(
        attachments,
        storage_root=storage_root,
        runtime_path_root=runtime_path_root,
        base_dir=base_dir,
        scope=scope,
        policy=resolved_policy,
    )
    return AttachmentImportResult(
        message=message,
        attachments=payload_attachments,
    )


def workspace_attachment_root(workdir_root: Path) -> Path:
    return workdir_root / WORKSPACE_AGENT_DIR / ATTACHMENT_INPUT_DIR


def workspace_attachment_runtime_root(runtime_workdir: str, scope: str) -> str:
    return str(
        PurePosixPath(runtime_workdir)
        / WORKSPACE_AGENT_DIR
        / ATTACHMENT_INPUT_DIR
        / scope
    )


def import_payload_attachments(
    attachments: Any,
    *,
    storage_root: Path,
    runtime_path_root: str,
    base_dir: Path | None = None,
    scope: str = "run",
    policy: AttachmentImportPolicy | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(attachments, list) or not attachments:
        return []
    resolved_policy = policy or AttachmentImportPolicy.from_env()
    items = [dict(item) for item in attachments if isinstance(item, dict)]
    if resolved_policy.max_files is not None and len(items) > resolved_policy.max_files:
        raise AttachmentImportError(
            "attachment count exceeds configured limit: "
            f"{len(items)} > {resolved_policy.max_files}",
            code="external_attachment_limit_exceeded",
        )
    imported: list[_ImportedLocalAttachment] = []
    try:
        for item in items:
            imported.append(
                _import_payload_attachment(
                    item,
                    storage_root=storage_root,
                    runtime_path_root=runtime_path_root,
                    base_dir=base_dir,
                    scope=scope,
                    policy=resolved_policy,
                )
            )
        _enforce_import_policy(
            [
                _PreparedLocalAttachment(
                    raw_path=imported_item.ref.display_name,
                    source=imported_item.target_dir / imported_item.ref.display_name,
                    size_bytes=imported_item.ref.size_bytes,
                )
                for imported_item in imported
            ],
            policy=resolved_policy,
        )
    except Exception:
        for imported_item in imported:
            shutil.rmtree(imported_item.target_dir, ignore_errors=True)
        raise
    return [item.ref.model_payload() for item in imported]


def import_local_attachment(
    raw_path: str,
    *,
    storage_root: Path,
    runtime_path_root: str,
    base_dir: Path | None = None,
    scope: str = "run",
    policy: AttachmentImportPolicy | None = None,
) -> RuntimeAttachmentRef:
    return _import_local_attachment_item(
        raw_path,
        storage_root=storage_root,
        runtime_path_root=runtime_path_root,
        base_dir=base_dir,
        scope=scope,
        policy=policy or AttachmentImportPolicy.from_env(),
    ).ref


def _import_local_attachment_item(
    raw_path: str,
    *,
    storage_root: Path,
    runtime_path_root: str,
    base_dir: Path | None = None,
    scope: str = "run",
    policy: AttachmentImportPolicy,
) -> _ImportedLocalAttachment:
    prepared = _prepare_local_attachment_source(raw_path, base_dir=base_dir)
    _enforce_import_policy([prepared], policy=policy)
    return _copy_prepared_local_attachment(
        prepared,
        storage_root=storage_root,
        runtime_path_root=runtime_path_root,
        scope=scope,
        policy=policy,
    )


def _copy_prepared_local_attachment(
    prepared: _PreparedLocalAttachment,
    *,
    storage_root: Path,
    runtime_path_root: str,
    scope: str,
    policy: AttachmentImportPolicy,
) -> _ImportedLocalAttachment:
    safe_name = _safe_filename(prepared.source.name)
    _validate_attachment_filename(safe_name)
    storage_root.mkdir(parents=True, exist_ok=True)
    target = _unique_storage_path(storage_root, safe_name)
    try:
        shutil.copy2(prepared.source, target)
        digest = file_sha256(target)
        size_bytes = target.stat().st_size
    except Exception as exc:
        shutil.rmtree(storage_root, ignore_errors=True)
        raise AttachmentImportError(
            f"attachment file could not be imported: {prepared.raw_path}: {exc}",
            path=prepared.raw_path,
        ) from exc
    runtime_path = _runtime_attachment_path(
        runtime_path_root=runtime_path_root,
        filename=target.name,
    )
    mime_type, _ = mimetypes.guess_type(safe_name)
    extracted = _extract_file_text(target, policy=policy)
    return _ImportedLocalAttachment(
        ref=RuntimeAttachmentRef(
            attachment_id=_attachment_id_for(runtime_path=runtime_path, digest=digest),
            display_name=target.name,
            source_kind="local_path",
            runtime_path=runtime_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=digest,
            scope=scope,
            access="read_only",
            imported_at=datetime.now(UTC).isoformat(),
            extracted_text=extracted.content,
            extracted_char_count=extracted.original_chars,
            extracted_text_truncated=extracted.truncated,
            parser=extracted.parser,
            parse_warnings=extracted.warnings,
        ),
        target_dir=storage_root,
    )


def _import_payload_attachment(
    item: dict[str, Any],
    *,
    storage_root: Path,
    runtime_path_root: str,
    base_dir: Path | None,
    scope: str,
    policy: AttachmentImportPolicy,
) -> _ImportedLocalAttachment:
    kind = str(item.get("kind") or "").strip().lower()
    display_name = _safe_filename(str(item.get("name") or item.get("display_name") or kind or "attachment"))
    mime_type = str(item.get("mime_type") or item.get("mime") or "").strip() or None
    declared_source_kind = str(item.get("source_kind") or "").strip()
    content = item.get("content")
    if kind == "text":
        text = str(content or "")
        if not text.strip():
            raise AttachmentImportError("text attachment content cannot be empty", path=display_name)
        filename = _ensure_suffix(display_name, ".txt")
        extracted = _bounded_attachment_text(text, parser="inline_text", warnings=(), policy=policy)
        return _write_runtime_attachment(
            data=text.encode("utf-8"),
            display_name=filename,
            source_kind=declared_source_kind or "inline_text",
            mime_type=mime_type or "text/plain",
            storage_root=storage_root,
            runtime_path_root=runtime_path_root,
            scope=scope,
            extracted=extracted,
        )
    if kind == "url":
        url = str(content or item.get("url") or "").strip()
        parsed = parse_url(url, metadata={"title": display_name})
        text = "\n\n".join(document.content for document in parsed.documents).strip()
        extracted = _bounded_attachment_text(
            text,
            parser=_first_loader(parsed.documents) or "url",
            warnings=tuple(parsed.warnings),
            policy=policy,
        )
        filename = _ensure_suffix(display_name or "url", ".txt")
        return _write_runtime_attachment(
            data=(text or url).encode("utf-8"),
            display_name=filename,
            source_kind="url",
            mime_type=mime_type or "text/plain",
            storage_root=storage_root,
            runtime_path_root=runtime_path_root,
            scope=scope,
            extracted=extracted,
            source_url=url,
        )
    if kind == "file":
        raw = str(content or item.get("path") or "").strip()
        encoding = str(item.get("encoding") or "").strip().lower()
        if encoding == "base64" or raw.startswith("data:"):
            data = _decode_base64_payload(raw)
            return _write_runtime_attachment(
                data=data,
                display_name=display_name,
                source_kind=declared_source_kind or "uploaded_file",
                mime_type=mime_type,
                storage_root=storage_root,
                runtime_path_root=runtime_path_root,
                scope=scope,
                policy=policy,
            )
        if raw:
            candidate = _resolve_source(raw, base_dir=base_dir)
            if candidate.exists():
                return _import_local_attachment_item(
                    raw,
                    storage_root=storage_root,
                    runtime_path_root=runtime_path_root,
                    base_dir=base_dir,
                    scope=scope,
                    policy=policy,
                )
        if raw:
            data = _decode_base64_payload(raw)
            return _write_runtime_attachment(
                data=data,
                display_name=display_name,
                source_kind=declared_source_kind or "uploaded_file",
                mime_type=mime_type,
                storage_root=storage_root,
                runtime_path_root=runtime_path_root,
                scope=scope,
                policy=policy,
            )
        return _import_local_attachment_item(
            raw,
            storage_root=storage_root,
            runtime_path_root=runtime_path_root,
            base_dir=base_dir,
            scope=scope,
            policy=policy,
        )
    raise AttachmentImportError(f"unsupported attachment kind: {kind or 'unknown'}", path=display_name)


def _write_runtime_attachment(
    *,
    data: bytes,
    display_name: str,
    source_kind: str,
    mime_type: str | None,
    storage_root: Path,
    runtime_path_root: str,
    scope: str,
    policy: AttachmentImportPolicy | None = None,
    extracted: _AttachmentText | None = None,
    source_url: str | None = None,
) -> _ImportedLocalAttachment:
    safe_name = _safe_filename(display_name)
    _validate_attachment_filename(safe_name)
    storage_root.mkdir(parents=True, exist_ok=True)
    target = _unique_storage_path(storage_root, safe_name)
    try:
        target.write_bytes(data)
        digest = file_sha256(target)
        size_bytes = target.stat().st_size
    except Exception as exc:
        shutil.rmtree(storage_root, ignore_errors=True)
        raise AttachmentImportError(
            f"attachment file could not be imported: {safe_name}: {exc}",
            path=safe_name,
        ) from exc
    resolved_policy = policy or AttachmentImportPolicy.from_env()
    text = extracted if extracted is not None else _extract_file_text(target, policy=resolved_policy)
    runtime_path = _runtime_attachment_path(
        runtime_path_root=runtime_path_root,
        filename=target.name,
    )
    guessed_mime, _ = mimetypes.guess_type(safe_name)
    return _ImportedLocalAttachment(
        ref=RuntimeAttachmentRef(
            attachment_id=_attachment_id_for(runtime_path=runtime_path, digest=digest),
            display_name=target.name,
            source_kind=source_kind,
            runtime_path=runtime_path,
            mime_type=mime_type or guessed_mime,
            size_bytes=size_bytes,
            sha256=digest,
            scope=scope,
            access="read_only",
            imported_at=datetime.now(UTC).isoformat(),
            extracted_text=text.content,
            extracted_char_count=text.original_chars,
            extracted_text_truncated=text.truncated,
            parser=text.parser,
            parse_warnings=text.warnings,
            source_url=source_url,
        ),
        target_dir=storage_root,
    )


def format_attachments_for_model(
    attachments: Any,
    *,
    include_extracted_text_for_images: bool = True,
) -> str:
    if not isinstance(attachments, list) or not attachments:
        return ""
    lines = [
        "Runtime attachments available for this turn:",
        "Use the path field when calling tools. Do not use or infer original host file paths.",
    ]
    for item in attachments:
        if not isinstance(item, dict):
            continue
        parts = _model_attachment_descriptor(item)
        if not parts:
            continue
        mime_type = _attachment_mime_type(item)
        digest = str(item.get("sha256") or "").strip()
        if digest:
            parts.append(f"sha256={digest}")
        lines.append("- " + "; ".join(parts))
        image_attachment = _is_image_mime_type(mime_type)
        extracted_text = (
            str(item.get("extracted_text") or "").strip()
            if include_extracted_text_for_images or not image_attachment
            else ""
        )
        if extracted_text:
            char_count = item.get("extracted_char_count")
            truncated = bool(item.get("extracted_text_truncated"))
            parser = str(item.get("parser") or "").strip()
            meta = []
            if parser:
                meta.append(f"parser={parser}")
            if isinstance(char_count, int):
                meta.append(f"chars={char_count}")
            if truncated:
                meta.append("truncated=true")
            lines.append(f"  extracted_text{(' (' + ', '.join(meta) + ')') if meta else ''}:")
            lines.extend(f"  {line}" for line in extracted_text.splitlines())
        warnings = item.get("parse_warnings")
        if isinstance(warnings, list) and warnings:
            lines.append("  parse_warnings=" + "; ".join(str(warning) for warning in warnings if str(warning).strip()))
    return "\n".join(lines) if len(lines) > 2 else ""


def format_current_user_attachment_manifest(attachments: Any) -> str:
    if not isinstance(attachments, list) or not attachments:
        return ""
    lines = [
        CURRENT_USER_ATTACHMENT_MANIFEST_HEADER,
        "Treat every item below as attached to this user message. Parsed content is provided separately.",
    ]
    for item in attachments:
        if not isinstance(item, dict):
            continue
        parts = _model_attachment_descriptor(item)
        if parts:
            lines.append("- " + "; ".join(parts))
    return "\n".join(lines) if len(lines) > 2 else ""


def _model_attachment_descriptor(item: dict[str, Any]) -> list[str]:
    attachment_id = str(item.get("attachment_id") or "").strip()
    path = str(item.get("path") or item.get("runtime_path") or "").strip()
    display_name = str(item.get("display_name") or "").strip()
    if not attachment_id or not path:
        return []
    parts = [
        f"id={attachment_id}",
        f"name={display_name or attachment_id}",
        f"path={path}",
    ]
    mime_type = _attachment_mime_type(item)
    if mime_type:
        parts.append(f"mime={mime_type}")
    size_bytes = item.get("size_bytes")
    if isinstance(size_bytes, int):
        parts.append(f"size_bytes={size_bytes}")
    return parts


def image_attachment_content_parts(attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(attachments, list) or not attachments:
        return []
    parts: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        mime_type = _attachment_mime_type(item)
        if not _is_image_mime_type(mime_type):
            continue
        path = str(item.get("path") or item.get("runtime_path") or "").strip()
        if not path:
            continue
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": _image_data_url(path=Path(path), mime_type=mime_type or "image/png"),
                },
            }
        )
    return parts


def image_attachment_count(attachments: Any) -> int:
    if not isinstance(attachments, list):
        return 0
    return sum(1 for item in attachments if isinstance(item, dict) and _is_image_mime_type(_attachment_mime_type(item)))


def has_attachment_payload(attachments: Any) -> bool:
    return isinstance(attachments, list) and any(isinstance(item, dict) for item in attachments)


def normalized_runtime_attachments(attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(attachments, list):
        return []
    return [dict(item) for item in attachments if isinstance(item, dict)]


def transcript_attachment_views(attachments: Any) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for item in normalized_runtime_attachments(attachments):
        name = _attachment_display_name(item)
        if not name:
            continue
        source_kind = str(item.get("source_kind") or "").strip()
        raw_kind = str(item.get("kind") or "").strip()
        mime_type = _attachment_mime_type(item)
        workspace_path = _attachment_workspace_path(item)
        views.append(
            {
                "kind": _attachment_view_kind(source_kind, raw_kind),
                "name": name,
                **({"source_kind": source_kind} if source_kind else {}),
                **({"mime_type": mime_type} if mime_type else {}),
                **(
                    {"workspace_scope": "workdir", "path": workspace_path}
                    if workspace_path
                    else {}
                ),
                **({"size_bytes": item.get("size_bytes")} if item.get("size_bytes") is not None else {}),
            }
        )
    return views


def _attachment_workspace_path(item: dict[str, Any]) -> str:
    raw_path = str(item.get("runtime_path") or item.get("path") or "").strip()
    if not raw_path:
        return ""
    normalized = raw_path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return ""
    for index in range(len(parts) - 1):
        if parts[index] in {".factory", WORKSPACE_AGENT_DIR} and parts[index + 1] == ATTACHMENT_INPUT_DIR:
            return str(PurePosixPath(*parts[index:]))
    try:
        input_files_index = parts.index(ATTACHMENT_INPUT_DIR)
    except ValueError:
        if normalized.startswith("/") or _looks_like_windows_absolute_path(normalized):
            return ""
        return str(PurePosixPath(*parts))
    return str(PurePosixPath(*parts[input_files_index:]))


def _looks_like_windows_absolute_path(path: str) -> bool:
    return len(path) >= 3 and path[0].isalpha() and path[1:3] == ":/"


def _attachment_mime_type(item: dict[str, Any]) -> str:
    mime_type = str(item.get("mime_type") or "").strip()
    if mime_type:
        return mime_type
    for key in ("display_name", "path", "runtime_path"):
        value = str(item.get(key) or "").strip()
        if not value:
            continue
        guessed, _encoding = mimetypes.guess_type(value)
        if guessed:
            return guessed
    return ""


def _attachment_display_name(item: dict[str, Any]) -> str:
    for key in ("display_name", "name"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    for key in ("path", "runtime_path"):
        value = str(item.get(key) or "").strip()
        if value:
            return PurePosixPath(value).name or Path(value).name
    return str(item.get("attachment_id") or "").strip()


def _attachment_view_kind(source_kind: str, raw_kind: str = "") -> str:
    if raw_kind in {"file", "text", "url"}:
        return raw_kind
    if source_kind == "url":
        return "url"
    if source_kind == "inline_text":
        return "text"
    return "file"


def _is_image_mime_type(mime_type: str) -> bool:
    return mime_type.lower().startswith("image/")


def _image_data_url(*, path: Path, mime_type: str) -> str:
    if not path.is_file():
        raise AttachmentImportError(
            f"image attachment file does not exist: {path}",
            path=str(path),
            code="runtime_image_attachment_missing",
        )
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def time_named_attachment_scope(now: datetime | None = None) -> str:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def merge_attachments_into_user_config(user_config: Any, attachments: Any) -> dict[str, Any]:
    result = dict(user_config or {}) if isinstance(user_config, dict) else {}
    existing = (
        [dict(item) for item in result.get("attachments") if isinstance(item, dict)]
        if isinstance(result.get("attachments"), list)
        else []
    )
    payload = (
        [dict(item) for item in attachments if isinstance(item, dict)]
        if isinstance(attachments, list)
        else []
    )
    merged = [*existing, *payload]
    if merged:
        result["attachments"] = merged
    return result


def attachment_import_error_payload(
    exc: AttachmentImportError,
    *,
    where: str = "runtime_attachments",
) -> dict[str, Any]:
    return {
        "where": where,
        "why": exc.code,
        "message": str(exc),
        "path": exc.path,
        "suggested_action": (
            "Use @/absolute/or/relative/file/path@ with an existing file, "
            "or remove the attachment marker."
        ),
    }


def _prepare_local_attachment_source(
    raw_path: str,
    *,
    base_dir: Path | None,
) -> _PreparedLocalAttachment:
    _validate_raw_attachment_path(raw_path)
    source = _resolve_source(raw_path, base_dir=base_dir)
    if not source.exists():
        raise AttachmentImportError(f"attachment file does not exist: {raw_path}", path=raw_path)
    if not source.is_file():
        raise AttachmentImportError(f"attachment path must be a file: {raw_path}", path=raw_path)
    try:
        size_bytes = source.stat().st_size
    except OSError as exc:
        raise AttachmentImportError(
            f"attachment file cannot be inspected: {raw_path}: {exc}",
            path=raw_path,
        ) from exc
    return _PreparedLocalAttachment(raw_path=raw_path, source=source, size_bytes=size_bytes)


def _enforce_import_policy(
    prepared_sources: list[_PreparedLocalAttachment],
    *,
    policy: AttachmentImportPolicy,
) -> None:
    if policy.max_files is not None and len(prepared_sources) > policy.max_files:
        raise AttachmentImportError(
            "attachment count exceeds configured limit: "
            f"{len(prepared_sources)} > {policy.max_files}",
            code="external_attachment_limit_exceeded",
        )
    total_bytes = sum(source.size_bytes for source in prepared_sources)
    if policy.max_total_bytes is not None and total_bytes > policy.max_total_bytes:
        raise AttachmentImportError(
            "attachment total size exceeds configured limit: "
            f"{total_bytes} > {policy.max_total_bytes}",
            code="external_attachment_limit_exceeded",
        )
    for source in prepared_sources:
        if policy.max_file_bytes is not None and source.size_bytes > policy.max_file_bytes:
            raise AttachmentImportError(
                "attachment file exceeds configured size limit: "
                f"{source.size_bytes} > {policy.max_file_bytes}",
                path=source.raw_path,
                code="external_attachment_limit_exceeded",
            )


def _extract_file_text(path: Path, *, policy: AttachmentImportPolicy) -> _AttachmentText:
    parsed = parse_file(path, root=path.parent)
    content = "\n\n".join(document.content for document in parsed.documents).strip()
    return _bounded_attachment_text(
        content,
        parser=_first_loader(parsed.documents),
        warnings=tuple(parsed.warnings),
        policy=policy,
    )


def _bounded_attachment_text(
    content: str,
    *,
    parser: str | None,
    warnings: tuple[str, ...],
    policy: AttachmentImportPolicy,
) -> _AttachmentText:
    text = str(content or "").strip()
    original_chars = len(text)
    limit = policy.max_model_chars
    if limit > 0 and len(text) > limit:
        text = text[:limit].rstrip()
        truncated = True
    else:
        truncated = False
    return _AttachmentText(
        content=text,
        original_chars=original_chars,
        truncated=truncated,
        parser=parser,
        warnings=warnings,
    )


def _first_loader(documents: Any) -> str | None:
    if not isinstance(documents, list):
        return None
    for document in documents:
        metadata = getattr(document, "metadata", None)
        if not isinstance(metadata, dict) and isinstance(document, dict):
            metadata = document.get("metadata")
        if not isinstance(metadata, dict):
            continue
        loader = str(metadata.get("loader") or "").strip()
        if loader:
            return loader
    return None


def _decode_base64_payload(value: str) -> bytes:
    payload = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttachmentImportError("file attachment content is not valid base64") from exc


def _ensure_suffix(value: str, suffix: str) -> str:
    name = _safe_filename(value)
    if Path(name).suffix:
        return name
    return f"{name}{suffix}"


def _validate_attachment_filename(filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in accepted_attachment_extensions():
        raise AttachmentImportError(
            f"unsupported attachment file type: {suffix or 'no_extension'}",
            path=filename,
            code="unsupported_attachment_type",
        )


def _resolve_source(raw_path: str, *, base_dir: Path | None) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        root = base_dir or Path.cwd()
        candidate = root / candidate
    return candidate.resolve(strict=False)


def _validate_raw_attachment_path(raw_path: str) -> None:
    if not raw_path.strip():
        raise AttachmentImportError(
            "attachment marker path cannot be empty",
            path=raw_path,
            code="invalid_external_attachment_marker",
        )
    if any(char in raw_path for char in ("\n", "\r", "\0")):
        raise AttachmentImportError(
            "attachment marker must contain one filesystem path",
            path=raw_path,
            code="invalid_external_attachment_marker",
        )


def _safe_filename(value: str) -> str:
    cleaned = "".join(
        "_" if char in {"/", "\\"} or not char.isprintable() else char
        for char in value
    ).strip()
    return cleaned or "attachment"


def _unique_storage_path(storage_root: Path, filename: str) -> Path:
    safe_name = _safe_filename(filename)
    candidate = storage_root / safe_name
    if not candidate.exists():
        return candidate
    parsed = Path(safe_name)
    stem = parsed.stem or parsed.name
    suffix = parsed.suffix
    index = 2
    while True:
        candidate = storage_root / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _optional_positive_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _attachment_max_files_from_env() -> int:
    configured = _optional_positive_int_env(ATTACHMENT_MAX_FILES_ENV)
    if configured is None:
        return DEFAULT_ATTACHMENT_MAX_FILES
    return min(configured, DEFAULT_ATTACHMENT_MAX_FILES)


def _runtime_attachment_path(*, runtime_path_root: str, filename: str) -> str:
    return str(PurePosixPath(runtime_path_root) / filename)


def _attachment_id_for(*, runtime_path: str, digest: str) -> str:
    source = runtime_path + "\0" + digest
    return f"att_{sha256(source.encode('utf-8')).hexdigest()[:16]}"

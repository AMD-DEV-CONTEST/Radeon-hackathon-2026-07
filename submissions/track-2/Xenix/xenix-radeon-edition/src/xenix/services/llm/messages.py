"""Provider-neutral message values and the canonical content-block algebra.

Conversation rows keep content blocks as JSON because SQLite is the durable
authority.  The service and adapters immediately turn that JSON into the
small, closed set of block types below.  This keeps provider/UI projections
from inventing a second block convention while still allowing a compact JSON
representation at the storage boundary.

The block fallback is intentionally conservative.  Only stable business
facts are included, and the returned Markdown is bounded before it can cross
to a text-only provider.  In particular, no local path, diagnostic payload,
or provider secret is copied into a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, TypeAlias

from ...exceptions import ValidationError


# These are deliberately modest.  They bound provider context and make a
# malformed persisted payload harmless without truncating the canonical JSON
# object itself.  Individual fields are bounded when parsed; the final
# fallback has a separate total bound.
MAX_BLOCK_TEXT_CHARS = 16_384
MAX_BLOCK_FIELD_CHARS = 512
MAX_BLOCK_MARKDOWN_CHARS = 4_096


def _bounded_text(value: Any, *, label: str, limit: int = MAX_BLOCK_FIELD_CHARS) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"Message block field '{label}' must be text.")
    if len(value) > limit:
        raise ValidationError(f"Message block field '{label}' exceeds its character bound.")
    return value


def _optional_bounded_text(value: Any, *, label: str, limit: int = MAX_BLOCK_FIELD_CHARS) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, label=label, limit=limit)


def _dataset_name(value: Any) -> str | None:
    """Validate the logical Dataset label used in the canonical block.

    Dataset ``name`` is a display label, not source-file provenance.  Keep
    path-shaped values out of the canonical/provider boundary even when a
    caller accidentally forwards a local path.
    """

    value = _optional_bounded_text(value, label="name")
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if "/" in value or "\\" in value:
        raise ValidationError("Message block field 'name' must be a logical Dataset name, not a path.")
    return value


def _bounded_identifier(value: Any, *, label: str) -> str:
    result = _bounded_text(value, label=label).strip()
    if not result:
        raise ValidationError(f"Message block field '{label}' cannot be blank.")
    # IDs are carried into the provider-facing textual fallback.  They are
    # opaque domain identities, never local paths; reject a malformed path
    # here rather than accidentally exposing one through ``to_markdown()``.
    if "/" in result or "\\" in result:
        raise ValidationError(f"Message block field '{label}' must not be a path.")
    return result


def _bounded_nonnegative_int(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"Message block field '{label}' must be a non-negative integer.")
    return value


def _safe_file_name(value: str | None) -> str | None:
    """Return a display-safe leaf name, never an absolute/local path."""

    if value is None:
        return None
    # Both separators are handled because persisted desktop payloads can be
    # authored on another platform.  Keep only the final leaf and reject
    # traversal-ish values that have no meaningful display name.
    leaf = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if leaf in {"", ".", ".."}:
        return None
    return leaf[:MAX_BLOCK_FIELD_CHARS]


def _bounded_markdown(value: str) -> str:
    if len(value) <= MAX_BLOCK_MARKDOWN_CHARS:
        return value
    return value[: MAX_BLOCK_MARKDOWN_CHARS - 1].rstrip() + "…"


@dataclass(frozen=True)
class MessageBlock:
    """Base protocol for canonical, persistable content blocks."""

    type: str = field(init=False, default="")

    def to_json(self) -> dict[str, Any]:
        raise NotImplementedError

    def to_markdown(self) -> str:
        raise NotImplementedError

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "CanonicalMessageBlock":
        if not isinstance(payload, Mapping):
            raise ValidationError("Message content block must be an object.")
        block_type = payload.get("type")
        if not isinstance(block_type, str) or not block_type.strip():
            raise ValidationError("Message content block type is required.")
        normalized = block_type.strip().lower()
        if normalized == "text":
            return TextBlock(text=_bounded_text(payload.get("text", ""), label="text", limit=MAX_BLOCK_TEXT_CHARS))
        if normalized == "markdown":
            return MarkdownBlock(text=_bounded_text(payload.get("text", ""), label="text", limit=MAX_BLOCK_TEXT_CHARS))
        if normalized == "dataset":
            # ``preview_columns``, source provenance and the presentation
            # flag belonged to the pre-Stage-23 projection.  Ignore them
            # before validating retained fields so historical payloads (some
            # contain fifty columns) remain readable without rewriting rows.
            return DatasetBlock(
                dataset_id=_bounded_identifier(payload.get("dataset_id"), label="dataset_id"),
                name=_dataset_name(payload.get("name")),
                row_count=_bounded_nonnegative_int(payload.get("row_count"), label="row_count"),
                column_count=_bounded_nonnegative_int(payload.get("column_count"), label="column_count"),
            )
        if normalized in {"source_attachment", "source-attachment"}:
            # Source attachments predate the canonical Dataset projection.
            # Their presentation metadata is retained only when it is a
            # harmless string; malformed/oversized legacy values are dropped
            # so reopening a historical Thread cannot fail on UI metadata.
            legacy_file_name = payload.get("file_name")
            if isinstance(legacy_file_name, str):
                legacy_file_name = legacy_file_name[:MAX_BLOCK_FIELD_CHARS]
            else:
                legacy_file_name = None
            legacy_source_format = payload.get("source_format")
            if isinstance(legacy_source_format, str):
                legacy_source_format = legacy_source_format[:MAX_BLOCK_FIELD_CHARS]
            else:
                legacy_source_format = None
            legacy_visible = payload.get("chatbot_visible", payload.get("visible"))
            if not isinstance(legacy_visible, bool):
                legacy_visible = None
            return SourceAttachmentBlock(
                artifact_id=_bounded_identifier(payload.get("artifact_id"), label="artifact_id"),
                file_name=_safe_file_name(legacy_file_name),
                source_format=legacy_source_format,
                chatbot_visible=legacy_visible,
            )
        raise ValidationError(f"Unsupported message content block type '{block_type}'.")


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValidationError("Message block presentation hint must be a boolean.")
    return value


@dataclass(frozen=True)
class TextBlock(MessageBlock):
    text: str
    type: Literal["text"] = field(init=False, default="text")

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "text",
            _bounded_text(self.text, label="text", limit=MAX_BLOCK_TEXT_CHARS),
        )

    def to_json(self) -> dict[str, Any]:
        return {"type": self.type, "text": self.text}

    def to_markdown(self) -> str:
        return _bounded_markdown(self.text)


@dataclass(frozen=True)
class MarkdownBlock(MessageBlock):
    text: str
    type: Literal["markdown"] = field(init=False, default="markdown")

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "text",
            _bounded_text(self.text, label="text", limit=MAX_BLOCK_TEXT_CHARS),
        )

    def to_json(self) -> dict[str, Any]:
        return {"type": self.type, "text": self.text}

    def to_markdown(self) -> str:
        return _bounded_markdown(self.text)


@dataclass(frozen=True)
class DatasetBlock(MessageBlock):
    dataset_id: str
    name: str | None = None
    row_count: int | None = None
    column_count: int | None = None
    type: Literal["dataset"] = field(init=False, default="dataset")

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_id", _bounded_identifier(self.dataset_id, label="dataset_id"))
        object.__setattr__(self, "name", _dataset_name(self.name))
        object.__setattr__(self, "row_count", _bounded_nonnegative_int(self.row_count, label="row_count"))
        object.__setattr__(self, "column_count", _bounded_nonnegative_int(self.column_count, label="column_count"))

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "dataset_id": self.dataset_id,
        }
        # Stage 23 canonical Dataset contract: exactly the compact identity
        # and historical summary.  ``None`` is explicit so every new write
        # has the same stable field shape.
        payload.update(
            {
                "name": self.name,
                "row_count": self.row_count,
                "column_count": self.column_count,
            }
        )
        return payload

    def to_markdown(self) -> str:
        parts = ["Attached dataset"]
        if self.name:
            parts.append(self.name)
        parts.append(f"dataset_id: {self.dataset_id}")
        if self.row_count is not None:
            parts.append(f"rows: {self.row_count}")
        if self.column_count is not None:
            parts.append(f"columns: {self.column_count}")
        return _bounded_markdown(parts[0] + " (" + "; ".join(parts[1:]) + ")")


@dataclass(frozen=True)
class SourceAttachmentBlock(MessageBlock):
    artifact_id: str
    file_name: str | None = None
    source_format: str | None = None
    chatbot_visible: bool | None = None
    type: Literal["source_attachment"] = field(init=False, default="source_attachment")

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _bounded_identifier(self.artifact_id, label="artifact_id"))
        file_name = self.file_name[:MAX_BLOCK_FIELD_CHARS] if isinstance(self.file_name, str) else None
        source_format = self.source_format[:MAX_BLOCK_FIELD_CHARS] if isinstance(self.source_format, str) else None
        object.__setattr__(self, "file_name", _safe_file_name(file_name))
        object.__setattr__(self, "source_format", source_format.strip() if source_format and source_format.strip() else None)
        object.__setattr__(self, "chatbot_visible", self.chatbot_visible if isinstance(self.chatbot_visible, bool) else None)

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type, "artifact_id": self.artifact_id}
        if self.file_name is not None:
            payload["file_name"] = self.file_name
        if self.source_format is not None:
            payload["source_format"] = self.source_format
        if self.chatbot_visible is not None:
            payload["chatbot_visible"] = self.chatbot_visible
        return payload

    def to_markdown(self) -> str:
        # SourceAttachmentBlock is retained solely for historical decode and
        # UI projection.  It must never cross the provider boundary carrying
        # artifact IDs, file names, formats, or paths.
        return "Attached source"


CanonicalMessageBlock: TypeAlias = TextBlock | MarkdownBlock | DatasetBlock | SourceAttachmentBlock
# Public aliases make the semantic boundary obvious to callers that refer to
# all content blocks as ``ContentBlock`` or ``MessageContentBlock``.
ContentBlock: TypeAlias = CanonicalMessageBlock
MessageContentBlock: TypeAlias = CanonicalMessageBlock


def normalize_message_block(value: Any) -> CanonicalMessageBlock:
    if isinstance(value, (TextBlock, MarkdownBlock, DatasetBlock, SourceAttachmentBlock)):
        return value
    if isinstance(value, Mapping):
        return MessageBlock.from_json(value)
    raise ValidationError("Message content block must be a typed block or JSON object.")


def normalize_message_blocks(values: Iterable[Any] | None) -> tuple[CanonicalMessageBlock, ...]:
    if values is None:
        return ()
    if isinstance(values, (Mapping, str, bytes)):
        raise ValidationError("Message content blocks must be an array.")
    return tuple(normalize_message_block(value) for value in values)


def blocks_to_json(values: Iterable[Any] | None) -> list[dict[str, Any]]:
    return [block.to_json() for block in normalize_message_blocks(values)]


def blocks_from_payload(payload: Mapping[str, Any] | None) -> tuple[CanonicalMessageBlock, ...]:
    if not isinstance(payload, Mapping):
        return ()
    values = payload.get("blocks")
    if values is None:
        values = payload.get("content_blocks", [])
    if values is None:
        return ()
    if not isinstance(values, list):
        raise ValidationError("Message content payload blocks must be an array.")
    return normalize_message_blocks(values)


def blocks_to_markdown(values: Iterable[Any] | None) -> str:
    lines = [block.to_markdown() for block in normalize_message_blocks(values)]
    return _bounded_markdown("\n".join(line for line in lines if line))


def assistant_text_from_blocks(values: Iterable[Any] | None) -> str | None:
    """Extract display text without flattening non-text block semantics."""

    texts: list[str] = []
    for block in normalize_message_blocks(values):
        if isinstance(block, (TextBlock, MarkdownBlock)) and block.text:
            texts.append(block.text)
    return "\n".join(texts) or None


@dataclass(frozen=True)
class AssistantOutputItem:
    """One optional assistant envelope from a provider response."""

    text: str | None = None
    reasoning: str | None = None
    refusal: str | None = None
    content_blocks: tuple[CanonicalMessageBlock, ...] = ()

    def __post_init__(self) -> None:
        blocks = normalize_message_blocks(self.content_blocks)
        object.__setattr__(self, "content_blocks", blocks)
        # Assistant rows retain their established text/reasoning/refusal
        # fields as the canonical representation.  A legacy scripted provider
        # may still send textual blocks, so normalize those once here rather
        # than losing text or persisting it twice as a TextBlock.
        text = self.text if self.text is not None else assistant_text_from_blocks(blocks)
        if text is not None:
            object.__setattr__(self, "text", _bounded_text(text, label="assistant.text", limit=MAX_BLOCK_TEXT_CHARS))
        if self.reasoning is not None:
            object.__setattr__(self, "reasoning", _bounded_text(self.reasoning, label="assistant.reasoning", limit=MAX_BLOCK_TEXT_CHARS))
        if self.refusal is not None:
            object.__setattr__(self, "refusal", _bounded_text(self.refusal, label="assistant.refusal", limit=MAX_BLOCK_TEXT_CHARS))

    @property
    def is_empty(self) -> bool:
        return not any(value for value in (self.text, self.reasoning, self.refusal, self.content_blocks))


@dataclass(frozen=True)
class ToolCallOutputItem:
    """A provider tool call in canonical source order."""

    provider_call_id: str
    tool_name: str
    provider_name: str
    arguments: dict[str, object]
    stream_index: int | None = None


ProviderOutputItem: TypeAlias = AssistantOutputItem | ToolCallOutputItem


def output_items_are_ordered(items: list[ProviderOutputItem]) -> bool:
    """Return whether *items* obey the Chat Completions output grammar."""

    assistant_seen = False
    tool_seen = False
    for item in items:
        if isinstance(item, AssistantOutputItem):
            if assistant_seen or tool_seen:
                return False
            assistant_seen = True
            continue
        if not isinstance(item, ToolCallOutputItem):
            return False
        tool_seen = True
        if not assistant_seen:
            # Tool-only responses are valid; the first Tool Call may be first.
            continue
    return bool(items)

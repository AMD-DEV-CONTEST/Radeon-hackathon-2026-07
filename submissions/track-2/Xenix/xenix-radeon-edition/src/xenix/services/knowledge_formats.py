from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictStr, model_validator


class KnowledgeFormatCapability(BaseModel):
    """One complete source-format route through the document pipeline."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_format: str
    display_name: str
    suffixes: tuple[StrictStr, ...]
    media_type: str
    probe_provider_id: str
    normalizer_provider_id: str
    parser_format: str
    route_provider_id: str
    parser_provider_id: str

    @model_validator(mode="after")
    def _validate_capability(self) -> KnowledgeFormatCapability:
        if (
            not self.source_format
            or self.source_format != self.source_format.strip().casefold()
        ):
            raise ValueError("Knowledge source formats must be normalized.")
        if not self.display_name.strip():
            raise ValueError("Knowledge format display names must be non-empty.")
        if not self.media_type.strip():
            raise ValueError("Knowledge format media types must be non-empty.")
        if (
            not self.parser_format
            or self.parser_format != self.parser_format.strip().casefold()
        ):
            raise ValueError("Knowledge parser formats must be normalized.")
        provider_ids = (
            self.probe_provider_id,
            self.normalizer_provider_id,
            self.route_provider_id,
            self.parser_provider_id,
        )
        if any(
            not provider_id
            or provider_id != provider_id.strip().casefold()
            for provider_id in provider_ids
        ):
            raise ValueError("Knowledge format provider IDs must be normalized.")
        if not self.suffixes:
            raise ValueError("Knowledge format capabilities require suffixes.")
        if any(
            len(suffix) < 2
            or not suffix.startswith(".")
            or suffix != suffix.strip().casefold()
            for suffix in self.suffixes
        ):
            raise ValueError("Knowledge format suffixes must be normalized extensions.")
        return self


class KnowledgeFormatCatalog(BaseModel):
    """Strict immutable document owning the complete format capability contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: int = 1
    capabilities: tuple[KnowledgeFormatCapability, ...]

    @model_validator(mode="after")
    def _validate_catalog(self) -> KnowledgeFormatCatalog:
        if self.version < 1:
            raise ValueError(
                "Knowledge format catalog version must be a positive integer."
            )
        if not self.capabilities:
            raise ValueError("Knowledge format catalog cannot be empty.")

        source_formats: set[str] = set()
        suffixes: set[str] = set()
        for capability in self.capabilities:
            if capability.source_format in source_formats:
                raise ValueError("Knowledge source formats must be unique.")
            source_formats.add(capability.source_format)
            for suffix in capability.suffixes:
                if suffix in suffixes:
                    raise ValueError("Knowledge format suffixes must be unique.")
                suffixes.add(suffix)
        return self


class KnowledgeFormatRegistry:
    """Indexed query interface over one validated format catalog."""

    def __init__(self, catalog: KnowledgeFormatCatalog) -> None:
        self._catalog = catalog
        self._by_format = {
            capability.source_format: capability
            for capability in catalog.capabilities
        }
        self._by_suffix = {
            suffix: capability
            for capability in catalog.capabilities
            for suffix in capability.suffixes
        }

    @property
    def catalog(self) -> KnowledgeFormatCatalog:
        return self._catalog

    @property
    def version(self) -> int:
        return self._catalog.version

    @property
    def capabilities(self) -> tuple[KnowledgeFormatCapability, ...]:
        return self._catalog.capabilities

    @property
    def supported_suffixes(self) -> frozenset[str]:
        return frozenset(self._by_suffix)

    @property
    def probe_provider_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.probe_provider_id for item in self._catalog.capabilities
            )
        )

    @property
    def normalizer_provider_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.normalizer_provider_id for item in self._catalog.capabilities
            )
        )

    @property
    def route_provider_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.route_provider_id for item in self._catalog.capabilities
            )
        )

    @property
    def parser_provider_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.parser_provider_id for item in self._catalog.capabilities
            )
        )

    @property
    def display_names(self) -> tuple[str, ...]:
        return tuple(item.display_name for item in self._catalog.capabilities)

    def capability_for_suffix(self, suffix: str) -> KnowledgeFormatCapability | None:
        return self._by_suffix.get(suffix.casefold())

    def capability_for_format(self, source_format: str) -> KnowledgeFormatCapability | None:
        return self._by_format.get(source_format.casefold())

    def file_dialog_filter(self, label: str = "Knowledge documents") -> str:
        patterns = " ".join(
            f"*{suffix}"
            for capability in self._catalog.capabilities
            for suffix in capability.suffixes
        )
        display_label = label.strip() or "Knowledge documents"
        return f"{display_label} ({patterns})"

    def supported_formats_message(self) -> str:
        names = self.display_names
        joined = names[0] if len(names) == 1 else f"{', '.join(names[:-1])}, and {names[-1]}"
        return f"Supported Knowledge formats are {joined}."


KNOWLEDGE_FORMAT_CATALOG = KnowledgeFormatCatalog(
    version=2,
    capabilities=(
        KnowledgeFormatCapability(
            source_format="txt",
            display_name="TXT",
            suffixes=(".txt",),
            media_type="text/plain",
            probe_provider_id="text",
            normalizer_provider_id="text",
            parser_format="txt",
            route_provider_id="text",
            parser_provider_id="text",
        ),
        KnowledgeFormatCapability(
            source_format="doc",
            display_name="DOC",
            suffixes=(".doc",),
            media_type="application/msword",
            probe_provider_id="cfb-word",
            normalizer_provider_id="doc-to-docx",
            parser_format="docx",
            route_provider_id="docx",
            parser_provider_id="docx",
        ),
        KnowledgeFormatCapability(
            source_format="docx",
            display_name="DOCX",
            suffixes=(".docx",),
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            probe_provider_id="ooxml-word",
            normalizer_provider_id="docx",
            parser_format="docx",
            route_provider_id="docx",
            parser_provider_id="docx",
        ),
        KnowledgeFormatCapability(
            source_format="ppt",
            display_name="PPT",
            suffixes=(".ppt",),
            media_type="application/vnd.ms-powerpoint",
            probe_provider_id="cfb-presentation",
            normalizer_provider_id="ppt-to-pptx",
            parser_format="pptx",
            route_provider_id="pptx",
            parser_provider_id="pptx",
        ),
        KnowledgeFormatCapability(
            source_format="pptx",
            display_name="PPTX",
            suffixes=(".pptx",),
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation"
            ),
            probe_provider_id="ooxml-presentation",
            normalizer_provider_id="pptx",
            parser_format="pptx",
            route_provider_id="pptx",
            parser_provider_id="pptx",
        ),
        KnowledgeFormatCapability(
            source_format="pdf",
            display_name="PDF",
            suffixes=(".pdf",),
            media_type="application/pdf",
            probe_provider_id="pdf",
            normalizer_provider_id="pdf",
            parser_format="pdf",
            route_provider_id="pdf",
            parser_provider_id="pdf",
        ),
        KnowledgeFormatCapability(
            source_format="jpeg",
            display_name="JPEG",
            suffixes=(".jpg", ".jpeg"),
            media_type="image/jpeg",
            probe_provider_id="image",
            normalizer_provider_id="image",
            parser_format="image",
            route_provider_id="image",
            parser_provider_id="image",
        ),
        KnowledgeFormatCapability(
            source_format="png",
            display_name="PNG",
            suffixes=(".png",),
            media_type="image/png",
            probe_provider_id="image",
            normalizer_provider_id="image",
            parser_format="image",
            route_provider_id="image",
            parser_provider_id="image",
        ),
    ),
)
KNOWLEDGE_FORMAT_REGISTRY = KnowledgeFormatRegistry(KNOWLEDGE_FORMAT_CATALOG)
SUPPORTED_KNOWLEDGE_SUFFIXES = KNOWLEDGE_FORMAT_REGISTRY.supported_suffixes


def knowledge_file_dialog_filter(label: str = "Knowledge documents") -> str:
    return KNOWLEDGE_FORMAT_REGISTRY.file_dialog_filter(label)


__all__ = [
    "KNOWLEDGE_FORMAT_CATALOG",
    "KNOWLEDGE_FORMAT_REGISTRY",
    "SUPPORTED_KNOWLEDGE_SUFFIXES",
    "KnowledgeFormatCapability",
    "KnowledgeFormatCatalog",
    "KnowledgeFormatRegistry",
    "knowledge_file_dialog_filter",
]

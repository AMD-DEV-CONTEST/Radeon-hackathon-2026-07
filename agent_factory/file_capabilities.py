from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import shutil
from typing import Any


TEXT_EXTENSIONS = {
    ".md", ".markdown", ".mdx", ".txt", ".rst", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".csv", ".tsv", ".py", ".ts", ".tsx",
    ".js", ".jsx", ".java", ".go", ".rs", ".sql", ".html", ".htm",
    ".xml", ".log", ".c", ".cc", ".cpp", ".h", ".hpp", ".css", ".sh",
    ".bash", ".zsh", ".vue", ".kt", ".swift", ".rb", ".php",
}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
LEGACY_WORD_EXTENSIONS = {".doc"}
SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".ods"}
PRESENTATION_EXTENSIONS = {".pptx", ".odp"}
LEGACY_PRESENTATION_EXTENSIONS = {".ppt"}
OPEN_DOCUMENT_EXTENSIONS = {".odt", ".ods", ".odp"}
RICH_TEXT_EXTENSIONS = {".rtf"}
EBOOK_EXTENSIONS = {".epub"}
EMAIL_EXTENSIONS = {".eml", ".msg"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".webp", ".heic", ".svg"}

OFFICE_EXTENSIONS = (
    DOCX_EXTENSIONS
    | LEGACY_WORD_EXTENSIONS
    | SPREADSHEET_EXTENSIONS
    | PRESENTATION_EXTENSIONS
    | LEGACY_PRESENTATION_EXTENSIONS
    | OPEN_DOCUMENT_EXTENSIONS
    | RICH_TEXT_EXTENSIONS
    | EBOOK_EXTENSIONS
)
MARKITDOWN_EXTENSIONS = DOCX_EXTENSIONS | {".pptx", ".xlsx", ".xls", ".msg"}
LIBREOFFICE_EXTENSIONS = LEGACY_WORD_EXTENSIONS | LEGACY_PRESENTATION_EXTENSIONS
SUPPORTED_FILE_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | OFFICE_EXTENSIONS | EMAIL_EXTENSIONS


@dataclass(frozen=True, slots=True)
class FileFormatGroup:
    group_id: str
    extensions: frozenset[str]


FORMAT_GROUPS = (
    FileFormatGroup("documents", frozenset(PDF_EXTENSIONS | DOCX_EXTENSIONS | LEGACY_WORD_EXTENSIONS | {".odt", ".rtf"})),
    FileFormatGroup("spreadsheets", frozenset(SPREADSHEET_EXTENSIONS | {".csv", ".tsv"})),
    FileFormatGroup("presentations", frozenset(PRESENTATION_EXTENSIONS | LEGACY_PRESENTATION_EXTENSIONS)),
    FileFormatGroup("text_code", frozenset(TEXT_EXTENSIONS - {".csv", ".tsv"})),
    FileFormatGroup("email_ebook", frozenset(EMAIL_EXTENSIONS | EBOOK_EXTENSIONS)),
    FileFormatGroup("images", frozenset(IMAGE_EXTENSIONS)),
)


@dataclass(frozen=True, slots=True)
class FileProcessingCapabilities:
    knowledge_extensions: tuple[str, ...]
    attachment_extensions: tuple[str, ...]
    preview_extensions: tuple[str, ...]
    parser_backends: tuple[str, ...]

    def to_public_dict(self) -> dict[str, Any]:
        knowledge = set(self.knowledge_extensions)
        attachments = set(self.attachment_extensions)
        previews = set(self.preview_extensions)
        return {
            "knowledge_extensions": list(self.knowledge_extensions),
            "attachment_extensions": list(self.attachment_extensions),
            "preview_extensions": list(self.preview_extensions),
            "knowledge_accept": ",".join(self.knowledge_extensions),
            "attachment_accept": ",".join(self.attachment_extensions),
            "parser_backends": list(self.parser_backends),
            "format_groups": [
                {
                    "group_id": group.group_id,
                    "knowledge_extensions": sorted(group.extensions & knowledge),
                    "attachment_extensions": sorted(group.extensions & attachments),
                    "preview_extensions": sorted(group.extensions & previews),
                }
                for group in FORMAT_GROUPS
                if group.extensions & (knowledge | attachments | previews)
            ],
        }


def file_processing_capabilities() -> FileProcessingCapabilities:
    knowledge = set(TEXT_EXTENSIONS)
    backends = ["internal_text", "email"]
    knowledge.add(".eml")

    if _module_available("bs4"):
        backends.append("beautifulsoup4")
    else:
        knowledge.difference_update({".html", ".htm"})
    if _module_available("pypdf"):
        knowledge.update(PDF_EXTENSIONS)
        backends.append("pypdf")
    if _module_available("markitdown"):
        knowledge.update(MARKITDOWN_EXTENSIONS)
        backends.append("markitdown")
    if _module_available("striprtf.striprtf"):
        knowledge.update(RICH_TEXT_EXTENSIONS)
        backends.append("striprtf")
    if _module_available("ebooklib"):
        knowledge.update(EBOOK_EXTENSIONS)
        backends.append("ebooklib")
    if _module_available("odf.opendocument"):
        knowledge.update(OPEN_DOCUMENT_EXTENSIONS)
        backends.append("odfpy")
    if shutil.which("soffice"):
        knowledge.update(LIBREOFFICE_EXTENSIONS)
        backends.append("libreoffice")

    attachments = knowledge | IMAGE_EXTENSIONS
    previews = attachments
    return FileProcessingCapabilities(
        knowledge_extensions=tuple(sorted(knowledge)),
        attachment_extensions=tuple(sorted(attachments)),
        preview_extensions=tuple(sorted(previews)),
        parser_backends=tuple(backends),
    )


def accepted_knowledge_extensions() -> frozenset[str]:
    return frozenset(file_processing_capabilities().knowledge_extensions)


def accepted_attachment_extensions() -> frozenset[str]:
    return frozenset(file_processing_capabilities().attachment_extensions)


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
        return False

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from policyseal.domain.enums import FileKind
from policyseal.domain.models import DocumentRegion, PolicyDecision, SourceFingerprint


class PreflightDisposition(StrEnum):
    PASS = "pass"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"
    PROCESSING_FAILED = "processing_failed"


@dataclass(frozen=True, slots=True)
class CapabilityFinding:
    code: str
    disposition: PreflightDisposition
    location: str
    message: str


@dataclass(frozen=True, slots=True)
class PreflightResult:
    file_kind: FileKind | None
    disposition: PreflightDisposition
    findings: tuple[CapabilityFinding, ...] = ()

    @property
    def blocked(self) -> bool:
        return self.disposition in {
            PreflightDisposition.BLOCK,
            PreflightDisposition.PROCESSING_FAILED,
        }


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source_path: Path
    source: SourceFingerprint
    file_kind: FileKind
    regions: tuple[DocumentRegion, ...]
    preflight: PreflightResult
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class OutputValidation:
    valid: bool
    structure_preserved: bool
    findings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PreviewArtifact:
    page: int
    path: Path
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class RenderedDocument:
    output_path: Path
    decisions: tuple[PolicyDecision, ...]
    validation: OutputValidation
    output_label: str | None = None


class DocumentAdapter(Protocol):
    file_kind: FileKind

    def preflight(self, path: Path) -> PreflightResult: ...

    def parse(self, path: Path) -> ParsedDocument: ...

    def render(
        self,
        parsed: ParsedDocument,
        decisions: tuple[PolicyDecision, ...],
        output_dir: Path,
    ) -> RenderedDocument: ...

    def reopen_validate(self, path: Path) -> OutputValidation: ...

    def preview(self, path: Path, output_dir: Path) -> tuple[PreviewArtifact, ...]: ...

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from policyseal.application.approvals import ApprovalService
from policyseal.application.evidence_package import build_evidence_package
from policyseal.domain.enums import RevisionStatus
from policyseal.domain.errors import ApprovalDenied, ExportDenied
from policyseal.domain.models import DisclosureRevision
from policyseal.storage.file_store import ControlledFileStore, FileNamespace
from policyseal.storage.repositories import PolicySealRepository


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    filename: str
    media_type: str
    data: bytes
    sha256: str


class ExportService:
    def __init__(
        self,
        repository: PolicySealRepository,
        file_store: ControlledFileStore,
        approval_service: ApprovalService,
        *,
        template_root: Path,
    ) -> None:
        self.repository = repository
        self.file_store = file_store
        self.approvals = approval_service
        self.template_root = template_root

    def business_file(
        self,
        revision_id: str,
        *,
        approval_id: str | None = None,
    ) -> ExportArtifact:
        revision = self._downloadable(revision_id)
        if revision.status is RevisionStatus.APPROVED:
            if approval_id is None:
                raise ExportDenied("approved output requires its exact approval token")
            try:
                self.approvals.consume(approval_id, revision.id)
            except ApprovalDenied as error:
                raise ExportDenied("approval is not consumable for this output") from error
        if revision.output_storage_id is None or revision.output_sha256 is None:
            raise ExportDenied("revision has no validated business output")
        data = self.file_store.read(FileNamespace.OUTPUTS, revision.output_storage_id)
        if hashlib.sha256(data).hexdigest() != revision.output_sha256:
            raise ExportDenied("stored output checksum no longer matches the revision")
        suffix = Path(revision.output_storage_id).suffix
        media_type = {
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }.get(suffix, "application/octet-stream")
        return ExportArtifact(
            filename=f"PolicySeal-{revision.id}{suffix}",
            media_type=media_type,
            data=data,
            sha256=revision.output_sha256,
        )

    def evidence_file(self, revision_id: str) -> ExportArtifact:
        revision = self._downloadable(revision_id)
        package = build_evidence_package(
            revision,
            self.repository.list_regions(revision.id),
            self.repository.list_decisions(revision.id),
            template_root=self.template_root,
        )
        return ExportArtifact(
            filename=f"PolicySeal-{revision.id}-evidence.zip",
            media_type="application/zip",
            data=package.data,
            sha256=package.sha256,
        )

    def _downloadable(self, revision_id: str) -> DisclosureRevision:
        try:
            revision = self.repository.get_revision(revision_id)
        except KeyError as error:
            raise ExportDenied("formal revision does not exist") from error
        if revision.status not in {RevisionStatus.EXPORTABLE, RevisionStatus.APPROVED}:
            raise ExportDenied("revision status does not allow download")
        return revision
